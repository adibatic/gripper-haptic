# pyright: reportAttributeAccessIssue=false
"""
test_tactiles.py — TacTiles bench self-test. Runs ON THE ESP32-C6 (MicroPython).

Purpose: confirm the TacTiles pin actuators physically fire. No host PC and
no live stream needed — this drives all selected fingers together on a fixed
ON_S / OFF_S cycle so you can watch/feel every finger engage at once.

Copy the library + this test to the board, then exec it in the REPL:

    python -m mpremote connect /dev/ttyACM0 fs cp firmware/haptic.py :
    python -m mpremote connect /dev/ttyACM0 fs cp firmware/test_tactiles.py :
    python -m mpremote connect /dev/ttyACM0 repl
    >>> exec(open('test_tactiles.py').read())

Use `mpremote repl` (not `mpremote run`) so Ctrl-C reaches the board and the
finally block turns every actuator off. Ctrl-C stops the test; Ctrl-X exits
the REPL.

ON phase: every finger in FINGERS bursts together, back-to-back, once per
round, for ON_S seconds. OFF phase: all actuators off for OFF_S seconds.
Loops ON/OFF forever until interrupted.

Note: firing all fingers together draws more from the driver chip than one
finger at a time (see the sequential test's thermal comment) — this is meant
for short bench checks, not long unattended loops.
"""
import time

from haptic import (
    init_tactiles,
    stop_all_tactiles,
    TACTILE_VIBRATE_GAP_MIN_MS,
    TACTILE_VIBRATE_GAP_MAX_MS,
)

# ------------------------------------------------------------------ CONFIG ---
THUMB, INDEX, MIDDLE, RING, PINKY = 0, 1, 2, 3, 4

FINGERS   = [THUMB, INDEX]   # any subset, e.g. [THUMB, INDEX, MIDDLE, RING, PINKY]
INTENSITY = 1.0              # 0.0–1.0, applied to every finger
ON_S      = 20.0              # seconds all fingers vibrate together
OFF_S     = 1.0              # seconds all fingers stay off
# -----------------------------------------------------------------------------

assert len(FINGERS) > 0 and len(FINGERS) == len(set(FINGERS))
assert all(0 <= f <= 4 for f in FINGERS)
assert 0.0 <= INTENSITY <= 1.0

NAMES = ["THUMB", "INDEX", "MIDDLE", "RING", "PINKY"]

# Same intensity -> gap mapping as tactiles_vibrate_intensity, applied once
# per round instead of per finger, since fingers fire together each round.
_INTENSITY = max(0.0, min(1.0, INTENSITY))
GAP_MS = int(TACTILE_VIBRATE_GAP_MAX_MS
             - _INTENSITY * (TACTILE_VIBRATE_GAP_MAX_MS - TACTILE_VIBRATE_GAP_MIN_MS))


def run_tactile():
    tactiles = init_tactiles()
    try:
        print("🔧 TacTiles |", " ".join(NAMES[f] for f in FINGERS),
              "| ALL TOGETHER | intensity", INTENSITY,
              "|", ON_S, "s ON /", OFF_S, "s OFF loop | Ctrl-C to stop")
        while True:
            print("ON")
            end = time.ticks_add(time.ticks_ms(), int(ON_S * 1000))
            while time.ticks_diff(end, time.ticks_ms()) > 0:
                for f in FINGERS:
                    tactiles[f].burst()
                time.sleep_ms(GAP_MS)

            print("OFF")
            stop_all_tactiles(tactiles)
            time.sleep(OFF_S)
    finally:
        stop_all_tactiles(tactiles)
        print("✅ Done, actuators off.")


try:
    run_tactile()
except KeyboardInterrupt:
    print("\n⏹ Stopped")