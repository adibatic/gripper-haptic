from utilities import *

# ------------------------------------------------------------------ CONFIG ---
THUMB, INDEX, MIDDLE, RING, PINKY = 0, 1, 2, 3, 4

METHOD  = "tactile"   # "vibmotor" or "tactile"
FINGERS = [INDEX]      # any combination, e.g. [THUMB, INDEX, MIDDLE, RING, PINKY]

# Change only if needed
INTENSITY   = 0.5   # 0.0–1.0, applies to all selected fingers
DURATION_S  = 5.0   # seconds per test run
# -----------------------------------------------------------------------------


assert METHOD in ("vibmotor", "tactile")
assert len(FINGERS) > 0 and len(FINGERS) == len(set(FINGERS))
assert all(0 <= f <= 4 for f in FINGERS)
assert 0.0 <= INTENSITY <= 1.0

NAMES = ["THUMB", "INDEX", "MIDDLE", "RING", "PINKY"]


def run_vibmotor():
    pwms = init_pwms()
    enable_drivers()
    pattern = [0.0] * 5
    for f in FINGERS:
        pattern[f] = INTENSITY
    try:
        print("🔧 Vibmotor |", " ".join(NAMES[f] for f in FINGERS),
              f"| intensity {INTENSITY} | {DURATION_S}s ON/OFF loop | Ctrl-C to stop")
        while True:
            apply_pattern(pwms, pattern)
            time.sleep(DURATION_S)
            stop_all(pwms)
            time.sleep(DURATION_S)
    except KeyboardInterrupt:
        pass
    finally:
        stop_all(pwms)
        print("✅ Done")


def run_tactile():
    # Thermal guard: running multiple actuators simultaneously compounds heat.
    # Each finger runs sequentially, with a cooldown between them scaled to
    # how hard they worked. At full intensity the gap is TACTILE_VIBRATE_GAP_MAX_MS;
    # at lower intensity the gap scales down proportionally.
    cooldown_ms = int(TACTILE_VIBRATE_GAP_MAX_MS * INTENSITY)

    tactiles = init_tactiles()
    try:
        print("🔧 TacTile |", " ".join(NAMES[f] for f in FINGERS),
              f"| intensity {INTENSITY} | {DURATION_S}s per finger"
              f" | cooldown {cooldown_ms}ms between fingers")
        for i, f in enumerate(FINGERS):
            tactile_vibrate_intensity(tactiles[f], INTENSITY, DURATION_S)
            if i < len(FINGERS) - 1:   # no cooldown after the last finger
                time.sleep_ms(cooldown_ms)
    finally:
        stop_all_tactiles(tactiles)
        print("✅ Done")


try:
    run_vibmotor() if METHOD == "vibmotor" else run_tactile()
except KeyboardInterrupt:
    print("\n⏹ Stopped")