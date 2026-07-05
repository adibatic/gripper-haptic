"""
analysis.py — Implements thesis Chapter 5 (Results and Analysis)
exactly as specified: Sections 5.1, 5.3, 5.4, 5.5, 5.6.

Reads trial CSVs matching the filename schema produced by experiment.py:
    <participant>_<condition>_<object>_trial<N>.csv
and a Likert questionnaire CSV matching Section 4.5.2's item schema, then
computes and writes out every table/figure Chapter 5 calls for.

NOTE ON SECTION 5.2 (Sensor-to-Actuator Latency): this script does NOT
compute end-to-end latency, because the trial CSV schema (one row per
~30Hz control tick) does not capture true sensor-frame-to-actuator-state
latency. Section 5.2 explicitly requires a separate bench measurement;
see thesis text for what that measurement needs to capture.

Usage:
    python analysis.py --trials-dir data/experiment_logs \
        --likert-csv data/experiment_logs/likert_responses.csv \
        --out results

    # Quick pipeline test against fabricated data (see
    # generate_synthetic_test_data.py docstring — NEVER use this output
    # in the actual thesis):
    python generate_synthetic_test_data.py --out synthetic_test_data
    python analysis.py --trials-dir synthetic_test_data/trials \
        --likert-csv synthetic_test_data/likert_responses.csv \
        --out synthetic_test_results
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
    r"(?P<object>fragile|deformable)_trial(?P<trial>\d+)\.csv$"
)


# ---------------------------------------------------------------------------
# Section 5.1 — Derived Per-Trial Metrics
# ---------------------------------------------------------------------------

def compute_trial_metrics(trial_csv_path, contact_threshold_mm):
    """Compute the four per-trial metrics specified in thesis Section 5.1
    from one trial CSV (columns: t, gripper_pos_bit, force_proxy, force_N,
    max_depth_mm, haptic_intensity, motion_mode).

    force_proxy (the deformation-based grip-force proxy logged by
    experiment.py) is used in place of the old motor-current reading —
    the Robotiq's gCU register reads 0 mA on this unit regardless of
    contact, so current was never a usable signal.

    Returns a dict with peak_force_proxy, peak_depth_mm,
    time_to_first_contact_s, force_overshoot_proxy. Any metric that cannot
    be computed (e.g. no contact ever detected) is set to None rather than
    a fabricated value, and is excluded from aggregation with a printed
    warning.
    """
    df = pd.read_csv(trial_csv_path)
    if df.empty:
        return None

    t = df["t"].to_numpy()
    force = df["force_proxy"].to_numpy()
    depth = df["max_depth_mm"].to_numpy()

    peak_force = float(np.max(force))
    peak_depth = float(np.max(depth))

    # Time to first contact: first t where depth exceeds contact_threshold_mm
    contact_idx = np.where(depth > contact_threshold_mm)[0]
    time_to_first_contact = float(t[contact_idx[0]]) if len(contact_idx) > 0 else None

    # Force overshoot: rise in the force proxy after depth reaches its
    # plateau. Plateau is defined here as the first index at which depth
    # reaches within 5% of its own trial-maximum and stays at or above that
    # level for the remainder of the trial's first occurrence — i.e. the
    # first time depth hits (peak_depth * 0.95). This is an operational
    # definition chosen for this script; if you adopt a different
    # plateau definition when writing the thesis, update it here AND in
    # Section 5.1's text so the two stay consistent.
    overshoot = None
    if peak_depth > 0:
        plateau_idx = np.where(depth >= 0.95 * peak_depth)[0]
        if len(plateau_idx) > 0:
            plateau_first_idx = plateau_idx[0]
            force_at_plateau = force[plateau_first_idx]
            force_after_plateau_max = float(np.max(force[plateau_first_idx:]))
            overshoot = force_after_plateau_max - float(force_at_plateau)

    return {
        "peak_force_proxy": peak_force,
        "peak_depth_mm": peak_depth,
        "time_to_first_contact_s": time_to_first_contact,
        "force_overshoot_proxy": overshoot,
    }


def load_all_trials(trials_dir, contact_threshold_mm):
    """Scan trials_dir for files matching FNAME_RE, compute per-trial
    metrics for each, and return a long-format DataFrame with one row per
    trial: participant, condition, object, trial_num, + the four metrics.
    """
    rows = []
    paths = sorted(glob.glob(os.path.join(trials_dir, "*.csv")))
    unmatched = []

    for path in paths:
        fname = os.path.basename(path)
        m = FNAME_RE.match(fname)
        if not m:
            unmatched.append(fname)
            continue

        metrics = compute_trial_metrics(path, contact_threshold_mm)
        if metrics is None:
            print(f"WARNING: {fname} is empty or unreadable, skipped.")
            continue

        row = {
            "participant": m.group("participant"),
            "condition": m.group("condition"),
            "object": m.group("object"),
            "trial_num": int(m.group("trial")),
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

    return pd.DataFrame(rows)


def reduce_to_participant_condition_object(trial_df):
    """Section 5.1: reduce repeated trials (median across the two
    repetitions per participant/condition/object, per thesis Section 4.2)
    to one row per participant x condition x object.

    Rows with a None/NaN value for a given metric are excluded from the
    median for THAT metric only (e.g. a trial with no detected contact
    contributes to peak_force_proxy's median but not
    time_to_first_contact_s's), with a printed note if this occurs.
    """
    metric_cols = ["peak_force_proxy", "peak_depth_mm",
                   "time_to_first_contact_s", "force_overshoot_proxy"]

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
    """Holm-Bonferroni step-down correction. Returns corrected p-values
    in the SAME order as the input list (not sorted)."""
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
    metric x object x comparison."""
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
    reported separately from the 3-way comparison in Section 5.3."""
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
# Section 5.5 — Time-Series Visualisation
# ---------------------------------------------------------------------------

def plot_representative_trials(trials_dir, out_dir, n_per_condition=2):
    """Section 5.5: for a few representative trials per condition, plot
    max_depth_mm and force_proxy against t on a shared time axis.

    'Representative' here just means the first n_per_condition trials
    found per condition in directory listing order — this is a
    placeholder selection rule. When writing the thesis, replace this
    with a deliberate selection (e.g. the trial closest to that
    condition's median peak_force_proxy) and say so in the text.
    """
    paths_by_condition = defaultdict(list)
    for path in sorted(glob.glob(os.path.join(trials_dir, "*.csv"))):
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
            ax1 = axes[i, 0]
            ax2 = ax1.twinx()
            ax1.plot(df["t"], df["max_depth_mm"], color="tab:blue", label="max_depth_mm")
            ax2.plot(df["t"], df["force_proxy"], color="tab:red", label="force_proxy")
            ax1.set_xlabel("t (s)")
            ax1.set_ylabel("max_depth_mm", color="tab:blue")
            ax2.set_ylabel("force_proxy", color="tab:red")
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
    for the 2 actuator-specific items."""
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
    parser = argparse.ArgumentParser(description="Run thesis Chapter 5 analysis on real trial data.")
    parser.add_argument("--trials-dir", required=True, help="Directory of trial CSVs from experiment.py.")
    parser.add_argument("--likert-csv", default=None, help="Path to Likert questionnaire CSV (Section 4.5.2 schema). Optional.")
    parser.add_argument("--out", required=True, help="Output directory for tables and figures.")
    parser.add_argument("--contact-threshold-mm", type=float, default=0.05,
                         help="Depth threshold for 'first contact' (Section 5.1). "
                              "Default 0.05mm — adjust based on your sensor's measured "
                              "no-contact noise floor (Section 3.2.1) before real analysis.")
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)

    print(f"Loading trials from {args.trials_dir} ...")
    trial_df = load_all_trials(args.trials_dir, args.contact_threshold_mm)
    trial_df.to_csv(os.path.join(args.out, "section_5_1_per_trial_metrics.csv"), index=False)
    print(f"Wrote {os.path.join(args.out, 'section_5_1_per_trial_metrics.csv')} "
          f"({len(trial_df)} trials)")

    reduced_df = reduce_to_participant_condition_object(trial_df)
    reduced_df.to_csv(os.path.join(args.out, "section_5_1_reduced_metrics.csv"), index=False)
    print(f"Wrote {os.path.join(args.out, 'section_5_1_reduced_metrics.csv')} "
          f"({len(reduced_df)} participant x condition x object rows)")

    print("\nRunning Section 5.3 (cross-condition Friedman + Wilcoxon)...")
    metrics = ["peak_force_proxy", "peak_depth_mm", "time_to_first_contact_s", "force_overshoot_proxy"]
    cross_condition_results = {}
    for metric in metrics:
        cross_condition_results[metric] = friedman_and_pairwise(reduced_df, metric, args.out)
    write_cross_condition_report(cross_condition_results, args.out)

    print("\nRunning Section 5.4 (LRA vs TacTiles direct comparison)...")
    lra_tactiles_results = {}
    for metric in metrics:
        lra_tactiles_results[metric] = lra_vs_tactiles(reduced_df, metric)
    write_lra_vs_tactiles_report(lra_tactiles_results, args.out)

    print("\nGenerating Section 5.5 time-series figures...")
    plot_representative_trials(args.trials_dir, args.out)

    if args.likert_csv:
        print("\nRunning Section 5.6 (Likert survey analysis)...")
        analyze_likert(args.likert_csv, args.out)
    else:
        print("\nNOTE: --likert-csv not provided, skipping Section 5.6.")

    print(f"\nAll Section 5.1/5.3/5.4/5.5/5.6 outputs written to {args.out}/")
    print("Section 5.2 (sensor-to-actuator latency) requires a separate bench")
    print("measurement and is NOT computed by this script — see thesis Section 5.2.")


if __name__ == "__main__":
    main()