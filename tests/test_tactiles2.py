# pyright: reportAttributeAccessIssue=false
"""
test_tactiles2.py — TacTiles binary ON/OFF bench self-test. Runs ON THE ESP32-C6 (MicroPython).

Purpose: confirm the TacTiles pin actuators physically latch ON and OFF on a
fixed cycle. Unlike test_tactiles.py (continuous burst/gap vibration during
the ON phase), this fires a single engage() at the start of ON and holds the
latch for the full ON_S window — a binary contact/no-contact toggle, not a
buzz. Because the actuator is bistable it draws zero power while held either
way (see TacTiles.engage/disengage in haptic.py).

Copy the library + this test to the board, then exec it in the REPL:

    python -m mpremote connect /dev/ttyACM0 fs cp firmware/haptic.py :
    python -m mpremote connect /dev/ttyACM0 fs cp tests/test_tactiles2.py :
    python -m mpremote connect /dev/ttyACM0 repl
    >>> exec(open('test_tactiles2.py').read())

Use `mpremote repl` (not `mpremote run`) so Ctrl-C reaches the board and the
finally block turns every actuator off. Ctrl-C stops the test; Ctrl-X exits
the REPL.

ON phase: every finger in FINGERS engages together (pins extend and latch),
then gets a second engage() pulse RESTRIKE_MS later — the first pulse doesn't
always fully seat the pin against skin contact resistance, so the restrike
drives it the rest of the way for more felt pressure — then holds for ON_S
seconds. OFF phase: every finger disengages together (pins retract and
latch), held for OFF_S seconds. Loops ON/OFF forever until interrupted.
"""
import time

from haptic import init_tactiles, stop_all_tactiles

# ------------------------------------------------------------------ CONFIG ---
THUMB, INDEX, MIDDLE, RING, PINKY = 0, 1, 2, 3, 4

FINGERS      = [THUMB, INDEX]   # any subset, e.g. [THUMB, INDEX, MIDDLE, RING, PINKY]
ON_S         = 3.0              # seconds all fingers stay engaged (ON)
OFF_S        = 3.0              # seconds all fingers stay disengaged (OFF)
RESTRIKE_MS  = 25                # gap before a second engage() pulse, for more felt pressure
# -----------------------------------------------------------------------------

assert len(FINGERS) > 0 and len(FINGERS) == len(set(FINGERS))
assert all(0 <= f <= 4 for f in FINGERS)

NAMES = ["THUMB", "INDEX", "MIDDLE", "RING", "PINKY"]


def run_tactile():
    tactiles = init_tactiles()
    try:
        print("🔧 TacTiles |", " ".join(NAMES[f] for f in FINGERS),
              "| BINARY ON/OFF |", ON_S, "s ON /", OFF_S, "s OFF loop | Ctrl-C to stop")
        while True:
            print("ON")
            for f in FINGERS:
                tactiles[f].engage()
            time.sleep_ms(RESTRIKE_MS)
            for f in FINGERS:
                tactiles[f].engage()   # restrike: first pulse may not fully seat the pin against skin
            time.sleep(ON_S)

            print("OFF")
            for f in FINGERS:
                tactiles[f].disengage()
            time.sleep(OFF_S)
    finally:
        stop_all_tactiles(tactiles)
        print("✅ Done, actuators off.")


try:
    run_tactile()
except KeyboardInterrupt:
    print("\n⏹ Stopped")
