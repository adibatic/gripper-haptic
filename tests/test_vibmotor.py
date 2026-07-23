# pyright: reportAttributeAccessIssue=false
"""
test_vibmotor.py — LRA vibmotor bench self-test. Runs ON THE ESP32-C6 (MicroPython).

Purpose: confirm the LRA vibration motors physically buzz, mirroring
test_tactiles.py's ON/OFF cycle for the AC/LRA path (ACDriver, see
haptic.py). No host PC and no live stream needed — this drives all selected
fingers together on a fixed ON_S / OFF_S cycle so you can watch/feel every
motor engage at once.

Copy the library + this test to the board, then exec it in the REPL:

    python -m mpremote connect /dev/ttyACM0 fs cp firmware/haptic.py :
    python -m mpremote connect /dev/ttyACM0 fs cp tests/test_vibmotor.py :
    python -m mpremote connect /dev/ttyACM0 repl
    >>> exec(open('test_vibmotor.py').read())

Use `mpremote repl` (not `mpremote run`) so Ctrl-C reaches the board and the
finally block stops the driver. Ctrl-C stops the test; Ctrl-X exits the REPL.

ON phase: every finger in FINGERS buzzes together via ACDriver.tick()
(bipolar AC carrier, envelope-scaled by INTENSITY) for ON_S seconds. OFF
phase: the driver is stopped (coasted) for OFF_S seconds. Loops ON/OFF
forever until interrupted.

Note: ACDriver shares pins with TacTiles (init_bridges() vs init_tactiles())
— never run this alongside a TacTiles test on the same board.
"""
import time

from haptic import init_bridges, ACDriver

# ------------------------------------------------------------------ CONFIG ---
THUMB, INDEX, MIDDLE, RING, PINKY = 0, 1, 2, 3, 4

FINGERS   = [THUMB, INDEX]   # any subset, e.g. [THUMB, INDEX, MIDDLE, RING, PINKY]
INTENSITY = 1.0              # 0.0-1.0, applied to every finger
ON_S      = 3.0              # seconds the motors buzz
OFF_S     = 3.0              # seconds the motors rest
# -----------------------------------------------------------------------------

assert len(FINGERS) > 0 and len(FINGERS) == len(set(FINGERS))
assert all(0 <= f <= 4 for f in FINGERS)
assert 0.0 <= INTENSITY <= 1.0

NAMES = ["THUMB", "INDEX", "MIDDLE", "RING", "PINKY"]


def run_vibmotor():
    legs = init_bridges()
    driver = ACDriver(legs, FINGERS)
    try:
        print("🔧 Vibmotor |", " ".join(NAMES[f] for f in FINGERS),
              "| intensity", INTENSITY, "|", ON_S, "s ON /", OFF_S, "s rest loop | Ctrl-C to stop")
        while True:
            print("ON")
            driver.set_intensity(INTENSITY)
            end = time.ticks_add(time.ticks_ms(), int(ON_S * 1000))
            while time.ticks_diff(end, time.ticks_ms()) > 0:
                driver.tick()

            print("OFF")
            driver.stop()
            time.sleep(OFF_S)
    finally:
        driver.stop()
        print("✅ Done, motors off.")


try:
    run_vibmotor()
except KeyboardInterrupt:
    print("\n⏹ Stopped")
