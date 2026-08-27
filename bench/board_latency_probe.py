# pyright: reportAttributeAccessIssue=false
"""
Runs ON THE ESP32-C6 (MicroPython). Responder for the host-side latency
bench in bench/measure_latency.py.

    python -m mpremote connect /dev/ttyACM0 fs cp firmware/haptic.py :
    python -m mpremote connect /dev/ttyACM0 fs cp bench/board_latency_probe.py :
    python -m mpremote connect /dev/ttyACM0 repl
    >>> exec(open('board_latency_probe.py').read())

Use `repl`, not `run` — Ctrl-C must reach the board so the finally block
turns every actuator off. Ctrl-X detaches and frees the port for the host
script.

PROTOCOL
    Host sends one command character followed by a newline. The board
    replies with a single lowercase character and a newline.

    'P' -> 'p'   Echo only. No pins touched. This is the baseline: it
                 measures serial round trip plus parse cost, with no
                 actuation. Subtract it from the others.

    'E' -> 'e'   Energise the coil in the engage direction, reply
                 IMMEDIATELY, and only then hold for EM_ENGAGE_MS before
                 releasing. The reply therefore marks the instant current
                 first reaches the coil, which is the quantity the host
                 wants, rather than the instant the pulse finishes.

    'D' -> 'd'   Same, in the disengage direction.

    'T' -> 't'   Toggle TRIGGER_PIN. For scope work: put one probe on
                 TRIGGER_PIN and one on a coil lead, then trigger on the
                 edge. Costs nothing if no scope is attached.

    'X' -> 'x'   All actuators off. Sent by the host on exit.
"""
import sys
import select
import time

from haptic import (EM_PINS, EM_ENGAGE_MS, EM_DISENGAGE_MS, NSLEEP_PIN,
                    MOTOR_PWM_PINS, MOTOR_EN_PINS,
                    enable_drivers, disable_drivers)
from machine import Pin

if not hasattr(time, 'ticks_ms'):
    time.ticks_ms = lambda: int(time.time() * 1000)      # type: ignore
    time.ticks_us = lambda: int(time.time() * 1000000)   # type: ignore

# ------------------------------------------------------------------ CONFIG ---
CHANNEL = 0          # which EM channel to exercise (0 = T1 = thumb, right hand)

# Spare GPIO used only as a scope trigger. It must NOT appear in
# MOTOR_PWM_PINS, MOTOR_EN_PINS or NSLEEP_PIN in firmware/haptic.py.
# Set to None to disable the 'T' command entirely.
TRIGGER_PIN = 22
# -----------------------------------------------------------------------------

assert 0 <= CHANNEL < len(EM_PINS)

# Driving a trigger pin that is really a driver input would fight the coil
# drive and could mislead the measurement, so refuse rather than warn.
_CLAIMED = set(MOTOR_PWM_PINS) | set(MOTOR_EN_PINS) | {NSLEEP_PIN}
assert TRIGGER_PIN is None or TRIGGER_PIN not in _CLAIMED, (
    "TRIGGER_PIN %s is already used by the driver (see firmware/haptic.py); "
    "pick a free GPIO or set it to None" % TRIGGER_PIN)


def main():
    in1_pin, in2_pin = EM_PINS[CHANNEL]
    in1 = Pin(in1_pin, Pin.OUT)
    in2 = Pin(in2_pin, Pin.OUT)
    in1.value(0)
    in2.value(0)

    trig = None
    if TRIGGER_PIN is not None:
        trig = Pin(TRIGGER_PIN, Pin.OUT)
        trig.value(0)

    enable_drivers()

    poll = select.poll()
    poll.register(sys.stdin, select.POLLIN)

    print("READY ch=%d in1=%d in2=%d trigger=%s"
          % (CHANNEL, in1_pin, in2_pin, TRIGGER_PIN))

    try:
        while True:
            if not poll.poll(50):
                continue
            line = sys.stdin.readline()
            if not line:
                continue
            cmd = line.strip().upper()[:1]

            if cmd == 'P':
                # Baseline. Touch nothing, reply at once.
                sys.stdout.write('p\n')

            elif cmd == 'E':
                # Energise first, acknowledge second, hold third. The order
                # matters: the ack must mark coil-on, not pulse-end.
                in1.value(0)
                in2.value(1)
                sys.stdout.write('e\n')
                time.sleep_ms(EM_ENGAGE_MS)
                in1.value(0)
                in2.value(0)

            elif cmd == 'D':
                in1.value(1)
                in2.value(0)
                sys.stdout.write('d\n')
                time.sleep_ms(EM_DISENGAGE_MS)
                in1.value(0)
                in2.value(0)

            elif cmd == 'T':
                if trig is not None:
                    trig.value(1 - trig.value())
                sys.stdout.write('t\n')

            elif cmd == 'X':
                in1.value(0)
                in2.value(0)
                sys.stdout.write('x\n')

    except KeyboardInterrupt:
        pass
    finally:
        in1.value(0)
        in2.value(0)
        if trig is not None:
            trig.value(0)
        disable_drivers()
        print("\nprobe stopped, drivers off.")


main()
