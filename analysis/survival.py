"""
Sections 5.4 and 5.7 — fragile-object survival.

Survival is a paired binary outcome, so it needs different machinery from the
continuous metrics in comparisons.py: descriptive break counts, McNemar for a
single pair, and — across all three conditions — both a rate-level
Friedman/Wilcoxon and a stricter binary Cochran's Q/McNemar.
"""

import os
import csv

import numpy as np
from scipy import stats

from . import CONDITIONS
from .tests import holm_bonferroni, cochran_q, mcnemar_binary


def write_fragile_breakage_summary(trial_df, out_dir):
    """Section 5.2 (descriptive): raw success/break counts per condition,
    over all fragile trials with a recorded outcome (untagged trials, which
    predate the y/n prompt or skipped it, are excluded and reported)."""
    path = os.path.join(out_dir, "section_5_2_fragile_breakage.csv")
    fragile = trial_df[trial_df["object"] == "fragile"]
    tagged = fragile[fragile["fragile_survived"].notna()]
    n_untagged = len(fragile) - len(tagged)
    if n_untagged > 0:
        print(f"NOTE: {n_untagged} fragile trial(s) have no recorded success/break "
              f"outcome — excluded from section_5_2_fragile_breakage.csv.")
    breakage = {}
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
            breakage[condition] = (n_success / n_total, n_total)
    print(f"Wrote {path}")
    return breakage


def mcnemar_fragile_survival(reduced_df):
    """Section 5.2 (fragile only): exact McNemar test on fragile_survived —
    the statistically correct test for paired binary outcomes across two
    conditions (Wilcoxon, used for the continuous metrics, is not
    appropriate for a 0/1 outcome).

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
    complete = pivot.dropna(subset=["lra", "em"], how="any")

    n_dropped = len(pivot) - len(complete)
    if n_dropped > 0:
        print(f"NOTE: fragile_survived McNemar: dropping {n_dropped} participant(s) "
              f"missing lra or em.")

    ambiguous = complete[(complete["lra"] == 0.5) | (complete["em"] == 0.5)]
    if len(ambiguous) > 0:
        print(f"NOTE: fragile_survived McNemar: dropping {len(ambiguous)} participant(s) "
              f"whose two fragile reps disagreed (median 0.5) under lra or em — "
              f"McNemar needs one binary classification per participant per condition.")
    complete = complete.drop(ambiguous.index)

    if len(complete) < 4:
        print(f"WARNING: fragile_survived McNemar: only {len(complete)} usable "
              f"participant(s) — too few for a meaningful test. Skipping.")
        return None

    lra = complete["lra"].to_numpy()
    em = complete["em"].to_numpy()

    # Discordant pairs: b = survived under lra but not em, c = reverse.
    b = int(np.sum((lra == 1.0) & (em == 0.0)))
    c = int(np.sum((lra == 0.0) & (em == 1.0)))

    if b + c == 0:
        print("NOTE: fragile_survived McNemar: no discordant pairs (lra and em "
              "always agree) — p is undefined, reporting p=1.0.")
        return {"n": len(complete), "b": b, "c": c, "p": 1.0}

    result = stats.binomtest(min(b, c), b + c, p=0.5)
    return {"n": len(complete), "b": b, "c": c, "p": float(result.pvalue)}


def write_fragile_mcnemar_report(result, out_dir):
    """Writes the McNemar result for fragile_survived (lra vs em) to
    section_5_2_fragile_mcnemar.csv — a separate file from
    section_5_4_lra_vs_em.csv since the test/statistic differ."""
    path = os.path.join(out_dir, "section_5_2_fragile_mcnemar.csv")
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["n", "b_lra_survived_only", "c_em_survived_only", "mcnemar_p"])
        if result is None:
            writer.writerow(["", "", "", ""])
        else:
            writer.writerow([result["n"], result["b"], result["c"], f"{result['p']:.4f}"])
    print(f"Wrote {path}")


# ---------------------------------------------------------------------------
# Section 5.2 (inferential) — Fragile survival across ALL THREE conditions
#
# section_5_2_fragile_breakage.csv (above) reports raw counts only, and the
# Section 5.2's McNemar test covers lra vs em alone. The headline contrast of
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


PAIRS = [("visual_only", "lra"), ("visual_only", "em"), ("lra", "em")]


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

    raw, w_stats = [], []
    for a_name, b_name in PAIRS:
        a, b = rates[a_name].to_numpy(), rates[b_name].to_numpy()
        if np.all(a - b == 0):
            print(f"WARNING: fragile survival rate: {a_name} vs {b_name} has zero "
                  f"variance in paired differences — Wilcoxon undefined, skipping pair.")
            w_stats.append(None)
            raw.append(1.0)
            continue
        w_stat, w_p = stats.wilcoxon(a, b)
        w_stats.append(w_stat)
        raw.append(w_p)
    holm = holm_bonferroni(raw)
    pairwise = [(a, b, w_stats[i], raw[i], holm[i]) for i, (a, b) in enumerate(PAIRS)]

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

    q, q_p, dof = cochran_q(complete[CONDITIONS].to_numpy())
    raw, counts = [], []
    for a_name, b_name in PAIRS:
        a_only, b_only, p = mcnemar_binary(complete[a_name], complete[b_name])
        counts.append((a_only, b_only))
        raw.append(p)
    holm = holm_bonferroni(raw)
    pairwise = [(a, b, counts[i][0], counts[i][1], raw[i], holm[i])
                for i, (a, b) in enumerate(PAIRS)]
    return {"n": len(complete), "cochran_q": q, "cochran_p": q_p,
            "cochran_dof": dof, "pairwise": pairwise}


def fragile_survival_across_conditions(trial_df, reduced_df):
    """Section 5.2 (inferential): test fragile survival across all three
    conditions — the study's headline contrast, which the count-only
    breakage table and the lra-vs-em McNemar never tested. Runs the
    rate-level test (primary) and the binary majority-vote test
    (conservative). Returns {"rate": ..., "binary": ...}."""
    return {"rate": _rate_level_survival(trial_df),
            "binary": _binary_level_survival(reduced_df)}


def write_fragile_survival_tests_report(result, out_dir):
    """Writes the Section 5.2 inferential breakage tests to
    section_5_2_fragile_survival_tests.csv, one row per comparison, with a
    `level` column separating the rate-level (primary) and binary-level
    (conservative) analyses so both can be read from one table."""
    path = os.path.join(out_dir, "section_5_2_fragile_survival_tests.csv")
    rate, binary = result["rate"], result["binary"]
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["level", "n", "omnibus_test", "omnibus_stat", "omnibus_dof",
                          "omnibus_p", "comparison", "pairwise_test", "pairwise_stat",
                          "a_survived_only", "b_survived_only", "pairwise_p", "holm_p"])

        if rate is not None:
            med = ";".join(f"{c}={rate['medians'][c]:.3f}" for c in CONDITIONS)
            for a_name, b_name, w_stat, raw_p, holm_p in rate["pairwise"]:
                writer.writerow([
                    "rate", rate["n"], "friedman", f"{rate['friedman_stat']:.4f}",
                    len(CONDITIONS) - 1,
                    f"{rate['friedman_p']:.4f}", f"{a_name}_vs_{b_name}", "wilcoxon",
                    f"{w_stat:.4f}" if w_stat is not None else "", "", "",
                    f"{raw_p:.4f}", f"{holm_p:.4f}",
                ])
            writer.writerow(["rate_medians", rate["n"], "", "", "", "", med,
                             "", "", "", "", "", ""])
        else:
            writer.writerow(["rate", "", "friedman", "", "", "", "", "", "", "", "", "", ""])

        if binary is not None:
            # McNemar's statistic IS the discordant pair counts, already in the
            # a_survived_only/b_survived_only columns — no separate stat.
            for a_name, b_name, a_only, b_only, raw_p, holm_p in binary["pairwise"]:
                writer.writerow([
                    "binary", binary["n"], "cochran_q", f"{binary['cochran_q']:.4f}",
                    binary["cochran_dof"], f"{binary['cochran_p']:.4f}",
                    f"{a_name}_vs_{b_name}", "mcnemar", "", a_only, b_only,
                    f"{raw_p:.4f}", f"{holm_p:.4f}",
                ])
        else:
            writer.writerow(["binary", "", "cochran_q", "", "", "", "", "", "", "", "", "", ""])
    print(f"Wrote {path}")
