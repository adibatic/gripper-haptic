"""
Sections 5.2, 5.3 and 5.4 — condition comparisons on the per-trial metrics.

The cross-condition test compares all three conditions (Friedman, then pairwise
Wilcoxon with Holm correction) and feeds both the fragile results of 5.2 and the
deformable results of 5.3; 5.4 tests LRA against EM directly, and additionally
asks the separate question of whether those two are *equivalent* (TOST), which a
non-significant Wilcoxon result cannot answer on its own.
"""

import os
import csv

import numpy as np
from scipy import stats

from . import CONDITIONS, OBJECTS
from .tests import holm_bonferroni, tost_equivalence


def _complete_cases(reduced_df, metric, obj, conditions, label):
    """Participant x condition table of `metric` for one object class,
    restricted to participants present in every one of `conditions` (all
    these tests are paired, so incomplete participants can't be used).
    Prints how many were dropped. Returns the pivot."""
    sub = reduced_df[reduced_df["object"] == obj]
    pivot = sub.pivot(index="participant", columns="condition", values=metric)
    complete = pivot.dropna(subset=conditions, how="any")
    n_dropped = len(pivot) - len(complete)
    if n_dropped > 0:
        print(f"NOTE: {metric}/{obj} ({label}): dropping {n_dropped} participant(s) "
              f"missing at least one of {', '.join(conditions)}.")
    return complete


# ---------------------------------------------------------------------------
# Sections 5.2 and 5.3 — Cross-Condition Comparison (Friedman + Wilcoxon)
# ---------------------------------------------------------------------------

def friedman_and_pairwise(reduced_df, metric):
    """Sections 5.2 and 5.3: Friedman across the 3 conditions for `metric`, then
    pairwise Wilcoxon signed-rank with Holm correction.

    Pairwise results are reported unconditionally, with the Friedman result
    alongside; the thesis text should only INTERPRET them as confirmatory if
    the omnibus Friedman is itself significant, per standard practice.

    Args:
        reduced_df: Output of reduce_to_participant_condition_object().
        metric: Column name to test.

    Returns:
        Dict keyed by object ('fragile'/'deformable'), each value either
        {"n": ..., "friedman": None, "pairwise": None} (too few complete
        cases) or a dict with n/friedman_stat/friedman_p/pairwise/
        medians/iqrs.
    """
    results = {}

    for obj in OBJECTS:
        complete = _complete_cases(reduced_df, metric, obj, CONDITIONS, "Friedman")

        if len(complete) < 3:
            print(f"WARNING: {metric}/{obj}: only {len(complete)} complete participant(s) "
                  f"available — too few to run Friedman/Wilcoxon (need >= a handful for a "
                  f"meaningful test; scipy requires >= 3 just to run at all). Skipping.")
            results[obj] = {"n": len(complete), "friedman": None, "pairwise": None}
            continue

        visual = complete["visual_only"].to_numpy()
        lra = complete["lra"].to_numpy()
        em = complete["em"].to_numpy()

        friedman_stat, friedman_p = stats.friedmanchisquare(visual, lra, em)

        pairs = [("visual_only", "lra", visual, lra),
                 ("visual_only", "em", visual, em),
                 ("lra", "em", lra, em)]
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


def write_cross_condition_report(all_results, out_dir):
    """Writes a CSV summary table for Sections 5.2 and 5.3, one row per
    metric x object x comparison.

    Args:
        all_results: {metric: friedman_and_pairwise() result}, one entry
            per Section 5.1 metric.
        out_dir: Directory to write section_5_2_5_3_cross_condition.csv into.
    """
    path = os.path.join(out_dir, "section_5_2_5_3_cross_condition.csv")
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
# Section 5.4 — LRA Versus EM (direct paired comparison)
# ---------------------------------------------------------------------------

def lra_vs_em(reduced_df, metric):
    """Section 5.4: direct paired Wilcoxon between lra and em only,
    reported separately from the 3-way comparison in Sections 5.2 and 5.3.

    Args:
        reduced_df: Output of reduce_to_participant_condition_object().
        metric: Column name to test.

    Returns:
        Dict keyed by object ('fragile'/'deformable'); each value is
        None (too few complete cases), {"n", "stat": None, "p": None}
        (zero-variance differences), or a dict with n/stat/p/median_lra/
        median_em.
    """
    results = {}
    for obj in OBJECTS:
        complete = _complete_cases(reduced_df, metric, obj, ["lra", "em"], "LRA vs EM")

        if len(complete) < 3:
            print(f"WARNING: {metric}/{obj} (LRA vs EM): only {len(complete)} "
                  f"complete participant(s) — skipping.")
            results[obj] = None
            continue

        lra = complete["lra"].to_numpy()
        em = complete["em"].to_numpy()
        diffs = lra - em
        if np.all(diffs == 0):
            print(f"WARNING: {metric}/{obj}: LRA vs EM has zero variance, Wilcoxon undefined.")
            results[obj] = {"n": len(complete), "stat": None, "p": None}
            continue

        w_stat, w_p = stats.wilcoxon(lra, em)
        results[obj] = {
            "n": len(complete), "stat": float(w_stat), "p": float(w_p),
            "median_lra": float(np.median(lra)), "median_em": float(np.median(em)),
        }
    return results


def write_lra_vs_em_report(all_results, out_dir):
    """Writes a CSV summary table for Section 5.4, one row per metric x object.

    Args:
        all_results: {metric: lra_vs_em() result}, one entry per
            Section 5.1 metric.
        out_dir: Directory to write section_5_4_lra_vs_em.csv into.
    """
    path = os.path.join(out_dir, "section_5_4_lra_vs_em.csv")
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["metric", "object", "n", "wilcoxon_stat", "wilcoxon_p",
                          "median_lra", "median_em"])
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
                    f"{res.get('median_em', ''):.4f}" if res.get("median_em") is not None else "",
                ])
    print(f"Wrote {path}")


# ---------------------------------------------------------------------------
# Section 5.4 — TOST Equivalence (LRA vs EM)
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


def lra_vs_em_tost(reduced_df, metric, margin_sd, alpha=0.05):
    """Section 5.4: TOST equivalence between lra and em for `metric`,
    on the same complete-case participants as lra_vs_em() (Section
    5.4), so the two sections are directly comparable — 5.4 asks "is there
    a detectable difference," the TOST asks "can we rule out a difference of at
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
        complete = _complete_cases(reduced_df, metric, obj, ["lra", "em"], "TOST LRA vs EM")

        if len(complete) < 3:
            print(f"WARNING: {metric}/{obj} (TOST lra vs em): only {len(complete)} "
                  f"complete participant(s) — skipping.")
            results[obj] = None
            continue

        results[obj] = tost_equivalence(
            complete["lra"].to_numpy(), complete["em"].to_numpy(), margin_sd, alpha)
    return results


def write_tost_equivalence_report(all_results, margin_sd, alpha, out_dir):
    """Writes a CSV summary table for Section 5.4, one row per metric x object.

    Args:
        all_results: {metric: lra_vs_em_tost() result}, one entry per
            tested metric.
        margin_sd: The equivalence margin used (echoed into every row so the
            table is self-describing if read out of context).
        alpha: The per-side significance level used.
        out_dir: Directory to write section_5_4_tost_equivalence.csv into.
    """
    path = os.path.join(out_dir, "section_5_4_tost_equivalence.csv")
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["metric", "object", "n", "margin_sd", "alpha", "margin_raw",
                          "mean_diff_lra_minus_em", "p_lower", "p_upper", "p_tost",
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
