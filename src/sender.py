# host_send.py
import serial
import struct
import time

# ⚠️ Linux/macOS  /dev/ttyACM0, Windows  COM3、COM5 ...
ser = serial.Serial('/dev/ttyACM0', 115200)

# ESP32 PWM, between [0.0, 0.5]
pwm_vals = [0.0, 0.0, 0.5, 0.0, 0.0]  # ONLY motor 3

# packet to  20-byte's binary float format
packet = struct.pack('<5f', *pwm_vals)

# send
ser.write(packet)

print("✅ Sent:", pwm_vals)