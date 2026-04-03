from machine import Pin, PWM
import sys
import struct
import time

# ===================== CONFIG =====================
MOTOR_PWM_PINS = [20, 14, 6, 0, 4]   # M1–M5 PWM
MOTOR_EN_PINS  = [21, 15, 7, 1, 5]   # M1–M5 EN
NSLEEP_PIN     = 19

PWM_FREQ       = 200
PWM_MAX        = 1023

# ---------- Modes ----------
MODE_TEST      = True    # False → streaming mode

# Custom test pattern (0.0–1.0 per motor)
TEST_PATTERN   = [0.5, 0.0, 0.0, 0.0, 0.0]
TEST_PERIOD    = 5.0     # seconds ON/OFF
# ==================================================


# ===================== HELPERS =====================
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
# ==================================================


# ===================== MODES =====================
def test_mode(pwms):
    print("🔧 Test mode:", TEST_PATTERN)
    while True:
        apply_pattern(pwms, TEST_PATTERN)
        time.sleep(TEST_PERIOD)

        stop_all(pwms)
        time.sleep(TEST_PERIOD)


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
# ==================================================


# ===================== MAIN =====================
pwms = init_pwms()
enable_drivers()

try:
    if MODE_TEST:
        test_mode(pwms)
    else:
        stream_mode(pwms)

except KeyboardInterrupt:
    print("\n⏹ Ctrl-C received")

finally:
    stop_all(pwms)
    print("✅ Motors disabled safely")
