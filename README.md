# Haptic Feedback Methods: A Participant Survey and Qualitative Comparison

[![Python 3.7+](https://img.shields.io/badge/python-3.7+-blue.svg)](https://www.python.org/downloads/)
[![MicroPython](https://img.shields.io/badge/MicroPython-v1.25.0-green.svg)](https://micropython.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Overview

This repository contains the hardware driver code and supporting materials for a bachelor's thesis investigating the efficacy of haptic feedback modalities in teleoperation. Specifically, the project integrates a Robotiq 2F-85 Adaptive Gripper fitted with stress-deformation based tactile sensors. The tactile data is translated and sent to a custom multi-channel vibrotactile actuator platform (ESP32-C6) to deliver real-time stimuli. The study collects quantitative latency metrics and qualitative survey data to compare the user experience during delicate object manipulation.

The software stack controls up to 5 ERM vibration motors via PWM, alongside direct Modbus RTU communication with the Robotiq gripper via a host PC.

## Repository Structure

```text
haptic-survey/
├── src/
│   ├── main.py          # MicroPython firmware for ESP32-C6 (PWM motor control)
│   └── host_send.py     # PC-side script to send PWM commands over serial
├── survey/              # Survey instruments and response data
├── figures/             # Experimental setup photos and result figures
├── paper/               # Thesis manuscript (LaTeX source)
├── requirements.txt     # Python dependencies (pyserial)
└── README.md
```

## Hardware Requirements

- ESP32-C6 development board (e.g., ESP32-C6-DevKitC-1)
- USB-C or USB-A **data** cable (not power-only)
- Up to 5 ERM vibration motors (connected to M1–M5)
- Multi-Tactile Driver board

## Software Requirements

- Python ≥ 3.7 on host PC (Linux / macOS / Windows)
- MicroPython firmware: `ESP32_GENERIC_C6-20250415-v1.25.0.bin`
- Python dependencies in `requirements.txt` (see [Installation](#installation))

---

## Installation

### 1. Install host-side Python tools

```bash
pip install -r requirements.txt
```

### 2. Flash MicroPython onto the ESP32-C6 (one-time)

Download the firmware:

```bash
wget https://micropython.org/resources/firmware/ESP32_GENERIC_C6-20250415-v1.25.0.bin
```

Find your serial port:

```bash
ls /dev/ttyACM*        # Linux
# or: dmesg | grep tty
# Windows: check Device Manager for COMx
```

Erase and flash (⚠️ this erases all existing data on the device):

```bash
esptool.py --chip esp32c6 --port /dev/ttyACM0 erase_flash
esptool.py --chip esp32c6 --port /dev/ttyACM0 --baud 460800 write_flash -z 0x0 ESP32_GENERIC_C6-20250415-v1.25.0.bin
```

### 3. (Optional) Remove default boot script

```bash
mpremote connect /dev/ttyACM0 fs rm boot.py
```

---

## Usage

### Upload and run the motor control script

```bash
mpremote connect /dev/ttyACM0 fs cp src/main.py :
mpremote connect /dev/ttyACM0 run main.py
```

When running, the ESP32 will print:

```
🚀 Ready to receive PWM values from host...
```

### Send PWM commands from the host PC

Edit `src/host_send.py` to set your desired motor intensities (values between `0.0` and `1.0`), then run:

```bash
python src/host_send.py
```

A successful send prints:

```
✅ Sent: [0.5, 0.5, 0.5, 0.5, 0.5]
```

---

## How It Works

### ESP32-C6 (`main.py`)

The firmware listens for 20-byte packets over USB serial. Each packet encodes 5 little-endian `float32` values, one per motor channel. Values are clamped to `[0.0, 1.0]` and mapped to a 10-bit PWM duty cycle (0–1023) at 200 Hz — a frequency suitable for ERM vibration motors.

| Channel | PWM Pin | EN Pin |
|---------|---------|--------|
| M1      | GPIO 20 | GPIO 21 |
| M2      | GPIO 14 | GPIO 15 |
| M3      | GPIO 6  | GPIO 7  |
| M4      | GPIO 0  | GPIO 1  |
| M5      | GPIO 4  | GPIO 5  |

NSLEEP is held HIGH (no sleep) via GPIO 19.

### Host PC (`host_send.py`)

Packs a list of 5 floats into a 20-byte binary struct and writes it to the serial port at 115200 baud.

```python
packet = struct.pack('<5f', *pwm_vals)
ser.write(packet)
```

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
