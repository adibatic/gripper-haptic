"""
haptic.py — runs ON THE ESP32-C6 (MicroPython).

Actuator driver library for both haptic methods. Not host code: copy it to the
board and let an entry point import it — stream.py (the live receiver for
experiment.py), or test_haptic.py / test_tactiles.py / test_tactiles2.py for
bench self-tests.

Two actuator paths:
    LRA vibmotors — init_bridges() + ACDriver. Bipolar AC carrier; bench-
        confirmed that unipolar PWM produces no motion on this hardware.
    TacTiles     — init_tactiles(), with two selectable drivers:
        - TactileVibrationDriver: continuous burst/gap vibration (same
          tick()-per-loop design as ACDriver) so intensity maps to pulse
          rate. This is what stream.py's METHOD = "tactiles" drives
          experiment.py's "tactiles" condition with — the mechanism the
          study's first 19 participants' tactiles-condition data was
          collected under.
        - TactileLatchDriver: binary contact/no-contact latch (same
          engage()/restrike/disengage mechanism as tests/test_tactiles2.py)
          — crossing the contact threshold fires engage() + a restrike pulse
          and holds (zero power while held); dropping back below it fires a
          single disengage(). Selected via stream.py's METHOD = "tactiles2",
          which drives experiment.py's "tactiles2" condition.

The legacy PWM helpers (init_pwms / apply_pattern / stop_duties / stop_all) and
the stream_mode() / tactiles_stream_mode() receivers below are superseded by
stream.py for the experiment — they parse the OLD broadcast protocol (one float
to all 5 fingers) and remain only for the bench scripts.
"""
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
# Bumped 3 -> 4ms so each vibration tap has more pin throw (more perceptible
# "hit"), and TACTILE_BURST_US raised to match (must stay > 2*PULSE_MS*1000).
TACTILE_PULSE_MS    =   4
TACTILE_STAGGER_MS  =  10
TACTILE_BURST_COUNT =  10
TACTILE_BURST_US    = 9000   # interval per pulse (must be > 2*PULSE_MS*1000)
TACTILE_VIBRATE_BURST_COUNT = 10   # pulses per burst window (~50 ms)
# Gap floor lowered 50 -> 35ms so max-intensity vibration bursts more often
# (more intense buzz at high grip force) while still respecting the thermal
# limit below.
TACTILE_VIBRATE_GAP_MIN_MS  = 35   # gap at intensity 1.0
TACTILE_VIBRATE_GAP_MAX_MS  = 400  # gap at intensity 0.0
# thermal limit: ~120 switches/min → keep long-term average below 2 Hz.
# Re-check actual switch rate on hardware after tuning PULSE_MS/GAP_MIN —
# if the actuator runs hot, raise GAP_MIN back up first.

# TactileLatchDriver (binary contact/no-contact, see class below): the
# intensity level at/above which a channel is considered "in contact" and
# engaged; below it, disengaged. Same restrike gap as tests/test_tactiles2.py.
# Kept low (not 0.5) on purpose: intensity is deform_mm/DEPTH_SATURATION_MM
# (kernel/tactile.py), and MAX_SAFE_DEPTH_MM (run/experiment.py) blocks further
# closing at 1.0mm depth — for fragile objects (2.0mm saturation) that caps
# intensity at ~0.5 right at the safety cutoff, so a 0.5 threshold would only
# ever latch at the edge of the closing-block boundary (never reliably) and
# feel like no feedback at all. 0.1 fires on any real gel deformation instead
# of waiting for near-max grip force.
TACTILE_LATCH_THRESHOLD = 0.1
TACTILE_RESTRIKE_MS     = 25
# ==================================================


# ===================== HELPERS ====================
def enable_drivers():
    """Wakes the driver chip (NSLEEP high) and enables all 5 motor EN pins."""
    Pin(NSLEEP_PIN, Pin.OUT).value(1)
    for pin in MOTOR_EN_PINS:
        Pin(pin, Pin.OUT).value(1)


def disable_drivers():
    """Disables all 5 motor EN pins, then sleeps the driver chip (NSLEEP low)."""
    for pin in MOTOR_EN_PINS:
        Pin(pin, Pin.OUT).value(0)
    Pin(NSLEEP_PIN, Pin.OUT).value(0)


def init_pwms():
    """One PWM channel per MOTOR_PWM_PINS entry (duty 0), in M1-M5 order."""
    pwms = []
    for pin in MOTOR_PWM_PINS:
        pwm = PWM(Pin(pin))
        pwm.freq(PWM_FREQ)
        pwm.duty(0)
        pwms.append(pwm)
    return pwms


def apply_pattern(pwms, pattern):
    """Writes one duty cycle per channel (intensities 0.0-1.0, clamped)."""
    for pwm, val in zip(pwms, pattern):
        val = max(0.0, min(1.0, val))
        pwm.duty(int(val * PWM_MAX))


def stop_duties(pwms):
    """Silences all motors (duty 0) but keeps the driver chip AWAKE.

    Use this for the watchdog gap. Sleeping the chip on an idle tick means
    nothing wakes it and the next packet silently does nothing.
    """
    for pwm in pwms:
        pwm.duty(0)


def stop_all(pwms):
    """Full power-down. Only on real shutdown (a finally block) — nothing
    re-asserts the drivers until enable_drivers() runs again."""
    for pwm in pwms:
        pwm.duty(0)
    disable_drivers()
# =================================================


# ===================== MODES =====================
def test_mode(pwms, pattern, period):
    """Buzzes `pattern` on/off every `period` seconds until interrupted."""
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
    """LEGACY receiver: 20-byte binary packets (5 floats). Superseded by
    stream.py, which experiment.py actually talks to."""
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
    """One bistable pin actuator on an IN1/IN2 H-bridge leg. A pulse in one
    direction engages the pin, the opposite direction retracts it; both
    latch mechanically, so it draws zero power while held.

    Bench-confirmed the pin only contacts skin on the IN2-first pulse, not
    IN1-first — backwards from the H-bridge's nominal "forward" convention
    on this hardware. engage()/disengage() below pulse IN2/IN1 accordingly
    so callers keep the intuitive engage=contact, disengage=retract meaning."""

    def __init__(self, in1_pin, in2_pin):
        """Claims the IN1/IN2 GPIO pins as outputs and starts off (both low)."""
        self.in1 = Pin(in1_pin, Pin.OUT)
        self.in2 = Pin(in2_pin, Pin.OUT)
        self.off()

    def off(self):
        """Drives both legs low — coasts, no latching pulse."""
        self.in1.value(0)
        self.in2.value(0)

    def engage(self):
        """IN2 pulse (TACTILE_ENGAGE_MS) — pin contacts skin and latches."""
        self.in1.value(0)
        self.in2.value(1)
        time.sleep_ms(TACTILE_ENGAGE_MS)
        self.off()

    def disengage(self):
        """IN1 pulse (TACTILE_DISENGAGE_MS) — pin retracts and latches."""
        self.in1.value(1)
        self.in2.value(0)
        time.sleep_ms(TACTILE_DISENGAGE_MS)
        self.off()

    def pulse(self):
        """Forward pulse then reverse pulse (each TACTILE_PULSE_MS) — a
        quick tap with no sustained contact."""
        self.in1.value(1)
        self.in2.value(0)
        time.sleep_ms(TACTILE_PULSE_MS)
        self.off()
        self.in1.value(0)
        self.in2.value(1)
        time.sleep_ms(TACTILE_PULSE_MS)
        self.off()

    def burst(self, count=TACTILE_BURST_COUNT, interval_us=TACTILE_BURST_US):
        """Fires `count` pulses spaced `interval_us` apart.

        interval_us must exceed 2 * TACTILE_PULSE_MS * 1000 or pulses overlap.
        """
        for _ in range(count):
            self.pulse()
            delay = interval_us - (2 * TACTILE_PULSE_MS * 1000)
            if delay > 0:
                time.sleep_us(delay)


def init_tactiles():
    """Wakes the driver chip; returns one TacTiles per pin pair, in T1-T5 order."""
    Pin(NSLEEP_PIN, Pin.OUT).value(1)
    return [TacTiles(in1, in2) for in1, in2 in TACTILE_PINS]


def stop_all_tactiles(tactiles):
    """Turns off every actuator in `tactiles` (see TacTiles.off())."""
    for t in tactiles:
        t.off()


def tactiles_test_mode(tactiles, period):
    """Cycles all actuators through engage -> burst -> disengage, each
    phase lasting period/3 seconds, until interrupted."""
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
    """LEGACY receiver: 20-byte binary packets (5 floats). Superseded by
    stream.py, which experiment.py actually talks to."""
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
    """Sustained vibration via repeated bursts. The default gap keeps the
    switch rate under the actuator's ~120/min thermal limit."""
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
    """H-bridge leg pairs for the AC/LRA path, in M1-M5 order.

    Use INSTEAD of init_pwms() — they share pins; never init both at once.
    """
    Pin(NSLEEP_PIN, Pin.OUT).value(1)
    legs = []
    for in1, in2 in TACTILE_PINS:
        a = Pin(in1, Pin.OUT); a.value(0)
        b = Pin(in2, Pin.OUT); b.value(0)
        legs.append((a, b))
    return legs


class ACDriver:
    """Non-blocking bipolar AC carrier with envelope intensity.

    tick() never sleeps — call it as fast as the main loop allows. Each call
    advances the carrier by wall-clock time and writes the pins, so the buzz
    stays continuous regardless of what else the loop does. One intensity is
    shared by all the driver's fingers; use one driver per channel for
    independent levels.
    """
    def __init__(self, legs, fingers):
        self.legs = legs
        self.fingers = fingers
        self._intensity = 0.0
        self._pol = 0
        self._last_flip = time.ticks_us()
        self._win_start = time.ticks_ms()

    def set_intensity(self, val):
        """Sets the target intensity, clamped to [0.0, LRA_MAX_DUTY] — a
        hard thermal duty cap, not just a 1.0 clamp."""
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
        """Advances the envelope/carrier state machine by one tick and
        writes the H-bridge pins. Call as fast as possible — never sleeps;
        see the class docstring."""
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
        """Zeroes intensity and coasts all pins — immediate stop, no envelope decay."""
        self._intensity = 0.0
        self._coast()
# ==========================================================================


def tactiles_vibrate_intensity(tactile, intensity, duration_s,
                               burst_count=TACTILE_VIBRATE_BURST_COUNT):
    """Vibrates at a perceptual intensity by mapping it to the burst gap.
    Thermally safe at any setting, since the gap floor is fixed."""
    intensity = max(0.0, min(1.0, intensity))
    gap_ms = int(TACTILE_VIBRATE_GAP_MAX_MS
                 - intensity * (TACTILE_VIBRATE_GAP_MAX_MS - TACTILE_VIBRATE_GAP_MIN_MS))
    tactiles_vibrate(tactile, duration_s, burst_count=burst_count, gap_ms=gap_ms)


# ============ NON-BLOCKING TACTILE VIBRATION (vibmotor parity) =============
# run_tactiles_stream() in stream.py used to fire a single momentary pulse()
# (6ms) whenever a channel crossed a 0.5 threshold, rate-limited to once per
# 500ms — nothing like the vibmotor's continuous, intensity-proportional
# buzz, hence "barely any actuation" at the low/mid intensities where most
# grip readings live. This driver reuses the exact same burst/gap timing as
# tactiles_vibrate_intensity() above (same constants, same thermal budget)
# but as a tick()-driven state machine, so it can run continuously and
# share the loop with a second channel without blocking — the same design
# ACDriver uses for the LRA path.

class TactileVibrationDriver:
    """Non-blocking sustained vibration for one TacTiles actuator.

    tick() never sleeps — call it every loop pass, like ACDriver.tick().
    Intensity continuously scales the inter-burst gap (TACTILE_VIBRATE_GAP_*),
    so the actuator buzzes the whole time intensity > 0 instead of tapping
    once per threshold crossing.
    """

    def __init__(self, tactile):
        self.tactile = tactile
        self._intensity = 0.0
        self._state = 'gap'   # 'gap' | 'fwd' | 'rev' | 'between'
        self._pulses_done = 0
        self._next_ms = time.ticks_ms()

    def set_intensity(self, val):
        """Sets the target intensity, clamped to [0.0, 1.0]."""
        self._intensity = max(0.0, min(1.0, val))

    def _gap_ms(self):
        return int(TACTILE_VIBRATE_GAP_MAX_MS - self._intensity *
                   (TACTILE_VIBRATE_GAP_MAX_MS - TACTILE_VIBRATE_GAP_MIN_MS))

    def tick(self):
        """Advances the burst/gap state machine by one tick and writes the
        H-bridge pins. Call as fast as possible — never sleeps."""
        now = time.ticks_ms()

        if self._intensity <= 0.0:
            if self._state != 'gap':
                self.tactile.off()
                self._state = 'gap'
                self._pulses_done = 0
            self._next_ms = now
            return

        if time.ticks_diff(now, self._next_ms) < 0:
            return   # not due yet

        if self._state == 'gap':
            self.tactile.in1.value(1); self.tactile.in2.value(0)
            self._state = 'fwd'
            self._next_ms = time.ticks_add(now, TACTILE_PULSE_MS)
        elif self._state == 'fwd':
            self.tactile.in1.value(0); self.tactile.in2.value(1)
            self._state = 'rev'
            self._next_ms = time.ticks_add(now, TACTILE_PULSE_MS)
        elif self._state == 'rev':
            self.tactile.off()
            self._pulses_done += 1
            if self._pulses_done >= TACTILE_VIBRATE_BURST_COUNT:
                self._pulses_done = 0
                self._state = 'gap'
                self._next_ms = time.ticks_add(now, self._gap_ms())
            else:
                self._state = 'between'
                between_ms = max(0, (TACTILE_BURST_US // 1000) - 2 * TACTILE_PULSE_MS)
                self._next_ms = time.ticks_add(now, between_ms)
        elif self._state == 'between':
            self.tactile.in1.value(1); self.tactile.in2.value(0)
            self._state = 'fwd'
            self._next_ms = time.ticks_add(now, TACTILE_PULSE_MS)

    def stop(self):
        """Zeroes intensity and turns the actuator off immediately."""
        self._intensity = 0.0
        self.tactile.off()
        self._state = 'gap'
        self._pulses_done = 0
# ==========================================================================


# ============ NON-BLOCKING TACTILE LATCH (test_tactiles2 mechanism) ========
# stream.py's tactiles path (--condition tactiles) drives TactileVibrationDriver
# above — a continuous burst/gap buzz whose rate scales with intensity, the
# tests/test_tactiles.py mechanism, and what the study's first 19
# participants' tactiles-condition data was collected under.
# tests/test_tactiles2.py demonstrated a different, binary mechanism instead:
# engage() once at the start of contact (plus a restrike pulse RESTRIKE_MS
# later, since the first pulse doesn't always fully seat the pin), then hold
# the latch — no buzzing — until contact ends, at which point a single
# disengage() retracts and latches the other way. Because the actuator is
# bistable, it draws zero power while held either way. TactileLatchDriver
# below reproduces that same mechanism as a tick()-driven state machine so it
# can react to a live 0-1 intensity stream instead of test_tactiles2.py's
# fixed ON_S/OFF_S timer, while sharing a loop with a second channel like the
# other drivers. It's selected via stream.py's METHOD = "tactiles2", which
# drives experiment.py's "tactiles2" condition.

class TactileLatchDriver:
    """Non-blocking binary engage/disengage latch for one TacTiles actuator,
    mirroring tests/test_tactiles2.py: crossing TACTILE_LATCH_THRESHOLD
    upward fires engage() immediately and schedules a restrike engage()
    TACTILE_RESTRIKE_MS later, then holds latched; crossing back downward
    fires a single disengage(). No repeated pulsing while held in either
    state.

    tick() never sleeps beyond the brief engage()/disengage() pulse itself
    (6-10ms) — call it every loop pass, like the other drivers' tick().
    """

    def __init__(self, tactile):
        self.tactile = tactile
        self._intensity = 0.0
        self._engaged = False
        self._restrike_due = None

    def set_intensity(self, val):
        """Sets the target intensity, clamped to [0.0, 1.0]."""
        self._intensity = max(0.0, min(1.0, val))

    def tick(self):
        """Advances the latch state machine by one tick and, on a state
        change, fires the pin pulse."""
        now = time.ticks_ms()
        contact = self._intensity >= TACTILE_LATCH_THRESHOLD

        if contact and not self._engaged:
            self.tactile.engage()
            self._engaged = True
            self._restrike_due = time.ticks_add(now, TACTILE_RESTRIKE_MS)
        elif not contact and self._engaged:
            self.tactile.disengage()
            self._engaged = False
            self._restrike_due = None
        elif self._restrike_due is not None and time.ticks_diff(now, self._restrike_due) >= 0:
            self.tactile.engage()   # restrike: first pulse may not fully seat the pin against skin
            self._restrike_due = None

    def stop(self):
        """Disengages (if latched) and zeroes intensity — immediate stop."""
        if self._engaged:
            self.tactile.disengage()
        self._intensity = 0.0
        self._engaged = False
        self._restrike_due = None
# ==========================================================================