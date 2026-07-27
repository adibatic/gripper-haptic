"""
Figures — Section 5.5 time series, and the two figures thesis/preprint.tex
includes.

The preprint figures are drawn from the same in-memory frames the CSVs are
written from, so a figure cannot drift from the table beside it.
"""

import os
from collections import defaultdict

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from . import CONDITIONS
from .trials import FNAME_RE, find_trial_csvs, combined_series


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
    for path in find_trial_csvs(trials_dir):
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
            force, depth, force_label = combined_series(df, collapse)
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
        _save(fig, os.path.join(out_dir, f"section_5_5_timeseries_{condition}.png"))


# ---------------------------------------------------------------------------
# Preprint figures (thesis/preprint.tex)
#
# The two-page preprint carries two figures. Both are drawn from the same
# in-memory frames the CSVs above are written from, so a figure can never drift
# from the table beside it. Written only when --preprint-figures is given.
#
# Both are drawn at exactly COLUMN_WIDTH_IN so \includegraphics[width=\column-
# width] scales them 1:1. Drawing wider and letting LaTeX shrink to fit is what
# makes figure text illegible: at the old 6.4in width every label was reduced
# by half on the page, so nominal 8pt set as 4pt. Point sizes below are
# therefore the sizes that actually appear in the PDF — keep them within a
# point or two of the 12pt body's footnote size and do not widen the canvas.
# ---------------------------------------------------------------------------

# \the\columnwidth for preprint.tex (a4paper, 20mm margins, 6mm columnsep) is
# 233.31pt / 72.27 = 3.228in. Re-measure if the geometry ever changes.
COLUMN_WIDTH_IN = 3.228


LABELS = {"visual_only": "Visual\nonly", "lra": "LRA", "tactiles": "EM"}


COLORS = {"visual_only": "#9e9e9e", "lra": "#3b6ea5", "tactiles": "#c1543a"}


def _blend(color, alpha, background="white"):
    """Composite `color` at `alpha` over `background`, returning an opaque RGB.

    The EPS backend has no transparency: saving an alpha-blended artist to EPS
    either drops the blend or silently rasterises that artist, so the EPS and
    PNG of the same figure would not match. Pre-blending keeps both vector and
    identical.
    """
    fg = np.asarray(matplotlib.colors.to_rgb(color))
    bg = np.asarray(matplotlib.colors.to_rgb(background))
    return tuple(alpha * fg + (1.0 - alpha) * bg)


# Likert items plotted, in order. The two effort items are omitted: neither
# survives Holm correction (the preprint reports them in text), and four groups
# is what stays legible at the preprint's single-column width.
PREPRINT_ITEMS = [("force_perception", "Force\nperception"),
                  ("grasp_confidence", "Grasp\nconfidence"),
                  ("contact_detection", "Contact\ndetection"),
                  ("ease_of_manipulation", "Ease of\nmanip.")]


PREPRINT_PREFERENCES = [("preferred_overall", "Preferred\noverall"),
                        ("best_contact_state", "Best\ncontact")]


# Condition offsets within one item group in the ratings panel.
_OFFSETS = {"visual_only": -0.26, "lra": 0.0, "tactiles": 0.26}


def _stars(p):
    """Significance marker for an already-corrected p-value."""
    for threshold, marker in [(0.001, "***"), (0.01, "**"), (0.05, "*")]:
        if p < threshold:
            return marker
    return "n.s."


def plot_preprint_results(breakage, reduced_df, out_dir):
    """Preprint Fig. 1 — fragile objects: (a) pooled survival rate per
    condition, (b) per-participant post-plateau force overshoot.

    Args:
        breakage: {condition: (survival rate, n trials)} from
            write_fragile_breakage_summary().
        reduced_df: Per-participant medians from
            reduce_to_participant_condition_object().
        out_dir: Directory to write preprint_results.png into.
    """
    fragile = reduced_df[reduced_df["object"] == "fragile"]
    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(COLUMN_WIDTH_IN, 0.95))

    rates = [100 * breakage.get(c, (0.0, 0))[0] for c in CONDITIONS]
    ax_a.bar(range(len(CONDITIONS)), rates,
             color=[COLORS[c] for c in CONDITIONS], width=0.62)
    for i, rate in enumerate(rates):
        ax_a.text(i, rate + 2.5, f"{rate:.0f}%", ha="center", fontsize=6.5)
    # Headroom for the percentage labels, which sit above the tallest bar.
    ax_a.set_ylim(0, 112)
    ax_a.set_yticks([0, 50, 100])
    ax_a.set_ylabel("Surviving (%)", fontsize=6.5)
    ax_a.set_title("(a) Survival rate", fontsize=6.5)

    # +1 offset keeps exact-zero overshoot trials visible on a log axis.
    overshoot = [fragile.loc[fragile["condition"] == c, "force_overshoot_proxy"]
                 .dropna().to_numpy() + 1.0 for c in CONDITIONS]
    box = ax_b.boxplot(overshoot, widths=0.55, showfliers=False, patch_artist=True)
    for patch, condition in zip(box["boxes"], CONDITIONS):
        patch.set_facecolor(_blend(COLORS[condition], 0.65))
        patch.set_edgecolor("black")
        patch.set_linewidth(0.6)
    for element in ("whiskers", "caps"):
        for artist in box[element]:
            artist.set_linewidth(0.6)
    for median in box["medians"]:
        median.set_color("black")
        median.set_linewidth(1.0)
    for i, values in enumerate(overshoot, start=1):
        ax_b.plot([i] * len(values), values, "o", ms=1.8,
                  color=_blend("black", 0.45), mew=0)
    ax_b.set_yscale("log")
    ax_b.set_ylabel("Overshoot (a.u.+1)", fontsize=6.5)
    ax_b.set_title("(b) Force overshoot", fontsize=6.5)

    for ax in (ax_a, ax_b):
        ax.set_xticks(range(1, len(CONDITIONS) + 1) if ax is ax_b else range(len(CONDITIONS)))
        ax.set_xticklabels([LABELS[c].replace("\n", " ") for c in CONDITIONS], fontsize=6.5)
        ax.tick_params(length=2, pad=1.5)
        ax.tick_params(axis="y", labelsize=6.5)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
    _save(fig, os.path.join(out_dir, "preprint_results.png"))


def plot_preprint_likert(long_df, holm_by_pair, preference, out_dir):
    """Preprint Fig. 2 — (a) per-participant ratings per item and condition
    with Holm-corrected Wilcoxon brackets against visual-only, (b)
    forced-choice preference counts.

    Args:
        long_df: Long-format ratings from load_likert_long().
        holm_by_pair: {(item, comparison): Holm p} from write_likert_friedman().
        preference: {question: (counts, chi-square p)} from
            write_likert_preference().
        out_dir: Directory to write preprint_likert.png into.
    """
    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(COLUMN_WIDTH_IN, 1.15),
                                     gridspec_kw={"width_ratios": [2.85, 1.2]})
    rng = np.random.default_rng(0)

    for group, (item, _) in enumerate(PREPRINT_ITEMS):
        for condition in CONDITIONS:
            values = long_df.loc[(long_df["item"] == item)
                                 & (long_df["condition"] == condition),
                                 "value"].dropna().to_numpy(dtype=float)
            centre = group + _OFFSETS[condition]
            if len(np.unique(values)) > 1:
                parts = ax_a.violinplot([values], positions=[centre], widths=0.24,
                                        showextrema=False)
                for body in parts["bodies"]:
                    body.set_facecolor(_blend(COLORS[condition], 0.35))
                    body.set_alpha(1.0)
            # Jitter along x only, so the discrete 1-5 levels stay readable.
            ax_a.plot(centre + rng.uniform(-0.055, 0.055, len(values)), values,
                      "o", ms=1.6, color=_blend(COLORS[condition], 0.85),
                      mew=0, zorder=3)
            ax_a.plot([centre - 0.09, centre + 0.09], [np.median(values)] * 2,
                      "-", color="black", lw=0.9, zorder=4)

        for level, condition in enumerate(["lra", "tactiles"]):
            p = holm_by_pair.get((item, f"visual_only_vs_{condition}"))
            if p is None:
                continue
            y = 5.35 + 0.6 * level
            left, right = group + _OFFSETS["visual_only"], group + _OFFSETS[condition]
            ax_a.plot([left, left, right, right], [y - 0.12, y, y, y - 0.12],
                      color="black", lw=0.5)
            ax_a.text((left + right) / 2, y - 0.30, _stars(p), ha="center",
                      va="bottom", fontsize=6)

    ax_a.set_xticks(range(len(PREPRINT_ITEMS)))
    ax_a.set_xticklabels([label for _, label in PREPRINT_ITEMS], fontsize=5.5)
    ax_a.set_yticks([1, 2, 3, 4, 5])
    ax_a.set_ylim(0.5, 6.6)
    ax_a.set_ylabel("Rating (1–5)", fontsize=6.5)
    ax_a.set_title("(a) Ratings, Holm-corrected vs. visual-only", fontsize=6.5,
                   pad=11)
    ax_a.legend(handles=[plt.Line2D([], [], marker="s", ls="", ms=3,
                                    color=COLORS[c], label=LABELS[c].replace("\n", " "))
                         for c in CONDITIONS],
                fontsize=6, loc="lower center", ncol=3, frameon=False,
                handletextpad=0.2, columnspacing=1.0, bbox_to_anchor=(0.5, 1.0),
                borderaxespad=0.1)

    for i, (question, _) in enumerate(PREPRINT_PREFERENCES):
        counts, chi2_p = preference[question]
        bottom = 0
        for condition in CONDITIONS:
            n = counts[condition]
            ax_b.bar(i, n, 0.62, bottom=bottom, color=COLORS[condition])
            if n >= 3:
                ax_b.text(i, bottom + n / 2, str(n), ha="center", va="center",
                          fontsize=6, color="white")
            elif n:
                # Too thin to letter inside — label just outside the bar.
                ax_b.text(i + 0.36, bottom + n / 2, str(n), ha="left", va="center",
                          fontsize=6, color="#555555")
            bottom += n
        label = "$p$<.001" if chi2_p < 0.001 else f"$p$={chi2_p:.3f}"
        ax_b.text(i, bottom + 0.6, label, ha="center", fontsize=5.5)

    ax_b.set_xticks(range(len(PREPRINT_PREFERENCES)))
    ax_b.set_xticklabels([label for _, label in PREPRINT_PREFERENCES], fontsize=5)
    ax_b.set_xlim(-0.7, len(PREPRINT_PREFERENCES) - 0.3)
    ax_b.set_ylim(0, max(sum(c.values()) for c, _ in preference.values()) * 1.3)
    ax_b.set_ylabel("Participants", fontsize=6.5)
    ax_b.set_title("(b) Forced choice", fontsize=6)
    for ax in (ax_a, ax_b):
        ax.tick_params(length=2, pad=1.5)
        ax.tick_params(axis="y", labelsize=6.5)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
    _save(fig, os.path.join(out_dir, "preprint_likert.png"))


def _save(fig, path, pad=0.15):
    """Write `path` (.png, 300dpi) and its .eps sibling from one figure.

    preprint.tex includes these extension-less, so pdflatex picks up the PNG
    and a dvips/latex route picks up the EPS without the source changing.
    """
    fig.tight_layout(pad=pad)
    base = os.path.splitext(path)[0]
    for out_path in (f"{base}.png", f"{base}.eps"):
        fig.savefig(out_path, dpi=300)
        print(f"Wrote {out_path}")
    plt.close(fig)
