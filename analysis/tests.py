"""
Statistical primitives shared across sections.

Pure functions over arrays — no DataFrames, no file I/O, no printing. The
section modules (comparisons.py, survival.py, likert.py) supply the data and
own the reporting.
"""

import numpy as np
from scipy import stats


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


def cochran_q(binary_matrix):
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


def mcnemar_binary(a, b):
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
