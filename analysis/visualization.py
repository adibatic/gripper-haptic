"""
Section 5.5 time-series visualisation.

The two preprint figures that also come out of the analysis pipeline
(survival + overshoot, Likert ratings) live in analysis/preprint_figs.py
alongside the other three, hand-authored preprint figures — see that
module's docstring.
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


def _save(fig, path, pad=0.15):
    """Write `path` (.png, 300dpi) and its .eps sibling from one figure."""
    fig.tight_layout(pad=pad)
    base = os.path.splitext(path)[0]
    for out_path in (f"{base}.png", f"{base}.eps"):
        fig.savefig(out_path, dpi=300)
        print(f"Wrote {out_path}")
