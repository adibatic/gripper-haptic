"""
Every figure thesis/01_IMAC_HashimotoLab_C2TB1701_AdrielImaranSantoso.tex
includes, in one place so the five stay visually consistent.

preprint_fig1 (system data flow), preprint_fig2 (hardware plate), and
preprint_fig3 (method flow) are hand-authored block diagrams, not generated
from trial data — fig2's callouts are drawn over the label-free photo crops
in thesis/figures/photos/. Run this module directly to (re)draw them — it
needs -m since it imports CONDITIONS from the package:

    python -m analysis.preprint_figs

preprint_fig4 (fragile survival + force overshoot) and preprint_fig5
(subjective ratings + forced choice) ARE generated from trial data — they are
drawn from the same in-memory frames the analysis pipeline writes its CSVs
from, so a figure can never drift from the table beside it. They are plotted
by the pipeline itself (python -m analysis --preprint-figures DIR), not by
running this file.

All five are drawn at exactly COLUMN_WIDTH_IN so \\includegraphics[width=
\\columnwidth] scales them 1:1. Drawing wider and letting LaTeX shrink to fit
is what makes figure text illegible: at the old 6.4in width every label was
reduced by half on the page, so nominal 8pt set as 4pt. Point sizes below are
therefore the sizes that actually appear in the PDF — keep them within a
point or two of the 12pt body's footnote size and do not widen the canvas.

Every figure is written as both .png and .eps; the preprint's
\\includegraphics calls name the .eps explicitly, so build with the
latex + dvips + ps2pdf route rather than pdflatex (which cannot rasterise
EPS without epstopdf).
"""

import os

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

from . import CONDITIONS

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO_ROOT, "thesis", "figures")

GRAY = "#9e9e9e"
BLUE = "#3b6ea5"
RED = "#c1543a"
DARK = "#333333"

# \the\columnwidth for the preprint (a4paper, 20mm margins, 6mm columnsep) is
# 233.31pt / 72.27 = 3.228in. Re-measure if the geometry ever changes.
COLUMN_WIDTH_IN = 3.228

# fig1-3 are plotted in bare data coordinates (see new_fig()) rather than
# through pandas/pyplot's usual per-artist styling, so the rc_context below is
# the one place font/edge/text defaults are set for them — everything drawn
# through box()/arrow()/callout() also passes its own fontsize and color
# explicitly, so this is a fallback, not the source of truth.
DIAGRAM_RC = {"font.size": 7.5, "axes.edgecolor": DARK, "text.color": DARK}


# ---------------------------------------------------------------------------
# Shared helpers — fig1 and fig3's block-diagram primitives
# ---------------------------------------------------------------------------

def box(ax, x, y, w, h, text, facecolor="white", edgecolor=DARK, fontsize=7.5,
        fontweight="bold", linewidth=1.1):
    b = FancyBboxPatch((x, y), w, h,
                        boxstyle="round,pad=0.02,rounding_size=0.08",
                        linewidth=linewidth, edgecolor=edgecolor, facecolor=facecolor, zorder=2)
    ax.add_patch(b)
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
            fontsize=fontsize, fontweight=fontweight, color=DARK, zorder=3)
    return (x, y, w, h)


def arrow(ax, p0, p1, label=None, label_dx=0, label_dy=0.12, color=DARK, fontsize=6.6,
          style="-|>", rad=0.0):
    if label:
        mx, my = (p0[0] + p1[0]) / 2 + label_dx, (p0[1] + p1[1]) / 2 + label_dy
        ax.text(mx, my, label, ha="center", va="center", fontsize=fontsize,
                color=color, style="italic", zorder=1)
    a = FancyArrowPatch(p0, p1, arrowstyle=style, mutation_scale=9,
                         linewidth=1.1, color=color, zorder=3, shrinkA=0, shrinkB=0,
                         connectionstyle=f"arc3,rad={rad}")
    ax.add_patch(a)


def edge_point(box_xywh, side):
    x, y, w, h = box_xywh
    return {
        "top": (x + w / 2, y + h),
        "bottom": (x + w / 2, y),
        "left": (x, y + h / 2),
        "right": (x + w, y + h / 2),
    }[side]


def new_fig(w_in, h_in, xlim, ylim):
    fig, ax = plt.subplots(figsize=(w_in, h_in))
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    ax.axis("off")
    ax.set_position([0, 0, 1, 1])
    return fig, ax


# ---------------------------------------------------------------------------
# preprint_fig1: system data flow
# ---------------------------------------------------------------------------

def draw_system_dataflow():
    """Authored 1:1 at COLUMN_WIDTH_IN like fig2 and fig3, so \\includegraphics
    neither shrinks nor magnifies it and its 7.5pt text matches theirs on the
    page.

    The HOST PC sits in the middle because it is the only node with an edge to
    all four others -- finger control and touch sensors never talk to each
    other, they each talk to the PC. Centring the gripper instead forces both
    user-side arrows to detour around the gripper row, which is why that
    layout was rejected.

    Read as one continuous cycle, not two independent halves: camera -> PC ->
    finger control -> the object -> touch sensors -> PC -> actuator -> the
    human -> camera again. The two dashed arcs are the links a wire can't
    draw: the object being squeezed at the bottom, the human feeling it at
    the top.

    Deliberately unfilled. #eaf1f8/#f2ede7 are the pale forms of the LRA/EM
    condition colours below, so a fill here would claim this apparatus
    belongs to one condition -- but it is the rig common to all three.
    """
    with plt.rc_context(DIAGRAM_RC):
        fig, ax = new_fig(COLUMN_WIDTH_IN, 3.80, (0, 20), (-2.7, 21.0))

        group_style = dict(boxstyle="round,pad=0.02,rounding_size=0.12", linewidth=1.0,
                            edgecolor=GRAY, facecolor="none", linestyle=(0, (4, 3)), zorder=0)
        ax.add_patch(FancyBboxPatch((0.3, 13.5), 19.4, 3.6, **group_style))
        ax.add_patch(FancyBboxPatch((0.3, 1.3), 19.4, 3.6, **group_style))
        ax.text(0.6, 17.55, "USER", fontsize=6.6, fontweight="bold", color=GRAY,
                family="monospace", va="center", zorder=1)
        ax.text(0.6, 0.75, "GRIPPER", fontsize=6.6, fontweight="bold", color=GRAY,
                family="monospace", va="center", zorder=1)

        box(ax, 0.9, 14.1, 8.5, 2.4, "hand tracking\ncamera")
        box(ax, 10.6, 14.1, 8.5, 2.4, "wearable actuator\n(LRA or EM)")
        box(ax, 6.4, 8.0, 7.2, 2.2, "HOST PC")
        box(ax, 0.9, 1.9, 8.5, 2.4, "finger control")
        box(ax, 10.6, 1.9, 8.5, 2.4, "touch sensors")

        # All four curved the same rotational sense so the eye follows one cycle
        # rather than four independent spokes. They land close to the PC's own
        # centreline (not its outer corners) so the box reads as one pinched waist
        # of a figure-8, not four unrelated connection points along its edges.
        arrow(ax, (5.15, 14.1), (8.6, 10.2), label="pixel\ndistance", label_dx=-2.6,
              label_dy=0, rad=0.35)
        arrow(ax, (8.6, 8.0), (5.15, 4.3), label="open /\nclose", label_dx=-2.6,
              label_dy=0, rad=0.35)
        arrow(ax, (14.85, 4.3), (11.4, 8.0), label="dent\ndepth", label_dx=2.6,
              label_dy=0, rad=0.35)
        arrow(ax, (11.4, 10.2), (14.85, 14.1), label="haptic\nintensity (0\N{EN DASH}1)",
              label_dx=3.5, label_dy=0, rad=0.35)

        # Loop closure, top: dashed and grey because this link is the human, not a
        # wire. The label sits clear above the arc's peak (not in its belly) so
        # the dashes read as one continuous curve instead of being cut by the
        # label's background.
        ax.add_patch(FancyArrowPatch((14.85, 17.6), (5.15, 17.6), arrowstyle="-|>",
                                      mutation_scale=9, linewidth=1.0, color=GRAY, zorder=1,
                                      linestyle=(0, (3, 2)),
                                      connectionstyle="arc3,rad=0.65"))
        ax.text(10.0, 19.25, "human adjusts grip",
                ha="center", va="center", fontsize=6.6, style="italic", color=DARK, zorder=2)

        # Loop closure, bottom: same idea, but this link is the object being squeezed.
        ax.add_patch(FancyArrowPatch((5.15, 0.8), (14.85, 0.8), arrowstyle="-|>",
                                      mutation_scale=9, linewidth=1.0, color=GRAY, zorder=1,
                                      linestyle=(0, (3, 2)),
                                      connectionstyle="arc3,rad=0.65"))
        ax.text(10.0, -1.25, "object deforms",
                ha="center", va="center", fontsize=6.6, style="italic", color=DARK, zorder=2)

        fig.savefig(f"{OUT}/preprint_fig1.eps")
        fig.savefig(f"{OUT}/preprint_fig1.png", dpi=200)
        plt.close(fig)


# ---------------------------------------------------------------------------
# preprint_fig2: hardware photo plate
# ---------------------------------------------------------------------------

def draw_hardware_plate():
    """The images in figures/photos/ are label-free crops, so every callout is
    drawn here and the plate carries the same 7pt DARK type, hairline leaders
    and dashed-GRAY grouping as fig1 and fig3 rather than the heavier
    lettering a photo editor bakes in.

    Authored 1:1 at COLUMN_WIDTH_IN for the same reason as fig1, and kept
    close to square: at \\columnwidth a plate taller than it is wide costs a
    third of a column, and the preprint has no vertical space to give.

    Grouped USER / GRIPPER the way fig1 groups its blocks, so a reader coming
    from fig1 can map each block there onto the hardware here.
    """
    with plt.rc_context(DIAGRAM_RC):
        fig2_h = 3.45
        fig = plt.figure(figsize=(COLUMN_WIDTH_IN, fig2_h))
        # The callout layer sits above the photo axes: with the default order a
        # photo's own axes background clips any leader that crosses it, leaving
        # stubs.
        ax = fig.add_axes([0, 0, 1, 1], zorder=10)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")
        ax.patch.set_visible(False)
        aspect = COLUMN_WIDTH_IN / fig2_h

        def photo(name, x, top, w):
            """Draw figures/photos/<name>.png with its top-left at (x, top),
            width w.

            Axes fractions are only square in figure space, so the height
            carries the figure's aspect -- without it every photo comes out
            stretched.
            """
            img = plt.imread(f"{OUT}/photos/{name}.png")
            h = w * img.shape[0] / img.shape[1] * aspect
            a = fig.add_axes([x, top - h, w, h], zorder=1)
            a.axis("off")
            a.imshow(img, interpolation="antialiased")
            return (x, top - h, w, h)

        def at(rect, u, v):
            """Point (u, v) in a photo's own fractional coordinates, v from the top."""
            x, y, w, h = rect
            return (x + u * w, y + (1 - v) * h)

        def callout(x, y, text, tip, ha="center", va="bottom"):
            """A 7pt bold label at (x, y) with a hairline leader running to `tip`."""
            ax.text(x, y, text, ha=ha, va=va, fontsize=7.0, fontweight="bold",
                    color=DARK, zorder=4, linespacing=1.2)
            pad = -0.010 if va == "top" else (0.010 if va == "bottom" else 0)
            anchor = (x + (0.008 if ha == "left" else -0.008 if ha == "right" else 0), y + pad)
            ax.add_patch(FancyArrowPatch(anchor, tip, arrowstyle="-", linewidth=1.0,
                                          color=DARK, shrinkA=3, shrinkB=2, zorder=4))

        group_style = dict(boxstyle="round,pad=0.004,rounding_size=0.02", linewidth=1.0,
                            edgecolor=GRAY, facecolor="none", linestyle=(0, (4, 3)), zorder=0)
        ax.add_patch(FancyBboxPatch((0.015, 0.405), 0.475, 0.525, **group_style))
        ax.add_patch(FancyBboxPatch((0.515, 0.405), 0.470, 0.525, **group_style))
        ax.text(0.038, 0.930, "USER", fontsize=6.6, fontweight="bold", color=GRAY,
                family="monospace", va="center", backgroundcolor="white", zorder=1)
        ax.text(0.538, 0.930, "GRIPPER", fontsize=6.6, fontweight="bold", color=GRAY,
                family="monospace", va="center", backgroundcolor="white", zorder=1)
        ax.text(0.015, 0.998, "(a)", fontsize=7.5, fontweight="bold", color=DARK, va="top")

        hand = photo("wearable_hand", 0.045, 0.895, 0.26)
        cam = photo("camera", 0.060, 0.475, 0.29)
        grip = photo("gripper", 0.522, 0.895, 0.26)
        photo("touch_sensor", 0.855, 0.615, 0.090)

        callout(0.325, 0.855, "wearable\ndevice", at(hand, 0.40, 0.36), ha="left", va="top")
        callout(0.200, 0.560, "hand-tracking\ncamera", at(cam, 0.34, 0.10), ha="center", va="bottom")
        callout(0.800, 0.893, "robot\ngripper", at(grip, 0.33, 0.05), ha="left", va="top")
        callout(0.800, 0.780, "object", at(grip, 0.48, 0.44), ha="left", va="center")
        # The sensor is called out by the inset itself, so the leader runs from
        # the inset to the fingertip it magnifies and the label just titles the
        # inset.
        ax.text(0.900, 0.640, "touch\nsensor", ha="center", va="bottom", fontsize=7.0,
                fontweight="bold", color=DARK, zorder=4, linespacing=1.2)
        ax.add_patch(FancyArrowPatch((0.855, 0.570), at(grip, 0.72, 0.46), arrowstyle="-",
                                      linewidth=1.0, color=DARK, shrinkA=3, shrinkB=2, zorder=4))

        # The (b) strip: the same two actuators, worn. Equal photo widths and
        # centred labels so the pair reads as a comparison rather than two
        # unrelated photos.
        ax.plot([0.015, 0.985], [0.378, 0.378], color=GRAY, linewidth=0.8,
                linestyle=(0, (4, 3)), clip_on=False)
        ax.text(0.015, 0.348, "(b)", fontsize=7.5, fontweight="bold", color=DARK, va="top")
        ax.text(0.275, 0.338, "LRA", fontsize=7.5, fontweight="bold", color=DARK,
                ha="center", va="top")
        ax.text(0.725, 0.338, "EM", fontsize=7.5, fontweight="bold", color=DARK,
                ha="center", va="top")
        photo("lra_hand", 0.110, 0.285, 0.33)
        photo("em_hand", 0.560, 0.270, 0.33)

        fig.savefig(f"{OUT}/preprint_fig2.eps")
        fig.savefig(f"{OUT}/preprint_fig2.png", dpi=400)
        plt.close(fig)


# ---------------------------------------------------------------------------
# preprint_fig3: method flow
# ---------------------------------------------------------------------------

def draw_method_flow():
    with plt.rc_context(DIAGRAM_RC):
        fig, ax = new_fig(COLUMN_WIDTH_IN, 3.85, (0, 10), (2.2, 15.3))

        b1 = box(ax, 1.0, 13.9, 8.0, 1.1, "22 participants", fontsize=8)
        b2 = box(ax, 0.6, 11.6, 8.8, 1.5,
                 "Each tries all 3 conditions,\nalways in this order:\nVision only → LRA → EM")
        b3 = box(ax, 0.6, 9.3, 8.8, 1.5,
                 "Each condition × 2 object classes\n(fragile, deformable) × 5 grasps")
        b4 = box(ax, 2.4, 7.6, 5.2, 1.1, "660 trials total", fontsize=8)
        b5 = box(ax, 0.4, 5.1, 9.2, 1.85,
                 "From each trial: peak grip force,\npeak dent depth, excess force,\n"
                 "force reversals, and (fragile only)\nwhether it survived",
                 fontsize=6.9)
        b6 = box(ax, 0.3, 2.55, 4.35, 1.75,
                 "Compare conditions:\ndifferent, or close\nenough to call\nequivalent?",
                 fontsize=6.9, facecolor="#eaf1f8")
        b7 = box(ax, 5.35, 2.55, 4.35, 1.75,
                 "Participant ratings\n+ preferred\ncondition", fontsize=6.9, facecolor="#f2ede7")

        arrow(ax, edge_point(b1, "bottom"), edge_point(b2, "top"))
        arrow(ax, edge_point(b2, "bottom"), edge_point(b3, "top"))
        arrow(ax, edge_point(b3, "bottom"), edge_point(b4, "top"))
        arrow(ax, edge_point(b4, "bottom"), edge_point(b5, "top"))
        arrow(ax, (2.5, 5.1), edge_point(b6, "top"))
        arrow(ax, (7.5, 5.1), edge_point(b7, "top"))

        fig.savefig(f"{OUT}/preprint_fig3.eps")
        fig.savefig(f"{OUT}/preprint_fig3.png", dpi=200)
        plt.close(fig)


# ---------------------------------------------------------------------------
# preprint_fig4 / preprint_fig5 — drawn from trial data by the analysis
# pipeline (python -m analysis --preprint-figures DIR), not by __main__ below.
# ---------------------------------------------------------------------------

LABELS = {"visual_only": "Visual\nonly", "lra": "LRA", "tactiles": "EM"}


COLORS = {"visual_only": GRAY, "lra": BLUE, "tactiles": RED}


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
    """Preprint Fig. 4 — fragile objects: (a) pooled survival rate per
    condition, (b) per-participant post-plateau force overshoot.

    Args:
        breakage: {condition: (survival rate, n trials)} from
            write_fragile_breakage_summary().
        reduced_df: Per-participant medians from
            reduce_to_participant_condition_object().
        out_dir: Directory to write preprint_fig4.png into.
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
    box_ = ax_b.boxplot(overshoot, widths=0.55, showfliers=False, patch_artist=True)
    for patch, condition in zip(box_["boxes"], CONDITIONS):
        patch.set_facecolor(_blend(COLORS[condition], 0.65))
        patch.set_edgecolor("black")
        patch.set_linewidth(0.6)
    for element in ("whiskers", "caps"):
        for artist in box_[element]:
            artist.set_linewidth(0.6)
    for median in box_["medians"]:
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
    _save(fig, os.path.join(out_dir, "preprint_fig4.png"))


def plot_preprint_likert(long_df, holm_by_pair, preference, out_dir):
    """Preprint Fig. 5 — (a) per-participant ratings per item and condition
    with Holm-corrected Wilcoxon brackets against visual-only, (b)
    forced-choice preference counts.

    Args:
        long_df: Long-format ratings from load_likert_long().
        holm_by_pair: {(item, comparison): Holm p} from write_likert_friedman().
        preference: {question: (counts, chi-square p)} from
            write_likert_preference().
        out_dir: Directory to write preprint_fig5.png into.
    """
    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(COLUMN_WIDTH_IN, 1.15),
                                     gridspec_kw={"width_ratios": [2.85, 1.2]})
    rng = np.random.default_rng(0)

    for i, (item, item_label) in enumerate(PREPRINT_ITEMS):
        item_df = long_df[long_df["item"] == item]
        for condition in CONDITIONS:
            values = item_df.loc[item_df["condition"] == condition, "rating"].dropna().to_numpy()
            if len(values) == 0:
                continue
            x = i + _OFFSETS[condition] + rng.uniform(-0.05, 0.05, size=len(values))
            ax_a.plot(x, values, "o", ms=2.0, color=_blend(COLORS[condition], 0.55), mew=0)
            ax_a.plot([i + _OFFSETS[condition] - 0.09, i + _OFFSETS[condition] + 0.09],
                      [np.median(values)] * 2, color=COLORS[condition], linewidth=1.6)
        p = holm_by_pair.get((item, "lra_vs_visual"), (None, 1.0))[1]
        star = _stars(p)
        if star != "n.s.":
            y = item_df["rating"].max() + 0.4
            ax_a.text(i, y, star, ha="center", fontsize=7)

    ax_a.set_xticks(range(len(PREPRINT_ITEMS)))
    ax_a.set_xticklabels([label for _, label in PREPRINT_ITEMS], fontsize=6.5)
    ax_a.set_ylabel("Rating (1\N{EN DASH}5)", fontsize=6.5)
    ax_a.set_title("(a) Per-item ratings", fontsize=6.5)
    ax_a.set_ylim(0.5, 6.0)

    counts, _ = preference[PREPRINT_PREFERENCES[0][0]]
    conditions_present = [c for c in CONDITIONS if c in counts]
    ax_b.bar(range(len(conditions_present)), [counts[c] for c in conditions_present],
             color=[COLORS[c] for c in conditions_present], width=0.6)
    ax_b.set_xticks(range(len(conditions_present)))
    ax_b.set_xticklabels([LABELS[c].replace("\n", " ") for c in conditions_present], fontsize=6.5)
    ax_b.set_ylabel("Participants", fontsize=6.5)
    ax_b.set_title("(b) Forced choice", fontsize=6)
    for ax in (ax_a, ax_b):
        ax.tick_params(length=2, pad=1.5)
        ax.tick_params(axis="y", labelsize=6.5)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
    _save(fig, os.path.join(out_dir, "preprint_fig5.png"))


def _save(fig, path, pad=0.15):
    """Write `path` (.png, 300dpi) and its .eps sibling from one figure."""
    fig.tight_layout(pad=pad)
    base = os.path.splitext(path)[0]
    for out_path in (f"{base}.png", f"{base}.eps"):
        fig.savefig(out_path, dpi=300)
        print(f"Wrote {out_path}")


if __name__ == "__main__":
    # Only the three hand-authored diagrams: fig4/fig5 need real trial data
    # and are drawn by the analysis pipeline, not this script.
    draw_system_dataflow()
    draw_hardware_plate()
    draw_method_flow()
    print("done")
