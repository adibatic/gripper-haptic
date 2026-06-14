"""
collect_current_data.py — Synchronized tactile depth map + Robotiq gripper
motor current (gCU) data collector. No ROS, no BOTA — host PC only.

For each timestep, saves:
    <out>/images/<idx>.npy   -> depth map (float32, HxW, mm)
    <out>/current.csv        -> idx, t, current_mA, gripper_pos_mm

Typical use: close the gripper slowly onto an object while one 9DTact
sensor records contact deformation. The gripper's instantaneous motor
current (gCU register, ~10x = mA) is logged as a 1D proxy for grip
effort/force.

Usage:
    python collect_current_data.py --side left --out data/left --rate 20 --duration 30
"""

import os
import sys
import csv
import time
import argparse
import threading
import cv2
import yaml
import numpy as np

_repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_tact_main_dir = os.path.join(_repo_root, "src", "9DTact-main")
if _tact_main_dir not in sys.path:
    sys.path.insert(0, _tact_main_dir)
if os.path.join(_repo_root, "src") not in sys.path:
    sys.path.insert(0, os.path.join(_repo_root, "src"))

CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATHS = {
    'left': os.path.join(CONFIG_DIR, "shape_config_left.yaml"),
    'right': os.path.join(CONFIG_DIR, "shape_config_right.yaml"),
}

# ---------------------------------------------------------------------------
# Camera index — update this at the start of each session
# ---------------------------------------------------------------------------
TACTILE_CAM_L = 4   # Left tactile sensor (/dev/videoX)
TACTILE_CAM_R = 2   # Right tactile sensor (/dev/videoX)
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


def load_cfg(side: str):
    config_path = CONFIG_PATHS[side]
    if not os.path.exists(config_path):
        print(f"Error: Could not find {config_path}")
        sys.exit(1)
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.load(f, Loader=yaml.FullLoader)


def setup_camera(side: str):
    if side == 'left':
        thread_local.camera_index_override = TACTILE_CAM_L
    elif side == 'right':
        thread_local.camera_index_override = TACTILE_CAM_R


def main():
    parser = argparse.ArgumentParser(description="Collect synchronized tactile depth + gripper current data.")
    parser.add_argument("--side", choices=["left", "right"], required=True,
                         help="Which 9DTact sensor to record from.")
    parser.add_argument("--out", required=True, help="Output directory for this sensor's data.")
    parser.add_argument("--rate", type=float, default=20.0, help="Sampling rate in Hz.")
    parser.add_argument("--duration", type=float, default=30.0, help="Collection duration in seconds.")
    parser.add_argument("--gripper-port", default="auto",
                         help="Serial port for Robotiq gripper (e.g. /dev/ttyUSB0), or 'auto'.")
    args = parser.parse_args()

    from shape_reconstruction import Sensor
    from pyrobotiqgripper import RobotiqGripper

    setup_camera(args.side)
    cfg = load_cfg(args.side)
    sensor = Sensor(cfg)

    print("Connecting to Robotiq gripper...")
    gripper = RobotiqGripper(portname=args.gripper_port)
    if not gripper.isActivated():
        print("Activating gripper (keep hands clear)...")
        gripper.activate()

    img_dir = os.path.join(args.out, "images")
    os.makedirs(img_dir, exist_ok=True)
    csv_path = os.path.join(args.out, "current.csv")

    print(f"Collecting [{args.side.upper()}] at {args.rate} Hz for {args.duration} s -> {args.out}")
    print("Start moving/closing the gripper now.")

    period = 1.0 / args.rate
    n_steps = int(args.duration * args.rate)

    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["idx", "t", "current_mA", "gripper_pos_bit", "image_file"])

        t_start = time.time()
        for idx in range(n_steps):
            t0 = time.time()

            img = sensor.get_rectify_crop_image()
            img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            height_map = sensor.raw_image_2_height_map(img_gray)

            # readAll() updates gripper.paramDic with gCU (current) and gPO (position)
            gripper.readAll()
            current_mA = gripper.paramDic["gCU"] * 10.0
            position_bit = gripper.paramDic["gPO"]

            t = time.time() - t_start
            img_file = f"{idx:06d}.npy"
            np.save(os.path.join(img_dir, img_file), height_map.astype(np.float32))
            writer.writerow([idx, t, current_mA, position_bit, img_file])

            if idx % int(args.rate) == 0:
                print(f"  [{idx}/{n_steps}]  current={current_mA:.0f} mA  pos={position_bit}")

            elapsed = time.time() - t0
            sleep_time = period - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    print(f"Done. Saved {n_steps} samples to {args.out}")


if __name__ == "__main__":
    main()