# pyright: reportAttributeAccessIssue=false
"""
EM continuous burst/gap vibration bench self-test. Runs ON THE ESP32-C6
(MicroPython).

    python -m mpremote connect /dev/ttyACM0 fs cp firmware/haptic.py :
    python -m mpremote connect /dev/ttyACM0 fs cp tests/test_em.py :
    python -m mpremote connect /dev/ttyACM0 repl
    >>> exec(open('test_em.py').read())

Use `repl`, not `run` — Ctrl-C must reach the board so the finally block turns
every actuator off. Ctrl-X exits the REPL.

Note: firing all fingers together draws more from the driver chip than one
finger at a time — meant for short bench checks, not long unattended loops.
"""
import time

from haptic import (
    init_em,
    stop_all_em,
    EM_VIBRATE_GAP_MIN_MS,
    EM_VIBRATE_GAP_MAX_MS,
)

# ------------------------------------------------------------------ CONFIG ---
THUMB, INDEX, MIDDLE, RING, PINKY = 0, 1, 2, 3, 4

FINGERS   = [THUMB, INDEX]   # any subset, e.g. [THUMB, INDEX, MIDDLE, RING, PINKY]
INTENSITY = 1.0              # 0.0–1.0, applied to every finger
ON_S      = 3.0              # seconds all fingers vibrate together
OFF_S     = 3.0              # seconds all fingers stay off
# -----------------------------------------------------------------------------

assert len(FINGERS) > 0 and len(FINGERS) == len(set(FINGERS))
assert all(0 <= f <= 4 for f in FINGERS)
assert 0.0 <= INTENSITY <= 1.0

NAMES = ["THUMB", "INDEX", "MIDDLE", "RING", "PINKY"]

# Same intensity -> gap mapping as em_vibrate_intensity, applied once per round
# instead of per finger, since fingers fire together each round.
_INTENSITY = max(0.0, min(1.0, INTENSITY))
GAP_MS = int(EM_VIBRATE_GAP_MAX_MS
             - _INTENSITY * (EM_VIBRATE_GAP_MAX_MS - EM_VIBRATE_GAP_MIN_MS))


def run_em():
    ems = init_em()
    try:
        print("🔧 EM |", " ".join(NAMES[f] for f in FINGERS),
              "| ALL TOGETHER | intensity", INTENSITY,
              "|", ON_S, "s ON /", OFF_S, "s OFF loop | Ctrl-C to stop")
        while True:
            print("ON")
            end = time.ticks_add(time.ticks_ms(), int(ON_S * 1000))
            while time.ticks_diff(end, time.ticks_ms()) > 0:
                for f in FINGERS:
                    ems[f].burst()
                time.sleep_ms(GAP_MS)

            print("OFF")
            stop_all_em(ems)
            time.sleep(OFF_S)
    finally:
        stop_all_em(ems)
        print("✅ Done, actuators off.")


try:
    run_em()
except KeyboardInterrupt:
    print("\n⏹ Stopped")
