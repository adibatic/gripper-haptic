# pyright: reportAttributeAccessIssue=false
"""
stream.py — runs ON THE ESP32-C6 (MicroPython).

Live haptic receiver for experiment.py. Parses "{left},{right}\n" lines and
drives the two channels independently: left -> thumb (M1), right -> index (M2).
If no packet arrives within WATCHDOG_MS both channels drop to 0, but the driver
chip stays awake so the next packet vibrates immediately.

Set METHOD to match the host's --condition: "vibmotor" for lra, "tactiles" for
tactiles. visual_only needs no receiver at all.

    python -m mpremote connect /dev/ttyACM0 fs cp firmware/haptic.py :
    python -m mpremote connect /dev/ttyACM0 fs cp firmware/stream.py :
    python -m mpremote connect /dev/ttyACM0 repl
    >>> exec(open('stream.py').read())

Use `repl`, not `run` — Ctrl-C must reach the board to stop the motors via the
finally block. Ctrl-X detaches and frees the port for experiment.py.
"""
import sys
import select
import time

# Mock MicroPython time methods so this file still lints/runs in a desktop IDE.
if not hasattr(time, 'ticks_ms'):
    time.ticks_ms = lambda: int(time.time() * 1000)  # type: ignore
    time.ticks_add = lambda t, d: t + d  # type: ignore
    time.ticks_diff = lambda t1, t2: t1 - t2  # type: ignore

from haptic import *

# ------------------------------------------------------------------ CONFIG ---
THUMB, INDEX = 0, 1   # M1 = thumb (driven by left sensor), M2 = index (right sensor)

METHOD = "vibmotor"   # "vibmotor" for --condition lra, "tactiles" for --condition tactiles

WATCHDOG_MS = 200     # drop both channels to 0 if no packet arrives within this window

# tactiles only: fire a pulse when a channel's value exceeds this, at most once
# per rate-limit window (protects the actuator's ~120 switches/min thermal budget).
TACTILE_PULSE_THRESHOLD = 0.5
TACTILE_RATE_LIMIT_MS   = 500
# -----------------------------------------------------------------------------

assert METHOD in ("vibmotor", "tactiles")


def parse_packet(line):
    """Returns (left, right) clamped to [0, 1], or None if the line is
    malformed — ignored rather than raised, so a stray byte can't kill the loop."""
    if not line:
        return None
    parts = line.strip().split(",")
    if len(parts) != 2:
        return None
    try:
        left = float(parts[0])
        right = float(parts[1])
    except ValueError:
        return None
    left = 0.0 if left < 0.0 else (1.0 if left > 1.0 else left)
    right = 0.0 if right < 0.0 else (1.0 if right > 1.0 else right)
    return left, right


def run_vibmotor_stream():
    """LRA path. One ACDriver per channel, since ACDriver applies a single
    envelope to all its fingers — two 1-finger drivers is how thumb and index
    get independent intensities. Polling is non-blocking so the carriers never
    starve."""
    poll = select.poll()
    poll.register(sys.stdin, select.POLLIN)

    legs = init_bridges()
    drv_thumb = ACDriver(legs, [THUMB])
    drv_index = ACDriver(legs, [INDEX])
    last_rx = time.ticks_ms()  # type: ignore

    try:
        print("🔧 STREAM vibmotor (AC) | THUMB<-left  INDEX<-right | "
              "waiting for packets from experiment.py... Ctrl-C to stop")
        while True:
            # 1) Non-blocking packet check (timeout 0 -> never stalls the carriers)
            if poll.poll(0):
                parsed = parse_packet(sys.stdin.readline())
                if parsed is not None:
                    left, right = parsed
                    drv_thumb.set_intensity(left)
                    drv_index.set_intensity(right)
                    last_rx = time.ticks_ms()  # type: ignore

            # 2) Watchdog: silence both if the host went quiet (chip stays awake)
            if time.ticks_diff(time.ticks_ms(), last_rx) > WATCHDOG_MS:  # type: ignore
                drv_thumb.set_intensity(0.0)
                drv_index.set_intensity(0.0)

            # 3) Advance both carriers/envelopes and write the pins
            drv_thumb.tick()
            drv_index.tick()
    except KeyboardInterrupt:
        pass
    finally:
        drv_thumb.stop()
        drv_index.stop()
        disable_drivers()
        print("\n✅ Done, motors off.")


def run_tactiles_stream():
    """TacTiles path. Pulses a channel when its intensity exceeds
    TACTILE_PULSE_THRESHOLD, rate-limited per channel to protect the
    actuator's thermal budget."""
    poll = select.poll()
    poll.register(sys.stdin, select.POLLIN)

    tactiles = init_tactiles()
    last_action = {THUMB: time.ticks_ms(), INDEX: time.ticks_ms()}  # type: ignore
    last_rx = time.ticks_ms()  # type: ignore

    try:
        print("🔧 STREAM TacTiles | THUMB<-left  INDEX<-right | "
              "waiting for packets from experiment.py... Ctrl-C to stop")
        while True:
            if poll.poll(0):
                parsed = parse_packet(sys.stdin.readline())
                if parsed is not None:
                    left, right = parsed
                    now = time.ticks_ms()  # type: ignore
                    for ch, val in ((THUMB, left), (INDEX, right)):
                        if (val > TACTILE_PULSE_THRESHOLD and
                                time.ticks_diff(now, last_action[ch]) > TACTILE_RATE_LIMIT_MS):  # type: ignore
                            tactiles[ch].pulse()
                            last_action[ch] = now
                    last_rx = now

            if time.ticks_diff(time.ticks_ms(), last_rx) > WATCHDOG_MS:  # type: ignore
                stop_all_tactiles(tactiles)

            time.sleep_ms(2)  # type: ignore  # tactiles are event-driven; no carrier to starve
    except KeyboardInterrupt:
        pass
    finally:
        stop_all_tactiles(tactiles)
        disable_drivers()
        print("\n✅ Done, actuators off.")


try:
    if METHOD == "vibmotor":
        run_vibmotor_stream()
    else:
        run_tactiles_stream()
except KeyboardInterrupt:
    print("\n⏹ Stopped")
