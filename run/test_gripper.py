"""
test_gripper.py  —  host PC
High-FPS Hand-Tracking & Keyboard-controlled Robotiq 2F-85 (no haptic feedback).

  GLOBAL CONTROLS:
  m      →  toggle automatic hand-tracking mode (with debounce protection)
  q      →  quit program
  ↑ / k  →  open gripper (Manual mode only)
  ↓ / j  →  close gripper (Manual mode only)
"""

import time
import math
import threading
import cv2
import mediapipe as mp
from pynput import keyboard

# MediaPipe Tasks imports
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'src'))

from pyrobotiqgripper import RobotiqGripper

# ------------------------------------------------------------------ CONFIG ---
GRIPPER_PORT    = "/dev/ttyUSB0"

# Advanced Vision Tuning (Pinch Tracking)
PINCH_DIST_PX   = 15      
SPREAD_DIST_PX  = 90      
SMOOTHING_ALPHA = 0.25    

MAX_POS         = 225     
SPEED           = 200     
FORCE           = 100     
MOTION_HZ       = 25      # Gripper command send rate

# ---------------------------------------------------------------------------
# Camera index — update this at the start of each session
# ---------------------------------------------------------------------------
HAND_CAM_INDEX  = 0   # Hand-tracking webcam (/dev/videoX)
# ---------------------------------------------------------------------------

gripper_lock = threading.Lock()
motion_mode_active = False
stop_event = threading.Event()

# Shared variable so the camera loop doesn't have to wait for the serial port
shared_target_pos = 0.0 

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
    """Background thread for printing gripper position/state."""
    interval = 1.0 / 10
    while not stop_event.is_set():
        t0 = time.monotonic()
        try:
            with gripper_lock:
                gripper.readAll()
            pos  = gripper.paramDic["gPO"]
            mode_str = "HAND TRACKING" if motion_mode_active else "MANUAL KEYBOARD"
            print(f"\r  [Hardware] Pos: {pos:3d}/{MAX_POS} | Mode: {mode_str}      ", end="", flush=True)
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
            if abs(final_pos - last_sent_pos) > 2:
                move_nonblocking(gripper, final_pos)
                last_sent_pos = final_pos

        elapsed = time.monotonic() - t0
        time.sleep(max(0.0, interval - elapsed))


def open_camera(index: int):
    cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
    if not cap.isOpened():
        return None
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
    
    print(f"Connecting to gripper on {GRIPPER_PORT} …", end=" ", flush=True)
    gripper = RobotiqGripper(GRIPPER_PORT)

    gripper.readAll()
    if gripper.paramDic.get("gSTA") != 3:
        gripper.reset()
        time.sleep(0.5)
        gripper.activate()
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

    print(f"\n  [Controls] Press 'm' anywhere to toggle tracking mode.")
    print(f"  [Controls] Press 'q' anywhere to quit.\n")

    current_direction = None
    last_toggle_time = 0.0

    def on_press(key):
        nonlocal current_direction, last_toggle_time
        global motion_mode_active
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
        min_hand_detection_confidence=0.5,
        min_hand_presence_confidence=0.6,
        min_tracking_confidence=0.6,
        running_mode=vision.RunningMode.VIDEO
    )
    detector = vision.HandLandmarker.create_from_options(options)
    
    smoothed_target_pos = 0.0
    stream_start_time = time.time() 

    while not stop_event.is_set():
        ret, frame = cap.read()
        if not ret:
            break

        frame = cv2.flip(frame, 1)
        
        small_frame = cv2.resize(frame, (0, 0), fx=0.5, fy=0.5)
        rgb_small = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)
        
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_small)
        frame_timestamp_ms = int((time.time() - stream_start_time) * 1000)
        
        results = detector.detect_for_video(mp_image, frame_timestamp_ms)
        current_dist = -1
        
        if results.hand_landmarks:
            for hand_landmarks in results.hand_landmarks:
                h, w, c = small_frame.shape
                
                thumb = hand_landmarks[4]
                index = hand_landmarks[8]
                
                cx1, cy1 = int(thumb.x * w), int(thumb.y * h)
                cx2, cy2 = int(index.x * w), int(index.y * h)
                current_dist = math.hypot(cx2 - cx1, cy2 - cy1)
                
                cx1_full, cy1_full = cx1 * 2, cy1 * 2
                cx2_full, cy2_full = cx2 * 2, cy2 * 2
                
                cv2.circle(frame, (cx1_full, cy1_full), 8, (255, 0, 255), cv2.FILLED)
                cv2.circle(frame, (cx2_full, cy2_full), 8, (255, 0, 255), cv2.FILLED)
                cv2.line(frame, (cx1_full, cy1_full), (cx2_full, cy2_full), (255, 0, 255), 2)
                break 

        if motion_mode_active:
            if current_dist != -1:
                if current_dist <= PINCH_DIST_PX:
                    raw_target = MAX_POS
                elif current_dist >= SPREAD_DIST_PX:
                    raw_target = 0
                else:
                    pct = 1.0 - ((current_dist - PINCH_DIST_PX) / (SPREAD_DIST_PX - PINCH_DIST_PX))
                    raw_target = int(pct * MAX_POS)
            else:
                raw_target = int(smoothed_target_pos)
            
            # Update the smoothed pos
            smoothed_target_pos = (SMOOTHING_ALPHA * raw_target) + ((1.0 - SMOOTHING_ALPHA) * smoothed_target_pos)
            
            # INSTANTLY hand this off to the background thread without waiting!
            shared_target_pos = smoothed_target_pos
        else:
            try:
                smoothed_target_pos = gripper.paramDic.get("gPO", 0)
                shared_target_pos = smoothed_target_pos
            except Exception:
                pass

        # GUI
        overlay = frame.copy()
        cv2.rectangle(overlay, (15, 15), (320, 100), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)

        mode_text = "MODE: HAND TRACKING" if motion_mode_active else "MODE: MANUAL"
        mode_color = (0, 255, 0) if motion_mode_active else (255, 150, 0)
        cv2.putText(frame, mode_text, (25, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.6, mode_color, 2)
        cv2.putText(frame, f"Target Pos: {int(smoothed_target_pos)} / {MAX_POS}", (25, 65), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        
        dist_text = f"Finger Dist: {int(current_dist)}px" if current_dist != -1 else "Finger Dist: No Hand"
        cv2.putText(frame, dist_text, (25, 85), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        cv2.imshow("Robotic Gripper Vision Feed", frame)
        cv2.waitKey(1)

    print("\nStopping Window & Threads …")
    stop_event.set()
    listener.stop()
    status_thread.join(timeout=1.0)
    motion_thread.join(timeout=1.0)
    detector.close()
    cap.release()
    cv2.destroyAllWindows()
    print("Done.")

if __name__ == "__main__":
    main()