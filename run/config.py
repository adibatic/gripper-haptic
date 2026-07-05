"""
config.py — camera indices shared by src/calibration.py, src/measurement.py,
and experiment.py.

Update these three values once per session instead of editing each script
separately. Confirm indices with `ls /dev/video*` before each session
(README step 5) — /dev/videoX ordering can shift on reboot.

Lives in scripts/ alongside experiment.py; the src/ modules reach it via a
sys.path insert (see the "Path setup" section near the top of each file).
"""

# ---------------------------------------------------------------------------
# Verified hardware indices — update before each session
# ---------------------------------------------------------------------------
HAND_CAM_INDEX = 2   # Hand-tracking webcam    (/dev/videoX)
TACTILE_CAM_L  = 0   # Left tactile sensor     (/dev/videoX)
TACTILE_CAM_R  = 4   # Right tactile sensor    (/dev/videoX)