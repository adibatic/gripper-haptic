"""
tactile.py

9DTact tactile sensing: turns one sensor's gel deformation into a grip-force
proxy. Shared by experiment.py (live, both sensors) and setup.py (standalone
tools), so both measure exactly the same quantity.

Both sensors read one shared run/shape_config.yaml; load_config() injects the
per-side sensor_id, which is what points each at its own calibration data.
"""

import os
import time
import cv2
from dataclasses import dataclass
import multiprocessing as mp
import numpy as np
import yaml
from camera import thread_local # Importing camera.py also activates the per-sensor VideoCapture routing

CONTACT_THRESH_MM   = 0.1       # Per-pixel deformation counting as contact
LOW_DEFORM_THRESH_MM = 0.03     # Sensitive threshold for fragile/deformable
                                # objects — they barely indent the gel, so the
                                # standalone force-proxy collection uses this to
                                # register low-deformation contact the trial-time
                                # CONTACT_THRESH_MM would miss.
BASELINE_FRAMES     = 30        # Frames averaged for zeroing
DEPTH_SATURATION_MM = 2.0       # Depth mapped to haptic intensity 1.0


@dataclass
class TactileReading:
    """Live values for one sensor, updated by experiment.py's sensor thread."""
    intensity: float = 0.0
    max_depth_mm: float = 0.0
    force_proxy: float = 0.0

class SharedTactileReading:
    """Same read interface as TactileReading (.intensity/.max_depth_mm/
    .force_proxy), but backed by shared memory so a separate PROCESS — not
    just a thread — can write it. A thread-based sensor loop shares memory
    for free, but its per-frame rectify/height-map math is CPU-bound enough
    to starve the main process's GIL, which stalls the Qt hand-tracking
    window even though the vision loop itself keeps running."""

    def __init__(self):
        self._values = mp.Array('d', 3)  # intensity, max_depth_mm, force_proxy

    @property
    def intensity(self) -> float:
        return self._values[0]

    @property
    def max_depth_mm(self) -> float:
        return self._values[1]

    @property
    def force_proxy(self) -> float:
        return self._values[2]

    def set(self, intensity: float, max_depth_mm: float, force_proxy: float):
        with self._values.get_lock():
            self._values[0] = intensity
            self._values[1] = max_depth_mm
            self._values[2] = force_proxy

# =============================================================================
# CONFIG
# =============================================================================

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CONFIG_PATH = os.path.join(_REPO_ROOT, "run", "shape_config.yaml")

# Derived from _REPO_ROOT rather than read from shape_config.yaml, so a cloned
# or renamed repo directory can never leave a stale absolute path behind.
CALIBRATION_ROOT_DIR = os.path.join(_REPO_ROOT, "data", "calibration")

# Per-side values. Add here rather than forking the YAML, so shared values
# (BallRad, crop_size, thresholds) cannot drift apart between left and right.
SIDE_OVERRIDES = {
    'left':  {'sensor_id': 'L'},
    'right': {'sensor_id': 'R'},
}


def _deep_merge(base, override):
    """Recursively merges `override` into a copy of `base`."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(side: str, config_path: str = None):
    """Loads the shared config with `side`'s overrides applied.

    Returns:
        Merged config dict, ready for Sensor(cfg) / Camera(cfg).
    """
    if side not in SIDE_OVERRIDES:
        raise KeyError(f"side must be 'left' or 'right', got {side!r}")

    path = config_path or CONFIG_PATH
    if not os.path.exists(path):
        raise FileNotFoundError(f"Shared sensor config not found: {path}")

    with open(path, 'r', encoding='utf-8') as f:
        cfg = yaml.load(f, Loader=yaml.FullLoader)

    # Overridden here (not read from the YAML) so a renamed/relocated repo
    # can't leave a stale absolute path pointing at a directory that no
    # longer exists.
    cfg['calibration_root_dir'] = CALIBRATION_ROOT_DIR

    return _deep_merge(cfg, SIDE_OVERRIDES[side])


# =============================================================================
# SENSING
# =============================================================================

def grab_height_map(sensor):
    """Reads one frame from `sensor` and returns its height map (mm)."""
    img = sensor.get_rectify_crop_image()
    img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return sensor.raw_image_2_height_map(img_gray).astype(np.float32)


def capture_baseline(sensor, n_frames):
    """Averages n_frames of no-contact height maps into a per-pixel baseline."""
    print(f"Capturing baseline over {n_frames} frames — keep the sensor untouched...")
    acc = None
    for _ in range(n_frames):
        hm = grab_height_map(sensor)
        acc = hm if acc is None else acc + hm
    print("Baseline captured.")
    return acc / float(n_frames)


def compute_metrics(height_map, baseline, contact_thresh):
    """Turns one height map into the grip-force proxy metrics.

    `volume` (the sum of |deformation| over the contact region) is the headline
    proxy: monotonic with normal force, but UNCALIBRATED. On deformable objects
    it mixes grip force with the object's own compliance, so treat it as contact
    intensity unless calibrated (setup.py calibrate-force).

    Returns:
        (volume, area_px, max_deform_mm, mean_deform_mm, abs_deformation).
        max_deform_mm is the 99th percentile — a peak robust to hot pixels.
    """
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


# =============================================================================
# VALIDATION
# =============================================================================

def validate_calibration(cfg, label=""):
    """Checks a side's calibration exists and its crop window fits the image.

    Both failures are otherwise silent: a missing file dies later with an opaque
    error, and an oversized crop is truncated by NumPy without warning — making
    that side integrate force over a smaller area than the other, which biases
    every left/right comparison.

    Returns:
        A list of warning strings (empty if the crop is clean).

    Raises:
        FileNotFoundError: If any calibration .npy is missing.
    """
    sensor_dir = os.path.join(cfg['calibration_root_dir'], 'sensor_' + str(cfg['sensor_id']))
    cam_dir = sensor_dir + cfg['camera_calibration']['camera_calibration_dir']
    depth_dir = sensor_dir + cfg['depth_calibration']['depth_calibration_dir']

    required = {
        'row_index': cam_dir + cfg['camera_calibration']['row_index_path'],
        'col_index': cam_dir + cfg['camera_calibration']['col_index_path'],
        'position_scale': cam_dir + cfg['camera_calibration']['position_scale_path'],
        'Pixel_to_Depth': depth_dir + cfg['depth_calibration']['Pixel_to_Depth_path'],
    }
    missing = [name for name, path in required.items() if not os.path.exists(path)]
    if missing:
        raise FileNotFoundError(
            f"[{label}] missing calibration file(s): {', '.join(missing)}.\n"
            f"  Run: python run/setup.py calibrate-camera --side {label}\n"
            f"       python run/setup.py calibrate-sensor --side {label}")

    warnings = []

    # row_index is the remap grid, so its shape is the image's shape.
    row_index = np.load(required['row_index'])
    img_h, img_w = row_index.shape[:2]

    # Frames are no longer rotated, so calibration produced under the old
    # rotating capture has its axes swapped and is unusable — catch it here
    # rather than let it silently produce a garbage height map.
    cam_w, cam_h = cfg['camera_setting']['resolution']
    if (img_h, img_w) != (cam_h, cam_w):
        raise ValueError(
            f"[{label}] STALE CALIBRATION: stored grid is {img_h}x{img_w}, but the "
            f"camera gives {cam_h}x{cam_w}. This data was calibrated when frames "
            f"were rotated 90 degrees; rotation has since been removed, so it is "
            f"invalid.\n"
            f"  Delete data/calibration/sensor_{cfg['sensor_id']}/ and redo BOTH steps:\n"
            f"    python run/setup.py calibrate-camera --side {label}\n"
            f"    python run/setup.py calibrate-sensor --side {label}")

    position_scale = np.load(required['position_scale'])
    center_row, center_col = position_scale[0], position_scale[1]
    crop_h, crop_w = cfg['camera_calibration']['crop_size']

    h_begin, h_end = int(center_row - crop_h / 2), int(center_row + crop_h / 2)
    w_begin, w_end = int(center_col - crop_w / 2), int(center_col + crop_w / 2)

    actual_h = min(h_end, img_h) - max(h_begin, 0)
    actual_w = min(w_end, img_w) - max(w_begin, 0)

    if actual_h != crop_h or actual_w != crop_w:
        warnings.append(
            f"[{label}] CROP TRUNCATED: window rows[{h_begin}:{h_end}] "
            f"cols[{w_begin}:{w_end}] does not fit the {img_h}x{img_w} rectified "
            f"image. Delivered crop is {actual_h}x{actual_w}, not {crop_h}x{crop_w} "
            f"— this side will under-read force relative to the other.\n"
            f"  -> Recalibrate this side with the contact region centred, or "
            f"reduce crop_size in shape_config.yaml so the window fits.")

    return warnings


# =============================================================================
# HARDWARE INTERFACE
# =============================================================================

class TactileSensor:
    """One live 9DTact sensor: connects it, zeroes it, and reads the proxy."""

    def __init__(self, side: str, camera_index):
        self.side = side            # "left" or "right"
        self.label = side
        self.camera_index = camera_index
        self.sensor = None
        self.baseline = None

    def connect(self, max_retries: int = 8, retry_delay: float = 1.5):
        from shape_reconstruction import Sensor

        # thread_local so this sensor's own process opens the right camera.
        thread_local.camera_index_override = self.camera_index
        cfg = load_config(self.side)

        for problem in validate_calibration(cfg, self.label):
            print(f"\n[Tactile][WARNING] {problem}\n")

        last_msg = None
        for attempt in range(1, max_retries + 1):
            try:
                self.sensor = Sensor(cfg)
                return
            except (TypeError, RuntimeError, OSError) as e:
                # Only keep the message, not the exception object: holding the
                # exception (and its traceback) alive across the loop would
                # keep the failed attempt's half-opened cv2.VideoCapture alive
                # too — via the traceback's stack frames — leaving the device
                # "busy" on the very next open() attempt.
                last_msg = str(e)
                print(f"[Tactile][WARNING] {self.label} camera not ready yet "
                      f"(attempt {attempt}/{max_retries}): {last_msg}", flush=True)
            # Back off a bit more each retry so a still-busy USB hub gets more
            # time to settle instead of hammering it at a fixed interval.
            time.sleep(retry_delay + 0.5 * attempt)
        raise RuntimeError(
            f"{self.label} tactile camera never became ready after {max_retries} "
            f"attempts: {last_msg}"
        )

    def _height_map(self):
        return grab_height_map(self.sensor)

    def capture_baseline(self, frames: int = BASELINE_FRAMES):
        self.baseline = capture_baseline(self.sensor, frames)

    def read(self):
        """Returns (intensity, max_depth_mm, force_proxy) for the current frame."""
        height_map = self._height_map()
        volume, _, max_deform, _, _ = compute_metrics(height_map, self.baseline, CONTACT_THRESH_MM)
        intensity = max(0.0, min(1.0, max_deform / DEPTH_SATURATION_MM))
        return intensity, max_deform, volume

    @property
    def is_open(self) -> bool:
        return self.sensor is not None and self.sensor.cap.isOpened()

    def close(self):
        if self.sensor is not None:
            try:
                self.sensor.cap.release()
            except Exception:
                pass
