"""
setup.py

Per-sensor tooling for one 9DTact sensor. Run from the repo root:

    python run/setup.py calibrate-camera --side {left,right}   # 1: grid calibration
    python run/setup.py calibrate-sensor --side {left,right}   # 2: depth calibration
    python run/setup.py reconstruct      --side {left,right}   # 3: live viewer
    python run/setup.py collect          --side ... --out DIR  # 4: log the force proxy
    python run/setup.py calibrate-force  --side {left,right}   # 5: fit proxy -> Newtons

Steps 1 and 2 delegate to 9DTact's own CameraCalibration / SensorCalibration;
this file adds the per-side plumbing and verifies the result afterwards, since
a truncated crop or an all-NaN depth table otherwise passes silently.

The force proxy itself (grab_height_map / capture_baseline / compute_metrics)
lives in kernel/tactile.py, shared with experiment.py.

`--side both` for reconstruct is broken (OpenCV/Qt threading) — use two terminals.
"""

# =============================================================================
# IMPORTS & SETUP
# =============================================================================

# Standard library imports
import os
import sys
import csv
import time
import tempfile
import argparse
import threading
from collections import deque
from contextlib import contextmanager

# Third-party imports
import cv2
import yaml
import numpy as np

# ---------------------------------------------------------------------------
# Path setup — make the kernel modules and the bundled 9DTact library
# importable from here, then import with bare names.
# ---------------------------------------------------------------------------
_repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_kernel_dir = os.path.join(_repo_root, "kernel")
_tact_main_dir = os.path.join(_repo_root, "src", "9DTact-main")
for _p in (_kernel_dir, _tact_main_dir):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# The shared shape_config.yaml lives next to this file in run/, but it is owned
# by kernel/tactile.py (load_config injects each side's sensor_id) — see below.
CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))

# Camera indices / routing shared with experiment.py; importing
# camera.py activates the cv2.VideoCapture monkeypatch as a side effect.
from camera import TACTILE_CAM_L, TACTILE_CAM_R, thread_local  # noqa: E402
from tactile import (grab_height_map, capture_baseline, compute_metrics,  # noqa: E402
                     validate_calibration, load_config,
                     BASELINE_FRAMES, CONTACT_THRESH_MM)


# =============================================================================
# HELPERS
# =============================================================================

def load_cfg(side: str):
    """Loads the shared config with this side's overrides (kernel/tactile.py)."""
    try:
        return load_config(side)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)


def setup_camera(side: str):
    """Selects which camera the next Sensor(cfg)/Camera(cfg) call opens."""
    if side == 'left':
        thread_local.camera_index_override = TACTILE_CAM_L
    elif side == 'right':
        thread_local.camera_index_override = TACTILE_CAM_R


def open_sensor(side: str):
    """Routes the camera, loads the config, validates calibration, connects.

    Returns:
        (sensor, cfg).
    """
    from shape_reconstruction import Sensor

    setup_camera(side)
    cfg = load_cfg(side)
    for problem in validate_calibration(cfg, side):
        print(f"\n[WARNING] {problem}\n")
    return Sensor(cfg), cfg


def read_proxy(sensor, baseline, contact_thresh):
    """One frame -> (volume, area_px, max_deform_mm, mean_deform_mm, absdef)."""
    return compute_metrics(grab_height_map(sensor), baseline, contact_thresh)


def draw_rolling_plot(values, width=640, height=200, label="force proxy"):
    """Lightweight OpenCV rolling line plot (no matplotlib in the live loop)."""
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


# ---------------------------------------------------------------------------
# Steps 1 & 2: Calibration (delegated to the 9DTact library)
# ---------------------------------------------------------------------------

@contextmanager
def _as_temp_yaml(cfg):
    """Writes a cfg dict to a temp YAML and yields its path, deleting it after.

    9DTact's calibration classes take a config *path*, but our per-side config
    only exists as a dict (load_config injects sensor_id). This bridges the gap.
    """
    fd, path = tempfile.mkstemp(suffix=".yaml", prefix="shape_config_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f)
        yield path
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _print_calibration_header(side: str):
    """Calibration pairs with the frame geometry — redo both steps together."""
    print(f"\n=== Calibration — {side.upper()} ===")
    print("Camera and depth calibration are a pair: redo BOTH steps for a side")
    print("whenever either is redone, or the depth table won't match the grid.\n")


def _detect_grid_points(ref, sample):
    """Finds the calibration board's grid points, mirroring 9DTact's own
    detection. Used only to diagnose a failed run — see _diagnose_grid().

    Returns:
        (points Nx2 as [row, col], diff image, undersized areas, oversized areas).
    """
    ref_g = cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY)
    sample_g = cv2.cvtColor(sample, cv2.COLOR_BGR2GRAY)

    diff = ref_g - sample_g
    diff = diff * (diff < 100).astype(np.uint8)
    diff[diff < 5] = 0

    binary = cv2.adaptiveThreshold(diff, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                    cv2.THRESH_BINARY, 51, 0)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    morph = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(morph, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

    # The library keeps contours between 200 and 2000 px. Those thresholds are
    # hardcoded there, so track near-misses too — they are the actionable signal.
    points, undersized, oversized = [], [], []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < 200:
            if area > 40:                  # ignore specks; keep plausible dots
                undersized.append(area)
            continue
        if area > 2000:
            oversized.append(area)
            continue
        moments = cv2.moments(contour)
        points.append([int(moments['m01'] / moments['m00']),
                       int(moments['m10'] / moments['m00'])])
    return np.array(points), diff, undersized, oversized


def _diagnose_grid(side: str, cfg: dict):
    """Explains a failed calibrate-camera run and saves a debug overlay.

    9DTact detects the grid points and indexes straight into them without
    checking how many it found, so a partial detection dies with an opaque
    IndexError. Re-run the detection on the frames it already saved to report
    the real cause.
    """
    cam_dir = (os.path.join(cfg['calibration_root_dir'], 'sensor_' + str(cfg['sensor_id']))
               + cfg['camera_calibration']['camera_calibration_dir'])
    image_format = cfg['camera_calibration']['image_format']
    ref_path = f"{cam_dir}/ref.{image_format}"
    sample_path = f"{cam_dir}/sample.{image_format}"

    rows = cfg['camera_calibration']['row_points']
    cols = cfg['camera_calibration']['col_points']
    expected = rows * cols

    print(f"\n[ERROR] Camera calibration failed for {side.upper()}.")

    if not (os.path.exists(ref_path) and os.path.exists(sample_path)):
        print("  The reference/sample frames were not captured — rerun.")
        return

    points, diff, undersized, oversized = _detect_grid_points(
        cv2.imread(ref_path), cv2.imread(sample_path))
    found = len(points)

    print(f"  Detected {found} grid points, but shape_config.yaml expects "
          f"{expected} ({rows} row_points x {cols} col_points).")

    debug = cv2.cvtColor(diff, cv2.COLOR_GRAY2BGR)
    for row, col in points:
        cv2.circle(debug, (int(col), int(row)), 6, (0, 0, 255), 2)
    debug_path = f"{cam_dir}/detected_points_debug.{image_format}"
    cv2.imwrite(debug_path, debug)
    print(f"  Debug overlay (red = detected): {debug_path}")

    if found < expected and undersized:
        print(f"\n  >> {len(undersized)} more blobs were found but fell BELOW the "
              f"library's 200 px minimum (sizes {int(min(undersized))}-"
              f"{int(max(undersized))} px).")
        if found + len(undersized) >= expected:
            print(f"     {found} + {len(undersized)} = {found + len(undersized)}, which "
                  f"covers the {expected} expected — so the dots ARE all there, just too")
            print("     faint. PRESS HARDER and more squarely: the dots must deform the gel")
            print("     enough to register. That threshold is hardcoded in the library, so")
            print("     pressing harder is the fix, not a config change.")
    elif found > expected and oversized:
        print(f"\n  >> {len(oversized)} blobs exceeded the 2000 px maximum — dots are")
        print("     merging together. Press more lightly.")

    print("\n  Open the overlay to see which dots were missed. Common causes:")
    print("    - pressed too lightly or unevenly (most common)")
    print("    - part of the board sits outside the gel — it must fit within it")
    print("    - lighting/focus: the dots must be distinct in the debug image")
    print(f"\n  If the board is actually {cols}x{rows} rather than {rows}x{cols}, swap")
    print("  row_points/col_points in run/shape_config.yaml to match how the camera")
    print("  natively sees the grid.")


def calibrate_camera(side: str, cfg: dict):
    """Step 1: grid calibration via 9DTact's CameraCalibration, then verified.

    Both guards matter. The library indexes into the detected grid points
    without checking how many it found, so a partial detection dies with an
    opaque IndexError — _diagnose_grid() explains it instead. And a run whose
    crop window overflows the image still "succeeds", but NumPy truncates the
    slice and that side under-reads force.
    """
    from shape_reconstruction._1_Camera_Calibration import CameraCalibration

    _print_calibration_header(side)
    print("Use the calibration board from 9DTact_Design/fabrication/calibration_board.STL")
    print("Press it FIRMLY and SQUARELY — every dot must contact the gel, or the")
    print("grid detection comes up short.")
    print("Follow the library's prompts ('y' to capture, 'q' to abort).\n")

    setup_camera(side)
    try:
        with _as_temp_yaml(cfg) as cfg_path:
            CameraCalibration(cfg_path).run()
    except (IndexError, ValueError, ZeroDivisionError):
        cv2.destroyAllWindows()
        _diagnose_grid(side, cfg)
        return

    cv2.destroyAllWindows()

    print(f"\nVerifying {side} calibration ...")
    problems = validate_calibration(cfg, side)
    if problems:
        for w in problems:
            print(f"\n[WARNING] {w}\n")
    else:
        print(f"Camera calibration complete and verified for {side.upper()}.")


def calibrate_sensor(side: str, cfg: dict):
    """Step 2: depth calibration via 9DTact's SensorCalibration, then verified.

    The check matters: if the detected contact radius reaches BallRad, the
    sphere geometry has no solution and every depth comes out NaN — the run
    still "succeeds" and every later force reading is silently zero.
    """
    from shape_reconstruction._2_Sensor_Calibration import SensorCalibration

    _print_calibration_header(side)
    ball_rad = cfg['depth_calibration']['BallRad']
    print(f"Prepare a ball of radius {ball_rad} mm (must match BallRad in shape_config.yaml).")
    print("Follow the library's prompts ('y' to capture, 'q' to abort).\n")

    setup_camera(side)
    with _as_temp_yaml(cfg) as cfg_path:
        SensorCalibration(cfg_path).run()

    cv2.destroyAllWindows()

    # Post-check: verify the saved Pixel_to_Depth table is usable.
    print(f"\nVerifying {side} depth calibration ...")
    sensor_dir = os.path.join(cfg['calibration_root_dir'], 'sensor_' + str(cfg['sensor_id']))
    p2d_path = sensor_dir + cfg['depth_calibration']['depth_calibration_dir'] \
        + cfg['depth_calibration']['Pixel_to_Depth_path']

    if not os.path.exists(p2d_path):
        print(f"[ERROR] {p2d_path} was not written — calibration did not complete.")
        return

    p2d = np.load(p2d_path)
    if p2d.size == 0 or not np.isfinite(p2d).any() or np.nanmax(p2d) <= 0:
        print(f"[ERROR] {side.upper()} depth lookup table is empty/NaN/all-zero.")
        print("  The contact circle was probably not detected, or the detected radius")
        print(f"  met or exceeded BallRad ({ball_rad} mm) — a sphere of that radius")
        print("  cannot produce a contact patch that wide, so every depth is NaN.")
        print("  Likely causes:")
        print("    - circle_detect_gray too sensitive (catching a wider smudge)")
        print("    - pixel_per_mm off (re-check Step 1)")
        print("    - BallRad does not match the ball you actually used")
        print("    - pressed too hard, deforming a wider area than true contact")
        return

    print(f"  depth lookup: {p2d.size} entries, range "
          f"[{np.nanmin(p2d[p2d > 0]):.3f}, {np.nanmax(p2d):.3f}] mm")
    print(f"Sensor (depth) calibration complete and verified for {side.upper()}.")


# ---------------------------------------------------------------------------
# Step 3: Live shape reconstruction
# ---------------------------------------------------------------------------

def reconstruct(side: str, cfg: dict):
    """Step 3: live tactile image, depth map, and point cloud. 'q' to quit."""
    from shape_reconstruction import Visualizer

    print(f"\n=== Reconstruction — {side.upper()} ===")
    print("Press 'q' in the image window to quit.")
    sensor, _ = open_sensor(side)
    visualizer = Visualizer(sensor.points)

    win_raw = f"RawImage_GRAY [{side}]"
    win_depth = f"DepthMap [{side}]"

    while sensor.cap.isOpened():
        img = sensor.get_rectify_crop_image()
        img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        cv2.imshow(win_raw, img_gray)

        height_map = sensor.raw_image_2_height_map(img_gray)
        depth_map = sensor.height_map_2_depth_map(height_map)
        cv2.imshow(win_depth, depth_map)

        height_map_exp = sensor.expand_image(height_map)

        key = cv2.waitKey(1)
        if key == ord('q'):
            break
        if not visualizer.vis.poll_events():
            break

        points, gradients = sensor.height_map_2_point_cloud_gradients(height_map_exp)
        visualizer.update(points, gradients)

    sensor.cap.release()
    cv2.destroyWindow(win_raw)
    cv2.destroyWindow(win_depth)
    visualizer.vis.destroy_window()
    print(f"Reconstruction stopped for {side.upper()}.")


def reconstruct_both():
    """BROKEN — OpenCV/Qt and Open3D are not thread-safe in this build.

    Use two terminals instead, one per side.
    """
    print("WARNING: --side both is known to fail on this setup (OpenCV/Qt")
    print("threading issue: 'NoneType' object is not subscriptable /")
    print("QObject::killTimer errors). Use two separate terminals instead:")
    print("  python run/setup.py reconstruct --side left")
    print("  python run/setup.py reconstruct --side right")
    print()

    stop_event = threading.Event()

    def worker(side):
        try:
            cfg_side = load_cfg(side)
            reconstruct(side, cfg_side)
        except Exception as e:
            print(f"[{side}] reconstruction error: {e}")
        finally:
            stop_event.set()

    t_left = threading.Thread(target=worker, args=('left',), daemon=True)
    t_right = threading.Thread(target=worker, args=('right',), daemon=True)
    t_left.start()
    t_right.start()

    t_left.join()
    t_right.join()


# ---------------------------------------------------------------------------
# Step 4: Grip-force data collection
# ---------------------------------------------------------------------------

def collect(args):
    """Step 4: logs one sensor's force proxy to CSV at args.rate Hz.

    Outputs <out>/force_proxy.csv and, with --save-images, <out>/images/*.npy.
    `volume` is UNCALIBRATED — see calibrate-force for Newtons.
    """

    sensor, _ = open_sensor(args.side)

    gripper = None
    if args.gripper_port is not None:
        # Reuse the same wrapper experiment.py uses, so there is one gripper
        # API in the codebase (pyRobotiqGripper v3.x).
        from gripper import GripperController
        gripper = GripperController(args.gripper_port)
        if not gripper.is_activated():
            print("[WARNING] Gripper not activated — position logging will read -1. "
                  "Activate it once first (note: activate() fully opens and closes "
                  "the gripper), then rerun.")

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

                volume, area_px, max_deform, mean_deform, absdef = read_proxy(
                    sensor, baseline, args.contact_thresh)

                position_bit = None
                if gripper is not None:
                    position_bit = gripper.read_position()

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
            if gripper is not None:
                gripper.close()
            cv2.destroyAllWindows()

    print(f"Done. Wrote metrics to {csv_path}")
    if args.save_images:
        print(f"Archived height maps to {img_dir}/")
    print("\nReminder: 'volume' is an UNCALIBRATED force proxy. To convert to Newtons,")
    print("press onto a load cell at known forces and fit F = a*volume + b.")


def calibrate_force(args):
    """Step 5: fits F = a*volume + b against a precision balance, and reports R^2.

    Interactive: press the gel onto a rigid indenter on the tared pan, hold
    steady, enter the reading in grams. The balance reads the reaction force,
    so no heavy object is needed. Use the same indenter geometry as the
    experiment — contact area changes the deformation volume.

    Writes force_calibration_<side>.csv and .png to <out>. Do not extrapolate
    beyond the calibrated range (a 600 g balance saturates near 5.9 N).
    """

    G_TO_N = 0.00981  # 1 g weight-force = 9.81 mN

    sensor, _ = open_sensor(args.side)

    print(f"\n=== STEP 5: Force calibration — {args.side.upper()} ===")
    print("Setup:")
    print("  1. Place the balance on a stable surface and TARE it to zero.")
    print("  2. Centre a small rigid indenter on the pan (disc, coin, bolt head).")
    print("     Use the SAME indenter geometry you expect during the experiment.")
    print("  3. Press this sensor's gel DOWN onto the indenter to load it.")
    print("     (Using the gripper itself to apply the load is more repeatable")
    print("      than pressing by hand.)")
    print("  4. Hold steady, let the balance settle, then follow the prompts.\n")

    input("Keep the sensor UNLOADED, then press Enter to capture the baseline...")
    baseline = capture_baseline(sensor, args.baseline_frames)

    def read_volume():
        """Averages `volume` over args.samples frames while you hold steady."""
        vals = [read_proxy(sensor, baseline, args.contact_thresh)[0]
                for _ in range(args.samples)]
        return float(np.mean(vals)), float(np.std(vals))

    grams_list, volume_list = [], []
    print("\nEnter the balance reading in GRAMS at each level. Aim for ~8-10 levels")
    print("spanning the force range you expect in the experiment (include one at 0 g).")
    print("Type 'done' when finished, or 'q' to abort.\n")

    while True:
        raw = input(f"  [{len(grams_list)} pts] Balance reading (g), or 'done': ").strip()
        if raw.lower() in ("q", "quit", "abort"):
            sensor.cap.release()
            print("Aborted; nothing saved.")
            return
        if raw.lower() in ("done", "d", ""):
            if len(grams_list) < 3:
                print("  Need at least 3 points to fit a line. Keep going.")
                continue
            break
        try:
            grams = float(raw)
        except ValueError:
            print("  Not a number — enter grams (e.g. 152.4), or 'done'.")
            continue
        if grams > 600:
            print(f"  WARNING: {grams} g exceeds the balance's 600 g range — reading unreliable.")

        mean_v, std_v = read_volume()
        grams_list.append(grams)
        volume_list.append(mean_v)
        print(f"    -> {grams:7.2f} g = {grams * G_TO_N:5.3f} N   "
              f"volume = {mean_v:9.1f} (sd {std_v:6.1f} over {args.samples} frames)")
        if std_v > 0.05 * max(mean_v, 1e-6):
            print("       NOTE: volume was drifting (>5% sd) — hold more steadily and "
                  "consider re-entering this level.")

    sensor.cap.release()

    grams_arr = np.array(grams_list, dtype=float)
    force_arr = grams_arr * G_TO_N
    volume_arr = np.array(volume_list, dtype=float)

    # Least-squares fit: F = a*volume + b
    a, b = np.polyfit(volume_arr, force_arr, 1)
    predicted = a * volume_arr + b
    ss_res = float(np.sum((force_arr - predicted) ** 2))
    ss_tot = float(np.sum((force_arr - force_arr.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float('nan')

    os.makedirs(args.out, exist_ok=True)
    csv_path = os.path.join(args.out, f"force_calibration_{args.side}.csv")
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["grams", "force_N", "volume"])
        for g, fn, v in zip(grams_arr, force_arr, volume_arr):
            writer.writerow([f"{g:.2f}", f"{fn:.4f}", f"{v:.4f}"])

    # Scatter + fitted line, for the thesis figure
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.scatter(volume_arr, force_arr, label="measured", zorder=3)
    xs = np.linspace(0, volume_arr.max() * 1.05, 100)
    ax.plot(xs, a * xs + b, color="tab:red",
            label=f"F = {a:.3e}·volume + {b:.3f}\n$R^2$ = {r2:.4f}")
    ax.set_xlabel("force proxy (volume, uncalibrated)")
    ax.set_ylabel("force (N)")
    ax.set_title(f"Force calibration — {args.side} sensor")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    png_path = os.path.join(args.out, f"force_calibration_{args.side}.png")
    fig.savefig(png_path, dpi=200)
    plt.close(fig)

    side_const = args.side.upper()
    print(f"\n=== Fit result — {side_const} ===")
    print(f"  points        : {len(grams_arr)}")
    print(f"  force range   : {force_arr.min():.3f} - {force_arr.max():.3f} N")
    print(f"  F = a*volume + b")
    print(f"    a = {a:.8e}")
    print(f"    b = {b:.8f}")
    print(f"    R^2 = {r2:.4f}")
    if r2 < 0.95:
        print("  WARNING: R^2 < 0.95 — the proxy is not tracking force linearly here.")
        print("    Likely causes: indenter shifting between levels, unsteady holds,")
        print("    or the gel saturating at the top of the range. Inspect the PNG.")
    print(f"\n  Paste into run/experiment.py:")
    print(f"    FORCE_CAL_A_{side_const}, FORCE_CAL_B_{side_const} = {a:.8e}, {b:.8f}")
    print(f"\n  Wrote {csv_path}")
    print(f"  Wrote {png_path}")
    print("\n  Reminder: this fit is only valid for the indenter geometry, gel, and")
    print("  mounting used just now. Freeze them for the rest of the study, and")
    print("  do not extrapolate beyond the calibrated force range above.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    """Parses the subcommand and dispatches."""
    parser = argparse.ArgumentParser(
        description="9DTact per-sensor calibration, reconstruction, and grip-force data collection.")
    subparsers = parser.add_subparsers(dest='command', required=True)

    p_cam = subparsers.add_parser('calibrate-camera', help='Step 1: camera/grid calibration')
    p_cam.add_argument('--side', choices=['left', 'right'], required=True)

    p_sensor = subparsers.add_parser('calibrate-sensor', help='Step 2: depth (ball) calibration')
    p_sensor.add_argument('--side', choices=['left', 'right'], required=True)

    p_recon = subparsers.add_parser('reconstruct', help='Step 3: live shape reconstruction')
    p_recon.add_argument('--side', choices=['left', 'right', 'both'], required=True)

    p_force = subparsers.add_parser(
        'calibrate-force',
        help="Step 5: fit force proxy to Newtons against a precision balance")
    p_force.add_argument("--side", choices=["left", "right"], required=True)
    p_force.add_argument("--out", default=os.path.join(CONFIG_DIR, "..", "data", "results"),
                          help="Directory for the calibration CSV + figure.")
    p_force.add_argument("--samples", type=int, default=20,
                          help="Frames averaged per force level while you hold steady.")
    p_force.add_argument("--baseline-frames", type=int, default=BASELINE_FRAMES,
                          help="Frames averaged for the no-contact baseline at startup.")
    p_force.add_argument("--contact-thresh", type=float, default=CONTACT_THRESH_MM,
                          help="Per-pixel deformation (mm) above which a pixel counts as contact. "
                               "Defaults to the same CONTACT_THRESH_MM experiment.py uses — "
                               "changing it here means calibrating against a different quantity "
                               "than the trials record.")

    p_collect = subparsers.add_parser('collect', help='Step 4: standalone grip-force proxy data collection')
    p_collect.add_argument("--side", choices=["left", "right"], required=True)
    p_collect.add_argument("--out", required=True, help="Output directory for this sensor's data.")
    p_collect.add_argument("--rate", type=float, default=20.0, help="Sampling rate in Hz.")
    p_collect.add_argument("--duration", type=float, default=30.0, help="Collection duration in seconds.")
    p_collect.add_argument("--baseline-frames", type=int, default=BASELINE_FRAMES,
                            help="Frames averaged for the no-contact baseline at startup.")
    p_collect.add_argument("--contact-thresh", type=float, default=CONTACT_THRESH_MM,
                            help="Per-pixel deformation (mm) above which a pixel counts as contact. "
                                 "Defaults to the same CONTACT_THRESH_MM experiment.py uses.")
    p_collect.add_argument("--save-images", action="store_true", default=True,
                            help="Archive raw height maps (.npy) for possible later supervised training.")
    p_collect.add_argument("--no-save-images", dest="save_images", action="store_false")
    p_collect.add_argument("--show", action="store_true", help="Show live depth map + rolling proxy plot.")
    p_collect.add_argument("--gripper-port", default=None,
                            help="Optional: also log gripper position (gPO). Current is NOT used.")

    args = parser.parse_args()

    if args.command == 'calibrate-camera':
        cfg = load_cfg(args.side)
        calibrate_camera(args.side, cfg)
    elif args.command == 'calibrate-sensor':
        cfg = load_cfg(args.side)
        calibrate_sensor(args.side, cfg)
    elif args.command == 'reconstruct':
        if args.side == 'both':
            reconstruct_both()
        else:
            cfg = load_cfg(args.side)
            reconstruct(args.side, cfg)
    elif args.command == 'collect':
        collect(args)
    elif args.command == 'calibrate-force':
        calibrate_force(args)


if __name__ == '__main__':
    main()
