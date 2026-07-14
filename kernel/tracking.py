"""
tracking.py

Hand tracking: maps thumb-index pinch distance to a gripper target position.

hand_tracking_loop is the experiment's foreground loop — experiment.py's main()
blocks on it and passes in the shared stop_event. `state` / `recording` are
experiment.py's SharedState / RecordingState, duck-typed here so this module
doesn't import experiment.py back.

Keys: 'r' start/stop a trial, 'o' toggle object class, 'c' cycle condition,
SPACE pause/resume tracking, 'q' quit. 'c' and SPACE are gated by
`recording` (must be paused and not recording — see RecordingState in
experiment.py); a condition change that needs different ESP32 firmware walks
the operator through reflashing it via `haptic_link` (_handle_firmware_swap).
"""

from __future__ import annotations

# =============================================================================
# IMPORTS & SETUP
# =============================================================================

import cv2
import math
import time
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

# Camera index / gripper limit come from their owning modules (kernel/ is on
# sys.path via the entry point that imports this).
from camera import HAND_CAM_INDEX
from gripper import MAX_POS


# =============================================================================
# PARAMETERS
# =============================================================================

# Hand tracking
PINCH_DIST_PX      = 30         # Range: 10 to 60
SPREAD_DIST_PX     = 180        # Range: 120 to 280
FINGER_DEADBAND_PX = 1.5        # Suppresses raw MediaPipe webcam jitter

SMOOTHING_ALPHA      = 0.45     # Higher = more instantaneous tracking
INPUT_GATE_THRESHOLD = 2        # Filters tremors before they become targets


# =============================================================================
# CAMERA & DETECTOR
# =============================================================================

def open_camera(index: int):
    """Opens the hand camera. Returns None if it can't be opened or read."""
    cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
    if not cap.isOpened():
        return None
    # MJPG so the hand cam and tactile cams can share one USB controller
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    ret, _ = cap.read()
    if not ret:
        cap.release()
        return None
    return cap


def create_hand_detector(model_path: str):
    """Builds the MediaPipe hand landmarker (single hand, VIDEO mode)."""
    base_options = python.BaseOptions(model_asset_path=model_path)
    options = vision.HandLandmarkerOptions(
        base_options=base_options,
        num_hands=1,
        min_hand_detection_confidence=0.6,
        min_hand_presence_confidence=0.75,
        min_tracking_confidence=0.75,
        running_mode=vision.RunningMode.VIDEO
    )
    return vision.HandLandmarker.create_from_options(options)


# =============================================================================
# GUI OVERLAY
# =============================================================================

def _draw_overlay(frame, target_pos: float, finger_dist: float, state: SharedState,
                   active: bool, paused: bool, condition: str, current_object: str):
    """Draws the status box: target position, finger distance, haptics,
    recording/condition state, and the paused/live banner."""
    overlay = frame.copy()
    cv2.rectangle(overlay, (15, 15), (320, 160), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)

    cv2.putText(frame, f"Target Pos: {int(target_pos)} / {MAX_POS}", (25, 40),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

    dist_text = f"Finger Dist: {int(finger_dist)}px" if finger_dist != -1 else "Finger Dist: No Hand"
    cv2.putText(frame, dist_text, (25, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

    cv2.putText(frame, f"Haptic L (thumb): {state.left.intensity:.2f}", (25, 80),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    cv2.putText(frame, f"Haptic R (index): {state.right.intensity:.2f}", (25, 100),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

    rec_text = (f"REC ({condition}/{current_object})" if active
                else f"Not recording — {condition}/{current_object} (press 'r')")
    rec_color = (0, 0, 255) if active else (180, 180, 180)
    cv2.putText(frame, rec_text, (25, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.5, rec_color, 1)

    pause_text = "PAUSED (SPACE to resume)" if paused else "LIVE (SPACE to pause)"
    pause_color = (0, 165, 255) if paused else (0, 200, 0)
    cv2.putText(frame, pause_text, (25, 145), cv2.FONT_HERSHEY_SIMPLEX, 0.6, pause_color, 2)


# =============================================================================
# TRACKING LOOP
# =============================================================================

def _prompt_fragile_outcome(frame, recording):
    """Blocks (this thread only — the sensor processes keep running) until
    'y'/'n' answers whether the fragile object survived the trial just
    stopped, so log_loop can tag the saved CSV's filename."""
    prompt = frame.copy()
    cv2.rectangle(prompt, (15, 150), (620, 200), (0, 0, 0), -1)
    cv2.putText(prompt, "This fragile trial ended -- "
                "object survived intact? [Y]es / [N]o",
                (25, 180), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 1)
    cv2.imshow("Robotic Gripper Vision Feed", prompt)
    while True:
        key = cv2.waitKey(0) & 0xFF
        if key in (ord('y'), ord('Y')):
            return "success"
        if key in (ord('n'), ord('N')):
            return "break"


def _handle_firmware_swap(haptic_link, new_condition, new_firmware):
    """Walks the operator through reflashing the ESP32 when the new
    condition's CONDITION_FIRMWARE entry differs from the previous one.
    Releases the serial port so mpremote/esptool can use it (this process
    holds it exclusively otherwise), blocks until the operator confirms,
    then reopens it. The video window will look frozen for this duration —
    that's expected, tracking is paused and no frames are being pumped."""
    print(f"\n[Firmware] '{new_condition}' needs different ESP32 firmware than the "
          f"previous condition. Releasing {haptic_link.port} so it can be reflashed.")
    haptic_link.close()
    if new_firmware is None:
        print("  -> Physically disconnect the ESP32, or make sure its current firmware "
              "isn't wired to drive any actuator (visual_only should feel nothing).")
    else:
        print("  -> In another terminal:")
        print(f"       python -m mpremote connect {haptic_link.port} fs cp firmware/haptic.py :")
        print(f"       python -m mpremote connect {haptic_link.port} fs cp firmware/stream.py :")
        print(f"     Edit METHOD = \"{new_firmware}\" at the top of firmware/stream.py BEFORE "
              f"copying it, then in the REPL:")
        print("       exec(open('stream.py').read())")
        print("     Detach with Ctrl-X once it's running.")
    input("  Press ENTER here once the ESP32 is ready (reflashed/reconnected) to resume streaming... ")
    haptic_link.reconnect()
    print(f"[Firmware] Reopened {haptic_link.port}. Resume tracking with SPACE when ready.")


def hand_tracking_loop(cap, detector, state: SharedState, recording: RecordingState,
                        haptic_link, stop_event):
    """Runs until stop_event is set: maps each frame's pinch distance to
    state.target_pos (which motion_loop sends to the gripper) and draws the
    overlay."""
    smoothed_target_pos = 0.0
    last_committed_target = 0.0
    stable_dist = -1.0
    last_frame_ts_ms = -1
    last_record_toggle_time = 0.0

    cv2.namedWindow("Robotic Gripper Vision Feed", cv2.WINDOW_AUTOSIZE)
    cv2.startWindowThread()

    while not stop_event.is_set():
        ret, frame = cap.read()
        if not ret:
            print(f"\n[Vision][ERROR] cap.read() failed on {HAND_CAM_INDEX} — "
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

        active, paused, condition, current_object = recording.snapshot()
        if not paused:
            # Frozen while paused: the gripper holds its last commanded
            # position instead of chasing the hand during setup/reflash.
            state.target_pos = smoothed_target_pos

        _draw_overlay(frame, smoothed_target_pos, current_dist, state,
                      active, paused, condition, current_object)

        cv2.imshow("Robotic Gripper Vision Feed", frame)

        key = cv2.waitKey(1) & 0xFF
        if key in (ord('q'), ord('Q')):
            stop_event.set()
            break
        elif key == ord(' '):
            new_state = recording.toggle_pause()
            if new_state is None:
                print("\n[Pause] Cannot pause/resume while recording — stop the trial ('r') first.")
            else:
                print(f"\n[Pause] {'PAUSED' if new_state else 'RESUMED — tracking live'}")
        elif key in (ord('r'), ord('R')):
            now = time.time()
            if now - last_record_toggle_time > 0.5:
                active, _, _, current_object = recording.snapshot()
                if active and current_object == "fragile":
                    outcome = _prompt_fragile_outcome(frame, recording)
                    recording.toggle_recording(outcome=outcome)
                else:
                    result = recording.toggle_recording()
                    if result is None:
                        print("\n[Record] Cannot start recording while paused — press SPACE to resume first.")
                last_record_toggle_time = now
        elif key in (ord('o'), ord('O')):
            changed, obj = recording.toggle_object()
            if changed:
                print(f"\n[Object] Current object class set to: {obj}")
            else:
                print("\n[Object] Cannot switch object class while recording — stop ('r') first.")
        elif key in (ord('c'), ord('C')):
            result = recording.cycle_condition()
            if result is None:
                print("\n[Condition] Cannot cycle condition unless paused and not recording "
                      "— press SPACE to pause first.")
            else:
                new_condition, new_firmware, firmware_changed = result
                print(f"\n[Condition] Switched to: {new_condition}")
                if firmware_changed:
                    _handle_firmware_swap(haptic_link, new_condition, new_firmware)
