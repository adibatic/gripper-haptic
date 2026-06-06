# Haptic Feedback Methods: A Participant Survey and Qualitative Comparison

[![Python 3.7+](https://img.shields.io/badge/python-3.7+-blue.svg)](https://www.python.org/downloads/)
[![MicroPython](https://img.shields.io/badge/MicroPython-v1.25.0-green.svg)](https://micropython.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Overview

This repository contains the hardware driver code and supporting materials for a bachelor's thesis investigating the efficacy of haptic feedback modalities in teleoperation. Specifically, the project integrates a Robotiq 2F-85 Adaptive Gripper fitted with stress-deformation based tactile sensors. The tactile data is translated and sent to a custom multi-channel haptic actuator platform (ESP32-C6) to deliver real-time stimuli. The study collects quantitative latency metrics and qualitative survey data to compare the user experience during delicate object manipulation.

The software stack supports two haptic feedback methods — ERM vibration motors (PWM) and TacTile pin actuators (H-bridge) — selectable from a single script, alongside direct Modbus RTU communication with the Robotiq gripper via a host PC.

## Repository Structure

```text
haptic-survey/
├── src/
│   ├── utilities.py     # Shared MicroPython driver library (ERM + TacTile)
│   ├── test_haptic.py   # Haptic test/stream script — set METHOD inside to switch type (ESP32-C6)
│   ├── test_gripper.py  # Robotiq gripper control script (host PC)
│   └── host_send.py     # PC-side script to send packets over serial
├── survey/              # Survey instruments and response data
├── figures/             # Experimental setup photos and result figures
├── paper/               # Thesis manuscript (LaTeX source)
├── requirements.txt     # Python dependencies (pyserial)
└── README.md
```

## Hardware Requirements

- ESP32-C6 development board (e.g., ESP32-C6-DevKitC-1)
- USB-C or USB-A **data** cable (not power-only)
- Up to 5 ERM vibration motors (connected to M1–M5), or
- Up to 5 TacTile pin actuators with H-bridge driver board (connected to T1–T5)

## Software Requirements

- Python ≥ 3.7 on host PC (Linux / macOS / Windows)
- MicroPython firmware: `ESP32_GENERIC_C6-20250415-v1.25.0.bin`
- Python dependencies in `requirements.txt` (see [Installation](#installation))

---

## Installation

### 1. Create a virtual environment

```bash
python -m venv .venv
```

Activate it:

```bash
# Linux / macOS
source .venv/bin/activate

# Windows (Command Prompt)
.venv\Scripts\activate.bat

# Windows (PowerShell)
.venv\Scripts\Activate.ps1
```

### 2. Install host-side Python tools

```bash
python -m pip install -r requirements.txt
```

### 3. Flash MicroPython onto the ESP32-C6 (one-time)

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

### 4. (Optional) Remove default boot script

```bash
mpremote connect /dev/ttyACM0 fs rm boot.py
```

---

## Usage

> **Note:** Always use `mpremote repl` to run scripts on the ESP32-C6. `mpremote run` does not relay Ctrl-C to the board — the script will keep running even after the host process exits. Inside the REPL, **Ctrl-C** interrupts the running script and **Ctrl-X** exits the REPL.

### Run the haptic script (`test_haptic.py`)

Open `src/test_haptic.py` and set the options at the top of the file:

```python
METHOD = "vibmotor"   # "vibmotor" for ERM motors, "tactile" for TacTile pins
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

### Run the gripper control script (`test_gripper.py`)

This runs on the host PC directly, not on the ESP32:

```bash
python src/test_gripper.py
```

A successful run prints:

```
🤖 Initializing Robotiq 2F-85 Gripper...
⚠️ Activating... keep hands clear!
✅ Activated! Moving to positions...
Moved to half-open position.
```

---

## How It Works

### ERM Vibration Motors

Selected via `METHOD = "vibmotor"` in `test_haptic.py`. The firmware applies a continuous PWM signal per channel. Values are clamped to `[0.0, 1.0]` and mapped to a 10-bit duty cycle (0–1023) at 200 Hz. In streaming mode, if no packet is received within 200 ms all motors stop automatically.

| Channel | Finger | PWM Pin | EN Pin |
|---------|--------|---------|--------|
| M1      | Thumb  | GPIO 20 | GPIO 21 |
| M2      | Index  | GPIO 14 | GPIO 15 |
| M3      | Middle | GPIO 6  | GPIO 7  |
| M4      | Ring   | GPIO 0  | GPIO 1  |
| M5      | Pinky  | GPIO 4  | GPIO 5  |

NSLEEP is held HIGH (no sleep) via GPIO 19.

### TacTile Pin Actuators

Selected via `METHOD = "tactile"` in `test_haptic.py`. TacTiles are bistable pin actuators driven by H-bridges. Each actuator is controlled by an IN1/IN2 pair — a short forward pulse engages the pin toward the skin; a reverse pulse retracts it. Because the actuator latches mechanically, zero power is drawn while held.

| Mode | Behaviour |
|------|-----------|
| `engage` | 6 ms forward pulse → pin contacts skin, latches |
| `disengage` | 10 ms reverse pulse → pin retracts, latches |
| `pulse` | 3 ms forward + 3 ms reverse → quick tap, no sustained contact |
| `burst` | Rapid sequence of pulses, up to ~200 Hz in short windows |

Sustained vibration is approximated by repeated bursts with a gap between them. The gap is set automatically based on intensity, keeping the long-term switch rate under the hardware thermal limit of ~120 switches/minute. In streaming mode, a pulse fires when the incoming value exceeds 0.5, with a 500 ms per-channel rate limit.

| Channel | Finger | IN1 Pin | IN2 Pin |
|---------|--------|---------|---------|
| T1      | Thumb  | GPIO 20 | GPIO 21 |
| T2      | Index  | GPIO 14 | GPIO 15 |
| T3      | Middle | GPIO 6  | GPIO 7  |
| T4      | Ring   | GPIO 0  | GPIO 1  |
| T5      | Pinky  | GPIO 4  | GPIO 5  |

### Robotiq 2F-85 (`test_gripper.py`)

The gripper is controlled from the host PC via Modbus RTU at 115200 baud over a USB-to-RS485 adapter (`/dev/ttyUSB0`). The `pyrobotiqgripper` library handles activation, calibration, and position commands.

| Parameter | Value |
|-----------|-------|
| Port      | `/dev/ttyUSB0` |
| Baud rate | 115200 |
| Protocol  | Modbus RTU |
| Slave ID  | 0x09 |

---

## Writing & Manuscript

The thesis manuscript is in the `paper/` directory.

- Requires a LaTeX distribution (TeX Live or MiKTeX).
- Compile with `latexmk -pdf paper/main.tex` or using the LaTeX Workshop VS Code extension.
- Figures are pulled from the `figures/` directory.

---

## Author

**Adriel I. Santoso**  
Department of Mechanical and Aerospace Engineering, Tohoku University