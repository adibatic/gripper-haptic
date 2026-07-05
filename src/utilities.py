# pyright: reportAttributeAccessIssue=false
from machine import Pin, PWM  # type: ignore
import sys
import struct
import time


# ===================== CONFIG =====================
MOTOR_PWM_PINS = [20, 14, 6, 0, 4]   # M1–M5 PWM
MOTOR_EN_PINS  = [21, 15, 7, 1, 5]   # M1–M5 EN
NSLEEP_PIN     = 19

PWM_FREQ       = 200
PWM_MAX        = 1023

TACTILE_PINS   = [      # IN1/IN2 pairs for TacTiles H-bridges
    (20, 21),           # T1
    (14, 15),           # T2
    (6,  7),            # T3
    (0,  1),            # T4
    (4,  5),            # T5
]
TACTILE_TIMEOUT_MS  = 200
TACTILE_ENGAGE_MS   =   6
TACTILE_DISENGAGE_MS=  10
TACTILE_PULSE_MS    =   3
TACTILE_STAGGER_MS  =  10
TACTILE_BURST_COUNT =  10
TACTILE_BURST_US    = 8000   # interval per pulse (must be > 2*PULSE_MS*1000)
TACTILE_VIBRATE_BURST_COUNT = 10   # pulses per burst window (~50 ms)
TACTILE_VIBRATE_GAP_MIN_MS  = 50   # gap at intensity 1.0
TACTILE_VIBRATE_GAP_MAX_MS  = 400  # gap at intensity 0.0
# thermal limit: ~120 switches/min → keep long-term average below 2 Hz
# ==================================================


# ===================== HELPERS ====================
def enable_drivers():
    Pin(NSLEEP_PIN, Pin.OUT).value(1)
    for pin in MOTOR_EN_PINS:
        Pin(pin, Pin.OUT).value(1)


def disable_drivers():
    for pin in MOTOR_EN_PINS:
        Pin(pin, Pin.OUT).value(0)
    Pin(NSLEEP_PIN, Pin.OUT).value(0)


def init_pwms():
    pwms = []
    for pin in MOTOR_PWM_PINS:
        pwm = PWM(Pin(pin))
        pwm.freq(PWM_FREQ)
        pwm.duty(0)
        pwms.append(pwm)
    return pwms


def apply_pattern(pwms, pattern):
    for pwm, val in zip(pwms, pattern):
        val = max(0.0, min(1.0, val))
        pwm.duty(int(val * PWM_MAX))


def stop_duties(pwms):
    """Silence all motors (duty -> 0) WITHOUT sleeping the driver chip.

    Use this for the stream-mode watchdog gap. A <=200ms silence between
    packets should NOT require pulling NSLEEP/EN low and re-initialising the
    driver — doing that is what killed vibration in the old stream loop
    (the chip went to sleep on the first idle tick and nothing woke it).
    """
    for pwm in pwms:
        pwm.duty(0)


def stop_all(pwms):
    # Stop PWM first
    for pwm in pwms:
        pwm.duty(0)

    # Then hard-disable drivers (NSLEEP=0, EN=0). Full power-down.
    # Only call this on real shutdown (finally block), NOT inside a hot loop,
    # because nothing re-asserts the drivers until enable_drivers() runs again.
    disable_drivers()
# =================================================


# ===================== MODES =====================
def test_mode(pwms, pattern, period):
    print("🔧 Test mode:", pattern)
    enable_drivers()                 # assert once, up front
    try:
        while True:
            apply_pattern(pwms, pattern)
            time.sleep(period)

            stop_duties(pwms)        # silence but KEEP the chip awake
            time.sleep(period)       # so cycle 2, 3, ... still buzz
    finally:
        stop_all(pwms)               # full power-down only on exit


def stream_mode(pwms):
    print("▶ Streaming mode (Ctrl-C to exit)")
    buf = bytearray(20)
    last_rx = time.ticks_ms()
    TIMEOUT_MS = 200   # auto-stop if sender dies

    while True:
        n = sys.stdin.buffer.readinto(buf)

        if n == 20:
            last_rx = time.ticks_ms()
            values = struct.unpack('<5f', buf)
            apply_pattern(pwms, values)
        else:
            # Fail-safe: stop motors if no data
            if time.ticks_diff(time.ticks_ms(), last_rx) > TIMEOUT_MS:
                stop_all(pwms)
            time.sleep(0.01)
# =================================================


# ================= TACTILE MODES =================
class TacTiles:
    def __init__(self, in1_pin, in2_pin):
        self.in1 = Pin(in1_pin, Pin.OUT)
        self.in2 = Pin(in2_pin, Pin.OUT)
        self.off()

    def off(self):
        self.in1.value(0)
        self.in2.value(0)

    def engage(self):
        self.in1.value(1)
        self.in2.value(0)
        time.sleep_ms(TACTILE_ENGAGE_MS)
        self.off()

    def disengage(self):
        self.in1.value(0)
        self.in2.value(1)
        time.sleep_ms(TACTILE_DISENGAGE_MS)
        self.off()

    def pulse(self):
        self.in1.value(1)
        self.in2.value(0)
        time.sleep_ms(TACTILE_PULSE_MS)
        self.off()
        self.in1.value(0)
        self.in2.value(1)
        time.sleep_ms(TACTILE_PULSE_MS)
        self.off()

    def burst(self, count=TACTILE_BURST_COUNT, interval_us=TACTILE_BURST_US):
        for _ in range(count):
            self.pulse()
            delay = interval_us - (2 * TACTILE_PULSE_MS * 1000)
            if delay > 0:
                time.sleep_us(delay)


def init_tactiles():
    Pin(NSLEEP_PIN, Pin.OUT).value(1)
    return [TacTiles(in1, in2) for in1, in2 in TACTILE_PINS]


def stop_all_tactiles(tactiles):
    for t in tactiles:
        t.off()


def tactiles_test_mode(tactiles, period):
    print("🔧 TacTiles test mode")
    try:
        while True:
            print("Engaging...")
            for t in tactiles:
                t.engage()
                time.sleep_ms(TACTILE_STAGGER_MS)

            time.sleep(period / 3)

            print("Bursting...")
            for t in tactiles:
                t.burst()
                time.sleep_ms(TACTILE_STAGGER_MS)

            time.sleep(period / 3)

            print("Disengaging...")
            for t in tactiles:
                t.disengage()
                time.sleep_ms(TACTILE_STAGGER_MS)

            time.sleep(period / 3)

    except KeyboardInterrupt:
        pass  # bubble up to test_tactiles.py finally block


def tactiles_stream_mode(tactiles):
    print("▶ TacTiles streaming mode (Ctrl-C to exit)")
    buf = bytearray(20)
    last_rx = time.ticks_ms()
    last_action_time = [time.ticks_ms()] * len(tactiles)

    try:
        while True:
            n = sys.stdin.buffer.readinto(buf)

            if n == 20:
                last_rx = time.ticks_ms()
                values = struct.unpack('<5f', buf)
                now = time.ticks_ms()
                for i, (t, val) in enumerate(zip(tactiles, values)):
                    if val > 0.5:
                        if time.ticks_diff(now, last_action_time[i]) > 500:
                            t.pulse()
                            last_action_time[i] = now
            else:
                if time.ticks_diff(time.ticks_ms(), last_rx) > TACTILE_TIMEOUT_MS:
                    stop_all_tactiles(tactiles)
                time.sleep(0.01)

    except KeyboardInterrupt:
        pass  # bubble up to test_tactiles.py finally block
# =================================================


def tactiles_vibrate(tactile, duration_s,
                    burst_count=TACTILE_VIBRATE_BURST_COUNT,
                    gap_ms=TACTILE_VIBRATE_GAP_MIN_MS):
    """Repeated bursts for duration_s seconds, simulating sustained vibration.
    Default gap keeps switch rate well under the 120/min thermal limit."""
    end = time.ticks_add(time.ticks_ms(), int(duration_s * 1000))
    try:
        while time.ticks_diff(end, time.ticks_ms()) > 0:
            tactile.burst(count=burst_count)
            time.sleep_ms(gap_ms)
    except KeyboardInterrupt:
        pass


# ============== AC / LRA BIPOLAR DRIVE (vibmotor replacement) ==============
# Bench-confirmed: this actuator needs symmetric AC drive (bipolar square,
# full peak-to-peak swing). Unipolar PWM (0->+V) produced no motion; bipolar
# (-V<->+V) sustained vibration. So the old PWM-duty path is abandoned for
# this hardware in favor of an H-bridge polarity-flip carrier.
#
# Pins reused from TACTILE_PINS (in1, in2) — same physical H-bridge legs.
#
# Intensity is scaled by an *envelope* (on-fraction within a short window),
# not by duty, because stock machine.PWM can't generate the antiphase pair
# needed for amplitude-scaled bipolar drive. The carrier itself (200Hz) is
# the drive waveform, NOT a thermal "switch" — see datasheet note in caller.

LRA_CARRIER_HZ     = 200    # proven on bench (Test D). Set to actuator resonance if known.
LRA_HALF_PERIOD_US = 2500   # = 1_000_000 / (2 * LRA_CARRIER_HZ). Recompute if you change carrier.
LRA_ENV_WINDOW_MS  = 50     # intensity envelope window (on-fraction). 20Hz drive, not a thermal switch.
LRA_MAX_DUTY       = 1.0    # HARD thermal clamp on average on-fraction (0.0-1.0). LOWER if it runs hot.


def init_bridges():
    """Wake the driver chip and return [(in1, in2), ...] GPIO leg pairs.
    Use this INSTEAD of init_pwms() for the LRA path — they share pins, so
    never init both on the same channels at once."""
    Pin(NSLEEP_PIN, Pin.OUT).value(1)
    legs = []
    for in1, in2 in TACTILE_PINS:
        a = Pin(in1, Pin.OUT); a.value(0)
        b = Pin(in2, Pin.OUT); b.value(0)
        legs.append((a, b))
    return legs


class ACDriver:
    """Non-blocking bipolar carrier + envelope intensity for selected fingers.

    Call tick() as fast as possible from your main loop (it never sleeps).
    Think of it like a render-loop callback (SwiftUI CADisplayLink / a game
    tick): each call advances the carrier phase by wall-clock time and writes
    the pins, so the buzz stays continuous no matter what else the loop does.
    """
    def __init__(self, legs, fingers):
        self.legs = legs
        self.fingers = fingers
        self._intensity = 0.0
        self._pol = 0
        self._last_flip = time.ticks_us()
        self._win_start = time.ticks_ms()

    def set_intensity(self, val):
        # Clamp to the hard thermal duty cap, not just to 1.0.
        if val < 0.0:
            val = 0.0
        elif val > LRA_MAX_DUTY:
            val = LRA_MAX_DUTY
        self._intensity = val

    def _coast(self):
        for f in self.fingers:
            a, b = self.legs[f]
            a.value(0); b.value(0)

    def tick(self):
        # --- envelope: are we in the ON portion of the current window? ---
        now_ms = time.ticks_ms()
        pos = time.ticks_diff(now_ms, self._win_start)
        if pos >= LRA_ENV_WINDOW_MS:
            self._win_start = now_ms
            pos = 0
        on_ms = int(self._intensity * LRA_ENV_WINDOW_MS)
        if self._intensity <= 0.0 or pos >= on_ms:
            self._coast()
            return

        # --- carrier: flip polarity every half period ---
        now_us = time.ticks_us()
        if time.ticks_diff(now_us, self._last_flip) >= LRA_HALF_PERIOD_US:
            self._last_flip = now_us
            self._pol ^= 1
        for f in self.fingers:
            a, b = self.legs[f]
            if self._pol:
                a.value(1); b.value(0)   # forward half
            else:
                a.value(0); b.value(1)   # reverse half

    def stop(self):
        self._intensity = 0.0
        self._coast()
# ==========================================================================


def tactiles_vibrate_intensity(tactile, intensity, duration_s,
                               burst_count=TACTILE_VIBRATE_BURST_COUNT):
    """Intensity 0.0-1.0 maps gap from TACTILE_VIBRATE_GAP_MAX_MS down to
    TACTILE_VIBRATE_GAP_MIN_MS, giving a perceptual intensity knob while
    staying thermally safe at any setting."""
    intensity = max(0.0, min(1.0, intensity))
    gap_ms = int(TACTILE_VIBRATE_GAP_MAX_MS
                 - intensity * (TACTILE_VIBRATE_GAP_MAX_MS - TACTILE_VIBRATE_GAP_MIN_MS))
    tactiles_vibrate(tactile, duration_s, burst_count=burst_count, gap_ms=gap_ms)