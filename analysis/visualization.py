"""
Section 5.5 time-series visualisation.

The two preprint figures that also come out of the analysis pipeline
(survival + overshoot, Likert ratings) live in thesis/build_preprint_figs.py
alongside the other three, hand-authored preprint figures — see that
module's docstring.

Figure sizing note: each panel is included in the thesis at 0.32\\textwidth,
which is about 52 mm, so the figures are authored at that physical size and
laid out in points rather than being drawn large and scaled down. Type set
here in points therefore reaches the page at the same size, instead of the
four-fold reduction that made the earlier version illegible.
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


# Printed panel width (0.32\textwidth at the thesis geometry) in inches, so a
# point set here is a point on the page.
PANEL_IN = (2.15, 2.45)

# Type sizes in points, chosen against the \small caption face (11 pt) the
# panels sit under.
FS_TICK = 7.0
FS_LABEL = 8.0
FS_TITLE = 8.5

DEPTH_COLOUR = "tab:blue"
FORCE_COLOUR = "tab:red"

# Window drawn around the grasp: contact is depth above CONTACT_MM, and the
# panel keeps this much dead time either side of it for context.
CONTACT_MM = 0.05
CROP_LEAD_S = 1.0
CROP_TAIL_S = 1.5

CONDITION_LABELS = {"visual_only": "Visual-only", "lra": "LRA", "em": "EM"}


def _representative_path(paths, collapse):
    """Pick the trial whose peak force proxy is closest to the median peak
    across `paths`, so the plotted trace is the typical one for that
    condition rather than whichever file the directory listing returned
    first. Falls back to the first path if no trial yields a finite peak.

    Returns (path, dataframe) for the chosen trial.
    """
    peaks = []
    for path in paths:
        df = pd.read_csv(path)
        if df.empty:
            continue
        force, _, _ = combined_series(df, collapse)
        if np.isfinite(force).any():
            peaks.append((float(np.nanmax(force)), path, df))
    if not peaks:
        return paths[0], pd.read_csv(paths[0])
    median_peak = float(np.median([p for p, _, _ in peaks]))
    _, path, df = min(peaks, key=lambda row: abs(row[0] - median_peak))
    return path, df


def plot_representative_trials(trials_dir, out_dir, collapse, object_class="fragile"):
    """Section 5.5: plot one representative trial per condition, showing the
    contact depth and the force proxy against time on a shared time axis.

    Only `object_class` trials are considered, because the behaviour the
    figure exists to show — force continuing to rise after contact depth has
    levelled off — is a fragile-object argument; the deformable traces the
    earlier version happened to select could not display it.

    'Representative' means the trial whose peak force proxy is nearest that
    condition's median peak, and the caption in Section 5.5 states this
    selection rule.

    Args:
        trials_dir: Directory to scan for trial CSVs.
        out_dir: Directory to write the per-condition figures into.
        collapse: Sensor-combination mode for the force/depth series.
        object_class: Which object class to draw traces from.
    """
    paths_by_condition = defaultdict(list)
    for path in find_trial_csvs(trials_dir):
        m = FNAME_RE.match(os.path.basename(path))
        if m and m.group("object") == object_class:
            paths_by_condition[m.group("condition")].append(path)

    for condition in CONDITIONS:
        paths = paths_by_condition.get(condition, [])
        if not paths:
            print(f"NOTE: no {object_class} trials found for condition "
                  f"'{condition}', skipping its time-series plot.")
            continue

        path, df = _representative_path(paths, collapse)
        force, depth, force_label = combined_series(df, collapse)
        t = pd.to_numeric(df["t"], errors="coerce").to_numpy()

        fig, ax_depth = plt.subplots(figsize=PANEL_IN, layout="constrained")
        ax_force = ax_depth.twinx()

        ax_depth.plot(t, depth, color=DEPTH_COLOUR, linewidth=1.1)
        ax_depth.set_xlabel("Time (s)", fontsize=FS_LABEL)
        ax_depth.set_ylabel("Depth (mm)", color=DEPTH_COLOUR, fontsize=FS_LABEL)

        if np.isfinite(force).any():
            # Plotted in thousands: five-digit tick labels cost more panel
            # width than the extra precision is worth at this size.
            ax_force.plot(t, force / 1000.0, color=FORCE_COLOUR, linewidth=1.1)
            ax_force.set_ylabel(r"Force proxy ($10^3$ a.u.)", color=FORCE_COLOUR,
                                fontsize=FS_LABEL)
        else:
            # sum_n on uncalibrated logs: say so on the axis rather than
            # drawing an empty one that reads as a flat trace.
            ax_force.set_ylabel("Force proxy (not calibrated)",
                                color=FORCE_COLOUR, fontsize=FS_LABEL)

        # The plateau the text and the post-plateau metric are defined
        # against: the first sample at 95% of this trial's peak depth.
        finite_depth = depth[np.isfinite(depth)]
        if len(finite_depth) and finite_depth.max() > 0:
            reached = np.where(depth >= 0.95 * np.nanmax(depth))[0]
            if len(reached):
                ax_depth.axvline(t[int(reached[0])], color="0.45",
                                 linestyle="--", linewidth=0.8)

        for ax, colour in ((ax_depth, DEPTH_COLOUR), (ax_force, FORCE_COLOUR)):
            ax.tick_params(axis="y", labelsize=FS_TICK, labelcolor=colour,
                           length=2.5, pad=1.5)
        ax_depth.tick_params(axis="x", labelsize=FS_TICK, length=2.5, pad=1.5)
        ax_depth.margins(x=0.02)

        # Crop to the grasp itself. A trial spends most of its length with the
        # gripper open and both traces flat, which at panel size squeezes the
        # part being discussed into a few millimetres.
        in_contact = np.where(np.isfinite(depth) & (depth > CONTACT_MM))[0]
        if len(in_contact):
            ax_depth.set_xlim(max(t[0], t[int(in_contact[0])] - CROP_LEAD_S),
                              min(t[-1], t[int(in_contact[-1])] + CROP_TAIL_S))

        # The condition name is carried by the LaTeX subfigure caption, so the
        # panel title identifies only which trial this is. No suptitle: the
        # earlier version's suptitle collided with this line.
        m = FNAME_RE.match(os.path.basename(path))
        ax_depth.set_title(f"{m.group('participant')}, trial {int(m.group('trial'))}",
                           fontsize=FS_TITLE, pad=3.0)

        _save(fig, os.path.join(out_dir, f"section_5_5_timeseries_{condition}.png"))
        plt.close(fig)


def _save(fig, path):
    """Write `path` (.png, 300dpi) and its .eps sibling from one figure."""
    base = os.path.splitext(path)[0]
    for out_path in (f"{base}.png", f"{base}.eps"):
        fig.savefig(out_path, dpi=300)
        print(f"Wrote {out_path}")
