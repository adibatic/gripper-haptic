"""
calibrate_9dtact.py — Per-sensor calibration and reconstruction for 9DTact on Robotiq 2F-85.

Subcommands:
    python calibrate_9dtact.py calibrate-camera --side {left,right}
    python calibrate_9dtact.py calibrate-sensor --side {left,right}
    python calibrate_9dtact.py reconstruct      --side {left,right,both}

calibrate-camera : Step 1 — camera intrinsic/grid calibration using the
                    printed calibration board.
calibrate-sensor : Step 2 — depth (height map) calibration using a ball
                    of known radius.
reconstruct      : Live tactile image + depth map + Open3D point cloud,
                    for one sensor or both in parallel. Press 'y' on the
                    raw image window to set the reference frame, 'q' to quit.

Hardware indices and per-camera orientation fixes are applied automatically
via the RotatedVideoCapture proxy, same as in your working test script.
"""

import os
import sys
import argparse
import threading
import cv2
import yaml
import numpy as np
from scipy.interpolate import Rbf

# ---------------------------------------------------------------------------
# Path setup — ensure src/9DTact-main is importable
# ---------------------------------------------------------------------------
_repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_tact_main_dir = os.path.join(_repo_root, "src", "9DTact-main")
if _tact_main_dir not in sys.path:
    sys.path.insert(0, _tact_main_dir)

CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATHS = {
    'left': os.path.join(CONFIG_DIR, "shape_config_left.yaml"),
    'right': os.path.join(CONFIG_DIR, "shape_config_right.yaml"),
}

# ---------------------------------------------------------------------------
# Verified hardware indices and per-camera orientation corrections
# ---------------------------------------------------------------------------
TACTILE_CAM_L = 4   # Left tactile sensor (/dev/videoX)
TACTILE_CAM_R = 2   # Right tactile sensor (/dev/videoX)

thread_local = threading.local()
_real_video_capture = cv2.VideoCapture


class RotatedVideoCapture:
    """Proxy around cv2.VideoCapture that corrects orientation per sensor."""

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
# ---------------------------------------------------------------------------


def load_cfg(side: str):
    """Load the per-side config (shape_config_left.yaml / shape_config_right.yaml).

    Each config has its own sensor_id ('L'/'R') and an absolute
    calibration_root_dir, so Camera/Sensor write to
    run/calibration/sensor_L/... and run/calibration/sensor_R/...
    respectively, without needing to edit src/9DTact-main.
    """
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


# ---------------------------------------------------------------------------
# Step 1: Camera calibration
# ---------------------------------------------------------------------------

def calibrate_camera(side: str, cfg: dict):
    from shape_reconstruction import Camera

    print(f"\n=== STEP 1: Camera calibration — {side.upper()} ===")
    print("3D-print and use the calibration board from 9DTact_Design/fabrication/calibration_board.STL")
    setup_camera(side)
    camera = Camera(cfg, calibrated=False)

    cc = cfg['camera_calibration']
    row_points, col_points = cc['row_points'], cc['col_points']
    grid_distance = cc['grid_distance']
    image_format = cc['image_format']

    os.makedirs(camera.camera_calibration_dir, exist_ok=True)

    print("DON'T touch the sensor surface. Press 'y' to save the reference image.")
    ref = camera.get_raw_avg_image()
    cv2.imwrite(f"{camera.camera_calibration_dir}/ref.{image_format}", ref)
    print("Reference image saved.")

    print("Press the calibration board onto the sensor, then press 'y' to capture.")
    while True:
        sample = camera.get_raw_image()
        cv2.imshow('sample', sample)
        key = cv2.waitKey(1)
        if key == ord('y'):
            cv2.imwrite(f"{camera.camera_calibration_dir}/sample.{image_format}", sample)
            cv2.destroyWindow('sample')
            break
        if key == ord('q'):
            sys.exit(0)

    # Detect grid points
    ref_g = cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY)
    sample_g = cv2.cvtColor(sample, cv2.COLOR_BGR2GRAY)
    diff = ref_g - sample_g
    diff_mask = (diff < 100).astype('uint8')
    diff = diff * diff_mask
    diff[diff < 5] = 0
    binary = cv2.adaptiveThreshold(diff, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 51, 0)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    morph = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(morph, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

    all_point = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < 200 or area > 2000:
            continue
        M = cv2.moments(c)
        cx, cy = int(M['m10'] / M['m00']), int(M['m01'] / M['m00'])
        all_point.append([cy, cx])

    all_point = np.array(all_point)
    expected = row_points * col_points
    if len(all_point) != expected:
        # Save a debug overlay so detected points (and gaps) can be inspected.
        debug_img = cv2.cvtColor(diff, cv2.COLOR_GRAY2BGR)
        for (cy, cx) in all_point:
            cv2.circle(debug_img, (int(cx), int(cy)), 6, (0, 0, 255), 2)
        debug_path = f"{camera.camera_calibration_dir}/detected_points_debug.{image_format}"
        cv2.imwrite(debug_path, debug_img)

        print(f"ERROR: detected {len(all_point)} points, expected {expected} ({row_points}x{col_points}).")
        print(f"Debug overlay saved to: {debug_path}")
        print("Likely causes: contact pressure too light/uneven, lighting, focus,")
        print("or contour area thresholds (200-2000 px) not matching this board/camera.")
        print("Adjust and rerun calibrate-camera before proceeding.")
        cv2.destroyAllWindows()
        sys.exit(1)

    all_point = all_point[np.lexsort(all_point[:, ::-1].T)]
    for i in range(row_points):
        sl = slice(i * col_points, (i + 1) * col_points)
        tmp = all_point[sl]
        all_point[sl] = tmp[np.lexsort(tmp.T)]

    center_index = (row_points * col_points) // 2
    dis_sum = 0
    for ai in (-col_points, -1, 1, col_points):
        dis_sum += np.linalg.norm(all_point[center_index] - all_point[center_index + ai], ord=2)
    dis_avg = dis_sum / 4

    position_scale = all_point[center_index].tolist()
    pixel_per_mm = float(grid_distance / dis_avg)
    position_scale.append(pixel_per_mm)
    print('position_scale (row, col, pixel_per_mm):', position_scale)
    np.save(camera.position_scale_path, position_scale)

    # Build the row/col index remap
    real_position = np.zeros_like(all_point)
    for i in range(row_points):
        for j in range(col_points):
            real_position[i * col_points + j] = (
                all_point[center_index] +
                dis_avg * np.array([i - row_points // 2, j - col_points // 2])
            )

    itp_row = Rbf(real_position[:, 0], real_position[:, 1], all_point[:, 0], function='cubic')
    itp_col = Rbf(real_position[:, 0], real_position[:, 1], all_point[:, 1], function='cubic')
    col_mesh, row_mesh = np.meshgrid(range(ref_g.shape[1]), range(ref_g.shape[0]))
    row_index = np.clip(itp_row(row_mesh, col_mesh).astype('int32'), 0, ref_g.shape[0] - 1)
    col_index = np.clip(itp_col(row_mesh, col_mesh).astype('int32'), 0, ref_g.shape[1] - 1)

    np.save(camera.row_index_path, row_index)
    np.save(camera.col_index_path, col_index)

    cv2.destroyAllWindows()
    print(f"Camera calibration complete for {side.upper()}.")


# ---------------------------------------------------------------------------
# Step 2: Sensor (depth) calibration
# ---------------------------------------------------------------------------

def calibrate_sensor(side: str, cfg: dict):
    from shape_reconstruction import Sensor

    print(f"\n=== STEP 2: Sensor (depth) calibration — {side.upper()} ===")
    print("Prepare a ball (recommended radius ~4.0 mm depending on surface thickness).")
    setup_camera(side)
    sensor = Sensor(cfg, calibrated=False)

    dc = cfg['depth_calibration']
    BallRad = dc['BallRad']
    circle_detection_gray = dc['circle_detect_gray']
    show_circle_detection = dc['show_circle_detection']

    os.makedirs(sensor.depth_calibration_dir, exist_ok=True)

    print("DON'T touch the sensor surface. Press 'y' to save the reference image.")
    ref = sensor.get_raw_avg_image()
    cv2.imwrite(f"{sensor.depth_calibration_dir}/ref.png", ref)
    rc_ref = sensor.rectify_crop_image(ref)
    cv2.imwrite(f"{sensor.depth_calibration_dir}/rectify_crop_ref.png", rc_ref)
    print("Reference image saved.")

    print("Press the ball onto the sensor, then press 'y' to save the sample image.")
    sample = sensor.get_raw_avg_image()
    cv2.imwrite(f"{sensor.depth_calibration_dir}/sample.png", sample)
    rc_sample = sensor.rectify_crop_image(sample)
    cv2.imwrite(f"{sensor.depth_calibration_dir}/rectify_crop_sample.png", rc_sample)
    print("Sample image saved.")

    def circle_detection(diff):
        diff_gray = diff[:, :, :3].mean(axis=2)
        contact_mask = (diff_gray > circle_detection_gray).astype('uint8')
        contours, _ = cv2.findContours(contact_mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
        areas = [cv2.contourArea(c) for c in contours]
        if not areas:
            return (0, 0), 0
        sorted_areas = np.sort(areas)
        cnt = contours[areas.index(sorted_areas[-1])]
        (x, y), radius = cv2.minEnclosingCircle(cnt)
        center, radius = (int(x), int(y)), int(radius)
        if show_circle_detection:
            print("Adjust circle if needed (w/s/a/d = move, m/n = radius), then press 'q' to continue.")
            key = -1
            while key != ord('q'):
                circle_show = cv2.circle(np.array(diff), (int(x), int(y)), int(radius), (0, 255, 0), 1)
                circle_show[int(y), int(x)] = [255, 255, 255]
                cv2.imshow('contact', circle_show.astype('uint8'))
                key = cv2.waitKey(0)
                if key == ord('w'): y -= 1
                elif key == ord('s'): y += 1
                elif key == ord('a'): x -= 1
                elif key == ord('d'): x += 1
                elif key == ord('m'): radius += 1
                elif key == ord('n'): radius -= 1
            cv2.destroyWindow('contact')
            center = (int(x), int(y))
        return center, radius

    diff_raw = rc_ref - rc_sample
    diff_mask = (diff_raw < 150).astype('uint8')
    diff = diff_raw * diff_mask
    center, detect_radius_p = circle_detection(diff)

    detect_radius_mm = detect_radius_p * sensor.pixel_per_mm
    print(f"Detected contact circle: radius={detect_radius_p} px "
          f"({detect_radius_mm:.3f} mm), pixel_per_mm={sensor.pixel_per_mm:.5f}, "
          f"BallRad={BallRad} mm")
    if detect_radius_p and detect_radius_mm >= BallRad:
        print(f"ERROR: detected contact radius ({detect_radius_mm:.3f} mm) >= BallRad ({BallRad} mm).")
        print("A sphere of radius BallRad cannot produce a contact patch this wide —")
        print("this will make every height_map value NaN/0 (0 sample points).")
        print("Likely causes:")
        print("  - circle_detect_gray threshold too sensitive (picking up a wider")
        print("    smudge than the true ball contact patch) — try increasing it")
        print("  - pixel_per_mm from camera calibration is off (re-check step 1)")
        print("  - BallRad in shape_config_*.yaml doesn't match your actual ball")
        print("  - pressed too hard, deforming a wider area than the ball's true contact")
        cv2.destroyAllWindows()
        return

    gray_list, depth_list = [], []
    if detect_radius_p:
        x = np.linspace(0, diff.shape[0] - 1, diff.shape[0])
        y = np.linspace(0, diff.shape[1] - 1, diff.shape[1])
        xv, yv = np.meshgrid(y, x)
        xv -= center[0]
        yv -= center[1]
        rv = np.sqrt(xv ** 2 + yv ** 2)
        mask = rv < detect_radius_p
        temp = ((xv * mask) ** 2 + (yv * mask) ** 2) * sensor.pixel_per_mm ** 2
        height_map = (
            np.sqrt(BallRad ** 2 - temp) * mask
            - np.sqrt(BallRad ** 2 - (detect_radius_p * sensor.pixel_per_mm) ** 2)
        ) * mask
        height_map[np.isnan(height_map)] = 0
        diff_gray = diff[:, :, :3].mean(axis=2)
        for i in range(height_map.shape[0]):
            for j in range(height_map.shape[1]):
                if height_map[i, j] > 0:
                    gray_list.append(diff_gray[i, j])
                    depth_list.append(height_map[i, j])
        print(f"Sample points: {len(gray_list)}")
    else:
        print("WARNING: no contact circle detected. Press harder / check lighting and retry.")

    gray_arr = np.array(gray_list)
    depth_arr = np.array(depth_list)
    if gray_arr.size == 0:
        print("ERROR: no calibration data collected. Aborting depth calibration for this sensor.")
        cv2.destroyAllWindows()
        return

    GRAY_scope = int(gray_arr.max())
    P2D = np.zeros(GRAY_scope + 1)
    for g in range(GRAY_scope + 1):
        sel = gray_arr == g
        if sel.sum():
            P2D[g] = depth_arr[sel].mean()
    for g in range(GRAY_scope + 1):
        if P2D[g] == 0 and g > 0:
            for k in range(GRAY_scope - g):
                if P2D[g + 1 + k] != 0:
                    P2D[g] = P2D[g + 1 + k]
                    break

    np.save(sensor.Pixel_to_Depth_path, P2D)
    cv2.destroyAllWindows()
    print(f"Sensor (depth) calibration complete for {side.upper()}.")


# ---------------------------------------------------------------------------
# Step 3: Live shape reconstruction
# ---------------------------------------------------------------------------

def reconstruct(side: str, cfg: dict):
    """Live tactile image, depth map, and Open3D point cloud for one sensor.

    Mirrors the stock _3_Shape_Reconstruction.py, parameterized by side.
    Press 'y' on the RawImage window to set the reference frame (handled
    internally by Sensor on first calibrated read), 'q' to quit.
    """
    from shape_reconstruction import Sensor, Visualizer

    print(f"\n=== Reconstruction — {side.upper()} ===")
    print("Press 'q' in the image window to quit.")
    setup_camera(side)
    sensor = Sensor(cfg)
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
    """Run reconstruction for left and right sensors in parallel threads.

    Each thread loads its own config (shape_config_left.yaml /
    shape_config_right.yaml), so left and right calibration data and
    output paths (run/calibration/sensor_L, sensor_R) stay independent.

    CONFIRMED BROKEN on this setup: cv2.VideoCapture/cv2.imshow and
    Open3D are not thread-safe with this OpenCV/Qt build. Running this
    fails with 'NoneType' object is not subscriptable and
    "QObject::killTimer: Timers cannot be stopped from another thread".

    Use two separate terminal processes instead:
        python calibrate_9dtact.py reconstruct --side left
        python calibrate_9dtact.py reconstruct --side right
    each in its own terminal with the 9dtact env active.
    """
    print("WARNING: --side both is known to fail on this setup (OpenCV/Qt")
    print("threading issue: 'NoneType' object is not subscriptable /")
    print("QObject::killTimer errors). Use two separate terminals instead:")
    print("  python calibrate_9dtact.py reconstruct --side left")
    print("  python calibrate_9dtact.py reconstruct --side right")
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
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="9DTact per-sensor calibration and reconstruction.")
    subparsers = parser.add_subparsers(dest='command', required=True)

    p_cam = subparsers.add_parser('calibrate-camera', help='Step 1: camera/grid calibration')
    p_cam.add_argument('--side', choices=['left', 'right'], required=True)

    p_sensor = subparsers.add_parser('calibrate-sensor', help='Step 2: depth (ball) calibration')
    p_sensor.add_argument('--side', choices=['left', 'right'], required=True)

    p_recon = subparsers.add_parser('reconstruct', help='Step 3: live shape reconstruction')
    p_recon.add_argument('--side', choices=['left', 'right', 'both'], required=True)

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


if __name__ == '__main__':
    main()