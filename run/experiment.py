"""
experiment.py

Robotiq 2F-85 teleoperation experiment: hand-tracked gripper control with
9DTact tactile sensing and haptic feedback (left sensor -> thumb motor, right
-> index).

Orchestrator only — run parameters, shared state, background threads, main().
The hardware classes and the tracking loop live in kernel/.

    python run/experiment.py --condition lra --participant P01 --object fragile

Controls: 'r' start/stop a trial, 'o' switch object class, 'q' quit.
See README.md for prerequisites and the pre-participant checklist.
"""

# =============================================================================
# IMPORTS & SETUP
# =============================================================================

import os
import argparse
import csv
import cv2
from dataclasses import dataclass, field
import multiprocessing as mp
import sys
import threading
import time

# Make the kernel modules (and the bundled 9DTact library) importable, then
# import them with bare names — same convention the standalone tools use.
_repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_kernel_dir = os.path.join(_repo_root, "kernel")
_tact_main_dir = os.path.join(_repo_root, "src", "9DTact-main")
for _p in (_kernel_dir, _tact_main_dir):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from camera import HAND_CAM_INDEX, TACTILE_CAM_L, TACTILE_CAM_R, resolve    # noqa: E402
from gripper import GripperController, MAX_POS                              # noqa: E402
from tactile import TactileSensor, SharedTactileReading, CONFIG_PATH        # noqa: E402
from haptic_link import HapticLink                                          # noqa: E402
from tracking import open_camera, create_hand_detector, hand_tracking_loop  # noqa: E402

# Paths
CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))

# The shared sensor config (run/shape_config.yaml) is owned by kernel/tactile.py,
# which injects each side's sensor_id — see load_config()/SIDE_OVERRIDES there.


# =============================================================================
# PARAMETERS
# =============================================================================

# Gripper (mechanical limits like MAX_POS/SPEED/FORCE live in gripper.py)
GRIPPER_PORT    = "/dev/ttyUSB0"
MOTION_HZ       = 25
OUTPUT_DEADBAND = 3             # Filters motor stutter when hand is stationary

# Tactile sensor (contact/zeroing/intensity constants live in tactile.py)
FORCE_CAL_A_LEFT,  FORCE_CAL_B_LEFT  = None, None
FORCE_CAL_A_RIGHT, FORCE_CAL_B_RIGHT = None, None

# Haptic feedback
ESP32_PORT = "/dev/ttyACM0"
ESP32_BAUD = 115200
HAPTIC_HZ  = 15                 # Sensor read + serial send rate


# =============================================================================
# STATES
# =============================================================================

# Global runtime state
stop_event = threading.Event()  # For stopping all threads

@dataclass
class SharedState:
    """Written by the main thread (target_pos) and the two tactile-sensor
    processes (left/right, via shared memory): read by haptics, logging, GUI."""
    target_pos: float = 0.0
    left: SharedTactileReading = field(default_factory=SharedTactileReading)
    right: SharedTactileReading = field(default_factory=SharedTactileReading)


class RecordingState:
    """Recording toggle, trial counter, object class. Mutated by the keyboard
    thread; read by log_loop and the overlay."""

    def __init__(self, initial_object: str):
        self._lock = threading.Lock()
        self.active = False
        self.trial_number = 0
        self.current_object = initial_object
        self.last_outcome = None   # set when stopping a fragile trial: "success" or "break"

    def toggle_recording(self, outcome: str = None) -> bool:
        """Flips recording; returns the new state. `outcome` is stashed only
        when stopping a trial, so log_loop can tag the file it's about to close."""
        with self._lock:
            self.active = not self.active
            if not self.active:
                self.last_outcome = outcome
            return self.active

    def consume_outcome(self):
        """Returns and clears the outcome set by the last toggle_recording(outcome=...)."""
        with self._lock:
            outcome, self.last_outcome = self.last_outcome, None
            return outcome

    def toggle_object(self):
        """Flips fragile/deformable. Returns (changed, object); changed is
        False if a trial is recording."""
        with self._lock:
            if self.active:
                return False, self.current_object
            self.current_object = "deformable" if self.current_object == "fragile" else "fragile"
            return True, self.current_object

    def snapshot(self):
        """Returns (active, current_object) atomically."""
        with self._lock:
            return self.active, self.current_object


# =============================================================================
# BACKGROUND THREADS
# =============================================================================

# Gripper status
def status_loop(gripper: GripperController, state: SharedState):
    """Prints gripper position and both sensors' readings at 10 Hz."""
    interval = 1.0 / 10
    while not stop_event.is_set():
        t0 = time.monotonic()
        try:
            pos = gripper.read_position()
            print(f"\r  [Hardware] Pos: {pos:3d}/{MAX_POS} "
                  f"| L: {state.left.intensity:4.2f}/{state.left.force_proxy:6.0f} "
                  f"| R: {state.right.intensity:4.2f}/{state.right.force_proxy:6.0f}   ",
                  end="", flush=True)
        except Exception:
            pass

        elapsed = time.monotonic() - t0
        time.sleep(max(0.0, interval - elapsed))

# Gripper motion Loop
def motion_loop(gripper: GripperController, state: SharedState):
    """Sends state.target_pos to the gripper at MOTION_HZ, filtered by
    OUTPUT_DEADBAND to stop motor stutter when the hand is still."""
    interval = 1.0 / MOTION_HZ
    last_sent_pos = -1

    while not stop_event.is_set():
        t0 = time.monotonic()

        final_pos = int(state.target_pos)
        if abs(final_pos - last_sent_pos) > OUTPUT_DEADBAND:
            gripper.move(final_pos)
            last_sent_pos = final_pos

        elapsed = time.monotonic() - t0
        time.sleep(max(0.0, interval - elapsed))


# Tactile sensing & haptic streaming
def sensor_process_main(side: str, camera_index: int, shared_reading: SharedTactileReading,
                         sensor_stop_event: mp.Event, ready_event: mp.Event, start_streaming_event: mp.Event):
    sensor = TactileSensor(side, camera_index)
    try:
        sensor.connect()

        print(f"\n[Haptic] Capturing {sensor.label} tactile baseline — keep it untouched ...")
        sensor.capture_baseline()
        print(f"[Haptic] {sensor.label.capitalize()} baseline captured.")

        interval = 1.0 / HAPTIC_HZ
        print(f"[Haptic] {sensor.label.capitalize()} 9DTact sensor ready.")
        ready_event.set()

        # Hold off streaming until BOTH sensors have connected + baselined.
        # Left's continuous 30Hz reads were saturating the USB hub it shares
        # with the right camera, so right's own connect attempts never got a
        # clean frame while left was already streaming.
        start_streaming_event.wait()

        while not sensor_stop_event.is_set() and sensor.is_open:
            t0 = time.monotonic()
            intensity, max_depth, force_proxy = sensor.read()
            shared_reading.set(intensity, max_depth, force_proxy)
            elapsed = time.monotonic() - t0
            time.sleep(max(0.0, interval - elapsed))
    except Exception as e:
        print(f"\n[Haptic][ERROR] {side} sensor process died: {e}")
        print(f"  -> {side.capitalize()} intensity/force_proxy are now FROZEN at their last value.")
        print(f"  -> Most likely the {side} tactile camera "
              f"({resolve(camera_index)}) stopped returning frames. Check USB bandwidth.")
        import traceback
        traceback.print_exc()
    finally:
        sensor.close()


# Haptic send loop
def haptic_send_loop(link: HapticLink, state: SharedState, test_mode: bool):
    """Streams both sensors' intensities to the ESP32 at HAPTIC_HZ. In
    test_mode, streams a 0->1->0 ramp instead, ignoring the sensors."""
    if not link.is_connected:
        return

    interval = 1.0 / HAPTIC_HZ
    if test_mode:
        print(f"[Haptic] *** SELF-TEST MODE *** streaming a 0->1->0 ramp on both "
              f"channels via {link.port}, ignoring both tactile sensors. Motors should pulse.")
    else:
        print(f"[Haptic] Streaming L/R intensities to ESP32 on {link.port} @ {HAPTIC_HZ} Hz.")

    t_start = time.monotonic()
    try:
        while not stop_event.is_set():
            t0 = time.monotonic()
            if test_mode:
                # Known-good ramp: 0 -> 1 over 2 s, 1 -> 0 over 2 s, repeat.
                phase = (time.monotonic() - t_start) % 4.0
                ramp = phase / 2.0 if phase < 2.0 else (4.0 - phase) / 2.0
                left_intensity, right_intensity = ramp, ramp
            else:
                left_intensity, right_intensity = state.left.intensity, state.right.intensity
            link.send(left_intensity, right_intensity)
            elapsed = time.monotonic() - t0
            time.sleep(max(0.0, interval - elapsed))
    finally:
        link.close()


# Trial logging
def log_loop(gripper: GripperController, recording: RecordingState, state: SharedState,
             out_dir: str, condition: str, participant: str):
    """Writes one CSV row per tick while recording; a new file per trial.

    File: <out_dir>/<participant>_<condition>_<object>_trial<N>.csv
    Columns: t, gripper_pos_bit, left/right_force_proxy, left/right_force_N,
    left/right_max_depth_mm, left/right_haptic_intensity, motion_mode.
    A force_N column is empty unless that side's FORCE_CAL constants are set.
    """
    interval = 1.0 / HAPTIC_HZ
    os.makedirs(out_dir, exist_ok=True)

    def _force_n(volume, cal_a, cal_b):
        """Newton value from a calibrated (A, B) pair, or '' if unset."""
        if cal_a is not None and cal_b is not None:
            return f"{cal_a * volume + cal_b:.4f}"
        return ""

    csv_file = None
    writer = None
    trial_start = None
    was_recording = False
    trial_object = None

    try:
        while not stop_event.is_set():
            t0 = time.monotonic()

            is_recording, current_object = recording.snapshot()

            if is_recording and not was_recording:
                # New trial file; lock in the object class as of this moment
                # so a mid-trial 'o' press can't relabel it.
                recording.trial_number += 1
                trial_object = current_object
                fname = f"{participant}_{condition}_{trial_object}_trial{recording.trial_number}.csv"
                fpath = os.path.join(out_dir, fname)
                csv_file = open(fpath, "w", newline="")
                writer = csv.writer(csv_file)
                writer.writerow(["t", "gripper_pos_bit",
                                  "left_force_proxy", "right_force_proxy",
                                  "left_force_N", "right_force_N",
                                  "left_max_depth_mm", "right_max_depth_mm",
                                  "left_haptic_intensity", "right_haptic_intensity"])
                trial_start = time.monotonic()
                print(f"\n[Log] Recording trial {recording.trial_number} ({trial_object}) -> {fpath}")

            elif not is_recording and was_recording:
                # Recording just stopped — close the file
                if csv_file is not None:
                    csv_file.close()
                    outcome = recording.consume_outcome()
                    if trial_object == "fragile" and outcome is not None:
                        tagged_fpath = fpath.rsplit(".csv", 1)[0] + f"_{outcome}.csv"
                        os.rename(fpath, tagged_fpath)
                        print(f"\n[Log] Trial {recording.trial_number} saved -> {os.path.basename(tagged_fpath)}")
                    else:
                        print(f"\n[Log] Trial {recording.trial_number} saved.")
                csv_file = None
                writer = None

            if is_recording and writer is not None:
                try:
                    pos = gripper.read_position()
                except Exception:
                    pos = -1

                left_force_N = _force_n(state.left.force_proxy, FORCE_CAL_A_LEFT, FORCE_CAL_B_LEFT)
                right_force_N = _force_n(state.right.force_proxy, FORCE_CAL_A_RIGHT, FORCE_CAL_B_RIGHT)

                t = time.monotonic() - trial_start
                writer.writerow([f"{t:.4f}", pos,
                                  f"{state.left.force_proxy:.4f}", f"{state.right.force_proxy:.4f}",
                                  left_force_N, right_force_N,
                                  f"{state.left.max_depth_mm:.4f}", f"{state.right.max_depth_mm:.4f}",
                                  f"{state.left.intensity:.4f}", f"{state.right.intensity:.4f}"])
                csv_file.flush()

            was_recording = is_recording

            elapsed = time.monotonic() - t0
            time.sleep(max(0.0, interval - elapsed))
    finally:
        if csv_file is not None:
            csv_file.close()


# =============================================================================
# MAIN
# =============================================================================

sys.setswitchinterval(0.001)

def main():
    """Connects hardware, starts the threads, then runs the tracking loop."""

    parser = argparse.ArgumentParser(
        description="Integrated gripper + 9DTact + haptic feedback experiment."
    )

    parser.add_argument(
        "--condition",
        required=True,
        choices=["visual_only", "lra", "tactiles"],
        help=(
            "Feedback condition label for trial filenames. Data-labeling only — "
            "actual hardware behavior depends on the ESP32 firmware; for "
            "visual_only, disconnect the ESP32 or ignore sent intensities."
        )
    )

    parser.add_argument(
        "--participant",
        required=True,
        help="Participant ID, used in trial filenames."
    )

    parser.add_argument(
        "--object",
        default="fragile",
        choices=["fragile", "deformable"],
        help="Starting object class label. Switch mid-session with 'o'."
    )

    parser.add_argument(
        "--out",
        default=os.path.join(CONFIG_DIR, "..", "data", "experiment_logs"),
        help="Directory to save trial CSVs."
    )

    parser.add_argument(
        "--haptic-test",
        action="store_true",
        help=(
            "Stream a 0->1->0 ramp instead of the sensor, to self-test the "
            "ESP32 link/motors independent of the tactile sensor."
        )
    )

    parser.add_argument(
        "--model-path",
        default=None,
        help=(
            "Path to the MediaPipe hand_landmarker.task model. Defaults to "
            "hand_landmarker.task in the cwd, then next to this script."
        )
    )

    args = parser.parse_args()

    if HAND_CAM_INDEX == TACTILE_CAM_L or HAND_CAM_INDEX == TACTILE_CAM_R:
        print(f"[ERROR] HAND_CAM_INDEX ({HAND_CAM_INDEX}) must differ from "
              f"TACTILE_CAM_L ({TACTILE_CAM_L}) / TACTILE_CAM_R ({TACTILE_CAM_R}). "
              f"See camera.py. Exiting.")
        return

    if not os.path.exists(CONFIG_PATH):
        print(f"[ERROR] {CONFIG_PATH} not found. This shared config serves both "
              f"sensors; restore it before running. Exiting.")
        return

    print(f"Connecting to gripper on {GRIPPER_PORT} …", end=" ", flush=True)
    gripper = GripperController(GRIPPER_PORT)
    if not gripper.is_activated():
        # No auto-activation here — activate() runs a full open/close
        # calibration cycle, unwanted at experiment startup. Under
        # pyRobotiqGripper v3.x an unactivated gripper makes every move()
        # raise GripperNotActivatedError, so this is fatal rather than a
        # warning: bail out now instead of dying inside motion_loop.
        print(f"\n[ERROR] Gripper not activated (gSTA != 3). Activate it once first "
              f"(a one-off script calling activate() — note it fully opens and closes "
              f"the gripper), then rerun. Exiting.")
        gripper.close()
        return

    # v3.x requires the GTO bit before it accepts position commands; without
    # this every move() raises GripperNotStartedError. Unlike activate(),
    # start() does not move the gripper.
    gripper.start()
    print("ready.")

    state = SharedState()
    recording = RecordingState(initial_object=args.object)
    haptic_link = HapticLink(ESP32_PORT, ESP32_BAUD)
    sensor_stop_event = mp.Event()
    sensor_ready = {"left": mp.Event(), "right": mp.Event()}
    start_streaming_event = mp.Event()

    # Tactile sensors are started FIRST and the rest of startup waits for them.
    # The right sensor's first frames are fragile (device opens fine, then
    # returns None for several reads) and it loses that race every time it
    # has to share CPU with MediaPipe/EGL init or hand-tracking inference —
    # confirmed by it connecting instantly once those stop competing. Give
    # both sensors a contention-free window before anything else starts.
    print("Connecting tactile sensors …")
    sensor_processes = {
        "left": mp.Process(target=sensor_process_main,
                            args=("left", TACTILE_CAM_L, state.left, sensor_stop_event, sensor_ready["left"], start_streaming_event),
                            daemon=True),
        "right": mp.Process(target=sensor_process_main,
                             args=("right", TACTILE_CAM_R, state.right, sensor_stop_event, sensor_ready["right"], start_streaming_event),
                             daemon=True),
    }
    sensor_processes["left"].start()
    time.sleep(4.0)   # stagger so both sensors' initial burst reads don't collide on the shared USB bus
    sensor_processes["right"].start()

    def _abort_startup(message):
        print(f"\n[ERROR] {message}")
        sensor_stop_event.set()
        for p in sensor_processes.values():
            if p.is_alive():
                p.terminate()
        gripper.close()

    SENSOR_CONNECT_TIMEOUT = 60.0
    deadline = time.monotonic() + SENSOR_CONNECT_TIMEOUT
    for side, ready in sensor_ready.items():
        proc = sensor_processes[side]
        while not ready.is_set():
            if not proc.is_alive():
                _abort_startup(f"{side} tactile sensor process died before connecting "
                                f"(see its traceback above). Exiting.")
                return
            if time.monotonic() > deadline:
                _abort_startup(f"{side} tactile sensor did not connect within "
                                f"{SENSOR_CONNECT_TIMEOUT:.0f}s. Exiting.")
                return
            time.sleep(0.2)
    print("Both tactile sensors ready.")
    start_streaming_event.set()   # only now do both sensors begin their continuous read loops

    print(f"Initializing camera feed on {resolve(HAND_CAM_INDEX)} …", end=" ", flush=True)
    cap = open_camera(HAND_CAM_INDEX)
    if cap is None:
        _abort_startup(f"Could not open {resolve(HAND_CAM_INDEX)}. Indices shift when "
                        f"cameras re-enumerate — check `ls -l /dev/v4l/by-path/` and update "
                        f"kernel/camera.py. Exiting.")
        return
    print("ready.")

    threads = [
        threading.Thread(target=status_loop, args=(gripper, state), daemon=True),
        threading.Thread(target=motion_loop, args=(gripper, state), daemon=True),
        threading.Thread(target=haptic_send_loop, args=(haptic_link, state, args.haptic_test), daemon=True),
        threading.Thread(target=log_loop, args=(gripper, recording, state, args.out, args.condition, args.participant), daemon=True),
    ]
    for t in threads:
        t.start()

    print(f"  [Controls] Press 'r' in the video window to start/stop recording a trial.")
    print(f"  [Controls] Press 'o' in the video window to toggle object class (fragile/deformable) when not recording.")
    print(f"  [Controls] Press 'q' in the video window to quit.\n")

    if args.model_path:
        model_path = args.model_path
    else:
        model_path = 'hand_landmarker.task'
        if not os.path.exists(model_path):
            model_path = os.path.join(os.path.dirname(__file__), 'hand_landmarker.task')

    if not os.path.exists(model_path):
        print(f"\n[ERROR] '{model_path}' not found!")
        print("  Download it with:")
        print("    wget -O run/hand_landmarker.task \\")
        print("      https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
              "hand_landmarker/float16/latest/hand_landmarker.task")
        print("  Or point --model-path at an existing copy.")
        _abort_startup("Missing hand landmarker model.")
        cap.release()
        return

    detector = create_hand_detector(model_path)

    hand_tracking_loop(cap, detector, state, recording, stop_event)

    print("\nStopping Window & Threads …")
    stop_event.set()
    sensor_stop_event.set()
    for t in threads:
        t.join(timeout=1.0)
    for p in sensor_processes.values():
        p.join(timeout=2.0)
        if p.is_alive():
            p.terminate()
    detector.close()
    cap.release()
    gripper.close()
    cv2.destroyAllWindows()
    print("Done.")


if __name__ == "__main__":
    main()
