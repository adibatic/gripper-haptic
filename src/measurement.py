"""
measurement.py — Tactile grip-force data collection WITHOUT a force sensor.

WHY THIS EXISTS
---------------
The previous pipeline used the Robotiq gripper motor current (gCU register) as a
1D force label. That signal reads 0 mA regardless of contact, so it is unusable
as a training target. This script replaces it with a grip-force *proxy* derived
straight from the 9DTact gel deformation -- no gripper current, no 6-axis F/T
sensor, no ROS required.

WHAT IT MEASURES
----------------
At startup it averages a few no-contact frames into a per-pixel `baseline`
height map. Then for every frame:

    deformation   = height_map - baseline           # per-pixel, mm
    contact_mask  = |deformation| > contact_thresh   # mm
    volume        = sum(|deformation| over contact)  # <- headline force proxy
    area_px       = number of contact pixels
    max_deform_mm = 99th-percentile deformation (robust peak)
    mean_deform_mm= mean deformation over the contact region

`volume` is monotonic with normal force for a roughly elastic gel and is the
best single scalar to treat as "grip effort".

IMPORTANT CAVEATS
-----------------
* These numbers are UNCALIBRATED. They are proportional to force, not Newtons.
  To get real units, press the sensor onto a load cell (HX711 + cell, ~$8) at a
  few known forces and fit  F_newtons = a * volume + b. That linear fit is your
  calibration; apply it afterward.
* For *deformable* objects the gel deformation mixes grip force with the object's
  own compliance, so read `volume` as contact intensity / grip effort, not as a
  clean force, unless calibrated against a known load.

OUTPUTS
-------
    <out>/images/<idx>.npy   -> height map (float32, HxW, mm)   [archived for later]
    <out>/force_proxy.csv    -> idx, t, volume, area_px, max_deform_mm,
                                 mean_deform_mm[, gripper_pos_bit]

USAGE
-----
    python src/measurement.py --side left --out data/left --rate 20 --duration 30 --show
    python src/measurement.py --side left --out data/left --gripper-port /dev/ttyUSB0
"""

import os
import sys
import csv
import time
import argparse
import threading
from collections import deque

import cv2
import yaml
import numpy as np

# ---------------------------------------------------------------------------
# Path setup — ensure src/9DTact-main and scripts/ (config.py, yaml configs)
# are importable/reachable from here.
# ---------------------------------------------------------------------------
_repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_tact_main_dir = os.path.join(_repo_root, "src", "9DTact-main")
_scripts_dir = os.path.join(_repo_root, "scripts")
if _tact_main_dir not in sys.path:
    sys.path.insert(0, _tact_main_dir)
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

CONFIG_DIR = _scripts_dir   # shape_config_*.yaml live in scripts/, not here
CONFIG_PATHS = {
    'left': os.path.join(CONFIG_DIR, "shape_config_left.yaml"),
    'right': os.path.join(CONFIG_DIR, "shape_config_right.yaml"),
}

# ---------------------------------------------------------------------------
# Camera indices — set once in scripts/config.py, shared with calibration.py
# and experiment.py.
# ---------------------------------------------------------------------------
from config import TACTILE_CAM_L, TACTILE_CAM_R

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
            image = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
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


def grab_height_map(sensor):
    """One frame -> float32 height map (mm)."""
    img = sensor.get_rectify_crop_image()
    img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return sensor.raw_image_2_height_map(img_gray).astype(np.float32)


def capture_baseline(sensor, n_frames):
    """Average n_frames of (assumed) no-contact height maps into a per-pixel baseline."""
    print(f"Capturing baseline over {n_frames} frames — keep the sensor untouched...")
    acc = None
    for _ in range(n_frames):
        hm = grab_height_map(sensor)
        acc = hm if acc is None else acc + hm
    baseline = acc / float(n_frames)
    print("Baseline captured.")
    return baseline


def compute_metrics(height_map, baseline, contact_thresh):
    """Return (volume, area_px, max_deform_mm, mean_deform_mm, abs_deformation)."""
    deform = height_map - baseline
    absdef = np.abs(deform)
    mask = absdef > contact_thresh
    area_px = int(mask.sum())
    if area_px > 0:
        contact_vals = absdef[mask]
        volume = float(contact_vals.sum())
        max_deform = float(np.percentile(contact_vals, 99))
        mean_deform = float(contact_vals.mean())
    else:
        volume = max_deform = mean_deform = 0.0
    return volume, area_px, max_deform, mean_deform, absdef


def draw_rolling_plot(values, width=640, height=200, label="force proxy"):
    """Lightweight OpenCV-drawn rolling line plot (no matplotlib in the live loop)."""
    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    if len(values) >= 2:
        vmax = max(max(values), 1e-6)
        n = len(values)
        pts = []
        for i, v in enumerate(values):
            x = int(i / (n - 1) * (width - 1))
            y = int((height - 1) - (v / vmax) * (height - 1))
            pts.append((x, y))
        cv2.polylines(canvas, [np.array(pts, np.int32)], False, (0, 255, 0), 1)
    txt = f"{label}: {values[-1]:.1f}" if values else label
    cv2.putText(canvas, txt, (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
    return canvas


def main():
    parser = argparse.ArgumentParser(description="Collect tactile deformation-based grip-force proxy data.")
    parser.add_argument("--side", choices=["left", "right"], required=True)
    parser.add_argument("--out", required=True, help="Output directory for this sensor's data.")
    parser.add_argument("--rate", type=float, default=20.0, help="Sampling rate in Hz.")
    parser.add_argument("--duration", type=float, default=30.0, help="Collection duration in seconds.")
    parser.add_argument("--baseline-frames", type=int, default=30,
                        help="Frames averaged for the no-contact baseline at startup.")
    parser.add_argument("--contact-thresh", type=float, default=0.1,
                        help="Per-pixel deformation (mm) above which a pixel counts as contact.")
    parser.add_argument("--save-images", action="store_true", default=True,
                        help="Archive raw height maps (.npy) for possible later supervised training.")
    parser.add_argument("--no-save-images", dest="save_images", action="store_false")
    parser.add_argument("--show", action="store_true", help="Show live depth map + rolling proxy plot.")
    parser.add_argument("--gripper-port", default=None,
                        help="Optional: also log gripper position (gPO). Current is NOT used.")
    args = parser.parse_args()

    from shape_reconstruction import Sensor

    setup_camera(args.side)
    cfg = load_cfg(args.side)
    sensor = Sensor(cfg)

    gripper = None
    if args.gripper_port is not None:
        from pyrobotiqgripper import RobotiqGripper
        gripper = RobotiqGripper(portname=args.gripper_port)
        if not gripper.isActivated():
            print("Activating gripper (keep hands clear)...")
            gripper.activate()

    baseline = capture_baseline(sensor, args.baseline_frames)

    img_dir = os.path.join(args.out, "images")
    if args.save_images:
        os.makedirs(img_dir, exist_ok=True)
    else:
        os.makedirs(args.out, exist_ok=True)
    csv_path = os.path.join(args.out, "force_proxy.csv")

    print(f"Collecting [{args.side.upper()}] at {args.rate} Hz for {args.duration} s -> {args.out}")
    print("Start pressing / closing onto the object now.")

    period = 1.0 / args.rate
    n_steps = int(args.duration * args.rate)
    plot_buf = deque(maxlen=int(args.rate * 10))  # last ~10 s of the proxy

    header = ["idx", "t", "volume", "area_px", "max_deform_mm", "mean_deform_mm"]
    if gripper is not None:
        header.append("gripper_pos_bit")

    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)

        t_start = time.time()
        try:
            for idx in range(n_steps):
                t0 = time.time()

                height_map = grab_height_map(sensor)
                volume, area_px, max_deform, mean_deform, absdef = compute_metrics(
                    height_map, baseline, args.contact_thresh)

                position_bit = None
                if gripper is not None:
                    gripper.readAll()
                    position_bit = gripper.paramDic["gPO"]

                t = time.time() - t_start
                row = [idx, t, volume, area_px, max_deform, mean_deform]
                if position_bit is not None:
                    row.append(position_bit)
                writer.writerow(row)

                if args.save_images:
                    np.save(os.path.join(img_dir, f"{idx:06d}.npy"), height_map)

                plot_buf.append(volume)

                if idx % int(args.rate) == 0:
                    print(f"  [{idx}/{n_steps}]  volume={volume:9.1f}  area={area_px:6d}px  "
                          f"max={max_deform:.2f}mm")

                if args.show:
                    depth_vis = sensor.height_map_2_depth_map(absdef)
                    cv2.imshow(f"Deformation [{args.side}]", depth_vis)
                    cv2.imshow("Force proxy (volume)",
                               draw_rolling_plot(list(plot_buf), label="volume"))
                    if cv2.waitKey(1) == ord('q'):
                        print("\nStopped early by user.")
                        break

                elapsed = time.time() - t0
                sleep_time = period - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)
        finally:
            sensor.cap.release()
            cv2.destroyAllWindows()

    print(f"Done. Wrote metrics to {csv_path}")
    if args.save_images:
        print(f"Archived height maps to {img_dir}/")
    print("\nReminder: 'volume' is an UNCALIBRATED force proxy. To convert to Newtons,")
    print("press onto a load cell at known forces and fit F = a*volume + b.")


if __name__ == "__main__":
    main()