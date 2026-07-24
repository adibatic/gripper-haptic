# Tactile-Feedback Teleoperation: Grip Force and Grasping Performance Across Haptic Actuator Types for Fragile and Deformable Objects

## Overview

This repository is the source code for a bachelor's thesis investigating grip force and grasping performance across haptic feedback actuator types in robotic gripper teleoperation. A Robotiq 2F-85 Adaptive Gripper is fitted with stress-deformation-based tactile sensors; tactile data is translated and sent to a custom multi-channel actuator platform (ESP32-C6) for real-time stimuli. The study collects quantitative latency metrics and qualitative survey data comparing user experience during delicate object manipulation.

The stack supports two haptic feedback methods — LRA vibration motors (PWM) and TacTiles pin actuators (H-bridge) — selectable from a single script, plus direct Modbus RTU communication with the Robotiq gripper from a host PC.

## Repository Structure

The project splits into three code roots: `run/` (host scripts you execute),
`kernel/` (host-side modules those scripts import), and `firmware/` (code that
runs on the ESP32-C6, not the PC).

```text
gripper-haptic/
├── data/                           # Experimental data (logs + calibration)
│   ├── calibration/                # Per-sensor calibration data (sensor_L / sensor_R)
│   ├── experiment_logs/            # Logs from experiment.py, one subfolder per participant (P01/, P02/, ...)
│   └── results/                    # Results from analysis.py
├── designs/                        # CAD models and 3D print assets
├── firmware/                       # Runs on the ESP32-C6 (MicroPython)
│   ├── haptic.py                   # LRA + TacTiles driver library
│   └── stream.py                   # Live stream receiver for experiment.py
├── kernel/                         # Host-side modules imported by run/ scripts
│   ├── camera.py                   # Camera indices + per-sensor VideoCapture routing
│   ├── gripper.py                  # GripperController + gripper limits/defaults
│   ├── haptic_link.py              # HapticLink — host side of the ESP32 serial link
│   ├── tactile.py                  # 9DTact sensing: TactileSensor + force-proxy helpers
│   └── tracking.py                 # Hand tracking + MediaPipe + tracking loop
├── run/                            # Host scripts you execute
│   ├── analysis.py                 # Analysis pipeline (Friedman, Wilcoxon, figures)
│   ├── experiment.py               # Main experiment: params, threads, main loop
│   ├── setup.py                    # 9DTact calibration / reconstruction / collection CLI
│   └── shape_config.yaml           # Shared 9DTact sensor config (sensor_id injected per side)
├── src/                            # Source submodules and core libraries
│   ├── 9DTact-main/                # 9DTact tactile sensor source code
│   └── pyRobotiqGripper-master/    # Robotiq gripper driver
├── tests/                          # Board-only bench self-tests (MicroPython)
│   ├── test_tactiles.py            # TacTiles continuous burst/gap vibration, ON/OFF loop
│   ├── test_tactiles2.py           # TacTiles binary engage/disengage latch, ON/OFF loop
│   └── test_vibmotor.py            # LRA vibmotor (ACDriver) buzz, ON/rest loop
├── thesis/                         # Thesis manuscript (LaTeX source)
│   ├── figures/                    # Thesis figures
│   ├── main.tex                    # Main LaTeX file
│   └── references.bib              # References
├── .gitignore                      # Git ignore rules
├── ESP32_GENERIC_C6-<...>.bin      # MicroPython firmware for ESP32-C6
├── pyrightconfig.json              # Python type checking config
├── README.md                       # This file
└── requirements.txt                # Required dependencies
```

## Hardware Requirements

* NVIDIA GPU with driver supporting **CUDA ≥13.0** (check with `nvidia-smi`)
* Robotiq 2F-85 with USB-RS485 adapter (for communication to the host PC)
* ESP32-C6 development board (custom-made for haptic feedback)
* 1 USB-C **data** cable (for the ESP32-C6)
* 2 USB-Micro-B cables (for 9DTact LED board power supply)
* 3 USB-Micro-B **data** cables (for 9DTact cameras and hand tracking camera)
* 2 LRA vibration motors (mounted near the thumb/index proximal joints)
* 2 TacTiles pin actuators (mounted at the thumb/index fingertips)

## Setup & Installation (One-Time)

One unified conda environment (`hapticf`, Python 3.10) runs all host-side scripts on **Linux**:
- Gripper control
- ESP32-C6 serial
- 9DTact tactile sensing
- Hand tracking
- Data analysis

ROS is not required.

> Note on package installations: Use only `python -m pip`, not `conda install` in this env. Mixing the two causes `ClobberErrors` requiring a full rebuild.

**1. Create and activate the conda environment**
```bash
# conda remove -n hapticf --all -y            # uncomment to wipe an existing env before recreating
conda create -n hapticf python=3.10 -y
conda activate hapticf
conda env config vars set PYTHONNOUSERSITE=1  # isolate from ~/.local
conda deactivate && conda activate hapticf
```

**2. Install matching PyTorch and other dependencies**
Check your CUDA version first:
```bash
nvidia-smi | grep -i "CUDA Version"
```
Drivers are backward compatible, so this just needs to be ≥13.0. Use `--extra-index-url` (not `--index-url`) since `cu130` doesn't mirror every dependency:
```bash
python -m pip install torch==2.9.1 torchvision==0.24.1 torchaudio==2.9.1 \
  --extra-index-url https://download.pytorch.org/whl/cu130
```
After that, install the remaining dependencies:
```bash
python -m pip install -r requirements.txt
```

> To verify the installation, run:
```bash
python -c "import cv2, scipy, ml_collections, open3d, torch, numpy, serial, pymodbus, mediapipe, pandas; print('cuda:', torch.cuda.is_available()); print('all ok')"
```

**3. Install 9DTact and pyRobotiqGripper from source**
Download or clone source code dependencies into `src/`:
- [9DTact](https://github.com/linchangyi1/9DTact) → `src/9DTact-main/`
- [pyRobotiqGripper](https://github.com/castetsb/pyRobotiqGripper/tree/master) → `src/pyRobotiqGripper-master/`
```bash
cd src/9DTact-main
python -m pip install -e . --no-deps --config-settings editable_mode=compat
cd ../pyRobotiqGripper-master
python -m pip install -e ".[all]" --no-deps --config-settings editable_mode=compat
cd ../..
conda env config vars set PYTHONPATH="$(pwd)"
conda deactivate && conda activate hapticf
```

> Note on versions: Both 9DTact and pyRobotiqGripper are actively developed upstream, so a fresh clone may pull a newer version than what this guide was tested against. If you hit install or import errors, check your installed version first:
```bash
python -m pip show 9DTact pyrobotiqgripper
```
> This guide was last verified working against 9DTact **v1.0** and pyRobotiqGripper **v3.2.7**.

> **Gripper must be activated once before running the experiment.** Under pyRobotiqGripper v3.x, an unactivated gripper makes every `move()` raise `GripperNotActivatedError`, so `experiment.py` checks at startup and exits with an error rather than failing mid-trial. Activation is a one-off `activate()` call — note it **fully opens and closes** the gripper, which is why `experiment.py` never does it automatically. `experiment.py` does call `start()` (sets the GTO bit) on every launch; unlike `activate()`, that does not move the gripper.


**4. Download the MediaPipe hand-tracking model**
`experiment.py` uses MediaPipe's HandLandmarker for the live hand overlay. The model file isn't in this repo (binary asset) — download it into `run/`:
```bash
wget -O run/hand_landmarker.task \
  https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task
```

**5. Flash MicroPython onto the ESP32-C6**
Download the firmware `.bin` for your board from the [MicroPython downloads page](https://micropython.org/download/ESP32_GENERIC_C6/) and place it in the repo root.
```bash
ls /dev/ttyACM*   # ttyACM0 = ESP32-C6
```
Then flash it:
```bash
python -m esptool --chip esp32c6 --port /dev/ttyACM0 erase-flash
python -m esptool --chip esp32c6 --port /dev/ttyACM0 --baud 460800 write-flash -z 0x0 ESP32_GENERIC_C6-20260406-v1.28.0.bin
```
> This guide was last verified working against ESP32-C6 MicroPython firmware **v1.28.0**.

**6. Confirm the sensor cameras are detected**

Cameras are addressed by **`/dev/v4l/by-path/`**, not `/dev/videoN`. The `N` is reassigned whenever a camera re-enumerates on the USB bus, so it drifts between sessions; `by-path` is keyed to the physical port and stays put. (`by-id` is not usable here — all three cameras report the same vendor/product and `SerialNumber 0001`, so they collide.)

```bash
ls -l /dev/v4l/by-path/
```

Each camera exposes **two** nodes: `-video-index0` is the capture device, `-video-index1` is the metadata node and **cannot** return frames.

Preview each one
```bash
ffplay /dev/videox   # replace x with index to check (-video-index0)
```

Then set `HAND_CAM_INDEX`, `TACTILE_CAM_L`, and `TACTILE_CAM_R` in `kernel/camera.py` to the three `index0` paths.

> **USB bandwidth.** The tactile cameras are the fragile part of this rig. `camera.py` forces MJPG at open (V4L2 ignores a format set *after* the resolution — that bug caused raw uncompressed streams, corrupted frames, and mid-run `USB disconnect`s). Even so, put the two tactile cameras on **different USB controllers** if you can (`lsusb -t` shows the tree) — two cameras sharing one USB 2.0 hub is what saturates it. Symptoms of saturation, in order: colour glitches, then `cap.read()` failures, then the device disappearing.

> **Felt haptic delay / stale frames.** `camera.py` also pins the tactile cameras' V4L2 capture queue to 1 frame (`cv2.CAP_PROP_BUFFERSIZE`). Without this, the default multi-frame queue lets unread frames pile up whenever a `read()` (reconstruction/height-map math) takes longer than one frame interval, so every later read returns a progressively staler frame — felt as haptic feedback that lags more as a session goes on, not a fixed constant delay. If it still feels delayed after this, check whether `sensor_process_main`'s per-loop `elapsed` (`run/experiment.py`) is regularly exceeding `1/HAPTIC_HZ` (~67ms) — that means reconstruction itself, not queuing, is the bottleneck.

> **If a camera stops opening:** check `sudo dmesg | tail -40` for `USB disconnect`. Replug (or `sudo modprobe -r uvcvideo && sudo modprobe uvcvideo`), then re-check `ls -l /dev/v4l/by-path/` — the paths are stable, but a camera moved to a *different port* gets a new path and `kernel/camera.py` needs updating.


**7. Calibrate the 9DTact sensors**

You need the calibration board (`src/9DTact-main/9DTact_Design/fabrication/calibration_board.STL`) and a ball matching `BallRad` in `run/shape_config.yaml` (default 4.0mm). Run per side:

```bash
python run/setup.py calibrate-camera --side left     # board
python run/setup.py calibrate-sensor --side left     # ball
python run/setup.py reconstruct      --side left     # verify: any object
```

Press **`y`** with nothing touching the sensor (reference frame), press the board/ball onto it, then **`y`** again. For reconstruct, press `y` to start imaging, and `q` to exit imaging. Open3D warnings will appear but they are ignorable. Repeat for `--side right`.

Each side's calibration lands in `data/calibration/sensor_L` / `sensor_R` (the path is set by `calibration_root_dir` in `run/shape_config.yaml`, with `sensor_<id>` appended per side).

> **Press firmly and squarely.** `calibrate-camera` must find every dot on the board; dots that only graze the gel come out too faint to detect. If it fails, it reports how many it found, saves a debug overlay showing which ones were missed, and names the likely cause.

**8. Optional — Force Calibration (convert deformation to Newtons)**

The Robotiq exposes no F/T reading and its `gCU` current register reads 0 mA regardless of contact, so grip force is derived from gel deformation instead (`deformation = height_map − baseline`). `experiment.py` computes this live per trial and logs it as `left_force_proxy`/`right_force_proxy` (see the trial-output column table under "Experiment" for what `volume`/`area_px`/`max_deform_mm`/`mean_deform_mm` mean).

`volume` (the deformation proxy logged per trial) is uncalibrated (∝ force, not Newtons) — fine for cross-condition comparison as-is, since Friedman/Wilcoxon are rank-based and a monotonic rescaling cannot change the p-values. This step is only needed if you want to report absolute force in Newtons; the study's rank-based analysis does not require it. Run the guided calibration once per side:

```bash
python run/setup.py calibrate-force --side left
python run/setup.py calibrate-force --side right
cd ..
```

It prompts you through the procedure, fits `force_N = a*volume + b` by least squares, prints `a`/`b`/R², and writes a scatter+fit figure and CSV to `data/results/`. Paste the printed constants into `FORCE_CAL_A_LEFT`/`FORCE_CAL_B_LEFT` (and `..._RIGHT`) in `experiment.py`.

**Procedure (a precision balance works as the force reference — no load cell needed):**
1. Place the balance on a stable surface and **tare** it to zero.
2. Centre a small **rigid indenter** on the pan (disc, coin, bolt head). Use the same indenter geometry you expect during trials — contact area affects deformation volume, so a fit done with a different indenter will not transfer.
3. Press the sensor's gel **down onto the indenter**. The balance reads the reaction force, so you never need a heavy object; you supply the force and the balance measures it. Using the gripper to apply the load is more repeatable than pressing by hand.
4. Hold steady, let the balance settle, and enter the reading in grams at each of ~8–10 levels spanning your expected force range (include one at 0 g). Force in N = grams × 0.00981.

> **Range:** a 600 g balance saturates at ≈5.9 N. Check your actual peak grip forces first — if trials routinely exceed the balance's range, you can only calibrate the lower portion, and **extrapolating the fit beyond the calibrated range is not defensible**. Cap the reported range and note it as a limitation instead.

> **Validity:** the fit holds only for the gel, sensor mounting, indenter, and `--contact-thresh` used during calibration — freeze them for the rest of the study. It applies to that side only; calibrate left and right separately, since their gel/mounting and `pixel_per_mm` differ.

---

## Experiment

**Prerequisites:**
* `hapticf` conda env is set up and activated (Setup & Installation, Step 1).
```bash
conda activate hapticf
```
* ESP32-C6 flashed and Robotiq gripper connected (Setup & Installation, Step 4).
```bash
ls /dev/tty{USB,ACM}*   # ttyACM0 = ESP32-C6, ttyUSB0 = Robotiq (via USB-RS485)
```
* Camera indices correctly assigned in `kernel/camera.py` (Setup & Installation, Step 5). 

```bash
ls -l /dev/v4l/by-path/
ffplay /dev/videox   # replace x with index to check (-video-index0)
```
Then set `HAND_CAM_INDEX`, `TACTILE_CAM_L`, and `TACTILE_CAM_R` in `kernel/camera.py` to the corresponding `index0` paths.

* Left and right sensors fully calibrated (Setup & Installation, Step 6).

**1. Start the ESP32 receiver**

The board runs the **receiver** (`firmware/stream.py`); `experiment.py` is the sender. `stream.py` is a stream-only receiver dedicated to the experiment — it parses `experiment.py`'s `"{left:.4f},{right:.4f}\n"` packets and drives the two channels **independently** (left -> thumb, right -> index). Set `METHOD` in `firmware/stream.py` to match your `--condition`: `"vibmotor"` for `lra`, `"tactiles"` for `tactiles`, `"tactiles2"` for `tactiles2`. (For `visual_only` you don't need to run this file at all.) Also set `HAND` in `firmware/stream.py` to match your `--hand` (`"right"`: thumb=M1/index=M2, `"left"`: thumb=M5/index=M4) — a left-hand mount is wired to a different pin pair.

> `stream.py` already implements the 2-value protocol above. The older
> `stream_mode()` / `tactiles_stream_mode()` in `firmware/haptic.py` are the
> legacy single-value broadcast receivers (one float to all five fingers) and
> are **not** what `experiment.py` talks to — use `stream.py`.

```bash
python -m mpremote connect /dev/ttyACM0 fs cp firmware/haptic.py :
python -m mpremote connect /dev/ttyACM0 fs cp firmware/stream.py :
python -m mpremote connect /dev/ttyACM0 repl
```

In the REPL, start it, then detach with **Ctrl-X** (frees the port, leaves it running):

```python
exec(open('stream.py').read())
```

**2. Activate the gripper (once per power-cycle)**

The Robotiq 2F-85 must be activated after every power-up before `experiment.py` will run — it checks `gSTA` at startup and exits with an error otherwise (see Setup & Installation, note under Step 3). Activation runs a full open/close self-calibration, so **clear any objects between the jaws** first:

```bash
python -c "
from pyrobotiqgripper import RobotiqGripper
g = RobotiqGripper('/dev/ttyUSB0')
g.connect()
g.activate()
print('Activated:', g.isActivated())
g.disconnect()
"
```

**3. Run the experiment**

One launch now covers a whole participant — all 4 conditions x 2 objects — instead of relaunching per condition/object. `--condition`/`--object` are just the STARTING values; cycle through the rest at runtime with `c`/`o`:

```bash
python run/experiment.py --condition visual_only --participant P01 --object fragile --out data/experiment_logs
```

| Flag | Values | Description |
| --- | --- | --- |
| `--condition` | `visual_only`, `lra`, `tactiles`, `tactiles2` | STARTING condition label for trial filenames. Cycle at runtime with **`c`** (only while paused and not recording — see Controls). Labels the saved data only — actual actuator behavior depends on which firmware is loaded on the ESP32; switching to/from a condition that needs different firmware walks you through reflashing it. `tactiles2` drives the binary contact-latch mechanism (see "TacTiles Pin Actuators" below) instead of `tactiles`'s continuous vibration. |
| `--hand` | `right` (default), `left` | Which hand wears the actuator glove. Printed at startup and passed to the reflash prompt so you set `HAND` in `firmware/stream.py` to match (`right`: thumb=0/index=1, `left`: thumb=4/index=3) — labeling/reflash-instruction only, does not itself move anything. |
| `--participant` | any string, e.g. `P01` | Participant ID, included in trial filenames. Relaunch per participant so a drifting gel baseline doesn't bias `volume`. |
| `--object` | `fragile`, `deformable` | Starting object class for trial filenames. Switch mid-session with **`o`** (cannot switch while recording). |
| `--out` | directory path | Base directory for trial CSVs. Default: `data/experiment_logs`. Each participant's trials are written into a `<out>/<participant>/` subfolder — with 4 conditions x 2 objects x N trials per participant, this keeps each participant's files together instead of one flat directory mixing everyone's trials. |

**Controls:**

Gripper position is driven entirely by hand-tracking — no manual/keyboard override. The session **starts paused**: nothing moves or buzzes until you resume. The same key legend is drawn on-screen (bottom-left of the video feed) as a reminder.

| Key | Action |
| --- | --- |
| `SPACE` | Pause / resume hand tracking. Paused freezes the gripper at its last position and sends 0-intensity to the haptics — use it whenever adjusting the rig, swapping objects, or between conditions. Blocked while a trial is recording. |
| `r` | Start / stop recording a trial. Blocked while paused — resume first. Stopping a trial prompts `[Y]es`/`[N]o` (fragile objects only, survived intact?) then `[S]ave`/`[D]iscard` — pick `D` to throw away a bad take (aborted grasp, setup mistake, etc.) instead of writing it to disk. |
| `o` | Toggle object class (`fragile` ↔ `deformable`) — only when not recording |
| `c` | Cycle condition (`visual_only` → `lra` → `tactiles` → `tactiles2` → ...) — only while paused and not recording. If the new condition needs different ESP32 firmware, walks you through releasing the serial port, reflashing (`mpremote`), and reconnecting before you resume. |
| `q` | Quit |

**Trial output files:**

```
data/experiment_logs/<participant>/<participant>_<condition>_<object>_trial<N>.csv
```

Discarded trials (`D` at the save/discard prompt) are not written — the CSV is deleted after the prompt and that trial number is skipped, so gaps in `trial<N>` numbering are expected and not a sign of missing data.

Columns per row (~30 Hz while recording is active):

| Column | Description |
| --- | --- |
| `t` | Seconds since trial start |
| `gripper_pos_bit` | Raw Robotiq position (0–225) |
| `left_force_proxy` / `right_force_proxy` | Deformation volume — grip-force proxy (uncalibrated), left/right sensor. Replaces the dead `current_mA`. See "Optional — Force Calibration" in Setup & Installation. |
| `left_force_N` / `right_force_N` | Calibrated force (N) per side, `FORCE_CAL_A_<SIDE>*volume + FORCE_CAL_B_<SIDE>`; empty unless that side's calibration constants are set in `experiment.py` |
| `left_max_depth_mm` / `right_max_depth_mm` | Raw max sensor indentation depth (mm), per side |


The per-side force proxy is `volume` from `compute_metrics()` (`kernel/tactile.py`); the underlying per-frame metrics are:

| Metric | Meaning |
| --- | --- |
| `volume` | Σ\|deformation\| over the contact region — headline force proxy |
| `area_px` | Pixels in contact |
| `max_deform_mm` | 99th-percentile deformation depth |
| `mean_deform_mm` | Mean deformation over the contact region |

> **Schema note:** this uses left/right column pairs, replacing the older single-sensor columns (`force_proxy`, `force_N`, `max_depth_mm`, `haptic_intensity`). `analysis.py` reads this schema and collapses the two sides per metric via `--collapse` (see below).

**Analyzing results:**

```bash
python run/analysis.py \
  --trials-dir data/experiment_logs \
  --likert-csv data/experiment_logs/likert_responses.csv \
  --out results \
  --collapse sum_n
```

`--trials-dir` is scanned recursively, so pointing it at `data/experiment_logs` picks up every participant's trial CSVs from their `P01/`, `P02/`, ... subfolders in one pass — no need to run analysis.py per participant.

See `run/analysis.py` for the full Chapter 5 analysis pipeline (Friedman test, Wilcoxon, time-series figures).

> **`--collapse` (combining the two sensors):** each metric needs one force + one depth series per trial, so the left/right sensors are collapsed. `sum_n` (default) sums the calibrated `force_N` columns (Newtons) and takes `max` depth — the headline once both sensors are load-cell calibrated ([Step 7](#7-collect-grip-force-proxy-via-gel-deformation)). `max` uses the max of the raw force proxies (uncalibrated) and works before calibration. Contact time is "first of either finger" under both. Since the Friedman/Wilcoxon tests are rank-based, `sum` and `mean` give identical results; only `sum_n` vs `max` can reorder trials — run both into separate `--out` dirs and confirm the significant findings agree. On uncalibrated data `sum_n` leaves the two force metrics blank (empty `force_N`) and tells you to switch to `--collapse max`.

> **Camera note:** the three device paths in `kernel/camera.py` must be distinct — `experiment.py` checks at startup and exits if two collide. They are `/dev/v4l/by-path/` paths (see [Step 5](#5-confirm-the-sensor-cameras-are-detected)), which survive re-enumeration, so they only need changing if a camera is moved to a different USB port.

---

## Hardware Reference

### Gripper Range & Fixture Safety

> **Sensor fixture protection.** Commanding a full close against a rigid object that doesn't compress drives the jaws into it past the point of pure closing force — the excess torque has nowhere to go but into tilting the 9DTact sensor fixture, which has broken the mount a few times. Two mitigations, both retunable if it keeps happening on harder objects:
> - **`MAX_POS`** (`kernel/gripper.py`) is capped at `195`, below the Robotiq's true mechanical closed position (`225`), leaving margin before jaw hard-stop.
> - **`MAX_SAFE_DEPTH_MM`** (`run/experiment.py`, default `0.7`mm) is a runtime cutoff in `motion_loop`: once either sensor's `max_depth_mm` reaches this depth, the object has stopped compressing, and `motion_loop` blocks any *further* closing (opening is never blocked) until depth drops back down. It's set below `DEPTH_SATURATION_MM` (`kernel/tactile.py` — where haptic intensity saturates to 1.0) so it engages before the gel is fully bottomed out. A `[Safety] Max sensor depth reached ...` message prints to the console when it first engages.
>
>   `DEPTH_SATURATION_MM` is now **per object class**: `2.0`mm for `fragile`, `0.6`mm for `deformable`. Deformable objects barely indent the gel and were hitting the `0.7`mm safety cutoff well before reaching the old single `2.0`mm saturation point — capping deformable-trial haptic intensity at ~0.35 and making the LRA/TacTiles feedback feel weak regardless of grip force. The `0.6`mm deformable saturation point reaches full intensity with margin to spare below the safety cutoff. `TactileSensor.read(object_class=...)` (`kernel/tactile.py`) picks the saturation point; `SharedState.object_class` (`run/experiment.py`) mirrors `RecordingState.current_object` into shared memory so the sensor processes — which run separately from the keyboard thread — pick it up on the next tick after pressing `o`.

### Hand Tracking (`kernel/tracking.py`)

MediaPipe HandLandmarker maps the thumb-tip/index-tip landmark distance (per frame) to the gripper's target position; `PINCH_DIST_PX` is the pixel distance treated as "fully closed" and `SPREAD_DIST_PX` as "fully open".

> **Actuator occlusion — MediaPipe dropping out during `tactiles`.** The TacTiles actuator body is mounted directly on the thumb and index fingertips, i.e. right over the landmarks (`4`, `8`) this module tracks — unlike the LRA motors, which sit nearer the proximal joints and don't sit on top of those landmarks. With MediaPipe's default confidence thresholds (`0.6`/`0.75`/`0.75`), that partial occlusion was enough to lose hand presence entirely ("No Hand" on the overlay) once the TacTiles hardware was in frame — this is the "mediapipe is off" symptom specific to the tactiles condition (and now tactiles2, which uses the same fingertip-mounted hardware). `create_hand_detector()` now uses lower thresholds (`min_hand_detection_confidence=0.4`, `min_hand_presence_confidence=0.5`, `min_tracking_confidence=0.5`) so tracking survives the occlusion. If detection still drops out on your rig, lower these further — but each notch down trades some jitter/false-positive resistance for detection robustness.

> **Gripper travel shorter than the operator's real finger motion.** The TacTiles actuator body also adds physical standoff between the thumb and index contact points (mounted right at the fingertip, unlike the joint-mounted LRA motors), so with the hardware on, fingers can no longer physically reach the bare-finger `PINCH_DIST_PX` (previously `30`px) — the gripper undershot `MAX_POS` and never fully closed, making the whole mapped range feel compressed. `PINCH_DIST_PX` is now `45`px. Retune per rig/actuator thickness: with the actuator mounted, pinch your fingers fully together, read `Finger Dist` off the on-screen overlay, and set `PINCH_DIST_PX` a few px above that floor (comment in `kernel/tracking.py` gives the suggested `10`–`60` tuning range).

### Robotiq 2F-85 (`kernel/gripper.py`)

The gripper is controlled from the host PC via Modbus RTU at 115200 baud over a USB-to-RS485 adapter (`/dev/ttyUSB0`). The `pyrobotiqgripper` library handles activation, calibration, and position commands.

| Parameter | Value |
| --- | --- |
| Port | `/dev/ttyUSB0` |
| Baud rate | 115200 |
| Protocol | Modbus RTU |
| Slave ID | 0x09 |

### Actuator Placement

The two haptic actuator types are mounted at different positions on the glove, not just driven by different hardware: LRA vibration motors sit near the thumb/index proximal joints, while TacTiles pin actuators sit at the thumb/index fingertips. Both deliver intensity-modulated, continuous-style feedback (`ACDriver`'s envelope-scaled bipolar carrier; `TactileVibrationDriver`'s intensity-scaled burst/gap rate) — the `lra` vs `tactiles` comparison is therefore a comparison of actuator technology *and* placement (proximal joint vs. fingertip) under the same continuous-feedback strategy, not a comparison of feedback *mechanism* (continuous vs. binary contact). The binary contact-latch mechanism (`tactiles2`/`TactileLatchDriver`, mirroring `tests/test_tactiles2.py`) exists in the codebase but is a separate design point, outside this comparison.

### LRA Vibration Motors

Selected via `METHOD = "vibmotor"` in `firmware/stream.py`. The firmware applies a continuous PWM signal per channel. Values are clamped to `[0.0, 1.0]` and mapped to a 10-bit duty cycle (0–1023) at 200 Hz. In streaming mode, if no packet is received within 200 ms all motors stop automatically.

> **As of the dual-sensor host update**, the stream receiver must parse
> `"{left:.4f},{right:.4f}\n"` and drive M1 (thumb) from `left` and M2
> (index) from `right` independently — not one value broadcast to every
> channel. M3/M4/M5 (middle/ring/pinky) have no corresponding sensor and
> should stay at 0 unless you wire up more sensors.

| Channel | Finger | PWM Pin | EN Pin | Driven by |
| --- | --- | --- | --- | --- |
| M1 | Thumb | GPIO 20 | GPIO 21 | left sensor |
| M2 | Index | GPIO 14 | GPIO 15 | right sensor |
| M3 | Middle | GPIO 6 | GPIO 7 | idle (no sensor) |
| M4 | Ring | GPIO 0 | GPIO 1 | idle (no sensor) |
| M5 | Pinky | GPIO 4 | GPIO 5 | idle (no sensor) |

NSLEEP is held HIGH (no sleep) via GPIO 19.

### TacTiles Pin Actuators

Selected via `METHOD = "tactiles"` in `firmware/stream.py`. TacTiles are bistable pin actuators driven by H-bridges. Each actuator is controlled by an IN1/IN2 pair — a short pulse in one direction engages the pin toward the skin; the opposite direction retracts it. Because the actuator latches mechanically, zero power is drawn while held.

> Bench-confirmed the pin only contacts skin on the IN2 pulse, not IN1 — backwards from the H-bridge's nominal "forward" convention. `TacTiles.engage()`/`disengage()` (`firmware/haptic.py`) pulse IN2/IN1 accordingly, so `engage` always means contact and `disengage` always means retract regardless of the underlying pin direction.

| Mode | Behaviour |
| --- | --- |
| `engage` | 6 ms IN2 pulse → pin contacts skin, latches |
| `disengage` | 10 ms IN1 pulse → pin retracts, latches |
| `pulse` | 3 ms forward + 3 ms reverse → quick tap, no sustained contact |
| `burst` | Rapid sequence of pulses, up to ~200 Hz in short windows |

Sustained vibration is approximated by repeated bursts with a gap between them, driven non-blocking (`TactileVibrationDriver`, mirroring the LRA path's `ACDriver`) so both channels buzz continuously and independently. The gap between bursts is set continuously from intensity — short gap (more frequent bursts) at high intensity, long gap at low intensity — keeping the long-term switch rate under the hardware thermal limit of ~120 switches/minute. This gives the same "buzzes the whole time intensity > 0" feel as the vibmotor path, rather than a single tap fired only when a threshold is crossed. This is the mechanism the study's `tactiles` condition data was collected under.

> **Vibration intensity tuning.** `TACTILE_PULSE_MS` (each tap's pin-throw duration) and `TACTILE_VIBRATE_GAP_MIN_MS` (the burst gap floor at intensity 1.0) in `firmware/haptic.py` control how strong the buzz feels — longer pulses and a lower gap floor both read as more intense. Current defaults are `TACTILE_PULSE_MS = 4` and `TACTILE_VIBRATE_GAP_MIN_MS = 35` (up from `3`/`50`). If the actuator runs hot at these settings, raise `TACTILE_VIBRATE_GAP_MIN_MS` back up first — it directly trades off against the ~120 switches/minute thermal limit noted above; `TACTILE_BURST_US` must stay `> 2 * TACTILE_PULSE_MS * 1000` if you change `TACTILE_PULSE_MS` again.

> **`METHOD = "tactiles2"` (binary contact latch, `--condition tactiles2`).** `stream.py` also supports a second TacTiles path — `run_tactiles2_stream()` driving `TactileLatchDriver` (`firmware/haptic.py`), the same binary contact/no-contact mechanism as `tests/test_tactiles2.py`, selected via `experiment.py --condition tactiles2` (cycle to it at runtime with `c`, after `tactiles`). Once a channel's streamed intensity reaches `TACTILE_LATCH_THRESHOLD` (default `0.1`), it fires `engage()` plus a restrike `engage()` `TACTILE_RESTRIKE_MS` (default `25`ms) later — the first pulse doesn't always fully seat the pin against skin contact resistance — then holds the latch (zero power, no further pulsing) until intensity drops back below the threshold, which fires a single `disengage()`. The threshold defaults low rather than to e.g. `0.5` because intensity is `deform_mm / DEPTH_SATURATION_MM[object_class]` and `MAX_SAFE_DEPTH_MM` (`run/experiment.py`, `1.0`mm) blocks further closing once either sensor reaches that depth — for `fragile` objects (`2.0`mm saturation) that caps intensity at `~0.5` right at the closing-block boundary, so a `0.5` threshold would only ever latch at that edge (if at all).
>
> **Note:** `tactiles2` was added after the study's first 19 participants, who only ran `visual_only`/`lra`/`tactiles`. Their `tactiles` trials remain valid vibration-condition data; `tactiles2` trials only exist for participants run after this change — keep that in mind for any analysis that assumes every participant covers all conditions.

| Channel | Finger | IN1 Pin | IN2 Pin |
| --- | --- | --- | --- |
| T1 | Thumb | GPIO 20 | GPIO 21 |
| T2 | Index | GPIO 14 | GPIO 15 |
| T3 | Middle | GPIO 6 | GPIO 7 |
| T4 | Ring | GPIO 0 | GPIO 1 |
| T5 | Pinky | GPIO 4 | GPIO 5 |

### Bench Self-Tests (`tests/`)

Board-only sanity checks — no host PC, gripper, or live stream needed. Copy
`firmware/haptic.py` plus the test file to the board and `exec()` it in the
REPL (see each file's docstring for the exact `mpremote` commands); use
`mpremote repl`, not `mpremote run`, so Ctrl-C reaches the board and turns
every actuator off.

| File | Actuator | Behaviour |
| --- | --- | --- |
| `test_tactiles.py` | TacTiles | Continuous burst/gap vibration, `ON_S` seconds ON / `OFF_S` seconds OFF |
| `test_tactiles2.py` | TacTiles | Binary latch — `engage()` held for `ON_S`, `disengage()` held for `OFF_S`, no buzzing |
| `test_vibmotor.py` | LRA vibmotor | `ACDriver` bipolar AC buzz, `ON_S` seconds ON / `OFF_S` seconds rest |

All three default to `THUMB, INDEX` at full intensity on a 6s ON / 3s OFF loop — edit `FINGERS`/`INTENSITY`/`ON_S`/`OFF_S` at the top of each file to change it.

---

## Writing & Manuscript

The thesis manuscript is in the `paper/` directory.

* Requires a LaTeX distribution (TeX Live or MiKTeX).
* Compile with `latexmk -pdf paper/main.tex` or using the LaTeX Workshop VS Code extension.
* Figures are pulled from the `figures/` directory.

---

## Author

**Adriel I. Santoso** Department of Mechanical and Aerospace Engineering, Tohoku University