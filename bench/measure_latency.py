"""
Host side of the sensor-to-actuator latency bench (thesis Section 5.7).

The loop this measures has three stages. Only the first two can be timed in
software; the third needs an instrument.

    A. SENSE     tactile frame capture -> depth map -> haptic intensity
                 Timed here by running the real pipeline over N frames.

    B. LINK      host serial write -> board parse -> coil energised
                 Timed here as a round trip against bench/board_latency_probe.py,
                 with an echo-only baseline subtracted so the number reflects
                 actuation dispatch rather than USB round trip.

    C. ACTUATE   coil energised -> pin physically moves
                 NOT measurable in software. Two options, in order of
                 preference:
                   1. Oscilloscope. Probe TRIGGER_PIN and a coil lead, send
                      't' commands, read the delay directly.
                   2. Microphone. The EM pin click is audible. Pass --audio
                      to have this script record while it fires pulses and
                      report the acoustic delay. Resolution is one audio
                      sample, so ~0.02 ms at 48 kHz, but the number includes
                      the speed of sound over the mic distance (~3 ms/m).

Reported as median and interquartile range, matching the convention used
throughout Chapter 5.

USAGE

    # Flash and start the board probe first (see that file's docstring),
    # detach the REPL with Ctrl-X, then:

    python bench/measure_latency.py --stage link --n 200
    python bench/measure_latency.py --stage sense --n 200
    python bench/measure_latency.py --stage link --audio --n 30

    # Everything, written to CSV:
    python bench/measure_latency.py --stage all --n 200 --out bench/results
"""

from __future__ import annotations

import argparse
import csv
import os
import statistics
import sys
import time

try:
    import serial
except ImportError:
    serial = None


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

def summarise(name, samples_ms):
    """Median / IQR / p95, the same robust statistics Chapter 5 uses."""
    if not samples_ms:
        return {"stage": name, "n": 0}
    s = sorted(samples_ms)
    n = len(s)
    return {
        "stage": name,
        "n": n,
        "median_ms": round(statistics.median(s), 3),
        "iqr_low_ms": round(s[int(0.25 * (n - 1))], 3),
        "iqr_high_ms": round(s[int(0.75 * (n - 1))], 3),
        "p95_ms": round(s[int(0.95 * (n - 1))], 3),
        "min_ms": round(s[0], 3),
        "max_ms": round(s[-1], 3),
    }


def print_summary(rows):
    if not rows:
        return
    keys = ["stage", "n", "median_ms", "iqr_low_ms", "iqr_high_ms", "p95_ms", "min_ms", "max_ms"]
    widths = {k: max(len(k), *(len(str(r.get(k, ""))) for r in rows)) for k in keys}
    print()
    print("  ".join(k.ljust(widths[k]) for k in keys))
    print("  ".join("-" * widths[k] for k in keys))
    for r in rows:
        print("  ".join(str(r.get(k, "")).ljust(widths[k]) for k in keys))
    print()


def write_csv(rows, out_dir, filename):
    if not rows or not out_dir:
        return
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, filename)
    keys = ["stage", "n", "median_ms", "iqr_low_ms", "iqr_high_ms", "p95_ms", "min_ms", "max_ms"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in keys})
    print(f"Wrote {path}")


# --------------------------------------------------------------------------
# Stage B: link latency
# --------------------------------------------------------------------------

def _probe(ser, cmd, expect, timeout_s=1.0):
    """Sends one command, returns the round-trip time in ms, or None."""
    ser.reset_input_buffer()
    t0 = time.perf_counter()
    ser.write((cmd + "\n").encode())
    ser.flush()
    deadline = t0 + timeout_s
    buf = b""
    while time.perf_counter() < deadline:
        chunk = ser.read(1)
        if not chunk:
            continue
        buf += chunk
        if chunk == b"\n":
            t1 = time.perf_counter()
            if buf.strip().decode(errors="replace") == expect:
                return (t1 - t0) * 1000.0
            buf = b""
    return None


def measure_link(port, baud, n, settle_ms):
    """Baseline echo vs echo-after-energise. The difference isolates the
    cost of actually driving the coil from the USB round trip."""
    if serial is None:
        print("pyserial not installed. pip install pyserial", file=sys.stderr)
        return [], {}

    print(f"Opening {port} at {baud} ...")
    with serial.Serial(port, baud, timeout=0.05) as ser:
        time.sleep(0.5)
        ser.reset_input_buffer()

        # Discard the board's READY banner and any warm-up jitter.
        for _ in range(5):
            _probe(ser, "P", "p")

        baseline, engage, disengage = [], [], []
        for i in range(n):
            b = _probe(ser, "P", "p")
            if b is not None:
                baseline.append(b)

            e = _probe(ser, "E", "e")
            if e is not None:
                engage.append(e)
            time.sleep(settle_ms / 1000.0)

            d = _probe(ser, "D", "d")
            if d is not None:
                disengage.append(d)
            time.sleep(settle_ms / 1000.0)

            if (i + 1) % 25 == 0:
                print(f"  {i + 1}/{n}")

        _probe(ser, "X", "x")

    rows = [
        summarise("link_baseline_echo", baseline),
        summarise("link_engage_roundtrip", engage),
        summarise("link_disengage_roundtrip", disengage),
    ]
    med_b = rows[0].get("median_ms")
    if med_b is not None:
        for key, samples in (("link_engage_dispatch", engage),
                             ("link_disengage_dispatch", disengage)):
            rows.append(summarise(key, [s - med_b for s in samples]))
    return rows, {"baseline_median_ms": med_b}


# --------------------------------------------------------------------------
# Stage A: sense latency
# --------------------------------------------------------------------------

def measure_sense(n, side, camera_index, object_class):
    """Times the real tactile pipeline through the same TactileSensor that
    run/experiment.py uses: grab a frame, reconstruct depth, reduce to the
    intensity that would be streamed to the board."""
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    for p in (os.path.join(root, "kernel"), os.path.join(root, "run")):
        if p not in sys.path:
            sys.path.insert(0, p)

    try:
        from tactile import TactileSensor  # type: ignore
        import camera as camera_mod        # type: ignore
    except ImportError as exc:
        print(f"Could not import kernel/tactile.py ({exc}).", file=sys.stderr)
        print("Run from the repository root, with the sensor plugged in and "
              "the 9DTact dependencies importable.", file=sys.stderr)
        return []

    if camera_index is None:
        camera_index = (camera_mod.TACTILE_CAM_L if side == "left"
                        else camera_mod.TACTILE_CAM_R)

    sensor = TactileSensor(side, camera_index)
    try:
        sensor.connect()
        print(f"  capturing {side} baseline, keep the sensor untouched ...")
        sensor.capture_baseline()

        for _ in range(10):          # warm up the capture pipeline
            sensor.read(object_class)

        samples = []
        for i in range(n):
            t0 = time.perf_counter()
            sensor.read(object_class)
            samples.append((time.perf_counter() - t0) * 1000.0)
            if (i + 1) % 25 == 0:
                print(f"  {i + 1}/{n}")
    finally:
        try:
            sensor.close()
        except Exception:
            pass

    return [summarise("sense_frame_to_intensity", samples)]


# --------------------------------------------------------------------------
# Stage C: acoustic actuation latency (optional)
# --------------------------------------------------------------------------

def measure_audio(port, baud, n, settle_ms, samplerate, threshold):
    """Fires engage pulses while recording, and reports the delay from the
    board's acknowledgement to the click onset.

    Caveats worth stating in the thesis if this number is used:
      - includes the acoustic flight time, roughly 3 ms per metre
      - onset detection is a simple amplitude threshold, so a noisy room
        inflates it
    """
    if serial is None:
        print("pyserial not installed.", file=sys.stderr)
        return []
    try:
        import numpy as np
        import sounddevice as sd
    except ImportError:
        print("--audio needs numpy and sounddevice. pip install sounddevice numpy",
              file=sys.stderr)
        return []

    window_s = 0.30
    samples = []

    with serial.Serial(port, baud, timeout=0.05) as ser:
        time.sleep(0.5)
        ser.reset_input_buffer()
        for _ in range(3):
            _probe(ser, "P", "p")

        for i in range(n):
            rec = sd.rec(int(window_s * samplerate), samplerate=samplerate,
                         channels=1, dtype="float32")
            time.sleep(0.05)                      # let the stream settle

            t_ack = None
            t_start = time.perf_counter()
            if _probe(ser, "E", "e") is not None:
                t_ack = time.perf_counter()

            sd.wait()
            audio = np.abs(rec[:, 0])

            if t_ack is None:
                continue
            ack_offset_s = t_ack - t_start + 0.05
            ack_idx = int(ack_offset_s * samplerate)

            noise = float(np.median(audio[:max(1, ack_idx // 2)])) if ack_idx > 2 else 0.0
            trip = max(threshold, noise * 8.0)
            after = audio[ack_idx:]
            hits = np.nonzero(after > trip)[0]
            if len(hits):
                samples.append(hits[0] / samplerate * 1000.0)

            time.sleep(settle_ms / 1000.0)
            _probe(ser, "D", "d")
            time.sleep(settle_ms / 1000.0)
            if (i + 1) % 10 == 0:
                print(f"  {i + 1}/{n}  detected={len(samples)}")

        _probe(ser, "X", "x")

    if not samples:
        print("No clicks detected. Move the microphone closer, raise the gain, "
              "or lower --audio-threshold.", file=sys.stderr)
    return [summarise("actuate_ack_to_click_acoustic", samples)]


# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", choices=["link", "sense", "all"], default="link")
    ap.add_argument("--port", default="/dev/ttyACM0", help="ESP32 serial port")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--n", type=int, default=200, help="samples per stage")
    ap.add_argument("--settle-ms", type=float, default=60.0,
                    help="pause between pulses; keep well above the thermal "
                         "budget noted in firmware/haptic.py")
    ap.add_argument("--side", default="right", choices=["left", "right"],
                    help="tactile sensor side for --stage sense")
    ap.add_argument("--camera-index", type=int, default=None,
                    help="override the camera index for --stage sense "
                         "(defaults to kernel/camera.py's TACTILE_CAM_L/R)")
    ap.add_argument("--object-class", default="fragile",
                    choices=["fragile", "deformable"],
                    help="selects the depth saturation point, as in the study")
    ap.add_argument("--audio", action="store_true", help="also run the acoustic stage")
    ap.add_argument("--audio-samplerate", type=int, default=48000)
    ap.add_argument("--audio-threshold", type=float, default=0.02)
    ap.add_argument("--out", default=None, help="directory for CSV output")
    args = ap.parse_args()

    rows = []

    if args.stage in ("link", "all"):
        print("== Stage B: link latency ==")
        link_rows, _ = measure_link(args.port, args.baud, args.n, args.settle_ms)
        rows += link_rows

    if args.stage in ("sense", "all"):
        print("== Stage A: sense latency ==")
        rows += measure_sense(args.n, args.side, args.camera_index,
                              args.object_class)

    if args.audio:
        print("== Stage C: acoustic actuation latency ==")
        rows += measure_audio(args.port, args.baud, min(args.n, 50), args.settle_ms,
                              args.audio_samplerate, args.audio_threshold)

    print_summary(rows)
    write_csv(rows, args.out, "section_5_7_latency.csv")

    if rows:
        print("Stage C is not covered by --stage link/sense. Without an "
              "oscilloscope or --audio, report the link figure as a lower "
              "bound on end-to-end latency, not as the end-to-end figure.")


if __name__ == "__main__":
    main()
