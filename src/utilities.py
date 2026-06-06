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


def stop_all(pwms):
    # Stop PWM first
    for pwm in pwms:
        pwm.duty(0)

    # Then hard-disable drivers
    disable_drivers()
# =================================================


# ===================== MODES =====================
def test_mode(pwms, pattern, period):
    print("🔧 Test mode:", pattern)
    while True:
        apply_pattern(pwms, pattern)
        time.sleep(period)

        stop_all(pwms)
        time.sleep(period)


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


def tactiles_vibrate_intensity(tactile, intensity, duration_s,
                               burst_count=TACTILE_VIBRATE_BURST_COUNT):
    """Intensity 0.0-1.0 maps gap from TACTILE_VIBRATE_GAP_MAX_MS down to
    TACTILE_VIBRATE_GAP_MIN_MS, giving a perceptual intensity knob while
    staying thermally safe at any setting."""
    intensity = max(0.0, min(1.0, intensity))
    gap_ms = int(TACTILE_VIBRATE_GAP_MAX_MS
                 - intensity * (TACTILE_VIBRATE_GAP_MAX_MS - TACTILE_VIBRATE_GAP_MIN_MS))
    tactiles_vibrate(tactile, duration_s, burst_count=burst_count, gap_ms=gap_ms)