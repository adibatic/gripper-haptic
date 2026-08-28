"""
Section 5.1 — trial loading and derived per-trial metrics.

Reads the trial CSVs written by experiment.py
(<trials-dir>/<participant>/<participant>_<condition>_<object>_trial<N>.csv),
computes one row of metrics per trial, and reduces those to a per-participant
median per condition and object class — the unit every test in comparisons.py
and survival.py operates on.
"""

import os
import re
import glob

import numpy as np
import pandas as pd


# Matches experiment.py's filename schema:
# <participant>_<condition>_<object>_trial<N>.csv
FNAME_RE = re.compile(
    r"^(?P<participant>[^_]+)_(?P<condition>visual_only|lra|em)_"
    r"(?P<object>fragile|deformable)_trial(?P<trial>\d+)"
    r"(?:_(?P<outcome>success|break))?\.csv$"
)


def find_trial_csvs(trials_dir):
    """Recursively finds every *.csv under trials_dir, so both the current
    <trials_dir>/<participant>/*.csv layout (experiment.py) and a flat
    <trials_dir>/*.csv layout (legacy runs) are picked up."""
    return sorted(glob.glob(os.path.join(trials_dir, "**", "*.csv"), recursive=True))


# ---------------------------------------------------------------------------
# Section 5.1 — Derived Per-Trial Metrics
# ---------------------------------------------------------------------------

def combined_series(df, collapse):
    """Collapse experiment.py's per-side columns into one force + one depth
    series for a trial.

    Args:
        df: One trial's DataFrame (left_/right_ schema from experiment.py).
        collapse: "sum_n" (grip force = left_force_N + right_force_N) or
            "max" (grip force = max of the two raw force proxies). Depth is
            the elementwise max of the two sides either way.

    Returns:
        (force, depth, force_label): force is all-NaN under "sum_n" when the
        force_N columns are empty (sensors not yet load-cell calibrated).
    """
    depth = np.maximum(
        pd.to_numeric(df["left_max_depth_mm"], errors="coerce"),
        pd.to_numeric(df["right_max_depth_mm"], errors="coerce"),
    ).to_numpy()
    if collapse == "sum_n":
        left_n = pd.to_numeric(df["left_force_N"], errors="coerce")
        right_n = pd.to_numeric(df["right_force_N"], errors="coerce")
        force = (left_n + right_n).to_numpy()
        force_label = "grip force (N, L+R)"
    else:  # "max"
        force = np.maximum(
            pd.to_numeric(df["left_force_proxy"], errors="coerce"),
            pd.to_numeric(df["right_force_proxy"], errors="coerce"),
        ).to_numpy()
        force_label = "force proxy (max L/R, uncalibrated)"
    return force, depth, force_label


def _count_reversals(force_segment):
    """Counts local direction reversals (sign changes in consecutive
    differences) in a 1D force segment, ignoring NaNs. Used as a proxy for
    force-correction oscillations — each reversal is one up-then-down or
    down-then-up turn in the force trace. Returns None if fewer than 3
    finite samples (too short to have a direction to reverse)."""
    finite = force_segment[np.isfinite(force_segment)]
    if len(finite) < 3:
        return None
    d = np.diff(finite)
    d = d[d != 0]  # flat runs don't count as a direction
    if len(d) < 2:
        return 0
    signs = np.sign(d)
    return int(np.sum(signs[1:] != signs[:-1]))


def compute_trial_metrics(trial_csv_path, contact_threshold_mm, collapse):
    """Compute the per-trial metrics from one trial CSV (schema: t,
    gripper_pos_bit, left/right_force_proxy, left/right_force_N,
    left/right_max_depth_mm): the four thesis Section 5.1 metrics, plus
    three exploratory trajectory-shape metrics added to characterize *how*
    a grasp unfolds, not just its outcome — approach_rate_mm_s (how fast
    depth rises during the approach), n_force_reversals_post_plateau (force
    correction oscillations once contact is established), and
    time_above_90pct_peak_s (dwell time at high force). These support the
    object-mechanics-interaction analysis: fragile objects reward a force
    CEILING (fewer/smaller reversals, less dwell near peak), deformable
    objects reward graded CONFORMING control (no ceiling to avoid), so the
    same haptic feedback is expected to shape these differently by object.

    The two sensors are collapsed to one force + one depth series by
    combined_series(collapse); force is the deformation-based grip-force
    proxy (or its calibrated Newton form under sum_n), used in place of the
    old motor-current reading — the Robotiq's gCU register reads 0 mA on
    this unit regardless of contact, so current was never usable.

    Any metric that cannot be computed is set to None (not fabricated) and
    excluded from aggregation with a printed warning. Under collapse="sum_n"
    on uncalibrated data the two force metrics come back None (empty
    force_N), while the depth/contact metrics still compute.

    Args:
        trial_csv_path: Path to one trial CSV.
        contact_threshold_mm: Depth above which contact is considered detected.
        collapse: How to combine the two sides — "sum_n" or "max".

    Returns:
        A dict with peak_force_proxy, peak_depth_mm,
        time_to_first_contact_s, force_overshoot_proxy,
        approach_rate_mm_s, n_force_reversals_post_plateau,
        time_above_90pct_peak_s — or None if the CSV is empty. (Metric keys
        are kept stable across collapse modes; under sum_n the force-based
        values are in Newtons, not proxy units.)
    """
    df = pd.read_csv(trial_csv_path)
    if df.empty:
        return None

    t = pd.to_numeric(df["t"], errors="coerce").to_numpy()
    force, depth, _ = combined_series(df, collapse)

    peak_depth = float(np.nanmax(depth)) if np.isfinite(depth).any() else None
    peak_force = float(np.nanmax(force)) if np.isfinite(force).any() else None

    # Time to first contact: first t where depth exceeds contact_threshold_mm
    # (depth is the max of both sides, so this is first-of-either-finger).
    contact_idx_arr = np.where(depth > contact_threshold_mm)[0]
    contact_idx = int(contact_idx_arr[0]) if len(contact_idx_arr) > 0 else None
    time_to_first_contact = float(t[contact_idx]) if contact_idx is not None else None

    # Plateau: first index at which depth reaches within 5% of its own
    # trial-maximum — i.e. the first time depth hits (peak_depth * 0.95).
    # This is an operational definition chosen for this script and shared
    # by force_overshoot_proxy AND the two post-plateau metrics below; if
    # you adopt a different plateau definition when writing the thesis,
    # update it here AND in Section 5.1's text so all stay consistent.
    plateau_idx = None
    if peak_depth is not None and peak_depth > 0:
        plateau_idx_arr = np.where(depth >= 0.95 * peak_depth)[0]
        if len(plateau_idx_arr) > 0:
            plateau_idx = int(plateau_idx_arr[0])

    # Force overshoot: rise in the force after depth reaches its plateau.
    overshoot = None
    if peak_force is not None and plateau_idx is not None:
        force_at_plateau = force[plateau_idx]
        tail = force[plateau_idx:]
        if np.isfinite(force_at_plateau) and np.isfinite(tail).any():
            overshoot = float(np.nanmax(tail)) - float(force_at_plateau)

    # Approach rate (exploratory): mean rate of depth increase from first
    # contact to plateau, mm/s. None if contact and plateau coincide/invert
    # (zero or negative elapsed time — e.g. depth is already at 95% of its
    # max on the very first contacted sample).
    approach_rate = None
    if contact_idx is not None and plateau_idx is not None and plateau_idx > contact_idx:
        dt = t[plateau_idx] - t[contact_idx]
        if dt > 0:
            d_depth = depth[plateau_idx] - depth[contact_idx]
            approach_rate = float(d_depth / dt)

    # Force-correction reversals post-plateau (exploratory): direction
    # changes in the force trace once contact has plateaued — a proxy for
    # how much a participant "hunts" for the right grip force rather than
    # settling.
    n_reversals = None
    if plateau_idx is not None:
        n_reversals = _count_reversals(force[plateau_idx:])

    # Dwell time above 90% of peak force (exploratory), over the whole
    # trial: sum of the time interval FOLLOWING each sample that is itself
    # >= 0.9 * peak_force. An interval-count approximation (not exact
    # trapezoidal integration under the threshold crossing), consistent
    # with the ~30 Hz sample rate.
    time_above_90pct_peak = None
    if peak_force is not None and peak_force > 0 and np.isfinite(force).sum() >= 2:
        threshold = 0.9 * peak_force
        above = np.isfinite(force) & (force >= threshold)
        dt = np.diff(t)
        time_above_90pct_peak = float(np.nansum(dt[above[:-1]]))

    return {
        "peak_force_proxy": peak_force,
        "peak_depth_mm": peak_depth,
        "time_to_first_contact_s": time_to_first_contact,
        "force_overshoot_proxy": overshoot,
        "approach_rate_mm_s": approach_rate,
        "n_force_reversals_post_plateau": n_reversals,
        "time_above_90pct_peak_s": time_above_90pct_peak,
    }


def load_all_trials(trials_dir, contact_threshold_mm, collapse):
    """Scan trials_dir for files matching FNAME_RE, compute per-trial
    metrics for each, and return a long-format DataFrame with one row per
    trial: participant, condition, object, trial_num, + the seven metrics
    from compute_trial_metrics() (four Section 5.1 + three exploratory).

    Args:
        trials_dir: Directory to scan for trial CSVs.
        contact_threshold_mm: Passed through to compute_trial_metrics().
        collapse: Sensor-combination mode, passed through ("sum_n" or "max").

    Returns:
        A DataFrame, one row per successfully-parsed trial.

    Raises:
        ValueError: If no valid trial CSVs are found.
    """
    rows = []
    paths = find_trial_csvs(trials_dir)
    unmatched = []

    for path in paths:
        fname = os.path.basename(path)
        m = FNAME_RE.match(fname)
        if not m:
            unmatched.append(fname)
            continue

        metrics = compute_trial_metrics(path, contact_threshold_mm, collapse)
        if metrics is None:
            print(f"WARNING: {fname} is empty or unreadable, skipped.")
            continue

        outcome = m.group("outcome")
        # Only fragile trials carry this tag (experiment.py's y/n breakage
        # prompt). Untagged fragile trials (recorded before this feature
        # existed, or where the prompt was skipped) and all deformable
        # trials get None here, which reduce_to_participant_condition_object()
        # and the Section 5.2-5.4 tests already treat as missing data.
        fragile_survived = {"success": 1.0, "break": 0.0}.get(outcome)

        row = {
            "participant": m.group("participant"),
            "condition": m.group("condition"),
            "object": m.group("object"),
            "trial_num": int(m.group("trial")),
            "fragile_survived": fragile_survived,
        }
        row.update(metrics)
        rows.append(row)

    if unmatched:
        print(f"WARNING: {len(unmatched)} file(s) did not match the expected filename "
              f"pattern '<participant>_<condition>_<object>_trial<N>.csv' and were skipped:")
        for f in unmatched:
            print(f"    {f}")

    if not rows:
        raise ValueError(f"No valid trial CSVs found in {trials_dir}. Nothing to analyze.")

    df = pd.DataFrame(rows)

    # Under sum_n on uncalibrated data both force metrics are empty; tell the
    # user how to proceed rather than silently reporting only depth stats.
    if collapse == "sum_n" and not df["peak_force_proxy"].notna().any():
        print("\nNOTE: --collapse sum_n needs calibrated force_N columns, but every "
              "trial's left_force_N/right_force_N is empty (sensors not yet load-cell "
              "calibrated). The two force metrics will be blank; depth/contact metrics "
              "still computed. Re-run with --collapse max to use the uncalibrated proxy, "
              "or calibrate first (see README, load-cell workflow).")

    return df


def reduce_to_participant_condition_object(trial_df):
    """Section 5.1: reduce repeated trials (median across the two
    repetitions per participant/condition/object, per thesis Section 4.2)
    to one row per participant x condition x object.

    Rows with a None/NaN value for a given metric are excluded from the
    median for THAT metric only (e.g. a trial with no detected contact
    contributes to peak_force_proxy's median but not
    time_to_first_contact_s's), with a printed note if this occurs.

    Args:
        trial_df: Long-format DataFrame from load_all_trials().

    Returns:
        A DataFrame with one row per participant x condition x object,
        plus an n_trials column.
    """
    metric_cols = ["peak_force_proxy", "peak_depth_mm",
                   "time_to_first_contact_s", "force_overshoot_proxy",
                   "approach_rate_mm_s", "n_force_reversals_post_plateau",
                   "time_above_90pct_peak_s", "fragile_survived"]

    grouped = trial_df.groupby(["participant", "condition", "object"])
    out_rows = []
    for (participant, condition, obj), group in grouped:
        row = {"participant": participant, "condition": condition, "object": obj,
               "n_trials": len(group)}
        for col in metric_cols:
            vals = group[col].dropna()
            if len(vals) < len(group):
                print(f"NOTE: {participant}/{condition}/{obj}: "
                      f"{len(group) - len(vals)} of {len(group)} trial(s) missing "
                      f"{col}, median computed from remaining {len(vals)}.")
            row[col] = float(vals.median()) if len(vals) > 0 else None
        out_rows.append(row)

    return pd.DataFrame(out_rows)
