"""
Robustness analyses supporting Sections 5.2 and 5.4.

Two questions the main pipeline does not answer, both raised by the
pre-submission review in thesis/REVIEW.md:

Saturation rate. The post-plateau force rise in comparisons.py is measured
against each trial's own peak depth, not against the point where the haptic
display stops changing, so it does not isolate squeezing the display could
no longer discourage. The proportion of trials driven into the depth safety
cutoff does isolate it, is defined identically in every condition, and needs
no assumption about where the display saturates.

Practice adjustment. Conditions ran in the fixed order visual-only, LRA, EM,
so condition is confounded with time on task. Dropping early trials answers
that at the cost of a third of the data; carrying the within-block trial
index as a covariate answers it while keeping every trial, which is what
practice_adjusted_survival() does.
"""

import os
import csv

import numpy as np
import pandas as pd
from scipy import stats

from . import CONDITIONS

# Depth at which run/experiment.py blocks further closing (MAX_SAFE_DEPTH_MM).
# Recorded depth stops just under it, since the block engages on the sample
# that reaches it, so the test is a near-equality rather than >= 1.0.
SAFETY_CUTOFF_MM = 1.0
CUTOFF_TOLERANCE_MM = 0.02


def saturation_rate(trial_df, obj="fragile"):
    """Per-participant proportion of `obj` trials in which either sensor
    reached the depth safety cutoff, compared across the three conditions
    with Friedman plus Holm-corrected pairwise Wilcoxon.

    Args:
        trial_df: Long-format per-trial DataFrame from load_all_trials().
        obj: Object class to restrict to.

    Returns:
        None if fewer than three complete participants, else a dict with
        n, medians, friedman_stat, friedman_p, pairwise (list of
        (a, b, wilcoxon_p, holm_p)) and trial_rates (pooled per condition).
    """
    from .tests import holm_bonferroni

    sub = trial_df[(trial_df["object"] == obj) & trial_df["peak_depth_mm"].notna()].copy()
    if sub.empty:
        return None
    sub["at_cutoff"] = (
        sub["peak_depth_mm"] >= SAFETY_CUTOFF_MM - CUTOFF_TOLERANCE_MM).astype(float)

    pivot = sub.groupby(["participant", "condition"])["at_cutoff"].mean().unstack()
    complete = pivot.dropna(subset=CONDITIONS, how="any")
    if len(complete) < 3:
        print(f"WARNING: saturation_rate/{obj}: only {len(complete)} complete "
              f"participant(s) — skipping.")
        return None

    visual, lra, em = (complete[c].to_numpy() for c in CONDITIONS)
    stat, p = stats.friedmanchisquare(visual, lra, em)

    pairs = [("visual_only", "lra", visual, lra),
             ("visual_only", "em", visual, em),
             ("lra", "em", lra, em)]
    raw = []
    for _, _, a, b in pairs:
        raw.append(1.0 if np.all(a - b == 0) else stats.wilcoxon(a, b).pvalue)
    holm = holm_bonferroni(raw)

    return {
        "n": len(complete),
        "medians": {c: float(np.median(complete[c])) for c in CONDITIONS},
        "friedman_stat": float(stat),
        "friedman_p": float(p),
        "pairwise": [(a, b, float(rp), float(hp))
                     for (a, b, _, _), rp, hp in zip(pairs, raw, holm)],
        "trial_rates": {c: float(sub[sub["condition"] == c]["at_cutoff"].mean())
                        for c in CONDITIONS},
    }


def practice_adjusted_survival(trial_df):
    """Fragile-object survival modelled on condition and within-block trial
    index together, so the fixed condition order can be separated from time
    on task.

    A GEE logistic model clustered on participant, with an exchangeable
    working correlation: survival ~ condition + trial_num. Comparing each
    condition coefficient against the same model without the trial_num term
    shows how much of the condition effect practice accounts for.

    Returns None (with a printed note) if statsmodels is unavailable, so the
    rest of the pipeline still runs.

    Args:
        trial_df: Long-format per-trial DataFrame from load_all_trials().

    Returns:
        None, or a dict with n_trials, n_participants, and `adjusted` /
        `unadjusted` maps of condition -> (coefficient, p-value, odds ratio),
        plus the trial-index coefficient and p-value.
    """
    try:
        import statsmodels.api as sm
    except ImportError:
        print("NOTE: statsmodels is not installed, so the practice-adjusted "
              "survival model is skipped. Install it (see requirements.txt) to "
              "regenerate section_5_2_practice_adjusted.csv.")
        return None

    sub = trial_df[(trial_df["object"] == "fragile")
                   & trial_df["fragile_survived"].notna()].copy()
    if sub["participant"].nunique() < 3:
        print("WARNING: practice_adjusted_survival: too few participants — skipping.")
        return None

    sub["surv"] = sub["fragile_survived"].astype(int)
    sub["condition"] = pd.Categorical(sub["condition"], categories=CONDITIONS)

    def _fit(formula):
        return sm.GEE.from_formula(
            formula, groups="participant", data=sub,
            family=sm.families.Binomial(),
            cov_struct=sm.cov_struct.Exchangeable()).fit()

    adjusted = _fit("surv ~ C(condition) + trial_num")
    unadjusted = _fit("surv ~ C(condition)")

    def _terms(fit):
        out = {}
        for condition in CONDITIONS[1:]:
            key = f"C(condition)[T.{condition}]"
            out[condition] = (float(fit.params[key]), float(fit.pvalues[key]),
                              float(np.exp(fit.params[key])))
        return out

    return {
        "n_trials": len(sub),
        "n_participants": int(sub["participant"].nunique()),
        "adjusted": _terms(adjusted),
        "unadjusted": _terms(unadjusted),
        "trial_index": (float(adjusted.params["trial_num"]),
                        float(adjusted.pvalues["trial_num"])),
    }


def write_robustness_report(saturation, practice, out_dir):
    """Writes section_5_2_saturation_rate.csv and, when the model ran,
    section_5_2_practice_adjusted.csv.

    Args:
        saturation: saturation_rate() result, or None.
        practice: practice_adjusted_survival() result, or None.
        out_dir: Directory to write into.
    """
    if saturation is not None:
        path = os.path.join(out_dir, "section_5_2_saturation_rate.csv")
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["level", "n", "friedman_stat", "friedman_p",
                             "comparison", "wilcoxon_p", "holm_p"])
            for a, b, raw_p, holm_p in saturation["pairwise"]:
                writer.writerow([
                    "participant_rate", saturation["n"],
                    f"{saturation['friedman_stat']:.4f}",
                    f"{saturation['friedman_p']:.4f}",
                    f"{a}_vs_{b}", f"{raw_p:.4f}", f"{holm_p:.4f}"])
            writer.writerow(["medians", saturation["n"], "", "",
                             ";".join(f"{c}={saturation['medians'][c]:.3f}"
                                      for c in CONDITIONS), "", ""])
            writer.writerow(["pooled_trial_rate", saturation["n"], "", "",
                             ";".join(f"{c}={saturation['trial_rates'][c]:.3f}"
                                      for c in CONDITIONS), "", ""])
        print(f"Wrote {path}")

    if practice is not None:
        path = os.path.join(out_dir, "section_5_2_practice_adjusted.csv")
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["model", "term", "coefficient", "odds_ratio", "p"])
            for model in ("adjusted", "unadjusted"):
                for condition, (coef, p, odds) in practice[model].items():
                    writer.writerow([model, condition, f"{coef:.4f}",
                                     f"{odds:.4f}", f"{p:.4f}"])
            coef, p = practice["trial_index"]
            writer.writerow(["adjusted", "trial_index", f"{coef:.4f}",
                             f"{np.exp(coef):.4f}", f"{p:.4f}"])
        print(f"Wrote {path}")
