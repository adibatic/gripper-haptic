# pyright: reportAttributeAccessIssue=false
"""
stream.py — runs ON THE ESP32-C6 (MicroPython).

Live haptic receiver for experiment.py. Parses "{left},{right}\n" lines and
drives the two channels independently: left -> thumb, right -> index.
If no packet arrives within WATCHDOG_MS both channels drop to 0, but the driver
chip stays awake so the next packet vibrates immediately.

Set METHOD to match the host's --condition: "vibmotor" for lra, "tactiles" for
tactiles (continuous burst/gap vibration, TactileVibrationDriver — the
mechanism the study's first 19 participants' tactiles-condition data was
collected under), "tactiles2" for tactiles2 (binary engage/disengage contact
latch from tests/test_tactiles2.py, TactileLatchDriver). visual_only needs no
receiver at all. Set HAND to match the host's --hand ("right" or "left") — it
picks which physical pin pair THUMB/INDEX point at, since a left-hand mount is
wired to different pins than a right-hand one (see CONFIG below).

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

if not hasattr(time, 'ticks_ms'):
    time.ticks_ms = lambda: int(time.time() * 1000)  # type: ignore
    time.ticks_add = lambda t, d: t + d  # type: ignore
    time.ticks_diff = lambda t1, t2: t1 - t2  # type: ignore

from haptic import *

# ------------------------------------------------------------------ CONFIG ---
HAND = "right"        # "right" or "left" — must match experiment.py's --hand.
                       # Sets which physical pin pair THUMB/INDEX point at, since
                       # a left-hand mount is wired to different TACTILE_PINS legs.
THUMB, INDEX = (0, 1) if HAND == "right" else (4, 3)
# right: M1 = thumb (driven by left sensor), M2 = index (right sensor)
# left:  M5 = thumb (driven by left sensor), M4 = index (right sensor)

METHOD = "vibmotor"   # "vibmotor" for --condition lra, "tactiles" for --condition
                      # tactiles (vibration), "tactiles2" for --condition
                      # tactiles2 (binary contact latch)

WATCHDOG_MS = 200     # drop both channels to 0 if no packet arrives within this window
# -----------------------------------------------------------------------------

assert METHOD in ("vibmotor", "tactiles", "tactiles2")
assert HAND in ("right", "left")


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
    """TacTiles path (--condition tactiles). Mirrors run_vibmotor_stream():
    one non-blocking TactileVibrationDriver per channel, ticked every loop
    pass so thumb and index buzz continuously with intensity mapped to pulse
    rate — not a single threshold-gated tap every 500ms. This is the
    mechanism the study's tactiles-condition data was collected under."""
    poll = select.poll()
    poll.register(sys.stdin, select.POLLIN)

    tactiles = init_tactiles()
    drv_thumb = TactileVibrationDriver(tactiles[THUMB])
    drv_index = TactileVibrationDriver(tactiles[INDEX])
    last_rx = time.ticks_ms()  # type: ignore

    try:
        print("🔧 STREAM TacTiles | THUMB<-left  INDEX<-right | "
              "waiting for packets from experiment.py... Ctrl-C to stop")
        while True:
            # 1) Non-blocking packet check (timeout 0 -> never stalls the drivers)
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

            # 3) Advance both burst/gap state machines and write the pins
            drv_thumb.tick()
            drv_index.tick()
    except KeyboardInterrupt:
        pass
    finally:
        drv_thumb.stop()
        drv_index.stop()
        disable_drivers()
        print("\n✅ Done, actuators off.")


def run_tactiles2_stream():
    """TacTiles path (--condition tactiles2). One non-blocking
    TactileLatchDriver per channel, ticked every loop pass. Uses the
    tests/test_tactiles2.py mechanism — engage() + restrike then hold latched
    while a channel's intensity is at/above TACTILE_LATCH_THRESHOLD (grasp
    contact), a single disengage() when it drops back below — instead of
    TactileVibrationDriver's continuous burst/gap buzz used by --condition
    tactiles."""
    poll = select.poll()
    poll.register(sys.stdin, select.POLLIN)

    tactiles = init_tactiles()
    drv_thumb = TactileLatchDriver(tactiles[THUMB])
    drv_index = TactileLatchDriver(tactiles[INDEX])
    last_rx = time.ticks_ms()  # type: ignore

    try:
        print("🔧 STREAM TacTiles2 (binary latch) | THUMB<-left  INDEX<-right | "
              "waiting for packets from experiment.py... Ctrl-C to stop")
        while True:
            # 1) Non-blocking packet check (timeout 0 -> never stalls the drivers)
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

            # 3) Advance both latch state machines and write the pins
            drv_thumb.tick()
            drv_index.tick()
    except KeyboardInterrupt:
        pass
    finally:
        drv_thumb.stop()
        drv_index.stop()
        disable_drivers()
        print("\n✅ Done, actuators off.")


try:
    if METHOD == "vibmotor":
        run_vibmotor_stream()
    elif METHOD == "tactiles":
        run_tactiles_stream()
    else:
        run_tactiles2_stream()
except KeyboardInterrupt:
    print("\n⏹ Stopped")
