"""
experiment.py — host PC, run in the `hapticf` conda env.

Hand-tracking & keyboard-controlled Robotiq 2F-85, with a 9DTact tactile
sensor (left finger) driving real-time LRA vibmotor haptic feedback on
the ESP32-C6. All dependencies (minimalmodbus, open3d, torch, mediapipe,
pyserial, pynput) are installed in the single `hapticf` conda environment
via requirements.txt — no separate .venv or 9dtact env needed.

  GLOBAL CONTROLS:
  m      →  toggle automatic hand-tracking mode (with debounce protection)
  q      →  quit program
  ↑ / k  →  open gripper (Manual mode only)
  ↓ / j  →  close gripper (Manual mode only)

HAPTIC FEEDBACK:
  The left 9DTact sensor's height map is read continuously. Intensity is
  computed as max(height_map) / DEPTH_SATURATION_MM, clamped to [0,1], and
  streamed at HAPTIC_HZ to /dev/ttyACM0 using the TEXT protocol — one float
  per line, f"{intensity:.4f}\\n" — matching test_haptic.py's
  run_vibmotor_stream() receiver. The board applies the value to every
  finger in its FINGERS list. If experiment.py stops sending (e.g. on
  exit/crash), the ESP32's stream-mode watchdog drops intensity to 0.

  NOTE: the ESP32 must be running the AC-drive stream receiver
  (ACDriver / bipolar carrier in test_haptic.py). The old PWM-duty path
  produced no motion on this actuator. Verify actual motor movement AND a
  rising force_proxy under contact in a throwaway recorded trial on a fresh
  boot before running any participant.

PREREQUISITES (see README):
  - src/calibration.py calibrate-camera/calibrate-sensor --side left
    completed successfully (run/calibration/sensor_L/... populated —
    this "run/" path is internal to the 9DTact library, not a repo folder)
  - ESP32-C6 running the AC-drive stream receiver (test_haptic.py with
    MODE="stream", or your dedicated board-side stream script) via mpremote repl
  - Robotiq gripper connected on /dev/ttyUSB0
  - hapticf conda env active (all deps in requirements.txt)

IMPORTANT — CAMERA INDEX REQUIREMENT:
  calibration.py's RotatedVideoCapture proxy (reused here) applies
  rotation/flip corrections keyed on TACTILE_CAM_L / TACTILE_CAM_R. The
  hand-tracking webcam (HAND_CAM_INDEX) is opened through the SAME proxy
  (cv2.VideoCapture is monkey-patched globally), so:

    HAND_CAM_INDEX must NOT equal TACTILE_CAM_L or TACTILE_CAM_R.

  If it does, the hand-tracking feed will be incorrectly rotated/flipped
  as if it were a tactile sensor. Update HAND_CAM_INDEX, TACTILE_CAM_L
  below to match your actual /dev/videoX devices before running.
"""

import os
import sys
import math
import struct
import threading
import time
import csv
import argparse

import cv2
import yaml
import numpy as np
import mediapipe as mp
from pynput import keyboard
import serial

from mediapipe.tasks import python
from mediapipe.tasks.python import vision

_repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_tact_main_dir = os.path.join(_repo_root, "src", "9DTact-main")
if _tact_main_dir not in sys.path:
    sys.path.insert(0, _tact_main_dir)
if os.path.join(_repo_root, "src") not in sys.path:
    sys.path.insert(0, os.path.join(_repo_root, "src"))

from pyrobotiqgripper import RobotiqGripper

# ------------------------------------------------------------------ CONFIG ---
GRIPPER_PORT     = "/dev/ttyUSB0"
ESP32_PORT       = "/dev/ttyACM0"
ESP32_BAUD       = 115200

# Advanced Vision Tuning (Pinch Tracking)
# Vision Tracking & MediaPipe Stabilizer — EXACTLY as in test_gripper.py
# (full-resolution pixels; the tracking loop below processes full frames)
PINCH_DIST_PX        = 30        # Range: 10 to 60
SPREAD_DIST_PX       = 180       # Range: 120 to 280
FINGER_DEADBAND_PX   = 1.5       # kills raw MediaPipe webcam jitter

# Motion Processing Profile — EXACTLY as in test_gripper.py
SMOOTHING_ALPHA      = 0.45      # higher = more instantaneous tracking
INPUT_GATE_THRESHOLD = 2         # filters tremors before they become targets
OUTPUT_DEADBAND      = 3         # filters motor stutter when hand is stationary

MAX_POS          = 225
SPEED            = 200
FORCE            = 100
MOTION_HZ        = 25      # Gripper command send rate

# Haptic feedback (left 9DTact sensor -> vibmotors)
HAPTIC_HZ            = 30      # sensor read + serial send rate
DEPTH_SATURATION_MM  = 2.6     # height_map value (mm) that maps to intensity 1.0
                                # (left sensor Pixel_to_Depth range ~1.33-2.60mm;
                                #  tune based on your calibration / object set)

# Deformation-based grip-force proxy (replaces the dead gCU motor current).
# volume = sum of |height_map - baseline| over pixels exceeding CONTACT_THRESH_MM.
CONTACT_THRESH_MM = 0.1   # per-pixel deformation (mm) counted as contact
BASELINE_FRAMES   = 30    # no-contact frames averaged into the baseline at startup
# Optional volume -> Newton calibration from src/measurement.py (README 3c).
# Leave as None to log raw volume; set both to also log a force_N column.
FORCE_CAL_A = None
FORCE_CAL_B = None

# ---------------------------------------------------------------------------
# Camera indices — set once in config.py (same folder as this file), shared
# with src/calibration.py and src/measurement.py. HAND_CAM_INDEX must not
# equal either tactile index (see CAMERA INDEX REQUIREMENT note above);
# checked at startup below.
# ---------------------------------------------------------------------------
from config import HAND_CAM_INDEX, TACTILE_CAM_L, TACTILE_CAM_R

CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
LEFT_CONFIG_PATH = os.path.join(CONFIG_DIR, "shape_config_left.yaml")

gripper_lock = threading.Lock()
motion_mode_active = False
stop_event = threading.Event()

# Shared variable so the camera loop doesn't have to wait for the serial port
shared_target_pos = 0.0

# Shared haptic intensity (0.0-1.0), updated by sensor_haptic_loop,
# read by the haptic_send_loop. Single float, GIL-protected read/write
# is sufficient here (no lock needed for a single float assignment).
shared_intensity = 0.0

# Shared raw max depth (mm), updated alongside shared_intensity, logged
# separately so the recorded CSV preserves the unsaturated physical value
# even if DEPTH_SATURATION_MM is later retuned.
shared_max_depth_mm = 0.0

# Shared deformation-based grip-force proxy (volume), updated alongside
# shared_intensity and logged in place of the now-zero motor current.
shared_force_proxy = 0.0

# When True (--haptic-test), haptic_send_loop ignores the tactile sensor and
# streams a slow 0->1->0 ramp instead — a known-good self-test that proves the
# ESP32 link + motors work from inside experiment.py, isolating the sender from
# the tactile intensity source.
haptic_test_mode = False

# Recording state (toggled with 'r'). When active, log_loop writes one row
# per HAPTIC_HZ tick to the current trial's CSV.
recording_active = False
trial_number = 0
log_lock = threading.Lock()

# Current object class label, included in trial filenames. Defaults to
# --object at startup; can be switched mid-session with the 'o' key
# (see Section 4.2/4.3 — each condition block includes both object classes).
current_object = "fragile"


# ---------------------------------------------------------------------------
# RotatedVideoCapture — same proxy as src/calibration.py, reused so the
# left 9DTact sensor reads correctly via Sensor(cfg).
# ---------------------------------------------------------------------------
thread_local = threading.local()
_real_video_capture = cv2.VideoCapture


class RotatedVideoCapture:
    def __init__(self, index, *args, **kwargs):
        self.index = index
        self.cap = _real_video_capture(index, *args, **kwargs)

    def _apply_corrections(self, image):
        if image is None:
            return image
        if self.index == TACTILE_CAM_L:
            image = cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
        elif self.index == TACTILE_CAM_R:
            image = cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
            image = cv2.flip(image, 0)
            image = cv2.flip(image, 1)
        return image

    def read(self, *args, **kwargs):
        retval, image = self.cap.read(*args, **kwargs)
        if retval:
            image = self._apply_corrections(image)
        return retval, image

    def retrieve(self, *args, **kwargs):
        retval, image = self.cap.retrieve(*args, **kwargs)
        if retval:
            image = self._apply_corrections(image)
        return retval, image

    def __getattr__(self, attr):
        return getattr(self.cap, attr)


def intercepted_video_capture(index, *args, **kwargs):
    override_index = getattr(thread_local, 'camera_index_override', None)
    if override_index is not None:
        return RotatedVideoCapture(override_index, *args, **kwargs)
    return RotatedVideoCapture(index, *args, **kwargs)


cv2.VideoCapture = intercepted_video_capture


def setup_left_sensor_camera():
    thread_local.camera_index_override = TACTILE_CAM_L


# ---------------------------------------------------------------------------
# Gripper helpers (from test_gripper.py)
# ---------------------------------------------------------------------------

def move_nonblocking(gripper: RobotiqGripper, position: int, speed: int = SPEED, force: int = FORCE):
    position = max(0, min(MAX_POS, position))
    with gripper_lock:
        gripper.write_registers(1000, [
            0b0000100100000000,
            position,
            speed * 0x100 + force,
        ])


def stop_moving(gripper: RobotiqGripper):
    with gripper_lock:
        gripper.write_registers(1000, [
            0b0000000100000000,
            0,
            0,
        ])


def status_loop(gripper: RobotiqGripper):
    """Background thread for printing gripper position/state + haptic intensity."""
    interval = 1.0 / 10
    while not stop_event.is_set():
        t0 = time.monotonic()
        try:
            with gripper_lock:
                gripper.readAll()
                pos = gripper.paramDic["gPO"]
            mode_str = "HAND TRACKING" if motion_mode_active else "MANUAL KEYBOARD"
            print(f"\r  [Hardware] Pos: {pos:3d}/{MAX_POS} | Mode: {mode_str} "
                  f"| Haptic: {shared_intensity:4.2f} | Fp: {shared_force_proxy:6.0f}   ",
                  end="", flush=True)
        except Exception:
            pass

        elapsed = time.monotonic() - t0
        time.sleep(max(0.0, interval - elapsed))


def motion_loop(gripper: RobotiqGripper):
    """Background thread: continuously sends the latest target position to the hardware."""
    global shared_target_pos
    interval = 1.0 / MOTION_HZ
    last_sent_pos = -1

    while not stop_event.is_set():
        t0 = time.monotonic()

        if motion_mode_active:
            final_pos = int(shared_target_pos)
            if abs(final_pos - last_sent_pos) > OUTPUT_DEADBAND:
                move_nonblocking(gripper, final_pos)
                last_sent_pos = final_pos

        elapsed = time.monotonic() - t0
        time.sleep(max(0.0, interval - elapsed))


# ---------------------------------------------------------------------------
# 9DTact sensor + haptic feedback loops
# ---------------------------------------------------------------------------

def sensor_haptic_loop():
    """Background thread: reads the left 9DTact sensor's height map and
    updates shared_intensity based on the deepest current deformation.

    intensity = clip(height_map.max() / DEPTH_SATURATION_MM, 0, 1)
    """
    global shared_intensity, shared_max_depth_mm, shared_force_proxy

    from shape_reconstruction import Sensor

    sensor = None
    try:
        setup_left_sensor_camera()
        with open(LEFT_CONFIG_PATH, 'r', encoding='utf-8') as f:
            cfg = yaml.load(f, Loader=yaml.FullLoader)
        sensor = Sensor(cfg)

        # MJPG on the tactile cam too — same USB-bandwidth reason as the hand
        # cam. Set after open; if the driver ignores a mid-stream change and
        # the hand video still stalls, lower this cam's resolution/FPS instead.
        try:
            sensor.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        except Exception:
            pass

        # No-contact baseline for the deformation force proxy (matches
        # src/measurement.py). Keep the sensor untouched at startup.
        print("\n[Haptic] Capturing tactile baseline — keep the left sensor untouched ...")
        _acc = None
        for _ in range(BASELINE_FRAMES):
            _img = sensor.get_rectify_crop_image()
            _hm = sensor.raw_image_2_height_map(
                cv2.cvtColor(_img, cv2.COLOR_BGR2GRAY)).astype(np.float32)
            _acc = _hm if _acc is None else _acc + _hm
        baseline = _acc / float(BASELINE_FRAMES)
        print("[Haptic] Baseline captured.")

        interval = 1.0 / HAPTIC_HZ
        print("[Haptic] Left 9DTact sensor ready, driving vibmotor intensity.")

        while not stop_event.is_set() and sensor.cap.isOpened():
            t0 = time.monotonic()

            img = sensor.get_rectify_crop_image()
            img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            height_map = sensor.raw_image_2_height_map(img_gray)

            max_depth = float(height_map.max())
            intensity = max(0.0, min(1.0, max_depth / DEPTH_SATURATION_MM))

            # Deformation-based grip-force proxy (sum of |deformation| over the
            # contact region) — logged in place of the dead motor current.
            absdef = np.abs(height_map.astype(np.float32) - baseline)
            contact = absdef > CONTACT_THRESH_MM
            volume = float(absdef[contact].sum()) if contact.any() else 0.0

            shared_intensity = intensity
            shared_max_depth_mm = max_depth
            shared_force_proxy = volume

            elapsed = time.monotonic() - t0
            time.sleep(max(0.0, interval - elapsed))
    except Exception as e:
        # A daemon thread dying silently is why intensity/force_proxy can
        # freeze at 0 with no error. Make that impossible to miss.
        print(f"\n[Haptic][ERROR] sensor thread died: {e}")
        print(f"  -> Haptic intensity and force_proxy are now FROZEN at their last value.")
        print(f"  -> Most likely the tactile camera (TACTILE_CAM_L={TACTILE_CAM_L}) "
              f"stopped returning frames. Check the index / USB bandwidth.")
        import traceback
        traceback.print_exc()
    finally:
        if sensor is not None:
            try:
                sensor.cap.release()
            except Exception:
                pass


def haptic_send_loop():
    """Background thread: sends shared_intensity to the ESP32 over serial
    using the text protocol — one float per line, "f{intensity:.4f}\\n" —
    matching test_haptic.py's run_vibmotor_stream() receiver. The board
    applies the single value to every finger in its FINGERS list.
    """
    try:
        ser = serial.Serial(ESP32_PORT, ESP32_BAUD, timeout=0.1)
    except Exception as e:
        print(f"\n[Haptic] WARNING: could not open {ESP32_PORT} ({e}). "
              f"Haptic feedback disabled.")
        return

    interval = 1.0 / HAPTIC_HZ
    if haptic_test_mode:
        print(f"[Haptic] *** SELF-TEST MODE *** streaming a 0->1->0 ramp on "
              f"{ESP32_PORT}, ignoring the tactile sensor. Motors should pulse.")
    else:
        print(f"[Haptic] Streaming to ESP32 on {ESP32_PORT} @ {HAPTIC_HZ} Hz.")

    _warned_write = False
    _t_start = time.monotonic()
    try:
        while not stop_event.is_set():
            t0 = time.monotonic()
            if haptic_test_mode:
                # Known-good ramp: 0 -> 1 over 2 s, 1 -> 0 over 2 s, repeat.
                phase = (time.monotonic() - _t_start) % 4.0
                intensity = phase / 2.0 if phase < 2.0 else (4.0 - phase) / 2.0
            else:
                intensity = shared_intensity
            # Text protocol: one float per line, matching test_haptic.py's
            # run_vibmotor_stream() (sys.stdin.readline() + float()).
            packet = f"{intensity:.4f}\n".encode("utf-8")
            try:
                ser.write(packet)
            except Exception as e:
                if not _warned_write:
                    print(f"\n[Haptic][ERROR] serial write failed: {e} "
                          f"(further write errors suppressed)")
                    _warned_write = True
            elapsed = time.monotonic() - t0
            time.sleep(max(0.0, interval - elapsed))
    finally:
        # Send a final zero so the ESP32 settles to off promptly,
        # though the 200ms watchdog would also handle this.
        try:
            ser.write(b"0.0000\n")
        except Exception:
            pass
        ser.close()


def log_loop(gripper: RobotiqGripper, out_dir: str, condition: str, participant: str):
    """Background thread: while recording_active is True, writes one row
    per HAPTIC_HZ tick to a per-trial CSV under out_dir.

    Columns: t (seconds since trial start), gripper_pos_bit, force_proxy,
    force_N, max_depth_mm, haptic_intensity, motion_mode (hand_tracking/manual).
    force_proxy is the deformation volume; force_N is its calibrated Newton
    value (empty unless FORCE_CAL_A/B are set). The old motor-current column is
    gone — gCU read 0 mA on this gripper.

    A new trial file is started each time recording is toggled on with 'r'.
    The object class active at that moment (current_object, switched with
    'o') is baked into the filename, matching the per-object trial design
    in thesis Section 4.2/4.3:
    Filenames: <out_dir>/<participant>_<condition>_<object>_trial<N>.csv
    Note: <N> is a simple per-session counter across ALL trials in this
    run, not reset per object — the object class is read from the
    filename itself, not inferred from N.
    """
    global trial_number

    interval = 1.0 / HAPTIC_HZ
    os.makedirs(out_dir, exist_ok=True)

    csv_file = None
    writer = None
    trial_start = None
    was_recording = False
    trial_object = None

    try:
        while not stop_event.is_set():
            t0 = time.monotonic()

            with log_lock:
                is_recording = recording_active

            if is_recording and not was_recording:
                # Recording just started — open a new trial file, locking
                # in the object class as of this moment so a mid-trial
                # 'o' press doesn't relabel an in-progress trial.
                trial_number += 1
                trial_object = current_object
                fname = f"{participant}_{condition}_{trial_object}_trial{trial_number}.csv"
                fpath = os.path.join(out_dir, fname)
                csv_file = open(fpath, "w", newline="")
                writer = csv.writer(csv_file)
                writer.writerow(["t", "gripper_pos_bit", "force_proxy", "force_N",
                                  "max_depth_mm", "haptic_intensity", "motion_mode"])
                trial_start = time.monotonic()
                print(f"\n[Log] Recording trial {trial_number} ({trial_object}) -> {fpath}")

            elif not is_recording and was_recording:
                # Recording just stopped — close the file
                if csv_file is not None:
                    csv_file.close()
                    print(f"\n[Log] Trial {trial_number} saved.")
                csv_file = None
                writer = None

            if is_recording and writer is not None:
                try:
                    with gripper_lock:
                        gripper.readAll()
                        pos = gripper.paramDic.get("gPO", -1)
                except Exception:
                    pos = -1

                volume = shared_force_proxy
                if FORCE_CAL_A is not None and FORCE_CAL_B is not None:
                    force_N = f"{FORCE_CAL_A * volume + FORCE_CAL_B:.4f}"
                else:
                    force_N = ""

                t = time.monotonic() - trial_start
                mode_str = "hand_tracking" if motion_mode_active else "manual"
                writer.writerow([f"{t:.4f}", pos, f"{volume:.4f}", force_N,
                                  f"{shared_max_depth_mm:.4f}", f"{shared_intensity:.4f}",
                                  mode_str])
                csv_file.flush()

            was_recording = is_recording

            elapsed = time.monotonic() - t0
            time.sleep(max(0.0, interval - elapsed))
    finally:
        if csv_file is not None:
            csv_file.close()


# ---------------------------------------------------------------------------
# Hand-tracking camera
# ---------------------------------------------------------------------------

def open_camera(index: int):
    cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
    if not cap.isOpened():
        return None
    # MJPG (compressed) instead of raw frames so the hand cam and the tactile
    # cam can share one USB controller without starving each other.
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    ret, _ = cap.read()
    if not ret:
        cap.release()
        return None
    return cap


def main():
    global motion_mode_active
    global shared_target_pos
    global current_object
    global haptic_test_mode

    parser = argparse.ArgumentParser(description="Integrated gripper + 9DTact + haptic feedback experiment.")
    parser.add_argument("--condition", required=True, choices=["visual_only", "lra", "tactiles"],
                         help="Feedback condition for this run, used in trial filenames. "
                              "Note: this only labels the data — actual LRA vs TacTiles "
                              "hardware behavior is determined by which firmware is running "
                              "on the ESP32 (haptic_stream.py drives LRA; for TacTiles, the "
                              "ESP32 must run the TacTiles equivalent). For 'visual_only', "
                              "either disconnect the ESP32 or note that sent intensities are "
                              "ignored by the operator.")
    parser.add_argument("--participant", required=True, help="Participant ID, used in trial filenames.")
    parser.add_argument("--object", default="fragile", choices=["fragile", "deformable"],
                         help="Starting object class label for trial filenames. "
                              "Switch mid-session with the 'o' key (does not affect "
                              "an in-progress recording).")
    parser.add_argument("--out", default=os.path.join(CONFIG_DIR, "..", "data", "experiment_logs"),
                         help="Directory to save trial CSVs.")
    parser.add_argument("--haptic-test", action="store_true",
                         help="Ignore the tactile sensor and stream a 0->1->0 ramp to the "
                              "ESP32 — proves the haptic link/motors work from inside "
                              "experiment.py. Use to isolate 'no haptic' (sender vs sensor).")
    args = parser.parse_args()

    current_object = args.object
    haptic_test_mode = args.haptic_test

    if HAND_CAM_INDEX == TACTILE_CAM_L or HAND_CAM_INDEX == TACTILE_CAM_R:
        print(f"[ERROR] HAND_CAM_INDEX ({HAND_CAM_INDEX}) must differ from "
              f"TACTILE_CAM_L ({TACTILE_CAM_L}) / TACTILE_CAM_R ({TACTILE_CAM_R}). "
              f"See module docstring. Exiting.")
        return

    if not os.path.exists(LEFT_CONFIG_PATH):
        print(f"[ERROR] {LEFT_CONFIG_PATH} not found. Run src/calibration.py "
              f"calibrate-camera/calibrate-sensor --side left first. Exiting.")
        return

    print(f"Connecting to gripper on {GRIPPER_PORT} …", end=" ", flush=True)
    gripper = RobotiqGripper(GRIPPER_PORT)

    gripper.readAll()
    if gripper.paramDic.get("gSTA") != 3:
        # Do NOT auto reset/activate here — activation runs a full close/open
        # calibration cycle, unwanted at experiment startup. Activate once
        # beforehand (e.g. run test_gripper.py) if this warning appears.
        print("\n[WARNING] Gripper not activated (gSTA != 3). Skipping auto-activation; "
              "movement commands may be ignored. Activate first (e.g. via test_gripper.py).")
    print("ready.")

    print(f"Initializing camera feed on /dev/video{HAND_CAM_INDEX} …", end=" ", flush=True)
    cap = open_camera(HAND_CAM_INDEX)
    if cap is None:
        print(f"\n[ERROR] Could not open /dev/video{HAND_CAM_INDEX}. Update HAND_CAM_INDEX and retry. Exiting.")
        return
    print("ready.")

    # Start the hardware background threads
    status_thread = threading.Thread(target=status_loop, args=(gripper,), daemon=True)
    status_thread.start()

    motion_thread = threading.Thread(target=motion_loop, args=(gripper,), daemon=True)
    motion_thread.start()

    sensor_thread = threading.Thread(target=sensor_haptic_loop, daemon=True)
    sensor_thread.start()

    haptic_thread = threading.Thread(target=haptic_send_loop, daemon=True)
    haptic_thread.start()

    log_thread = threading.Thread(
        target=log_loop, args=(gripper, args.out, args.condition, args.participant), daemon=True)
    log_thread.start()

    print(f"\n  [Controls] Press 'm' anywhere to toggle tracking mode.")
    print(f"  [Controls] Press 'r' anywhere to start/stop recording a trial.")
    print(f"  [Controls] Press 'o' anywhere to toggle object class (fragile/deformable) when not recording.")
    print(f"  [Controls] Press 'q' anywhere to quit.\n")

    current_direction = None
    last_toggle_time = 0.0
    last_record_toggle_time = 0.0

    def on_press(key):
        nonlocal current_direction, last_toggle_time, last_record_toggle_time
        global motion_mode_active, recording_active, current_object
        try:
            if hasattr(key, 'char') and key.char in ['q', 'Q']:
                stop_event.set()
                return False

            if hasattr(key, 'char') and key.char in ['m', 'M']:
                now = time.time()
                if now - last_toggle_time > 0.5:
                    motion_mode_active = not motion_mode_active
                    last_toggle_time = now
                    stop_moving(gripper)
                return

            if hasattr(key, 'char') and key.char in ['r', 'R']:
                now = time.time()
                if now - last_record_toggle_time > 0.5:
                    with log_lock:
                        recording_active = not recording_active
                    last_record_toggle_time = now
                return

            if hasattr(key, 'char') and key.char in ['o', 'O']:
                with log_lock:
                    if recording_active:
                        print("\n[Object] Cannot switch object class while recording — stop ('r') first.")
                    else:
                        current_object = "deformable" if current_object == "fragile" else "fragile"
                        print(f"\n[Object] Current object class set to: {current_object}")
                return

            if motion_mode_active:
                return

            is_close = (hasattr(key, 'char') and key.char == 'j') or key == keyboard.Key.down
            if is_close and current_direction != 'closing':
                current_direction = 'closing'
                move_nonblocking(gripper, MAX_POS)

            is_open = (hasattr(key, 'char') and key.char == 'k') or key == keyboard.Key.up
            if is_open and current_direction != 'opening':
                current_direction = 'opening'
                move_nonblocking(gripper, 0)
        except Exception:
            pass

    def on_release(key):
        nonlocal current_direction
        global motion_mode_active
        try:
            if motion_mode_active:
                return
            is_close = (hasattr(key, 'char') and key.char == 'j') or key == keyboard.Key.down
            is_open = (hasattr(key, 'char') and key.char == 'k') or key == keyboard.Key.up

            if (is_close and current_direction == 'closing') or (is_open and current_direction == 'opening'):
                current_direction = None
                stop_moving(gripper)
        except Exception:
            pass

    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()

    model_path = 'hand_landmarker.task'
    if not os.path.exists(model_path):
        model_path = os.path.join(os.path.dirname(__file__), 'hand_landmarker.task')

    if not os.path.exists(model_path):
        print(f"\n[ERROR] '{model_path}' not found!")
        stop_event.set()
        return

    base_options = python.BaseOptions(model_asset_path=model_path)
    options = vision.HandLandmarkerOptions(
        base_options=base_options,
        num_hands=1,
        min_hand_detection_confidence=0.6,
        min_hand_presence_confidence=0.75,
        min_tracking_confidence=0.75,
        running_mode=vision.RunningMode.VIDEO
    )
    detector = vision.HandLandmarker.create_from_options(options)

    smoothed_target_pos = 0.0
    last_committed_target = 0.0
    stable_dist = -1.0
    last_frame_ts_ms = -1

    while not stop_event.is_set():
        ret, frame = cap.read()
        if not ret:
            print(f"\n[Vision][ERROR] cap.read() failed on /dev/video{HAND_CAM_INDEX} — "
                  f"hand camera feed died. Likely USB bandwidth contention with the "
                  f"tactile camera (common right at startup, during baseline capture). "
                  f"Exiting hand-tracking loop.")
            break

        frame = cv2.flip(frame, 1)
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
        # MediaPipe VIDEO mode requires strictly increasing timestamps. Wall-clock
        # ms can repeat on a fast frame and raise; force monotonicity.
        frame_timestamp_ms = int(time.monotonic() * 1000)
        if frame_timestamp_ms <= last_frame_ts_ms:
            frame_timestamp_ms = last_frame_ts_ms + 1
        last_frame_ts_ms = frame_timestamp_ms

        results = detector.detect_for_video(mp_image, frame_timestamp_ms)
        current_dist = -1

        if results.hand_landmarks:
            for hand_landmarks in results.hand_landmarks:
                h, w, c = frame.shape

                thumb = hand_landmarks[4]
                index_finger = hand_landmarks[8]

                cx1, cy1 = int(thumb.x * w), int(thumb.y * h)
                cx2, cy2 = int(index_finger.x * w), int(index_finger.y * h)
                raw_measured_dist = math.hypot(cx2 - cx1, cy2 - cy1)

                # Finger deadband: ignore sub-pixel MediaPipe jitter
                if stable_dist == -1.0:
                    stable_dist = raw_measured_dist
                elif abs(raw_measured_dist - stable_dist) > FINGER_DEADBAND_PX:
                    stable_dist = raw_measured_dist

                current_dist = stable_dist

                cv2.circle(frame, (cx1, cy1), 8, (255, 0, 255), cv2.FILLED)
                cv2.circle(frame, (cx2, cy2), 8, (255, 0, 255), cv2.FILLED)
                cv2.line(frame, (cx1, cy1), (cx2, cy2), (255, 0, 255), 2)
                break
        else:
            stable_dist = -1.0

        if motion_mode_active:
            if current_dist != -1:
                if current_dist <= PINCH_DIST_PX:
                    raw_target = MAX_POS
                elif current_dist >= SPREAD_DIST_PX:
                    raw_target = 0
                else:
                    pct = 1.0 - ((current_dist - PINCH_DIST_PX) / (SPREAD_DIST_PX - PINCH_DIST_PX))
                    raw_target = int(pct * MAX_POS)

                # Input gate: only commit a new target if it moved enough
                if abs(raw_target - last_committed_target) > INPUT_GATE_THRESHOLD:
                    last_committed_target = float(raw_target)
            else:
                last_committed_target = smoothed_target_pos

            smoothed_target_pos = (SMOOTHING_ALPHA * last_committed_target) + ((1.0 - SMOOTHING_ALPHA) * smoothed_target_pos)

            # Snap when close so the gripper settles instead of creeping
            if abs(smoothed_target_pos - last_committed_target) < 1.0:
                smoothed_target_pos = last_committed_target

            shared_target_pos = smoothed_target_pos
        else:
            try:
                smoothed_target_pos = gripper.paramDic.get("gPO", 0)
                shared_target_pos = smoothed_target_pos
            except Exception:
                pass

        # GUI
        overlay = frame.copy()
        cv2.rectangle(overlay, (15, 15), (320, 140), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)

        mode_text = "MODE: HAND TRACKING" if motion_mode_active else "MODE: MANUAL"
        mode_color = (0, 255, 0) if motion_mode_active else (255, 150, 0)
        cv2.putText(frame, mode_text, (25, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.6, mode_color, 2)
        cv2.putText(frame, f"Target Pos: {int(smoothed_target_pos)} / {MAX_POS}", (25, 65), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        dist_text = f"Finger Dist: {int(current_dist)}px" if current_dist != -1 else "Finger Dist: No Hand"
        cv2.putText(frame, dist_text, (25, 85), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        cv2.putText(frame, f"Haptic Intensity: {shared_intensity:.2f}", (25, 105), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        rec_text = f"REC trial {trial_number} ({current_object})" if recording_active else f"Not recording — object: {current_object} (press 'r')"
        rec_color = (0, 0, 255) if recording_active else (180, 180, 180)
        cv2.putText(frame, rec_text, (25, 125), cv2.FONT_HERSHEY_SIMPLEX, 0.5, rec_color, 1)

        cv2.imshow("Robotic Gripper Vision Feed", frame)
        cv2.waitKey(1)

    print("\nStopping Window & Threads …")
    stop_event.set()
    listener.stop()
    status_thread.join(timeout=1.0)
    motion_thread.join(timeout=1.0)
    sensor_thread.join(timeout=1.0)
    haptic_thread.join(timeout=1.0)
    log_thread.join(timeout=1.0)
    detector.close()
    cap.release()
    cv2.destroyAllWindows()
    print("Done.")


if __name__ == "__main__":
    main()