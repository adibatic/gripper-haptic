"""
camera.py

Camera indices, and the routing that lets two sensors open two different
cameras.

Both sensors share one shape_config.yaml, whose camera_channel the 9DTact
library would otherwise use for every Sensor() — so both would open the same
device. Importing this module patches cv2.VideoCapture so each sensor's thread
can set thread_local.camera_index_override and get the camera it wants. The
patch also forces V4L2 and, on the tactile cameras, MJPG at open time — MJPG
must be set BEFORE the resolution or V4L2 ignores it, and uncompressed streams
use ~4x the USB bandwidth, which these cameras cannot sustain together.

/dev/videoN numbering is NOT stable — it is reassigned whenever a camera
re-enumerates on the USB bus. Re-check before each session:

    ls -l /dev/v4l/by-path/

Map each camera by its USB port and take the '-video-index0' entry; index1 is
the metadata node and cannot capture frames.
"""

import os
import cv2
import threading

HAND_CAM_INDEX = 4   # Hand-tracking webcam
TACTILE_CAM_L  = 0   # Left tactile sensor
TACTILE_CAM_R  = 2   # Right tactile sensor

TACTILE_CAMS = (TACTILE_CAM_L, TACTILE_CAM_R)

# Lets each sensor's background thread choose which camera opens next.
thread_local = threading.local()
_real_video_capture = cv2.VideoCapture


def resolve(device):
    """Human-readable device name, for error messages."""
    if isinstance(device, int):
        return f"/dev/video{device}"
    try:
        return os.path.realpath(device)
    except Exception:
        return str(device)


def intercepted_video_capture(device, *args, **kwargs):
    """Opens thread_local.camera_index_override if set, else `device`.

    Forces V4L2, and MJPG on the tactile cameras — before anything sets the
    resolution, since V4L2 silently ignores a format change made afterwards.
    """
    override = getattr(thread_local, 'camera_index_override', None)
    if override is not None:
        device = override

    cap = _real_video_capture(device, *(args or (cv2.CAP_V4L2,)), **kwargs)

    if not cap.isOpened():
        raise RuntimeError(
            f"Could not open camera {resolve(device)}.\n"
            f"  /dev/videoN numbering shifts when cameras re-enumerate. Re-check with:\n"
            f"    ls -l /dev/v4l/by-path/\n"
            f"  and update the indices at the top of kernel/camera.py.")

    if device in TACTILE_CAMS:
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))

    return cap


# Import-time side effect: activates the routing for the whole project.
cv2.VideoCapture = intercepted_video_capture
