# pyright: reportAttributeAccessIssue=false
"""
EM binary engage/disengage latch bench self-test. Runs ON THE ESP32-C6
(MicroPython). Unlike test_em.py (continuous burst/gap vibration during the ON
phase), this fires a single engage() at the start of ON and holds the latch for
the full ON_S window — a binary contact/no-contact toggle, not a buzz.

    python -m mpremote connect /dev/ttyACM0 fs cp firmware/haptic.py :
    python -m mpremote connect /dev/ttyACM0 fs cp tests/test_em2.py :
    python -m mpremote connect /dev/ttyACM0 repl
    >>> exec(open('test_em2.py').read())

Use `repl`, not `run` — Ctrl-C must reach the board so the finally block turns
every actuator off. Ctrl-X exits the REPL.
"""
import time

from haptic import init_em, stop_all_em

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


def run_em2():
    ems = init_em()
    try:
        print("🔧 EM |", " ".join(NAMES[f] for f in FINGERS),
              "| BINARY ON/OFF |", ON_S, "s ON /", OFF_S, "s OFF loop | Ctrl-C to stop")
        while True:
            print("ON")
            for f in FINGERS:
                ems[f].engage()
            time.sleep_ms(RESTRIKE_MS)
            for f in FINGERS:
                ems[f].engage()   # restrike: first pulse may not fully seat the pin against skin
            time.sleep(ON_S)

            print("OFF")
            for f in FINGERS:
                ems[f].disengage()
            time.sleep(OFF_S)
    finally:
        stop_all_em(ems)
        print("✅ Done, actuators off.")


try:
    run_em2()
except KeyboardInterrupt:
    print("\n⏹ Stopped")
