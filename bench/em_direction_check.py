# pyright: reportAttributeAccessIssue=false
"""
Runs ON THE ESP32-C6 (MicroPython). Answers one question: is the EM channel
actually driven by a bidirectional H-bridge, or by something that can only
push current one way?

    python -m mpremote connect /dev/ttyACM0 fs cp firmware/haptic.py :
    python -m mpremote connect /dev/ttyACM0 fs cp bench/em_direction_check.py :
    python -m mpremote connect /dev/ttyACM0 repl
    >>> exec(open('em_direction_check.py').read())

Use `repl`, not `run`, so Ctrl-C reaches the board and the finally block
turns the coil off.

WHY THIS TEST EXISTS

firmware/haptic.py drives each EM channel through an IN1/IN2 pair and
assumes a full bridge sits between those pins and the coil, so that IN2-high
pushes current one way and IN1-high pushes it back. If instead there is a
single low-side switch, or one half of the bridge is unpopulated, then only
one of the two directions does anything and the pin will never retract under
its own power.

The test isolates that by firing each direction on its own, in a randomised
order you cannot anticipate, and asking you what you felt. Guessing is the
failure mode this is designed to avoid, so the order is not printed until
after you answer.

SAFETY

Pulses are the same width the firmware already uses in normal operation, and
the coil is released immediately afterwards. There is a mandatory pause
between pulses that is longer than the thermal budget in firmware/haptic.py
requires. Nothing here holds a coil energised.
"""
import time
import urandom

from haptic import (EM_PINS, EM_ENGAGE_MS, EM_DISENGAGE_MS,
                    enable_drivers, disable_drivers)
from machine import Pin

# ------------------------------------------------------------------ CONFIG ---
CHANNEL   = 0     # 0 = T1 = thumb on a right-hand mount
TRIALS    = 6     # total pulses; half each direction
SETTLE_S  = 2.0   # pause between pulses, well above the thermal budget
# -----------------------------------------------------------------------------

assert 0 <= CHANNEL < len(EM_PINS)
assert TRIALS % 2 == 0


def _fire(in1, in2, direction):
    """One pulse. `direction` is 'IN2' (firmware's engage) or 'IN1'
    (firmware's disengage). Coil is released before returning."""
    if direction == 'IN2':
        in1.value(0)
        in2.value(1)
        time.sleep_ms(EM_ENGAGE_MS)
    else:
        in1.value(1)
        in2.value(0)
        time.sleep_ms(EM_DISENGAGE_MS)
    in1.value(0)
    in2.value(0)


def main():
    in1_pin, in2_pin = EM_PINS[CHANNEL]
    in1 = Pin(in1_pin, Pin.OUT)
    in2 = Pin(in2_pin, Pin.OUT)
    in1.value(0)
    in2.value(0)
    enable_drivers()

    order = ['IN2', 'IN1'] * (TRIALS // 2)
    # Fisher-Yates, so you cannot infer the direction from the sequence.
    for i in range(len(order) - 1, 0, -1):
        j = urandom.getrandbits(8) % (i + 1)
        order[i], order[j] = order[j], order[i]

    answers = []

    print("=" * 62)
    print("EM direction check, channel %d (IN1=GPIO%d, IN2=GPIO%d)"
          % (CHANNEL, in1_pin, in2_pin))
    print("=" * 62)
    print()
    print("Rest the actuator against your fingerpad, or watch the pin closely.")
    print("After each pulse, report what you felt or saw:")
    print()
    print("    o  pin moved OUT, toward the skin")
    print("    i  pin moved IN, away from the skin")
    print("    n  nothing at all")
    print()
    print("Answer honestly. The direction fired is hidden until the end.")
    print()
    input("Press ENTER to start... ")

    try:
        for k, direction in enumerate(order):
            print("\n--- pulse %d of %d ---" % (k + 1, TRIALS))
            time.sleep(SETTLE_S)
            _fire(in1, in2, direction)
            while True:
                a = input("  out / in / nothing  [o/i/n]: ").strip().lower()[:1]
                if a in ('o', 'i', 'n'):
                    answers.append(a)
                    break
    except KeyboardInterrupt:
        print("\ninterrupted")
        return
    finally:
        in1.value(0)
        in2.value(0)
        disable_drivers()

    # ---------------------------------------------------------------- report
    in2_ans = [a for a, d in zip(answers, order) if d == 'IN2']
    in1_ans = [a for a, d in zip(answers, order) if d == 'IN1']

    def tally(xs):
        return {'o': xs.count('o'), 'i': xs.count('i'), 'n': xs.count('n')}

    t2, t1 = tally(in2_ans), tally(in1_ans)

    print("\n" + "=" * 62)
    print("RESULT")
    print("=" * 62)
    print("  IN2 pulses (firmware calls this engage):  out=%d in=%d nothing=%d"
          % (t2['o'], t2['i'], t2['n']))
    print("  IN1 pulses (firmware calls this disengage): out=%d in=%d nothing=%d"
          % (t1['o'], t1['i'], t1['n']))
    print()

    in2_moves = t2['o'] + t2['i']
    in1_moves = t1['o'] + t1['i']
    half = TRIALS // 2

    if in2_moves >= half - 1 and in1_moves >= half - 1 and t2['o'] > t2['i'] and t1['i'] > t1['o']:
        verdict = ("BIDIRECTIONAL. Both directions move the pin, and they move "
                   "it opposite ways. Consistent with a real H-bridge, and the "
                   "thesis wording stands.")
    elif in2_moves >= half - 1 and in1_moves == 0:
        verdict = ("ONE DIRECTION ONLY (IN2). IN1 never moves the pin, so the "
                   "coil is only ever driven one way. Do not describe this as "
                   "an H-bridge-driven bistable actuator. See bench/README.md.")
    elif in1_moves >= half - 1 and in2_moves == 0:
        verdict = ("ONE DIRECTION ONLY (IN1). Mirror of the case above, and the "
                   "same conclusion.")
    elif in2_moves and in1_moves and not (t2['o'] > t2['i'] and t1['i'] > t1['o']):
        verdict = ("BOTH DIRECTIONS MOVE IT, BUT NOT OPPOSITELY. Either the "
                   "reports are inconsistent, or the pin is being knocked "
                   "rather than driven to a latched state. Re-run with the "
                   "actuator held still against the fingerpad.")
    else:
        verdict = ("INCONCLUSIVE. Too few movements detected. Check the coil is "
                   "connected, that this is the soldered channel, and re-run.")

    print("  " + verdict)
    print()
    print("  Fired order:", " ".join(order))
    print("  Your answers:", " ".join(answers))
    print()
    print("  Note: this is a behavioural test. It tells you what the hardware")
    print("  does, not what part is on the board. Pair it with reading the")
    print("  driver IC's top marking, per bench/README.md step 1.")


main()
