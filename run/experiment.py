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

# Standard library imports
import argparse
import csv
import os
import sys
import threading
import time
from dataclasses import dataclass, field

# Third-party imports
import cv2
from pynput import keyboard

# Make the kernel modules (and the bundled 9DTact library) importable, then
# import them with bare names — same convention the standalone tools use.
_repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_kernel_dir = os.path.join(_repo_root, "kernel")
_tact_main_dir = os.path.join(_repo_root, "src", "9DTact-main")
for _p in (_kernel_dir, _tact_main_dir):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from camera import HAND_CAM_INDEX, TACTILE_CAM_L, TACTILE_CAM_R, resolve  # noqa: E402
from gripper import GripperController, MAX_POS                    # noqa: E402
from tactile import TactileSensor, TactileReading, CONFIG_PATH    # noqa: E402
from haptic_link import HapticLink                                # noqa: E402
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
HAPTIC_HZ  = 30                 # Sensor read + serial send rate


# =============================================================================
# STATES
# =============================================================================

# Global runtime state
stop_event = threading.Event()  # For stopping all threads

@dataclass
class SharedState:
    """Written by one thread, read by others: target_pos (tracking ->
    motion_loop), left/right (sensor threads -> haptics, logging, GUI)."""
    target_pos: float = 0.0
    left: TactileReading = field(default_factory=TactileReading)
    right: TactileReading = field(default_factory=TactileReading)


class RecordingState:
    """Recording toggle, trial counter, object class. Mutated by the keyboard
    thread; read by log_loop and the overlay."""

    def __init__(self, initial_object: str):
        self._lock = threading.Lock()
        self.active = False
        self.trial_number = 0
        self.current_object = initial_object

    def toggle_recording(self) -> bool:
        """Flips recording; returns the new state."""
        with self._lock:
            self.active = not self.active
            return self.active

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
def sensor_haptic_loop(sensor: TactileSensor, reading: TactileReading):
    """Reads one sensor into `reading` at HAPTIC_HZ. One instance per side."""
    try:
        sensor.connect()

        print(f"\n[Haptic] Capturing {sensor.label} tactile baseline — keep it untouched ...")
        sensor.capture_baseline()
        print(f"[Haptic] {sensor.label.capitalize()} baseline captured.")

        interval = 1.0 / HAPTIC_HZ
        print(f"[Haptic] {sensor.label.capitalize()} 9DTact sensor ready.")

        while not stop_event.is_set() and sensor.is_open:
            t0 = time.monotonic()
            reading.intensity, reading.max_depth_mm, reading.force_proxy = sensor.read()
            elapsed = time.monotonic() - t0
            time.sleep(max(0.0, interval - elapsed))
    except Exception as e:
        # Surface daemon-thread deaths loudly — otherwise intensity/force
        # just silently freeze at their last value.
        print(f"\n[Haptic][ERROR] {sensor.label} sensor thread died: {e}")
        print(f"  -> {sensor.label.capitalize()} intensity/force_proxy are now FROZEN at their last value.")
        print(f"  -> Most likely the {sensor.label} tactile camera "
              f"({resolve(sensor.camera_index)}) stopped returning frames. Check USB bandwidth.")
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
                                  "left_haptic_intensity", "right_haptic_intensity",
                                  "motion_mode"])
                trial_start = time.monotonic()
                print(f"\n[Log] Recording trial {recording.trial_number} ({trial_object}) -> {fpath}")

            elif not is_recording and was_recording:
                # Recording just stopped — close the file
                if csv_file is not None:
                    csv_file.close()
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
                                  f"{state.left.intensity:.4f}", f"{state.right.intensity:.4f}",
                                  "hand_tracking"])
                csv_file.flush()

            was_recording = is_recording

            elapsed = time.monotonic() - t0
            time.sleep(max(0.0, interval - elapsed))
    finally:
        if csv_file is not None:
            csv_file.close()


# =============================================================================
# INPUT
# =============================================================================

def make_key_handler(recording: RecordingState):
    """Keyboard callback: 'r' recording, 'o' object class, 'q' quit."""
    last_record_toggle_time = 0.0

    def on_press(key):
        nonlocal last_record_toggle_time
        try:
            if hasattr(key, 'char') and key.char in ['q', 'Q']:
                stop_event.set()
                return False

            if hasattr(key, 'char') and key.char in ['r', 'R']:
                now = time.time()
                if now - last_record_toggle_time > 0.5:
                    recording.toggle_recording()
                    last_record_toggle_time = now
                return

            if hasattr(key, 'char') and key.char in ['o', 'O']:
                changed, obj = recording.toggle_object()
                if changed:
                    print(f"\n[Object] Current object class set to: {obj}")
                else:
                    print("\n[Object] Cannot switch object class while recording — stop ('r') first.")
        except Exception:
            pass

    return on_press


# =============================================================================
# MAIN
# =============================================================================

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

    print(f"Initializing camera feed on {resolve(HAND_CAM_INDEX)} …", end=" ", flush=True)
    cap = open_camera(HAND_CAM_INDEX)
    if cap is None:
        print(f"\n[ERROR] Could not open {resolve(HAND_CAM_INDEX)}. Indices shift when "
              f"cameras re-enumerate — check `ls -l /dev/v4l/by-path/` and update "
              f"kernel/camera.py. Exiting.")
        return
    print("ready.")

    state = SharedState()
    recording = RecordingState(initial_object=args.object)
    left_sensor = TactileSensor("left", TACTILE_CAM_L)
    right_sensor = TactileSensor("right", TACTILE_CAM_R)
    haptic_link = HapticLink(ESP32_PORT, ESP32_BAUD)

    # Start the hardware background threads
    threads = [
        threading.Thread(target=status_loop, args=(gripper, state), daemon=True),
        threading.Thread(target=motion_loop, args=(gripper, state), daemon=True),
        threading.Thread(target=sensor_haptic_loop, args=(left_sensor, state.left), daemon=True),
        threading.Thread(target=sensor_haptic_loop, args=(right_sensor, state.right), daemon=True),
        threading.Thread(target=haptic_send_loop, args=(haptic_link, state, args.haptic_test), daemon=True),
        threading.Thread(target=log_loop, args=(gripper, recording, state, args.out, args.condition, args.participant), daemon=True),
    ]
    for t in threads:
        t.start()

    print(f"\n  [Controls] Press 'r' anywhere to start/stop recording a trial.")
    print(f"  [Controls] Press 'o' anywhere to toggle object class (fragile/deformable) when not recording.")
    print(f"  [Controls] Press 'q' anywhere to quit.\n")

    listener = keyboard.Listener(on_press=make_key_handler(recording))
    listener.start()

    model_path = 'hand_landmarker.task'
    if not os.path.exists(model_path):
        model_path = os.path.join(os.path.dirname(__file__), 'hand_landmarker.task')

    if not os.path.exists(model_path):
        print(f"\n[ERROR] '{model_path}' not found!")
        stop_event.set()
        return

    detector = create_hand_detector(model_path)

    hand_tracking_loop(cap, detector, state, recording, stop_event)

    print("\nStopping Window & Threads …")
    stop_event.set()
    listener.stop()
    for t in threads:
        t.join(timeout=1.0)
    detector.close()
    cap.release()
    gripper.close()
    cv2.destroyAllWindows()
    print("Done.")


if __name__ == "__main__":
    main()
