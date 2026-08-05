# pyright: reportAttributeAccessIssue=false
"""
LRA bench self-test. Runs ON THE ESP32-C6 (MicroPython).

    python -m mpremote connect /dev/ttyACM0 fs cp firmware/haptic.py :
    python -m mpremote connect /dev/ttyACM0 fs cp tests/test_lra.py :
    python -m mpremote connect /dev/ttyACM0 repl
    >>> exec(open('test_lra.py').read())

Use `repl`, not `run` — Ctrl-C must reach the board so the finally block stops
the driver. Ctrl-X exits the REPL.

Note: ACDriver shares pins with EM (init_bridges() vs init_em()) — never run
this alongside an EM test on the same board.
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


def run_lra():
    legs = init_bridges()
    driver = ACDriver(legs, FINGERS)
    try:
        print("🔧 LRA |", " ".join(NAMES[f] for f in FINGERS),
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
    run_lra()
except KeyboardInterrupt:
    print("\n⏹ Stopped")
