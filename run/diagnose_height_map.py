"""
diagnose_height_map.py — Inspect the intermediate values in
Sensor.raw_image_2_height_map() to find the source of speckled/noisy
reconstructions.

Usage:
    python diagnose_height_map.py --side left
    python diagnose_height_map.py --side right

Saves to <out>/ (default: diagnostics/<side>/):
    ref_gray.png         - reference frame (grayscale)
    current_gray.png      - current frame (grayscale)
    diff_raw.png          - ref - current, scaled for visibility
    diff_raw_stats.txt    - min/max/mean/std of diff_raw, and Pixel_to_Depth info
    height_map.png        - resulting height map, scaled for visibility
"""

import os
import sys
import argparse
import threading
import cv2
import yaml
import numpy as np

_repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_tact_main_dir = os.path.join(_repo_root, "src", "9DTact-main")
if _tact_main_dir not in sys.path:
    sys.path.insert(0, _tact_main_dir)

CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATHS = {
    'left': os.path.join(CONFIG_DIR, "shape_config_left.yaml"),
    'right': os.path.join(CONFIG_DIR, "shape_config_right.yaml"),
}

TACTILE_CAM_L = 4
TACTILE_CAM_R = 2

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


def setup_camera(side):
    if side == 'left':
        thread_local.camera_index_override = TACTILE_CAM_L
    elif side == 'right':
        thread_local.camera_index_override = TACTILE_CAM_R


def load_cfg(side):
    with open(CONFIG_PATHS[side], 'r', encoding='utf-8') as f:
        return yaml.load(f, Loader=yaml.FullLoader)


def scale_for_display(arr):
    """Min-max scale an array to 0-255 uint8 for visualization."""
    arr = arr.astype(np.float64)
    lo, hi = arr.min(), arr.max()
    if hi - lo < 1e-9:
        return np.zeros_like(arr, dtype=np.uint8)
    scaled = (arr - lo) / (hi - lo) * 255.0
    return scaled.astype(np.uint8)


def main():
    parser = argparse.ArgumentParser(description="Diagnose height map pipeline.")
    parser.add_argument("--side", choices=["left", "right"], required=True)
    parser.add_argument("--out", default=None, help="Output directory (default: diagnostics/<side>)")
    args = parser.parse_args()

    out_dir = args.out or os.path.join(CONFIG_DIR, "diagnostics", args.side)
    os.makedirs(out_dir, exist_ok=True)

    from shape_reconstruction import Sensor

    setup_camera(args.side)
    cfg = load_cfg(args.side)
    sensor = Sensor(cfg)

    print(f"pixel_per_mm = {sensor.pixel_per_mm}")
    print(f"lighting_threshold = {sensor.lighting_threshold}")
    print(f"max_index = {sensor.max_index}")
    print(f"Pixel_to_Depth.shape = {sensor.Pixel_to_Depth.shape}")
    print(f"Pixel_to_Depth[0:10] = {sensor.Pixel_to_Depth[:10]}")
    print(f"Pixel_to_Depth min/max = {sensor.Pixel_to_Depth.min()}, {sensor.Pixel_to_Depth.max()}")

    cv2.imwrite(os.path.join(out_dir, "ref_gray.png"), sensor.ref_GRAY)

    print("\nCapturing current frame (no contact, hands off sensor)...")
    img = sensor.get_rectify_crop_image()
    img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    cv2.imwrite(os.path.join(out_dir, "current_gray.png"), img_gray)

    diff_raw = sensor.ref_GRAY.astype(np.int32) - img_gray.astype(np.int32) - sensor.lighting_threshold
    cv2.imwrite(os.path.join(out_dir, "diff_raw.png"), scale_for_display(diff_raw))

    stats_path = os.path.join(out_dir, "diff_raw_stats.txt")
    with open(stats_path, "w") as f:
        f.write(f"pixel_per_mm = {sensor.pixel_per_mm}\n")
        f.write(f"lighting_threshold = {sensor.lighting_threshold}\n")
        f.write(f"max_index = {sensor.max_index}\n\n")
        f.write(f"diff_raw (ref - current - lighting_threshold), no contact:\n")
        f.write(f"  min  = {diff_raw.min()}\n")
        f.write(f"  max  = {diff_raw.max()}\n")
        f.write(f"  mean = {diff_raw.mean():.4f}\n")
        f.write(f"  std  = {diff_raw.std():.4f}\n\n")
        f.write(f"Pixel_to_Depth shape = {sensor.Pixel_to_Depth.shape}\n")
        f.write(f"Pixel_to_Depth[0:15] = {sensor.Pixel_to_Depth[:15]}\n")
        f.write(f"Pixel_to_Depth min/max = {sensor.Pixel_to_Depth.min()}, {sensor.Pixel_to_Depth.max()}\n")

    print(f"\ndiff_raw (no contact) stats:")
    print(f"  min={diff_raw.min()}  max={diff_raw.max()}  mean={diff_raw.mean():.4f}  std={diff_raw.std():.4f}")
    print("\nIf std is large (e.g. > 1-2) with NOTHING touching the sensor, the")
    print("camera/lighting noise floor exceeds lighting_threshold, and")
    print("Pixel_to_Depth[diff] will produce nonzero 'depth' from pure noise")
    print("-> speckled height map unrelated to actual contact.")

    height_map = sensor.raw_image_2_height_map(img_gray)
    cv2.imwrite(os.path.join(out_dir, "height_map.png"), scale_for_display(height_map))
    print(f"\nheight_map (no contact) stats:")
    print(f"  min={height_map.min():.4f}  max={height_map.max():.4f}  "
          f"mean={height_map.mean():.4f}  std={height_map.std():.4f}")
    print("\nIdeally, with nothing touching the sensor, height_map should be")
    print("close to all-zero (small std). A large std here confirms noise-driven")
    print("speckle independent of lighting_threshold tuning alone.")

    print(f"\nAll diagnostics saved to {out_dir}/")
    sensor.cap.release()


if __name__ == '__main__':
    main()
