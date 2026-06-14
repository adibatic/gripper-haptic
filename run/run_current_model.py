"""
run_current_model.py — Apply a trained TactileCurrentNet to a live 9DTact
sensor feed, optionally logging alongside the actual gripper current for
comparison during grasping experiments.

Usage:
    python run_current_model.py --side left --model models/left/model.pt --log left_log.csv
    python run_current_model.py --side left --model models/left/model.pt --log left_log.csv --gripper-port /dev/ttyUSB0
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
import torch
import torch.nn as nn

_repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_tact_main_dir = os.path.join(_repo_root, "src", "9DTact-main")
if _tact_main_dir not in sys.path:
    sys.path.insert(0, _tact_main_dir)
if os.path.join(_repo_root, "src") not in sys.path:
    sys.path.insert(0, os.path.join(_repo_root, "src"))

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shape_config.yaml")

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


def load_cfg():
    if not os.path.exists(CONFIG_PATH):
        fallback = os.path.join(_repo_root, "shape_config.yaml")
        if os.path.exists(fallback):
            return yaml.load(open(fallback, 'r', encoding='utf-8'), Loader=yaml.FullLoader)
        print("Error: Could not find shape_config.yaml anywhere.")
        sys.exit(1)
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return yaml.load(f, Loader=yaml.FullLoader)


def setup_camera(side: str):
    if side == 'left':
        thread_local.camera_index_override = TACTILE_CAM_L
    elif side == 'right':
        thread_local.camera_index_override = TACTILE_CAM_R


class TactileCurrentNet(nn.Module):
    def __init__(self, in_channels=1):
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(in_channels, 16, 5, stride=2, padding=2), nn.BatchNorm2d(16), nn.ReLU(inplace=True),
            nn.Conv2d(16, 32, 5, stride=2, padding=2), nn.BatchNorm2d(32), nn.ReLU(inplace=True),
            nn.Conv2d(32, 64, 3, stride=2, padding=1), nn.BatchNorm2d(64), nn.ReLU(inplace=True),
            nn.Conv2d(64, 64, 3, stride=2, padding=1), nn.BatchNorm2d(64), nn.ReLU(inplace=True),
            nn.AdaptiveAvgPool2d((1, 1)),
        )
        self.head = nn.Sequential(
            nn.Flatten(),
            nn.Linear(64, 32), nn.ReLU(inplace=True),
            nn.Linear(32, 1),
        )

    def forward(self, x):
        x = self.features(x)
        return self.head(x).squeeze(-1)


def main():
    parser = argparse.ArgumentParser(description="Run trained tactile current model on live sensor feed.")
    parser.add_argument("--side", choices=["left", "right"], required=True)
    parser.add_argument("--model", required=True, help="Path to model.pt from train_current_model.py")
    parser.add_argument("--log", default=None, help="Optional CSV path to log predictions over time")
    parser.add_argument("--gripper-port", default=None,
                         help="If set, also reads the gripper's actual current (gCU) for live comparison.")
    args = parser.parse_args()

    from shape_reconstruction import Sensor

    setup_camera(args.side)
    cfg = load_cfg()
    sensor = Sensor(cfg)

    gripper = None
    if args.gripper_port is not None:
        from pyrobotiqgripper import RobotiqGripper
        gripper = RobotiqGripper(portname=args.gripper_port)
        if not gripper.isActivated():
            print("Activating gripper (keep hands clear)...")
            gripper.activate()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    ckpt = torch.load(args.model, map_location=device)

    model = TactileCurrentNet().to(device)
    model.load_state_dict(ckpt["model_state"])
    model.eval()

    img_mean, img_std = ckpt["img_mean"], ckpt["img_std"]
    cur_mean, cur_std = ckpt["cur_mean"], ckpt["cur_std"]

    log_file = None
    writer = None
    if args.log:
        log_file = open(args.log, "w", newline="")
        writer = csv.writer(log_file)
        header = ["t", "predicted_current_mA"]
        if gripper is not None:
            header.append("measured_current_mA")
        writer.writerow(header)

    print(f"Running current model on [{args.side.upper()}] sensor. Press 'q' to quit.")
    try:
        while sensor.cap.isOpened():
            img = sensor.get_rectify_crop_image()
            img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            height_map = sensor.raw_image_2_height_map(img_gray).astype(np.float32)

            x = (height_map - img_mean) / img_std
            x = torch.from_numpy(x).unsqueeze(0).unsqueeze(0).to(device)

            with torch.no_grad():
                pred_norm = float(model(x).cpu().numpy())
            pred_current = pred_norm * cur_std + cur_mean

            measured_current = None
            if gripper is not None:
                gripper.readAll()
                measured_current = gripper.paramDic["gCU"] * 10.0
                print(f"predicted={pred_current:7.1f} mA   measured={measured_current:7.1f} mA", end="\r")
            else:
                print(f"predicted current = {pred_current:7.1f} mA", end="\r")

            if writer is not None:
                row = [time.time(), pred_current]
                if measured_current is not None:
                    row.append(measured_current)
                writer.writerow(row)
                log_file.flush()

            depth_vis = sensor.height_map_2_depth_map(height_map)
            cv2.imshow(f"DepthMap [{args.side}]", depth_vis)
            if cv2.waitKey(1) == ord('q'):
                break
    finally:
        sensor.cap.release()
        cv2.destroyAllWindows()
        if log_file is not None:
            log_file.close()
            print(f"\nLog saved to {args.log}")


if __name__ == "__main__":
    main()
