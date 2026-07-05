# Tactile-Feedback Teleoperation: Grip Force and Grasping Performance Across Haptic Actuator Types for Fragile and Deformable Objects

## Overview

This repository is the source code for a bachelor's thesis investigating grip force and grasping performance across haptic feedback actuator types in robotic gripper teleoperation. A Robotiq 2F-85 Adaptive Gripper is fitted with stress-deformation-based tactile sensors; tactile data is translated and sent to a custom multi-channel actuator platform (ESP32-C6) for real-time stimuli. The study collects quantitative latency metrics and qualitative survey data comparing user experience during delicate object manipulation.

The stack supports two haptic feedback methods — LRA vibration motors (PWM) and TacTiles pin actuators (H-bridge) — selectable from a single script, plus direct Modbus RTU communication with the Robotiq gripper from a host PC.

## Repository Structure

```text
haptic-feedback/
├── data/                           # Experimental data logs
│   ├── experiment_logs/            # Logs from experiment.py
│   └── results/                    # Results from data_analysis.py
├── designs/                        # CAD models and 3D print assets
├── run/                            # Files to be executed for the project
│   ├── analysis.py                 # Data analysis pipeline (Friedman, Wilcoxon, figures)
│   ├── config.py                   # Configuration parameters for the experiment
│   ├── experiment.py               # Main experiment script
│   ├── shape_config_left.yaml      # Configuration file for left 9Dtact sensor
│   └── shape_config_right.yaml     # Configuration file for right 9Dtact sensor
├── src/                            # Source submodules and core libraries
│   ├── 9DTact-main/                # 9DTact tactile sensor source code
│   ├── pyRobotiqGripper-master/    # Robotiq gripper driver
│   ├── calibration.py              # Camera calibration, sensor calibration, and 3D reconstruction
│   ├── measurement.py              # Records tactile deformation-based grip-force proxy
│   └── utilities.py                # Shared MicroPython driver library (LRA + TacTiles)
├── models/                         # Trained current-prediction models (per sensor)
├── paper/                          # Thesis manuscript (LaTeX source)
├── README.md                       # This file
└── requirements.txt                # Python dependencies
```

## Hardware Requirements

* NVIDIA GPU with driver supporting **CUDA ≥13.0** (check with `nvidia-smi`)
* Robotiq 2F-85 with USB-RS485 adapter (for communication to the host PC)
* ESP32-C6 development board (custom-made for haptic feedback)
* 1 USB-C **data** cable (for the ESP32-C6)
* 2 USB-Micro-B cables (for 9DTact LED board power supply)
* 3 USB-Micro-B **data** cables (for 9DTact cameras and hand tracking camera)
* 2 LRA vibration motors (connected to thumb and index fingertips)
* 2 TacTiles pin actuators (connected to thumb and index fingertips)

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
# conda remove -n hapticf --all -y   # uncomment to wipe an existing env before recreating
conda create -n hapticf python=3.10 -y
conda activate hapticf
conda env config vars set PYTHONNOUSERSITE=1    # isolate from ~/.local
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
python -c "import cv2, scipy, ml_collections, open3d, torch, numpy, serial, minimalmodbus, mediapipe, pynput, pandas; print('cuda:', torch.cuda.is_available()); print('all ok')"
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
conda env config vars set PYTHONPATH=/home/adriel/Documents/haptic-feedback
conda deactivate && conda activate hapticf
```

> Note on versions: Both 9DTact and pyRobotiqGripper are actively developed upstream, so a fresh clone may pull a newer version than what this guide was tested against. If you hit install or import errors, check your installed version first:
```bash
pip show 9DTact pyrobotiqgripper
```
> This guide was last verified working against 9DTact **v1.0** and pyRobotiqGripper **v3.2.7**.


**4. Flash MicroPython onto the ESP32-C6**
Download the firmware `.bin` for your board from the [MicroPython downloads page](https://micropython.org/download/ESP32_GENERIC_C6/) and place it in the repo root.
```bash
ls /dev/tty{ACM}*   # ttyACM0 = ESP32-C6
```
Find the firmware file (paste this whole block at once — it's a single shell script):
```bash
BIN_FILE=$(ls -t *.bin 2>/dev/null | head -n 1)
if [ -z "$BIN_FILE" ]; then
  echo "No .bin file found — download the firmware first."
  exit 1
fi
echo "Flashing: $BIN_FILE"
```
Then flash it:
```bash
python -m esptool --chip esp32c6 --port /dev/ttyACM0 erase-flash
python -m esptool --chip esp32c6 --port /dev/ttyACM0 --baud 460800 write-flash -z 0x0 "$BIN_FILE"
```

**5. Confirm the sensor cameras are detected**
```bash
ls /dev/video*
ffplay /dev/videox   # Replace x with each index
```
After visual check, set `HAND_CAM_INDEX`, `TACTILE_CAM_L`, and `TACTILE_CAM_R` in `run/config.py` before each session.


**6. Calibrate the 9DTact sensors**
Prepare a calibration board from `src/9DTact-main/9DTact_Design/fabrication/calibration_board.STL` and a ball of radius 4.0mm, before running the following commands:
```bash
python src/calibration.py calibrate-camera --side left        # calibration board
python src/calibration.py calibrate-camera --side right
python src/calibration.py calibrate-sensor --side left        # 4.0mm ball
python src/calibration.py calibrate-sensor --side right
python src/calibration.py reconstruct --side left             # any object
python src/calibration.py reconstruct --side right
```
> For each step, press **`y`** with nothing touching the sensor to save the reference frame, then press the board/ball/object onto the sensor and **`y`** again to capture. `reconstruct` opens a live tactile image, depth map, and point cloud. If the detected grid-point count is off in calibration, adjust lighting/contact and rerun.
> Press `q` to exit the window.


**7. Collect grip force proxy via gel deformation**
The Robotiq exposes no F/T reading and its `gCU` current register reads 0 mA regardless of contact, so grip force is derived from gel deformation instead (`deformation = height_map − baseline`). `experiment.py` computes this live per trial; `measurement.py` is the standalone version for calibration/characterization only.

| Metric | Meaning |
| --- | --- |
| `volume` | Σ\|deformation\| over the contact region — headline force proxy |
| `area_px` | Pixels in contact |
| `max_deform_mm` | 99th-percentile deformation depth |
| `mean_deform_mm` | Mean deformation over the contact region |

```bash
python src/measurement.py --side left --out data/left --rate 20 --duration 30 --show
python src/measurement.py --side right --out data/right --rate 20 --duration 30 --show
```
`volume` is uncalibrated (∝ force, not Newtons) — fine for cross-condition comparison as-is. To convert to Newtons: press at several known forces (scale/load cell), fit `force_N = a*volume + b` via `np.polyfit`, and set `FORCE_CAL_A`/`FORCE_CAL_B` in `experiment.py`. Calibration is only valid if the gel, sensor, and `--contact-thresh` stay fixed between calibration and trials.

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
* Camera indices correctly assigned in `run/config.py` (Setup & Installation, Step 5).
* Left and right sensors fully calibrated (Setup & Installation, Step 6).

> **Before your first participant — go/no-go check:**
> 1. Gripper **open / sensor untouched** at launch — the baseline is captured at startup, so contact here corrupts every `volume`.
> 2. Record one **throwaway trial** (`r` to start/stop): confirm the `Fp:` readout rises on contact and returns to ~0 on release, and that the haptic actuator actually fires.
> 3. Reporting **Newtons**? Calibrate ([3b](#3b-grip-force-modeling-deformation-proxy)) and then freeze the gel/sensor/`--contact-thresh` for the rest of the study. For **relative** cross-condition comparison, skip calibration.
> 4. Relaunch `experiment.py` **per participant** so a drifting gel baseline doesn't bias `volume`.

**Step 1 — Start the ESP32 receiver**

The board runs the **receiver**; `experiment.py` is the sender. Set `METHOD="vibmotor"`, `MODE="stream"` in `run/test_haptic.py`, then in a separate terminal:

```bash
conda activate hapticf
python -m mpremote connect /dev/ttyACM0 fs cp src/utilities.py :
python -m mpremote connect /dev/ttyACM0 fs cp run/test_haptic.py :
python -m mpremote connect /dev/ttyACM0 repl
```

In the REPL, start it, then detach with **Ctrl-X** (frees the port, leaves it running):

```python
exec(open('test_haptic.py').read())
```

**Step 2 — Run the experiment**

```bash
conda activate hapticf
python run/experiment.py --condition lra --participant P01 --object fragile --out data/experiment_logs
```

| Flag | Values | Description |
| --- | --- | --- |
| `--condition` | `visual_only`, `lra`, `tactiles` | Labels the saved data with the feedback condition. Does **not** switch actuator hardware — that depends on which firmware is loaded on the ESP32. |
| `--participant` | any string, e.g. `P01` | Participant ID, included in trial filenames. |
| `--object` | `fragile`, `deformable` | Starting object class for trial filenames. Switch mid-session with **`o`** (cannot switch while recording). |
| `--out` | directory path | Where to save trial CSVs. Default: `data/experiment_logs`. |

**Controls:**

| Key | Action |
| --- | --- |
| `m` | Toggle hand-tracking / manual gripper control |
| `r` | Start / stop recording a trial |
| `o` | Toggle object class (`fragile` ↔ `deformable`) — only when not recording |
| `↑` / `k` | Open gripper (manual mode only) |
| `↓` / `j` | Close gripper (manual mode only) |
| `q` | Quit |

**Trial output files:**

```
data/experiment_logs/<participant>_<condition>_<object>_trial<N>.csv
```

Columns per row (~30 Hz while recording is active):

| Column | Description |
| --- | --- |
| `t` | Seconds since trial start |
| `gripper_pos_bit` | Raw Robotiq position (0–225) |
| `force_proxy` | Deformation volume — grip-force proxy (uncalibrated). Replaces the dead `current_mA`. See [3b](#3b-grip-force-modeling-deformation-proxy) |
| `force_N` | Calibrated force (N), `FORCE_CAL_A*volume + FORCE_CAL_B`; empty unless calibration constants are set in `experiment.py` |
| `max_depth_mm` | Raw max sensor indentation depth (mm) |
| `haptic_intensity` | 0.0–1.0 value streamed to ESP32 |
| `motion_mode` | `hand_tracking` or `manual` |

**Analyzing results:**

```bash
python run/analyze_results.py \
  --trials-dir data/experiment_logs \
  --likert-csv data/experiment_logs/likert_responses.csv \
  --out results
```

See `run/analyze_results.py` for the full Chapter 5 analysis pipeline (Friedman test, Wilcoxon, time-series figures).

> **Camera index note:** `HAND_CAM_INDEX` must not equal `TACTILE_CAM_L` or `TACTILE_CAM_R` at the top of `experiment.py` — the script checks this at startup and exits with an error if they collide. Update all three constants before each session.

---



### Robotiq 2F-85 (`test_gripper.py`)

The gripper is controlled from the host PC via Modbus RTU at 115200 baud over a USB-to-RS485 adapter (`/dev/ttyUSB0`). The `pyrobotiqgripper` library handles activation, calibration, and position commands.

| Parameter | Value |
| --- | --- |
| Port | `/dev/ttyUSB0` |
| Baud rate | 115200 |
| Protocol | Modbus RTU |
| Slave ID | 0x09 |

### LRA Vibration Motors

Selected via `METHOD = "vibmotor"` in `test_haptic.py`. The firmware applies a continuous PWM signal per channel. Values are clamped to `[0.0, 1.0]` and mapped to a 10-bit duty cycle (0–1023) at 200 Hz. In streaming mode, if no packet is received within 200 ms all motors stop automatically.

| Channel | Finger | PWM Pin | EN Pin |
| --- | --- | --- | --- |
| M1 | Thumb | GPIO 20 | GPIO 21 |
| M2 | Index | GPIO 14 | GPIO 15 |
| M3 | Middle | GPIO 6 | GPIO 7 |
| M4 | Ring | GPIO 0 | GPIO 1 |
| M5 | Pinky | GPIO 4 | GPIO 5 |

NSLEEP is held HIGH (no sleep) via GPIO 19.

### TacTiles Pin Actuators

Selected via `METHOD = "tactiles"` in `test_haptic.py`. TacTiles are bistable pin actuators driven by H-bridges. Each actuator is controlled by an IN1/IN2 pair — a short forward pulse engages the pin toward the skin; a reverse pulse retracts it. Because the actuator latches mechanically, zero power is drawn while held.

| Mode | Behaviour |
| --- | --- |
| `engage` | 6 ms forward pulse → pin contacts skin, latches |
| `disengage` | 10 ms reverse pulse → pin retracts, latches |
| `pulse` | 3 ms forward + 3 ms reverse → quick tap, no sustained contact |
| `burst` | Rapid sequence of pulses, up to ~200 Hz in short windows |

Sustained vibration is approximated by repeated bursts with a gap between them. The gap is set automatically based on intensity, keeping the long-term switch rate under the hardware thermal limit of ~120 switches/minute. In streaming mode, a pulse fires when the incoming value exceeds 0.5, with a 500 ms per-channel rate limit.

| Channel | Finger | IN1 Pin | IN2 Pin |
| --- | --- | --- | --- |
| T1 | Thumb | GPIO 20 | GPIO 21 |
| T2 | Index | GPIO 14 | GPIO 15 |
| T3 | Middle | GPIO 6 | GPIO 7 |
| T4 | Ring | GPIO 0 | GPIO 1 |
| T5 | Pinky | GPIO 4 | GPIO 5 |

---

## Writing & Manuscript

The thesis manuscript is in the `paper/` directory.

* Requires a LaTeX distribution (TeX Live or MiKTeX).
* Compile with `latexmk -pdf paper/main.tex` or using the LaTeX Workshop VS Code extension.
* Figures are pulled from the `figures/` directory.

---

## Author

**Adriel I. Santoso** Department of Mechanical and Aerospace Engineering, Tohoku University