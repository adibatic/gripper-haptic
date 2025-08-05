ESP32-C6 MicroPython Setup & Run Guide

Steps:

1. Go to: https://micropython.org/download/ESP32_GENERIC_C6/

2. Download the latest firmware release, e.g.:
   v1.25.0 (2025-04-15).bin

3. Install required tools:
   pip install esptool

4. Connect your ESP32-C6 and find the serial port:
   ls /dev/ttyACM0

   - If it doesn’t show up, try:
     dmesg | grep tty
   - Or reconnect the cable / use another USB port
   - You might need to run with sudo or add your user to the 'dialout' group

5. Flash the firmware (run from the folder where the .bin file is):
   esptool --chip esp32c6 --port /dev/ttyACM0 erase-flash
   esptool --chip esp32c6 --port /dev/ttyACM0 --baud 460800 write-flash -z 0x0 ESP32_GENERIC_C6-20250415-v1.25.0.bin

6. Run MicroPython code with REPL:
   pip install mpremote
   mpremote connect /dev/ttyACM0 fs cp main.py :
   mpremote connect /dev/ttyACM0 run main.py
