# Tactile-Feedback Teleoperation: Grip Force and Grasping Performance Across Haptic Actuator Types for Fragile and Deformable Objects

> [!IMPORTANT]
> **Source Code Dependencies**
> To run this project, you must first download the 9DTact source code and the Robotiq gripper driver into the `src/` directory:
> 1. Clone or download the `9DTact` repository into `src/9DTact-main/`
> 2. Download `pyrobotiqgripper.py` from the [pyRobotiqGripper Installation Guide](https://pyrobotiqgripper.readthedocs.io/en/latest/installation.html) and place it in `src/pyrobotiqgripper.py`

## Overview

This repository contains the hardware driver code and supporting materials for a bachelor's thesis investigating the efficacy of haptic feedback modalities in teleoperation. Specifically, the project integrates a Robotiq 2F-85 Adaptive Gripper fitted with stress-deformation based tactile sensors. The tactile data is translated and sent to a custom multi-channel haptic actuator platform (ESP32-C6) to deliver real-time stimuli. The study collects quantitative latency metrics and qualitative survey data to compare the user experience during delicate object manipulation.

The software stack supports two haptic feedback methods — ERM vibration motors (PWM) and TacTiles pin actuators (H-bridge) — selectable from a single script, alongside direct Modbus RTU communication with the Robotiq gripper via a host PC.

## Repository Structure

```text
haptic-feedback/
├── src/                 # Source submodules and core libraries
│   ├── 9DTact-main/     # 9DTact tactile sensor source code
│   ├── pyrobotiqgripper.py # Robotiq gripper driver
│   └── utilities.py     # Shared MicroPython driver library (ERM + TacTiles)
├── run/                 # Execution scripts for tests and experiments
│   ├── experiment.py    # Main sequence script
│   ├── shape_config.yaml# Configuration file for shapes
│   ├── test_9dtact.py   # 9DTact sensor testing script
│   ├── test_gripper.py # Robotiq gripper control script
│   ├── test_haptic.py   # Haptic test/stream script — set METHOD inside to switch type (ESP32-C6)
│   ├── calibrate_9dtact.py # 9DTact calibration + live reconstruction CLI
│   ├── collect_current_data.py # Records tactile depth maps + gripper motor current (gCU)
│   ├── train_current_model.py  # Trains depth map -> grip current (mA) regressor
│   └── run_current_model.py    # Runs the trained model live during grasping experiments
├── models/              # Trained current-prediction models (per sensor)
├── backups/             # System and data backups
├── data/                # Experimental data logs
├── designs/             # CAD models and 3D print assets
├── figures/             # Experimental setup photos and result figures
├── paper/               # Thesis manuscript (LaTeX source)
├── requirements.txt     # Python dependencies
└── README.md
```

## Hardware Requirements

* ESP32-C6 development board (e.g., ESP32-C6-DevKitC-1)
* USB-C or USB-A **data** cable (not power-only)
* Up to 5 ERM vibration motors (connected to M1–M5), or
* Up to 5 TacTiles pin actuators with H-bridge driver board (connected to T1–T5)

## Software Requirements

Two separate environments are used — one per subsystem. This keeps dependencies isolated and each environment minimal. ROS is not required.

| Component | Environment | Reason |
| --- | --- | --- |
| Robotiq gripper + ESP32 host scripts | `.venv` (pyserial only) | Lightweight; no version pinning needed |
| 9DTact shape reconstruction | `conda: 9dtact` (Python 3.8 + CUDA) | Requires Python 3.8 exactly; heavy GPU deps |

Other requirements:

* Python ≥ 3.7 on host PC (Linux / macOS / Windows)
* MicroPython firmware: `ESP32_GENERIC_C6-20250415-v1.25.0.bin`

---

## Installation

### Part 1 — Gripper and ESP32 host scripts (`.venv`)

#### 1. Create and activate the virtual environment

```bash
python -m venv .venv
```

```bash
# Linux / macOS
source .venv/bin/activate

# Windows (Command Prompt)
.venv\Scripts\activate.bat

# Windows (PowerShell)
.venv\Scripts\Activate.ps1
```

#### 2. Install host-side Python tools

```bash
python -m pip install -r requirements.txt
```

#### 3. Flash MicroPython onto the ESP32-C6 (one-time)

Download the firmware:

```bash
wget https://micropython.org/resources/firmware/ESP32_GENERIC_C6-20250415-v1.25.0.bin
```

With both devices plugged in, verify they are detected:

```bash
ls /dev/tty{USB,ACM}*
# Expected:
# /dev/ttyACM0   ← ESP32-C6
# /dev/ttyUSB0   ← Robotiq gripper (via USB-RS485 adapter)
```

If you get permission errors, add yourself to the `dialout` group:

```bash
sudo usermod -aG dialout $USER  # log out and back in after
# To apply immediately without logging out:
exec newgrp dialout
```

Erase and flash the ESP32 (⚠️ erases all existing data):

The ESP32-C6 must be in bootloader mode before esptool connects. Enter it manually:

1. Hold **BOOT**
2. Press and release **RESET** — keep holding BOOT
3. Run the command below
4. Release **BOOT** once you see `Connecting...`

```bash
esptool --chip esp32c6 --port /dev/ttyACM0 erase-flash
esptool --chip esp32c6 --port /dev/ttyACM0 --baud 460800 write-flash -z 0x0 ESP32_GENERIC_C6-20250415-v1.25.0.bin
```

#### 4. (Optional) Remove default boot script

```bash
mpremote connect /dev/ttyACM0 fs rm boot.py
```

---

### Part 2 — 9DTact shape reconstruction (`conda: 9dtact`)

#### 1. Create and activate the conda environment

```bash
conda create -n 9dtact python=3.8 -y
deactivate
conda activate 9dtact
which python  # confirm: .../envs/9dtact/bin/python
```

> **Important:** Use only `python -m pip` for all installs — never `conda install`. Mixing conda and pip package managers into the same env causes `ClobberErrors` that corrupt the environment and require a full rebuild.

#### 2. Install PyTorch with CUDA 11.8

```bash
python -m pip install torch==2.0.1+cu118 torchvision==0.15.2+cu118 torchaudio==2.0.2+cu118 \
  --index-url https://download.pytorch.org/whl/cu118
```

#### 3. Install remaining dependencies

```bash
python -m pip install \
  opencv-python \
  scipy==1.10.1 \
  ml_collections==0.1.1 \
  open3d \
  PyYAML==6.0.1 \
  numpy==1.23.5
```

#### 4. Register the local package

```bash
cd src/9DTact-main
python -m pip install -e . --no-deps
cd ../..
```

#### 5. Set the repo root on the Python path permanently

```bash
conda env config vars set PYTHONPATH=/home/adriel/Documents/haptic-feedback
conda deactivate
conda activate 9dtact
```

#### 6. Verify the environment

```bash
python -c "
import cv2, scipy, ml_collections, open3d, torch, numpy
print('cv2:', cv2.__version__)
print('numpy:', numpy.__version__)
print('torch:', torch.__version__)
print('cuda:', torch.cuda.is_available())
print('all ok')
"
```

**Expected output:**

```text
cv2: 4.x.x
numpy: 1.23.5
torch: 2.0.1+cu118
cuda: True
all ok
```

> **Note:** If the env ever gets corrupted (`ClobberErrors` from accidental `conda install`), rebuild cleanly: `conda deactivate && conda remove -n 9dtact --all -y`, then repeat from the top.

#### 7. Confirm the sensor cameras are detected

```bash
ls /dev/video*
# Should show at least /dev/video0
```

To identify which index corresponds to which camera:

```bash
for i in /dev/video*; do echo "$i: $(cat /sys/class/video4linux/$(basename $i)/name 2>/dev/null)"; done
```

Verify visually if needed:

```bash
ffplay /dev/videox   # replace x with the index to check
```

Update `HAND_CAM_INDEX` at the top of `test_gripper.py` and `TACTILE_CAM_L` / `TACTILE_CAM_R` at the top of `calibrate_9dtact.py` accordingly before each session.

---

## Usage

### 1. Robotiq 2F-85 Gripper (`test_gripper.py`)

This runs on the host PC directly, not on the ESP32. Activate the venv first:

```bash
source .venv/bin/activate
python run/test_gripper.py   # Make sure the hand-tracking webcam is connected
```

A successful run prints:

```
🤖 Initializing Robotiq 2F-85 Gripper...
⚠️ Activating... keep hands clear!
✅ Activated! Moving to positions...
Moved to half-open position.
```

---

### 2a. 9DTact Sensor Setup and Testing

All 9DTact commands run from inside the repo root with the `9dtact` conda env active:

```bash
deactivate          # exit .venv if active
conda deactivate     # exit base (repeat if prompt still shows extra envs)
conda activate 9dtact
which python         # should show .../envs/9dtact/bin/python
```

#### Step 1 — Camera calibration

3D-print the calibration board first: `9DTact_Design/fabrication/calibration_board.STL`

```bash
python run/calibrate_9dtact.py calibrate-camera --side left
python run/calibrate_9dtact.py calibrate-camera --side right
```

With nothing touching the sensor, press **`y`** to save the reference frame. Then press the calibration board flat onto the sensor and press **`y`** again to capture the sample frame. The script detects the grid points and computes the pixel remap and pixel-per-mm scale. If the detected point count doesn't match the expected grid size, it warns — adjust lighting or contact and rerun.

#### Step 2 — Sensor (depth) calibration

You need a ball with radius **~4.0 mm** (exact value depends on your gel surface thickness).

```bash
python run/calibrate_9dtact.py calibrate-sensor --side left
python run/calibrate_9dtact.py calibrate-sensor --side right
```

With nothing touching the sensor, press **`y`** to save the reference frame. Then press the ball onto the sensor — the sample frame is captured automatically, and the ball indentation is used to build the pixel-brightness-to-depth lookup table.

#### Step 3 — Shape reconstruction and data output

```bash
python run/calibrate_9dtact.py reconstruct --side left
python run/calibrate_9dtact.py reconstruct --side right
```

* Live tactile image, depth map, and an Open3D point cloud window will appear.
* Press **`q`** in the image window (or close the Open3D window) to stop.
* If this works, your sensor is functional. Reconstruction quality reflects how well focus and calibration were done.

**To view both sensors at once, run each in its own terminal** (do not use `--side both` — see below):

1. Open a new terminal tab/window (e.g. `Ctrl+Shift+T` for a new tab, `Ctrl+Shift+N` for a new window in most Linux terminal emulators).
2. In the new terminal, activate the env and navigate to the repo:
   ```bash
   conda activate 9dtact
   which python   # confirm: .../envs/9dtact/bin/python
   cd ~/Documents/haptic-feedback
   python run/calibrate_9dtact.py reconstruct --side right
   ```
3. In the original terminal, run the other side:
   ```bash
   python run/calibrate_9dtact.py reconstruct --side left
   ```

> **`--side both` is not supported on this setup.** It runs each sensor in its own Python thread, but `cv2.VideoCapture`/`cv2.imshow` and Open3D are not thread-safe with this OpenCV/Qt build — it fails with `'NoneType' object is not subscriptable` and `QObject::killTimer: Timers cannot be stopped from another thread`. Always use two separate terminal processes instead, as above.

The grip force modeling scripts below (`run/collect_current_data.py`, `run/run_current_model.py`) call the same `Sensor` class directly for their depth-map data, independent of `calibrate_9dtact.py reconstruct`.

---

### 2b. Grip Force Modeling (depth map → motor current)

> **Run from `run/` with the `9dtact` conda env active.** These scripts require both the 9DTact sensors (calibrated, step 2 above) and the Robotiq 2F-85 connected via `/dev/ttyUSB0` (Modbus RTU, 115200 baud).

The Robotiq gripper does not provide a true 6-axis force/torque reading. The only force-related signal available over Modbus is the instantaneous motor current (`gCU` register), where the reported value × 10 ≈ current in mA. This is used as a 1D proxy for grip effort, regressed against the tactile sensor's depth map.

**Step 1 — Collect synchronized data**

For one sensor at a time, slowly close the gripper onto a test object while recording the depth map and motor current together:

```bash
python run/collect_current_data.py --side left  --out data/left  --rate 20 --duration 30
python run/collect_current_data.py --side right --out data/right --rate 20 --duration 30
```

* `--gripper-port` defaults to `auto` (auto-detects `/dev/ttyUSB0`); pass it explicitly if auto-detection fails.
* Vary contact force, object shape, and grip speed across multiple runs (concatenate or keep as separate datasets) for a model that generalizes.
* Output: `<out>/images/*.npy` (depth maps, float32, mm) and `<out>/current.csv` (idx, t, current_mA, gripper_pos_bit, image_file).

**Step 2 — Train the regressor**

```bash
python run/train_current_model.py --data data/left  --out models/left  --epochs 100
python run/train_current_model.py --data data/right --out models/right --epochs 100
```

Outputs in `models/<side>/`, useful for physics analysis:

* `model.pt` — trained weights + normalization stats
* `train_history.csv`, `training_curve.png` — convergence
* `test_predictions.csv` — per-sample measured vs predicted current (mA)
* `test_metrics.csv` — RMSE, MAE, R², max error (mA)
* `predicted_vs_measured.png` — linearity/bias check
* `current_timeseries.png` — measured vs predicted over the test sequence

**Step 3 — Run live during grasping experiments**

```bash
python run_current_model.py --side left --model models/left/model.pt --log left_log.csv
# Also compare against the live measured current:
python run_current_model.py --side left --model models/left/model.pt --log left_log.csv --gripper-port /dev/ttyUSB0
```

Repeat steps 1–3 independently for each sensor (left/right) — each finger needs its own dataset and model.

---

### 3. Haptic Wearable (`test_haptic.py`)

> **Note:** Always use `mpremote repl` to run scripts on the ESP32-C6. `mpremote run` does not relay Ctrl-C to the board — the script will keep running even after the host process exits. Inside the REPL, **Ctrl-C** interrupts the running script and **Ctrl-X** exits the REPL.

Activate the venv first:

```bash
source .venv/bin/activate
```

Open `src/test_haptic.py` and set the options at the top of the file:

```python
METHOD = "vibmotor"   # "vibmotor" for ERM motors, "tactiles" for TacTiles pins
MODE   = "test"       # "test" for a timed self-contained run, "stream" for live packets
```

Select which fingers to activate and set intensity per finger — the file has step-by-step comments guiding you through this.

Copy files to the board, then open the REPL:

```bash
mpremote connect /dev/ttyACM0 fs cp src/utilities.py :
mpremote connect /dev/ttyACM0 fs cp src/test_haptic.py :
mpremote connect /dev/ttyACM0 repl
```

Inside the REPL:

```python
exec(open('test_haptic.py').read())
```

In test mode the ESP32 prints a summary of what is running, for example:

```
🔧 Vibmotor test
  THUMB  (ch0) → intensity 0.5
  INDEX  (ch1) → intensity 0.5
  MIDDLE (ch2) → intensity 0.5
  RING   (ch3) → intensity 0.5
  PINKY  (ch4) → intensity 0.5
  Duration: 5.0s
```

---

## How It Works

### Robotiq 2F-85 (`test_gripper.py`)

The gripper is controlled from the host PC via Modbus RTU at 115200 baud over a USB-to-RS485 adapter (`/dev/ttyUSB0`). The `pyrobotiqgripper` library handles activation, calibration, and position commands.

| Parameter | Value |
| --- | --- |
| Port | `/dev/ttyUSB0` |
| Baud rate | 115200 |
| Protocol | Modbus RTU |
| Slave ID | 0x09 |

### ERM Vibration Motors

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