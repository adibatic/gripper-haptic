"""Builds the two-panel results figure used in the preprint (thesis/preprint.tex).

Reads the analysis outputs in results/ (written by run/analysis.py) and writes
thesis/figures/preprint_results.png:

    (a) fragile-object survival rate per condition, pooled over all trials
    (b) per-participant force-overshoot proxy on fragile objects, by condition

Run from the repository root:

    python thesis/make_preprint_figure.py
"""

import csv
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(REPO, "results")
OUT = os.path.join(REPO, "thesis", "figures", "preprint_results.png")

CONDITIONS = ["visual_only", "lra", "tactiles"]
LABELS = {"visual_only": "Visual\nonly", "lra": "LRA", "tactiles": "TacTiles"}
COLORS = {"visual_only": "#9e9e9e", "lra": "#3b6ea5", "tactiles": "#c1543a"}


def read_breakage():
    """Pooled fragile survival rate per condition (section_5_7)."""
    path = os.path.join(RESULTS, "section_5_7_fragile_breakage.csv")
    with open(path) as f:
        rows = {r["condition"]: r for r in csv.DictReader(f)}
    return {c: (float(rows[c]["success_rate"]), int(rows[c]["n_trials"])) for c in CONDITIONS}


def read_overshoot():
    """Per-participant median force-overshoot proxy on fragile objects."""
    path = os.path.join(RESULTS, "section_5_1_reduced_metrics.csv")
    out = {c: [] for c in CONDITIONS}
    with open(path) as f:
        for r in csv.DictReader(f):
            if r["object"] != "fragile" or r["condition"] not in out:
                continue
            value = r["force_overshoot_proxy"]
            if value:
                out[r["condition"]].append(float(value))
    return out


def main():
    survival = read_breakage()
    overshoot = read_overshoot()

    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(6.4, 1.8))

    x = range(len(CONDITIONS))
    ax_a.bar(x, [100 * survival[c][0] for c in CONDITIONS],
             color=[COLORS[c] for c in CONDITIONS], width=0.62)
    for i, c in enumerate(CONDITIONS):
        rate, n = survival[c]
        ax_a.text(i, 100 * rate + 2, f"{100 * rate:.0f}%", ha="center", fontsize=8)
    ax_a.set_xticks(list(x))
    ax_a.set_xticklabels([LABELS[c] for c in CONDITIONS], fontsize=8)
    ax_a.set_ylim(0, 100)
    ax_a.set_ylabel("Fragile objects surviving (%)", fontsize=8)
    ax_a.set_title("(a) Survival rate, 100 trials/condition", fontsize=8)
    ax_a.tick_params(labelsize=8)

    data = [overshoot[c] for c in CONDITIONS]
    # +1 offset keeps exact-zero overshoot trials visible on a log axis.
    data = [[v + 1.0 for v in vals] for vals in data]
    bp = ax_b.boxplot(data, widths=0.55, showfliers=False, patch_artist=True)
    for patch, c in zip(bp["boxes"], CONDITIONS):
        patch.set_facecolor(COLORS[c])
        patch.set_alpha(0.65)
    for median in bp["medians"]:
        median.set_color("black")
    for i, vals in enumerate(data, start=1):
        ax_b.plot([i] * len(vals), vals, "o", ms=2.5, color="black", alpha=0.45)
    ax_b.set_yscale("log")
    ax_b.set_xticklabels([LABELS[c] for c in CONDITIONS], fontsize=8)
    ax_b.set_ylabel("Force overshoot (a.u. + 1)", fontsize=8)
    ax_b.set_title("(b) Post-plateau overshoot, fragile", fontsize=8)
    ax_b.tick_params(labelsize=8)

    fig.tight_layout()
    fig.savefig(OUT, dpi=300)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
