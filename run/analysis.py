"""
analysis.py

Thesis Chapter 5 (Sections 5.1, 5.3-5.6). Reads the trial CSVs written by
experiment.py (<trials-dir>/<participant>/<participant>_<condition>_<object>_
trial<N>.csv) plus a Likert CSV, and writes every table and figure.
--trials-dir is scanned recursively, so it also picks up flat/legacy layouts
where trial CSVs sit directly in --trials-dir instead of a per-participant
subfolder.

    python run/analysis.py --trials-dir data/experiment_logs --out results \\
        [--likert-csv ...] [--collapse sum_n|max]

--collapse combines the two sensors into one force + one depth series per trial:
    sum_n  grip force = left_force_N + right_force_N (Newtons). Needs
           calibration (setup.py calibrate-force); the headline once you have it.
    max    grip force = max of the raw force proxies (uncalibrated). Works now.
Depth is max(left, right) either way, so contact time is first-of-either-finger.
The tests are rank-based, so sum and mean give identical p-values — only sum_n
vs max can reorder trials. Run both and confirm the findings agree.

Section 5.2 (latency) is NOT computed here — it needs a separate bench
measurement; the ~30 Hz trial CSV cannot capture true sensor-to-actuator latency.
"""

import os
import re
import csv
import glob
import argparse
from collections import defaultdict

import numpy as np
import pandas as pd
from scipy import stats
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


CONDITIONS = ["visual_only", "lra", "tactiles"]
OBJECTS = ["fragile", "deformable"]

# Matches experiment.py's filename schema:
# <participant>_<condition>_<object>_trial<N>.csv
FNAME_RE = re.compile(
    r"^(?P<participant>[^_]+)_(?P<condition>visual_only|lra|tactiles)_"
    r"(?P<object>fragile|deformable)_trial(?P<trial>\d+)"
    r"(?:_(?P<outcome>success|break))?\.csv$"
)


def _find_trial_csvs(trials_dir):
    """Recursively finds every *.csv under trials_dir, so both the current
    <trials_dir>/<participant>/*.csv layout (experiment.py) and a flat
    <trials_dir>/*.csv layout (legacy runs) are picked up."""
    return sorted(glob.glob(os.path.join(trials_dir, "**", "*.csv"), recursive=True))


# ---------------------------------------------------------------------------
# Section 5.1 — Derived Per-Trial Metrics
# ---------------------------------------------------------------------------

def _combined_series(df, collapse):
    """Collapse experiment.py's per-side columns into one force + one depth
    series for a trial (see the module docstring's SENSOR COMBINATION note).

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
    three Section 5.8 trajectory-shape metrics added to characterize *how*
    a grasp unfolds, not just its outcome — approach_rate_mm_s (how fast
    depth rises during the approach), n_force_reversals_post_plateau (force
    correction oscillations once contact is established), and
    time_above_90pct_peak_s (dwell time at high force). These support the
    object-mechanics-interaction analysis: fragile objects reward a force
    CEILING (fewer/smaller reversals, less dwell near peak), deformable
    objects reward graded CONFORMING control (no ceiling to avoid), so the
    same haptic feedback is expected to shape these differently by object.

    The two sensors are collapsed to one force + one depth series by
    _combined_series(collapse); force is the deformation-based grip-force
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
    force, depth, _ = _combined_series(df, collapse)

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
    # update it here AND in Section 5.1/5.8's text so all stay consistent.
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

    # Approach rate (Section 5.8): mean rate of depth increase from first
    # contact to plateau, mm/s. None if contact and plateau coincide/invert
    # (zero or negative elapsed time — e.g. depth is already at 95% of its
    # max on the very first contacted sample).
    approach_rate = None
    if contact_idx is not None and plateau_idx is not None and plateau_idx > contact_idx:
        dt = t[plateau_idx] - t[contact_idx]
        if dt > 0:
            d_depth = depth[plateau_idx] - depth[contact_idx]
            approach_rate = float(d_depth / dt)

    # Force-correction reversals post-plateau (Section 5.8): direction
    # changes in the force trace once contact has plateaued — a proxy for
    # how much a participant "hunts" for the right grip force rather than
    # settling.
    n_reversals = None
    if plateau_idx is not None:
        n_reversals = _count_reversals(force[plateau_idx:])

    # Dwell time above 90% of peak force (Section 5.8), over the whole
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
    from compute_trial_metrics() (four Section 5.1 + three Section 5.8).

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
    paths = _find_trial_csvs(trials_dir)
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
        # and the Section 5.3/5.4 tests already treat as missing data.
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


# ---------------------------------------------------------------------------
# Section 5.3 — Cross-Condition Comparison (Friedman + Wilcoxon)
# ---------------------------------------------------------------------------

def friedman_and_pairwise(reduced_df, metric, out_dir):
    """Section 5.3: Friedman test across the 3 conditions for `metric`,
    then pairwise Wilcoxon signed-rank tests with Holm correction if the
    Friedman test is significant (or always, with a note, if requested —
    here we report pairwise tests regardless, with the Friedman result
    stated alongside so the reader can judge significance properly; the
    thesis text should only INTERPRET pairwise results as confirmatory if
    the omnibus Friedman test is itself significant, per standard practice).

    Requires complete cases: only participants with a non-null `metric`
    value in ALL THREE conditions for object='fragile' OR object='deformable'
    are included per object class (Friedman requires a complete, paired
    design). Participants with any missing condition for a given object
    are dropped from that object's test, with a printed note.

    Args:
        reduced_df: Output of reduce_to_participant_condition_object().
        metric: Column name to test (one of the four Section 5.1 metrics).
        out_dir: Unused here directly, kept for signature symmetry with
            the other Section 5.x report writers.

    Returns:
        Dict keyed by object ('fragile'/'deformable'), each value either
        {"n": ..., "friedman": None, "pairwise": None} (too few complete
        cases) or a dict with n/friedman_stat/friedman_p/pairwise/
        medians/iqrs.
    """
    results = {}

    for obj in OBJECTS:
        sub = reduced_df[reduced_df["object"] == obj]
        pivot = sub.pivot(index="participant", columns="condition", values=metric)

        complete = pivot.dropna(subset=CONDITIONS, how="any")
        n_dropped = len(pivot) - len(complete)
        if n_dropped > 0:
            print(f"NOTE: {metric}/{obj}: dropping {n_dropped} participant(s) with "
                  f"incomplete data across all 3 conditions (Friedman requires complete cases).")

        if len(complete) < 3:
            print(f"WARNING: {metric}/{obj}: only {len(complete)} complete participant(s) "
                  f"available — too few to run Friedman/Wilcoxon (need >= a handful for a "
                  f"meaningful test; scipy requires >= 3 just to run at all). Skipping.")
            results[obj] = {"n": len(complete), "friedman": None, "pairwise": None}
            continue

        visual = complete["visual_only"].to_numpy()
        lra = complete["lra"].to_numpy()
        tactiles = complete["tactiles"].to_numpy()

        friedman_stat, friedman_p = stats.friedmanchisquare(visual, lra, tactiles)

        pairs = [("visual_only", "lra", visual, lra),
                 ("visual_only", "tactiles", visual, tactiles),
                 ("lra", "tactiles", lra, tactiles)]
        pairwise_results = []
        raw_p_values = []
        for name_a, name_b, a, b in pairs:
            diffs = a - b
            if np.all(diffs == 0):
                # Wilcoxon is undefined for all-zero differences
                print(f"WARNING: {metric}/{obj}: {name_a} vs {name_b} has zero variance "
                      f"in paired differences — Wilcoxon undefined, skipping this pair.")
                pairwise_results.append((name_a, name_b, None, None))
                raw_p_values.append(1.0)
                continue
            w_stat, w_p = stats.wilcoxon(a, b)
            pairwise_results.append((name_a, name_b, w_stat, w_p))
            raw_p_values.append(w_p)

        # Holm-Bonferroni correction across the 3 pairwise comparisons
        holm_corrected = holm_bonferroni(raw_p_values)
        pairwise_results = [
            (name_a, name_b, w_stat, w_p, holm_p)
            for (name_a, name_b, w_stat, w_p), holm_p
            in zip(pairwise_results, holm_corrected)
        ]

        results[obj] = {
            "n": len(complete),
            "friedman_stat": float(friedman_stat),
            "friedman_p": float(friedman_p),
            "pairwise": pairwise_results,
            "medians": {c: float(np.median(complete[c])) for c in CONDITIONS},
            "iqrs": {c: (float(np.percentile(complete[c], 25)),
                          float(np.percentile(complete[c], 75))) for c in CONDITIONS},
        }

    return results


def holm_bonferroni(p_values):
    """Holm-Bonferroni step-down correction.

    Args:
        p_values: Raw p-values, any order.

    Returns:
        Corrected p-values in the SAME order as the input list (not sorted).
    """
    p_values = np.array(p_values)
    n = len(p_values)
    order = np.argsort(p_values)
    corrected = np.empty(n)
    prev_max = 0.0
    for rank, idx in enumerate(order):
        adj = (n - rank) * p_values[idx]
        adj = max(adj, prev_max)
        adj = min(adj, 1.0)
        corrected[idx] = adj
        prev_max = adj
    return corrected.tolist()


def write_cross_condition_report(all_results, out_dir):
    """Writes a CSV summary table for Section 5.3, one row per
    metric x object x comparison.

    Args:
        all_results: {metric: friedman_and_pairwise() result}, one entry
            per Section 5.1 metric.
        out_dir: Directory to write section_5_3_cross_condition.csv into.
    """
    path = os.path.join(out_dir, "section_5_3_cross_condition.csv")
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["metric", "object", "n", "friedman_stat", "friedman_p",
                          "comparison", "wilcoxon_stat", "wilcoxon_p", "holm_p"])
        for metric, by_object in all_results.items():
            for obj, res in by_object.items():
                if res["pairwise"] is None:
                    writer.writerow([metric, obj, res["n"], "", "", "", "", "", ""])
                    continue
                for name_a, name_b, w_stat, w_p, holm_p in res["pairwise"]:
                    writer.writerow([
                        metric, obj, res["n"],
                        f"{res['friedman_stat']:.4f}", f"{res['friedman_p']:.4f}",
                        f"{name_a}_vs_{name_b}",
                        f"{w_stat:.4f}" if w_stat is not None else "",
                        f"{w_p:.4f}" if w_p is not None else "",
                        f"{holm_p:.4f}" if holm_p is not None else "",
                    ])
    print(f"Wrote {path}")


# ---------------------------------------------------------------------------
# Section 5.4 — LRA Versus TacTiles (direct paired comparison)
# ---------------------------------------------------------------------------

def lra_vs_tactiles(reduced_df, metric):
    """Section 5.4: direct paired Wilcoxon between lra and tactiles only,
    reported separately from the 3-way comparison in Section 5.3.

    Args:
        reduced_df: Output of reduce_to_participant_condition_object().
        metric: Column name to test.

    Returns:
        Dict keyed by object ('fragile'/'deformable'); each value is
        None (too few complete cases), {"n", "stat": None, "p": None}
        (zero-variance differences), or a dict with n/stat/p/median_lra/
        median_tactiles.
    """
    results = {}
    for obj in OBJECTS:
        sub = reduced_df[reduced_df["object"] == obj]
        pivot = sub.pivot(index="participant", columns="condition", values=metric)
        complete = pivot.dropna(subset=["lra", "tactiles"], how="any")
        n_dropped = len(pivot) - len(complete)
        if n_dropped > 0:
            print(f"NOTE: {metric}/{obj} (LRA vs TacTiles): dropping {n_dropped} "
                  f"participant(s) missing lra or tactiles.")

        if len(complete) < 3:
            print(f"WARNING: {metric}/{obj} (LRA vs TacTiles): only {len(complete)} "
                  f"complete participant(s) — skipping.")
            results[obj] = None
            continue

        lra = complete["lra"].to_numpy()
        tactiles = complete["tactiles"].to_numpy()
        diffs = lra - tactiles
        if np.all(diffs == 0):
            print(f"WARNING: {metric}/{obj}: LRA vs TacTiles has zero variance, Wilcoxon undefined.")
            results[obj] = {"n": len(complete), "stat": None, "p": None}
            continue

        w_stat, w_p = stats.wilcoxon(lra, tactiles)
        results[obj] = {
            "n": len(complete), "stat": float(w_stat), "p": float(w_p),
            "median_lra": float(np.median(lra)), "median_tactiles": float(np.median(tactiles)),
        }
    return results


def write_lra_vs_tactiles_report(all_results, out_dir):
    """Writes a CSV summary table for Section 5.4, one row per metric x object.

    Args:
        all_results: {metric: lra_vs_tactiles() result}, one entry per
            Section 5.1 metric.
        out_dir: Directory to write section_5_4_lra_vs_tactiles.csv into.
    """
    path = os.path.join(out_dir, "section_5_4_lra_vs_tactiles.csv")
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["metric", "object", "n", "wilcoxon_stat", "wilcoxon_p",
                          "median_lra", "median_tactiles"])
        for metric, by_object in all_results.items():
            for obj, res in by_object.items():
                if res is None:
                    writer.writerow([metric, obj, "", "", "", "", ""])
                    continue
                writer.writerow([
                    metric, obj, res["n"],
                    f"{res['stat']:.4f}" if res.get("stat") is not None else "",
                    f"{res['p']:.4f}" if res.get("p") is not None else "",
                    f"{res.get('median_lra', ''):.4f}" if res.get("median_lra") is not None else "",
                    f"{res.get('median_tactiles', ''):.4f}" if res.get("median_tactiles") is not None else "",
                ])
    print(f"Wrote {path}")


# ---------------------------------------------------------------------------
# Section 5.9 — TOST Equivalence (LRA vs TacTiles)
#
# Section 5.4's Wilcoxon test can only fail to reject "no difference" — it
# cannot show the two actuators ARE equivalent. Two One-Sided Tests (TOST)
# is the standard way to make that a positive, defensible claim: it rejects
# H0 = "the true difference is at least as large as the equivalence margin"
# in favor of H1 = "the true difference is smaller than the margin", in
# BOTH directions. If both one-sided tests reject, the two conditions are
# statistically equivalent within that margin.
#
# The margin is a judgment call — the smallest difference you'd consider
# practically meaningful — expressed here as a multiple of the metric's
# own pooled standard deviation (an effect-size-scaled margin, so it is
# comparable across metrics with different units). --equiv-margin-sd
# defaults to 0.5 (a "medium" Cohen's d); tighten it (e.g. 0.3) for a
# stricter equivalence claim, or loosen it, but state your choice and its
# justification explicitly in the thesis text — this script does not pick
# it for you beyond the default.
# ---------------------------------------------------------------------------

def tost_equivalence(a, b, margin_sd, alpha=0.05):
    """Paired TOST (two one-sided t-tests) for whether `a` and `b` are
    equivalent within margin_sd * pooled_sd.

    Args:
        a, b: Paired 1D arrays (same participants, same order).
        margin_sd: Equivalence margin as a multiple of the pooled SD of a
            and b combined (effect-size-scaled, unitless).
        alpha: Significance level for each one-sided test (default 0.05,
            i.e. an overall two-one-sided-tests equivalence claim at the
            conventional 5% level).

    Returns:
        None if fewer than 3 pairs. Otherwise a dict with n, margin
        (in the metric's raw units), mean_diff, p_lower, p_upper,
        p_tost (= max of the two, the standard TOST reporting statistic),
        and equivalent (bool, p_tost < alpha).
    """
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    n = len(a)
    if n < 3:
        return None

    pooled_sd = float(np.std(np.concatenate([a, b]), ddof=1))
    margin = margin_sd * pooled_sd
    if margin == 0:
        # Degenerate: metric is constant across all observations. Equivalent
        # by definition (mean_diff is necessarily 0 too).
        return {"n": n, "margin": 0.0, "mean_diff": 0.0,
                "p_lower": 0.0, "p_upper": 0.0, "p_tost": 0.0, "equivalent": True}

    diffs = a - b
    mean_diff = float(np.mean(diffs))
    sd_diff = float(np.std(diffs, ddof=1))

    if sd_diff == 0:
        # No variance in the paired difference: equivalence is exact
        # (mean_diff within margin) or exactly violated, deterministically.
        equivalent = abs(mean_diff) < margin
        p = 0.0 if equivalent else 1.0
        return {"n": n, "margin": margin, "mean_diff": mean_diff,
                "p_lower": p, "p_upper": p, "p_tost": p, "equivalent": equivalent}

    se = sd_diff / np.sqrt(n)
    df = n - 1
    # H0: mean_diff <= -margin (too far below zero) vs H1: mean_diff > -margin
    t_lower = (mean_diff + margin) / se
    p_lower = float(stats.t.sf(t_lower, df))
    # H0: mean_diff >= margin (too far above zero) vs H1: mean_diff < margin
    t_upper = (mean_diff - margin) / se
    p_upper = float(stats.t.cdf(t_upper, df))
    p_tost = max(p_lower, p_upper)

    return {
        "n": n, "margin": margin, "mean_diff": mean_diff,
        "p_lower": p_lower, "p_upper": p_upper, "p_tost": p_tost,
        "equivalent": p_tost < alpha,
    }


def lra_vs_tactiles_tost(reduced_df, metric, margin_sd, alpha=0.05):
    """Section 5.9: TOST equivalence between lra and tactiles for `metric`,
    on the same complete-case participants as lra_vs_tactiles() (Section
    5.4), so the two sections are directly comparable — 5.4 asks "is there
    a detectable difference," 5.9 asks "can we rule out a difference of at
    least margin_sd standard deviations."

    Args:
        reduced_df: Output of reduce_to_participant_condition_object().
        metric: Column name to test.
        margin_sd: Equivalence margin, see tost_equivalence().
        alpha: Per-side significance level, see tost_equivalence().

    Returns:
        Dict keyed by object ('fragile'/'deformable'); each value is None
        (too few complete cases) or tost_equivalence()'s result dict.
    """
    results = {}
    for obj in OBJECTS:
        sub = reduced_df[reduced_df["object"] == obj]
        pivot = sub.pivot(index="participant", columns="condition", values=metric)
        complete = pivot.dropna(subset=["lra", "tactiles"], how="any")
        n_dropped = len(pivot) - len(complete)
        if n_dropped > 0:
            print(f"NOTE: {metric}/{obj} (TOST lra vs tactiles): dropping {n_dropped} "
                  f"participant(s) missing lra or tactiles.")

        if len(complete) < 3:
            print(f"WARNING: {metric}/{obj} (TOST lra vs tactiles): only {len(complete)} "
                  f"complete participant(s) — skipping.")
            results[obj] = None
            continue

        results[obj] = tost_equivalence(
            complete["lra"].to_numpy(), complete["tactiles"].to_numpy(), margin_sd, alpha)
    return results


def write_tost_equivalence_report(all_results, margin_sd, alpha, out_dir):
    """Writes a CSV summary table for Section 5.9, one row per metric x object.

    Args:
        all_results: {metric: lra_vs_tactiles_tost() result}, one entry per
            tested metric.
        margin_sd: The equivalence margin used (echoed into every row so the
            table is self-describing if read out of context).
        alpha: The per-side significance level used.
        out_dir: Directory to write section_5_9_tost_equivalence.csv into.
    """
    path = os.path.join(out_dir, "section_5_9_tost_equivalence.csv")
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["metric", "object", "n", "margin_sd", "alpha", "margin_raw",
                          "mean_diff_lra_minus_tactiles", "p_lower", "p_upper", "p_tost",
                          "equivalent"])
        for metric, by_object in all_results.items():
            for obj, res in by_object.items():
                if res is None:
                    writer.writerow([metric, obj, "", margin_sd, alpha, "", "", "", "", "", ""])
                    continue
                writer.writerow([
                    metric, obj, res["n"], margin_sd, alpha,
                    f"{res['margin']:.4f}", f"{res['mean_diff']:.4f}",
                    f"{res['p_lower']:.4f}", f"{res['p_upper']:.4f}", f"{res['p_tost']:.4f}",
                    res["equivalent"],
                ])
    print(f"Wrote {path}")


def write_fragile_breakage_summary(trial_df, out_dir):
    """Section 5.7 (descriptive): raw success/break counts per condition,
    over all fragile trials with a recorded outcome (untagged trials, which
    predate the y/n prompt or skipped it, are excluded and reported)."""
    path = os.path.join(out_dir, "section_5_7_fragile_breakage.csv")
    fragile = trial_df[trial_df["object"] == "fragile"]
    tagged = fragile[fragile["fragile_survived"].notna()]
    n_untagged = len(fragile) - len(tagged)
    if n_untagged > 0:
        print(f"NOTE: {n_untagged} fragile trial(s) have no recorded success/break "
              f"outcome — excluded from section_5_7_fragile_breakage.csv.")
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["condition", "n_trials", "n_success", "n_break", "success_rate"])
        for condition in CONDITIONS:
            sub = tagged[tagged["condition"] == condition]
            if len(sub) == 0:
                writer.writerow([condition, 0, 0, 0, ""])
                continue
            n_success = int(sub["fragile_survived"].sum())
            n_total = len(sub)
            writer.writerow([condition, n_total, n_success, n_total - n_success,
                              f"{n_success / n_total:.4f}"])
    print(f"Wrote {path}")

def mcnemar_fragile_survival(reduced_df):
    """Section 5.4 (fragile only): exact McNemar test on fragile_survived —
    the statistically correct test for paired binary outcomes across two
    conditions (Wilcoxon, used for the other four Section 5.1 metrics, is
    not appropriate for a 0/1 outcome).

    Requires each participant to have an UNAMBIGUOUS binary outcome per
    condition (both fragile reps agreeing on success or break). Participants
    whose two reps disagree (median 0.5) are dropped, with a note, since the
    test needs one classification per subject per condition.

    Args:
        reduced_df: Output of reduce_to_participant_condition_object().

    Returns:
        None if too few usable participants, else a dict with n, b, c
        (discordant pair counts) and p (exact two-sided binomial).
    """
    sub = reduced_df[reduced_df["object"] == "fragile"]
    pivot = sub.pivot(index="participant", columns="condition", values="fragile_survived")
    complete = pivot.dropna(subset=["lra", "tactiles"], how="any")

    n_dropped = len(pivot) - len(complete)
    if n_dropped > 0:
        print(f"NOTE: fragile_survived McNemar: dropping {n_dropped} participant(s) "
              f"missing lra or tactiles.")

    ambiguous = complete[(complete["lra"] == 0.5) | (complete["tactiles"] == 0.5)]
    if len(ambiguous) > 0:
        print(f"NOTE: fragile_survived McNemar: dropping {len(ambiguous)} participant(s) "
              f"whose two fragile reps disagreed (median 0.5) under lra or tactiles — "
              f"McNemar needs one binary classification per participant per condition.")
    complete = complete.drop(ambiguous.index)

    if len(complete) < 4:
        print(f"WARNING: fragile_survived McNemar: only {len(complete)} usable "
              f"participant(s) — too few for a meaningful test. Skipping.")
        return None

    lra = complete["lra"].to_numpy()
    tactiles = complete["tactiles"].to_numpy()

    # Discordant pairs: b = survived under lra but not tactiles, c = reverse.
    b = int(np.sum((lra == 1.0) & (tactiles == 0.0)))
    c = int(np.sum((lra == 0.0) & (tactiles == 1.0)))

    if b + c == 0:
        print("NOTE: fragile_survived McNemar: no discordant pairs (lra and tactiles "
              "always agree) — p is undefined, reporting p=1.0.")
        return {"n": len(complete), "b": b, "c": c, "p": 1.0}

    result = stats.binomtest(min(b, c), b + c, p=0.5)
    return {"n": len(complete), "b": b, "c": c, "p": float(result.pvalue)}

def write_fragile_mcnemar_report(result, out_dir):
    """Writes the McNemar result for fragile_survived (lra vs tactiles) to
    section_5_4_fragile_mcnemar.csv — a separate file from
    section_5_4_lra_vs_tactiles.csv since the test/statistic differ."""
    path = os.path.join(out_dir, "section_5_4_fragile_mcnemar.csv")
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["n", "b_lra_survived_only", "c_tactiles_survived_only", "mcnemar_p"])
        if result is None:
            writer.writerow(["", "", "", ""])
        else:
            writer.writerow([result["n"], result["b"], result["c"], f"{result['p']:.4f}"])
    print(f"Wrote {path}")


# ---------------------------------------------------------------------------
# Section 5.7 (inferential) — Fragile survival across ALL THREE conditions
#
# section_5_7_fragile_breakage.csv (above) reports raw counts only, and the
# Section 5.4 McNemar tests lra vs tactiles alone. The headline contrast of
# the study — vision-only vs haptic breakage — had no significance test, so
# this block adds one, at two levels:
#
#   PRIMARY (rate level): each participant's fragile-survival PROPORTION per
#   condition (successes / fragile trials), then Friedman across the three
#   conditions + pairwise Wilcoxon signed-rank with Holm. This keeps the
#   graded information (e.g. 2/5 vs 4/5 survived) that carries the effect,
#   and handles the unequal per-participant trial counts (P05/P07/P08/P10
#   ran many more fragile trials than the rest).
#
#   CONSERVATIVE (binary level): collapse each participant/condition to a
#   single survive/break majority vote, then Cochran's Q + pairwise McNemar
#   with Holm. This is the all-or-nothing view; it is much less powerful
#   because most participants survive the majority of trials in EVERY
#   condition, so the majority-vote is near-constant and the vision effect —
#   which lives in the proportion, not the majority — largely washes out.
#   Reported alongside the rate test as a robustness check, not the headline.
# ---------------------------------------------------------------------------

def _fragile_survival_rate(trial_df, conditions):
    """Participant x condition fragile-survival PROPORTION (mean of per-trial
    0/1 outcomes), over participants with at least one outcome-tagged fragile
    trial in every one of `conditions`. Returns (pivot, n_incomplete)."""
    fragile = trial_df[(trial_df["object"] == "fragile")
                       & (trial_df["fragile_survived"].notna())]
    pivot = (fragile.groupby(["participant", "condition"])["fragile_survived"]
             .mean().unstack())
    # Keep only conditions we test, then require all present per participant.
    for c in conditions:
        if c not in pivot.columns:
            pivot[c] = np.nan
    complete = pivot.dropna(subset=conditions, how="any")
    return complete[conditions], len(pivot) - len(complete)


def _fragile_survival_binary(reduced_df, conditions):
    """Participant x condition binary fragile-survival matrix, restricted to
    participants with an UNAMBIGUOUS (non-0.5) majority-vote outcome in every
    one of `conditions`.

    fragile_survived in reduced_df is the median of a participant's per-trial
    0/1 breakage outcomes — i.e. a majority vote (1 = most fragile reps
    survived, 0 = most broke). An even split lands on 0.5 and is dropped here,
    since both Cochran's Q and McNemar need one binary classification per
    participant per condition.

    Returns (pivot, n_incomplete, n_ambiguous): the complete/unambiguous pivot
    plus counts of the participants removed for each reason.
    """
    sub = reduced_df[reduced_df["object"] == "fragile"]
    pivot = sub.pivot(index="participant", columns="condition", values="fragile_survived")
    complete = pivot.dropna(subset=conditions, how="any")
    n_incomplete = len(pivot) - len(complete)

    amb = np.zeros(len(complete), dtype=bool)
    for c in conditions:
        amb |= (complete[c] == 0.5).to_numpy()
    n_ambiguous = int(amb.sum())
    complete = complete.loc[~amb]
    return complete, n_incomplete, n_ambiguous


def _cochran_q(binary_matrix):
    """Cochran's Q for N x k paired binary data (0/1).

    Q = (k-1)[k * sum(C_j^2) - (sum C_j)^2] / [k * sum(R_i) - sum(R_i^2)]
    where C_j is each condition's column total and R_i each participant's row
    total; Q ~ chi-square with k-1 df. Participants who are constant across all
    conditions (all survive or all break) contribute 0 to the denominator and
    so drop out naturally, as they should. Returns (Q, p, dof).
    """
    X = np.asarray(binary_matrix, dtype=float)
    _, k = X.shape
    col = X.sum(axis=0)
    row = X.sum(axis=1)
    denom = k * np.sum(row) - np.sum(row ** 2)
    if denom == 0:
        # Every participant is constant across conditions — no discordance,
        # Q is undefined. Report Q=0, p=1 (no evidence of a difference).
        return 0.0, 1.0, k - 1
    q = (k - 1) * (k * np.sum(col ** 2) - np.sum(col) ** 2) / denom
    dof = k - 1
    return float(q), float(stats.chi2.sf(q, dof)), dof


def _mcnemar_binary(a, b):
    """Exact (binomial) McNemar for two paired binary vectors.
    Returns (b_count, c_count, p) where b_count = a-survived-only,
    c_count = b-survived-only. p=1.0 when there are no discordant pairs."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    b_only = int(np.sum((a == 1.0) & (b == 0.0)))
    c_only = int(np.sum((a == 0.0) & (b == 1.0)))
    if b_only + c_only == 0:
        return b_only, c_only, 1.0
    p = stats.binomtest(min(b_only, c_only), b_only + c_only, p=0.5).pvalue
    return b_only, c_only, float(p)


PAIRS = [("visual_only", "lra"), ("visual_only", "tactiles"), ("lra", "tactiles")]


def _rate_level_survival(trial_df):
    """PRIMARY test: Friedman across conditions + pairwise Wilcoxon (Holm) on
    per-participant fragile-survival proportions. Returns None if too few
    complete participants, else a dict with n, friedman_stat/friedman_p,
    medians, and pairwise [(a, b, w_stat, raw_p, holm_p), ...]."""
    rates, n_incomplete = _fragile_survival_rate(trial_df, CONDITIONS)
    if n_incomplete > 0:
        print(f"NOTE: fragile survival (rate, 3-way): dropping {n_incomplete} "
              f"participant(s) without outcome-tagged fragile trials in every condition.")
    if len(rates) < 3:
        print(f"WARNING: fragile survival (rate): only {len(rates)} complete "
              f"participant(s) — too few for Friedman/Wilcoxon. Skipping.")
        return None

    cols = [rates[c].to_numpy() for c in CONDITIONS]
    fr_stat, fr_p = stats.friedmanchisquare(*cols)

    raw, stats_ = [], []
    for a_name, b_name in PAIRS:
        a, b = rates[a_name].to_numpy(), rates[b_name].to_numpy()
        if np.all(a - b == 0):
            print(f"WARNING: fragile survival rate: {a_name} vs {b_name} has zero "
                  f"variance in paired differences — Wilcoxon undefined, skipping pair.")
            stats_.append(None)
            raw.append(1.0)
            continue
        w_stat, w_p = stats.wilcoxon(a, b)
        stats_.append(w_stat)
        raw.append(w_p)
    holm = holm_bonferroni(raw)
    pairwise = [(a, b, stats_[i], raw[i], holm[i]) for i, (a, b) in enumerate(PAIRS)]

    return {
        "n": len(rates),
        "friedman_stat": float(fr_stat), "friedman_p": float(fr_p),
        "medians": {c: float(np.median(rates[c])) for c in CONDITIONS},
        "pairwise": pairwise,
    }


def _binary_level_survival(reduced_df):
    """CONSERVATIVE complement: Cochran's Q + pairwise McNemar (Holm) on the
    per-participant majority-vote survive/break outcome. Returns None if too
    few usable participants, else a dict with n, cochran_q/cochran_p/
    cochran_dof, and pairwise [(a, b, a_only, b_only, raw_p, holm_p), ...]."""
    complete, n_incomplete, n_ambiguous = _fragile_survival_binary(reduced_df, CONDITIONS)
    if n_incomplete > 0:
        print(f"NOTE: fragile survival (binary, 3-way): dropping {n_incomplete} "
              f"participant(s) missing at least one condition.")
    if n_ambiguous > 0:
        print(f"NOTE: fragile survival (binary, 3-way): dropping {n_ambiguous} "
              f"participant(s) whose fragile reps split evenly (median 0.5) somewhere.")
    if len(complete) < 4:
        print(f"WARNING: fragile survival (binary): only {len(complete)} usable "
              f"participant(s) — too few for a meaningful test. Skipping.")
        return None

    q, q_p, dof = _cochran_q(complete[CONDITIONS].to_numpy())
    raw, counts = [], []
    for a_name, b_name in PAIRS:
        a_only, b_only, p = _mcnemar_binary(complete[a_name], complete[b_name])
        counts.append((a_only, b_only))
        raw.append(p)
    holm = holm_bonferroni(raw)
    pairwise = [(a, b, counts[i][0], counts[i][1], raw[i], holm[i])
                for i, (a, b) in enumerate(PAIRS)]
    return {"n": len(complete), "cochran_q": q, "cochran_p": q_p,
            "cochran_dof": dof, "pairwise": pairwise}


def fragile_survival_across_conditions(trial_df, reduced_df):
    """Section 5.7 (inferential): test fragile survival across all three
    conditions — the study's headline contrast, which the count-only
    breakage table and the lra-vs-tactiles McNemar never tested. Runs the
    rate-level test (primary) and the binary majority-vote test
    (conservative). Returns {"rate": ..., "binary": ...}."""
    return {"rate": _rate_level_survival(trial_df),
            "binary": _binary_level_survival(reduced_df)}


def write_fragile_survival_tests_report(result, out_dir):
    """Writes the Section 5.7 inferential breakage tests to
    section_5_7_fragile_survival_tests.csv, one row per comparison, with a
    `level` column separating the rate-level (primary) and binary-level
    (conservative) analyses so both can be read from one table."""
    path = os.path.join(out_dir, "section_5_7_fragile_survival_tests.csv")
    rate, binary = result["rate"], result["binary"]
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["level", "n", "omnibus_test", "omnibus_stat", "omnibus_dof",
                          "omnibus_p", "comparison", "pairwise_test",
                          "a_survived_only", "b_survived_only", "pairwise_p", "holm_p"])

        if rate is not None:
            med = ";".join(f"{c}={rate['medians'][c]:.3f}" for c in CONDITIONS)
            for a_name, b_name, w_stat, raw_p, holm_p in rate["pairwise"]:
                writer.writerow([
                    "rate", rate["n"], "friedman", f"{rate['friedman_stat']:.4f}", 2,
                    f"{rate['friedman_p']:.4f}", f"{a_name}_vs_{b_name}", "wilcoxon",
                    "", "",
                    f"{raw_p:.4f}", f"{holm_p:.4f}",
                ])
            writer.writerow(["rate_medians", rate["n"], "", "", "", "", med,
                             "", "", "", "", ""])
        else:
            writer.writerow(["rate", "", "friedman", "", "", "", "", "", "", "", "", ""])

        if binary is not None:
            for a_name, b_name, a_only, b_only, raw_p, holm_p in binary["pairwise"]:
                writer.writerow([
                    "binary", binary["n"], "cochran_q", f"{binary['cochran_q']:.4f}",
                    binary["cochran_dof"], f"{binary['cochran_p']:.4f}",
                    f"{a_name}_vs_{b_name}", "mcnemar", a_only, b_only,
                    f"{raw_p:.4f}", f"{holm_p:.4f}",
                ])
        else:
            writer.writerow(["binary", "", "cochran_q", "", "", "", "", "", "", "", "", ""])
    print(f"Wrote {path}")


# ---------------------------------------------------------------------------
# Section 5.5 — Time-Series Visualisation
# ---------------------------------------------------------------------------

def plot_representative_trials(trials_dir, out_dir, collapse, n_per_condition=2):
    """Section 5.5: for a few representative trials per condition, plot the
    combined depth and force series against t on a shared time axis.

    'Representative' here just means the first n_per_condition trials
    found per condition in directory listing order — this is a
    placeholder selection rule. When writing the thesis, replace this
    with a deliberate selection (e.g. the trial closest to that
    condition's median peak_force_proxy) and say so in the text.

    Args:
        trials_dir: Directory to scan for trial CSVs.
        out_dir: Directory to write the per-condition figures into.
        collapse: Sensor-combination mode for the force/depth series.
        n_per_condition: How many trials to plot per condition.
    """
    paths_by_condition = defaultdict(list)
    for path in _find_trial_csvs(trials_dir):
        fname = os.path.basename(path)
        m = FNAME_RE.match(fname)
        if m:
            paths_by_condition[m.group("condition")].append(path)

    for condition in CONDITIONS:
        paths = paths_by_condition.get(condition, [])[:n_per_condition]
        if not paths:
            print(f"NOTE: no trials found for condition '{condition}', skipping its time-series plot.")
            continue

        fig, axes = plt.subplots(len(paths), 1, figsize=(8, 3 * len(paths)), squeeze=False)
        for i, path in enumerate(paths):
            df = pd.read_csv(path)
            force, depth, force_label = _combined_series(df, collapse)
            ax1 = axes[i, 0]
            ax2 = ax1.twinx()
            ax1.plot(df["t"], depth, color="tab:blue", label="max_depth_mm (max L/R)")
            ax1.set_xlabel("t (s)")
            ax1.set_ylabel("max_depth_mm (max L/R)", color="tab:blue")
            if np.isfinite(force).any():
                ax2.plot(df["t"], force, color="tab:red", label=force_label)
                ax2.set_ylabel(force_label, color="tab:red")
            else:
                ax2.set_ylabel(f"{force_label} — n/a", color="tab:red")
            ax1.set_title(os.path.basename(path))
        fig.suptitle(f"Representative trials — {condition}")
        fig.tight_layout()
        out_path = os.path.join(out_dir, f"section_5_5_timeseries_{condition}.png")
        fig.savefig(out_path, dpi=150)
        plt.close(fig)
        print(f"Wrote {out_path}")


# ---------------------------------------------------------------------------
# Section 5.6 — Qualitative Survey Results
# ---------------------------------------------------------------------------

LIKERT_ITEMS = [
    "item1_confident_force", "item2_detect_contact", "item3_detect_risk",
    "item4_mental_effort", "item5_in_control",
]
LIKERT_ACTUATOR_ITEMS = ["item6_responsive", "item7_natural"]


def analyze_likert(likert_csv_path, out_dir):
    """Section 5.6: per-item median/IQR per condition, Friedman across
    conditions for the 5 core items, and direct lra-vs-tactiles Wilcoxon
    for the 2 actuator-specific items.

    Args:
        likert_csv_path: Path to the Likert questionnaire CSV. If missing,
            prints a note and returns without writing anything.
        out_dir: Directory to write the three Section 5.6 CSVs into.
    """
    if not os.path.exists(likert_csv_path):
        print(f"NOTE: Likert CSV not found at {likert_csv_path} — skipping Section 5.6.")
        return

    df = pd.read_csv(likert_csv_path)

    summary_path = os.path.join(out_dir, "section_5_6_likert_summary.csv")
    with open(summary_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["item", "condition", "n", "median", "iqr_low", "iqr_high"])

        for item in LIKERT_ITEMS + LIKERT_ACTUATOR_ITEMS:
            for condition in CONDITIONS:
                vals = pd.to_numeric(
                    df[df["condition"] == condition][item], errors="coerce").dropna()
                if len(vals) == 0:
                    continue
                writer.writerow([item, condition, len(vals),
                                  f"{vals.median():.2f}",
                                  f"{np.percentile(vals, 25):.2f}",
                                  f"{np.percentile(vals, 75):.2f}"])
    print(f"Wrote {summary_path}")

    # Friedman across conditions for core items (complete cases only)
    friedman_path = os.path.join(out_dir, "section_5_6_likert_friedman.csv")
    with open(friedman_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["item", "n", "friedman_stat", "friedman_p"])
        for item in LIKERT_ITEMS:
            pivot = df.pivot(index="participant_id", columns="condition", values=item)
            pivot = pivot.apply(pd.to_numeric, errors="coerce")
            complete = pivot.dropna(subset=CONDITIONS, how="any")
            if len(complete) < 3:
                print(f"WARNING: Likert item '{item}': only {len(complete)} complete "
                      f"participant(s) — skipping Friedman test.")
                writer.writerow([item, len(complete), "", ""])
                continue
            stat, p = stats.friedmanchisquare(
                complete["visual_only"], complete["lra"], complete["tactiles"])
            writer.writerow([item, len(complete), f"{stat:.4f}", f"{p:.4f}"])
    print(f"Wrote {friedman_path}")

    # LRA vs TacTiles direct comparison for actuator-specific items
    actuator_path = os.path.join(out_dir, "section_5_6_likert_lra_vs_tactiles.csv")
    with open(actuator_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["item", "n", "wilcoxon_stat", "wilcoxon_p"])
        for item in LIKERT_ACTUATOR_ITEMS:
            pivot = df.pivot(index="participant_id", columns="condition", values=item)
            pivot = pivot.apply(pd.to_numeric, errors="coerce")
            complete = pivot.dropna(subset=["lra", "tactiles"], how="any")
            if len(complete) < 3:
                print(f"WARNING: Likert item '{item}': only {len(complete)} complete "
                      f"participant(s) — skipping Wilcoxon test.")
                writer.writerow([item, len(complete), "", ""])
                continue
            diffs = complete["lra"] - complete["tactiles"]
            if (diffs == 0).all():
                print(f"WARNING: Likert item '{item}': zero variance, Wilcoxon undefined.")
                writer.writerow([item, len(complete), "", ""])
                continue
            stat, p = stats.wilcoxon(complete["lra"], complete["tactiles"])
            writer.writerow([item, len(complete), f"{stat:.4f}", f"{p:.4f}"])
    print(f"Wrote {actuator_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    """Parses args and runs the full Chapter 5 pipeline: loads and reduces
    trial data (5.1), cross-condition and LRA-vs-TacTiles comparisons
    (5.3/5.4), representative time-series figures (5.5), and — if
    --likert-csv is given — the survey analysis (5.6)."""
    parser = argparse.ArgumentParser(description="Run thesis Chapter 5 analysis on real trial data.")
    parser.add_argument("--trials-dir", required=True, help="Directory of trial CSVs from experiment.py.")
    parser.add_argument("--likert-csv", default=None, help="Path to Likert questionnaire CSV (Section 4.5.2 schema). Optional.")
    parser.add_argument("--out", required=True, help="Output directory for tables and figures.")
    parser.add_argument("--contact-threshold-mm", type=float, default=0.05,
                         help="Depth threshold for 'first contact' (Section 5.1). "
                              "Default 0.05mm — adjust based on your sensor's measured "
                              "no-contact noise floor (Section 3.2.1) before real analysis.")
    parser.add_argument("--collapse", choices=["sum_n", "max"], default="sum_n",
                         help="How to combine the left/right sensors into each metric. "
                              "sum_n: grip force = left_force_N + right_force_N (calibrated "
                              "Newtons) — the headline once calibrated. max: max of the raw "
                              "force proxies (uncalibrated) — works pre-calibration. Depth is "
                              "max(L,R) either way. Run both and confirm findings agree.")
    parser.add_argument("--equiv-margin-sd", type=float, default=0.5,
                         help="Section 5.9 TOST equivalence margin, as a multiple of each "
                              "metric's pooled SD (effect-size-scaled). Default 0.5 (a "
                              "'medium' Cohen's d) — this is a judgment call about the "
                              "smallest difference you'd consider practically meaningful; "
                              "state and justify your choice in the thesis text.")
    parser.add_argument("--equiv-alpha", type=float, default=0.05,
                         help="Per-side significance level for the Section 5.9 TOST test "
                              "(default 0.05, the conventional two-one-sided-tests level).")
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)

    print(f"Loading trials from {args.trials_dir} (collapse={args.collapse}) ...")
    trial_df = load_all_trials(args.trials_dir, args.contact_threshold_mm, args.collapse)
    trial_df.to_csv(os.path.join(args.out, "section_5_1_per_trial_metrics.csv"), index=False)
    print(f"Wrote {os.path.join(args.out, 'section_5_1_per_trial_metrics.csv')} "
          f"({len(trial_df)} trials)")
    
    write_fragile_breakage_summary(trial_df, args.out)

    reduced_df = reduce_to_participant_condition_object(trial_df)
    reduced_df.to_csv(os.path.join(args.out, "section_5_1_reduced_metrics.csv"), index=False)
    print(f"Wrote {os.path.join(args.out, 'section_5_1_reduced_metrics.csv')} "
          f"({len(reduced_df)} participant x condition x object rows)")

    print("\nRunning Section 5.3 (cross-condition Friedman + Wilcoxon)...")
    metrics = ["peak_force_proxy", "peak_depth_mm", "time_to_first_contact_s", "force_overshoot_proxy"]
    trajectory_metrics = ["approach_rate_mm_s", "n_force_reversals_post_plateau",
                           "time_above_90pct_peak_s"]
    all_metrics = metrics + trajectory_metrics
    cross_condition_results = {}
    for metric in all_metrics:
        cross_condition_results[metric] = friedman_and_pairwise(reduced_df, metric, args.out)
    write_cross_condition_report(cross_condition_results, args.out)

    print("\nRunning Section 5.4 (LRA vs TacTiles direct comparison)...")
    lra_tactiles_results = {}
    for metric in all_metrics:
        lra_tactiles_results[metric] = lra_vs_tactiles(reduced_df, metric)
    write_lra_vs_tactiles_report(lra_tactiles_results, args.out)

    print("\nRunning Section 5.4 (fragile breakage: McNemar lra vs tactiles)...")
    mcnemar_result = mcnemar_fragile_survival(reduced_df)
    write_fragile_mcnemar_report(mcnemar_result, args.out)

    print(f"\nRunning Section 5.9 (TOST equivalence, lra vs tactiles, "
          f"margin={args.equiv_margin_sd} pooled SD, alpha={args.equiv_alpha})...")
    tost_results = {}
    for metric in all_metrics:
        tost_results[metric] = lra_vs_tactiles_tost(
            reduced_df, metric, args.equiv_margin_sd, args.equiv_alpha)
    write_tost_equivalence_report(tost_results, args.equiv_margin_sd, args.equiv_alpha, args.out)

    print("\nRunning Section 5.7 (fragile survival across conditions: rate-level "
          "Friedman/Wilcoxon + binary Cochran's Q/McNemar, incl. vision vs haptic)...")
    survival_tests = fragile_survival_across_conditions(trial_df, reduced_df)
    write_fragile_survival_tests_report(survival_tests, args.out)

    print("\nGenerating Section 5.5 time-series figures...")
    plot_representative_trials(args.trials_dir, args.out, args.collapse)

    if args.likert_csv:
        print("\nRunning Section 5.6 (Likert survey analysis)...")
        analyze_likert(args.likert_csv, args.out)
    else:
        print("\nNOTE: --likert-csv not provided, skipping Section 5.6.")

    print(f"\nAll Section 5.1/5.3/5.4/5.5/5.6 outputs written to {args.out}/ (collapse={args.collapse})")
    print("ROBUSTNESS: re-run with the other --collapse mode into a separate --out and")
    print("confirm the significant findings hold under both (sum_n and max are the only")
    print("two collapses that can reorder trials) — report that in Section 5.1.")
    print("Section 5.2 (sensor-to-actuator latency) requires a separate bench")
    print("measurement and is NOT computed by this script — see thesis Section 5.2.")


if __name__ == "__main__":
    main()