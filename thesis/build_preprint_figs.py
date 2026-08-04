"""
Every figure thesis/01_IMAC_HashimotoLab_C2TB1701_AdrielImaranSantoso.tex
includes, in one place so the six stay visually consistent.

preprint_fig1 (system data flow), preprint_fig2 (hardware plate),
preprint_fig3 (method flow) and preprint_fig4 (object plate) are
hand-authored, not generated from trial data — fig2's and fig4's callouts are
drawn over the label-free photo crops in thesis/figures/photos/. Run this
module directly to (re)draw them, from anywhere (it locates the repo root
itself to reach both thesis/figures/ and the analysis package):

    python thesis/build_preprint_figs.py

preprint_fig5 (fragile survival + excess deformation) and preprint_fig6
(subjective ratings + favorite picks) ARE generated from trial data — they are
drawn from the same in-memory frames the analysis pipeline writes its CSVs
from, so a figure can never drift from the table beside it. They are plotted
by the pipeline itself (python -m analysis --preprint-figures DIR), which
imports plot_preprint_results/plot_preprint_likert from this file rather than
running it.

All six are drawn at exactly COLUMN_WIDTH_IN so \\includegraphics[width=
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
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

# This file lives in thesis/, a sibling of the analysis package, not inside
# it — so CONDITIONS needs an absolute import with the repo root on the path,
# not the package-relative one this module used before it moved.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
from analysis import CONDITIONS

OUT = os.path.join(REPO_ROOT, "thesis", "figures")

GRAY = "#9e9e9e"
BLUE = "#3b6ea5"
RED = "#c1543a"
DARK = "#333333"

# \the\columnwidth for the preprint (a4paper, 20mm margins, 6mm columnsep) is
# 233.31pt / 72.27 = 3.228in. Re-measure if the geometry ever changes.
COLUMN_WIDTH_IN = 3.228

# fig4's three object crops are placed at this one shared scale so their
# relative sizes on the page are the relative sizes on the bench.
PHOTO_SCALE_IN_PER_PX = 0.00098

# fig1-4 are plotted in bare data coordinates (see new_fig()) rather than
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

    The one arrow that leaves the cycle is the CSV tap on the right. It is
    there because the two touch-sensor quantities have different destinations
    and readers keep conflating them: dent depth is what the actuator renders
    (live, in the loop), deformation volume is only ever written to disk and
    becomes the grip-force proxy every number in the Results rests on. Drawing
    the tap is what makes that split visible without a sentence of prose.

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
        box(ax, 0.9, 1.9, 8.5, 2.4, "finger position")
        box(ax, 10.6, 1.9, 8.5, 2.4, "touch sensors")

        # All four curved the same rotational sense so the eye follows one cycle
        # rather than four independent spokes. They land close to the PC's own
        # centreline (not its outer corners) so the box reads as one pinched waist
        # of a figure-8, not four unrelated connection points along its edges.
        arrow(ax, (5.15, 14.1), (8.6, 10.2), label="pixel\ndistance", label_dx=-2.6,
              label_dy=0, rad=0.35)
        arrow(ax, (8.6, 8.0), (5.15, 4.3), label="open /\nclose", label_dx=-2.6,
              label_dy=0, rad=0.35)
        arrow(ax, (14.85, 4.3), (11.4, 8.0), label="dent depth,\ndeformation\nvolume",
              label_dx=3.2, label_dy=0, rad=0.35)
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

    Laid out in INCHES FROM THE TOP-LEFT rather than figure fractions (which
    every other figure here uses). Two panels stacked in one canvas means any
    change to one panel's height silently rescales the other's fractions;
    inches keep each panel's printed size fixed no matter what the canvas
    does, which is what made adding (b)'s component row a local edit instead
    of a re-derivation of every constant in (a).
    """
    with plt.rc_context(DIAGRAM_RC):
        fig_h = 4.28
        fig = plt.figure(figsize=(COLUMN_WIDTH_IN, fig_h))
        # The callout layer sits above the photo axes: with the default order a
        # photo's own axes background clips any leader that crosses it, leaving
        # stubs.
        ax = fig.add_axes([0, 0, 1, 1], zorder=10)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")
        ax.patch.set_visible(False)

        def fx(d):
            """Inches from the left edge -> figure fraction."""
            return d / COLUMN_WIDTH_IN

        def fy(d):
            """Inches BELOW the top edge -> figure fraction."""
            return 1.0 - d / fig_h

        def photo(name, x, top, w):
            """Draw figures/photos/<name>.png with its top-left corner at
            (x, top) inches, w inches wide. Returns its (x, top, w, h) in
            inches."""
            img = plt.imread(f"{OUT}/photos/{name}.png")
            h = w * img.shape[0] / img.shape[1]
            a = fig.add_axes([fx(x), fy(top + h), w / COLUMN_WIDTH_IN, h / fig_h], zorder=1)
            a.axis("off")
            a.imshow(img, interpolation="antialiased")
            return (x, top, w, h)

        def at(rect, u, v):
            """Point (u, v) in a photo's own fractional coordinates, v from the
            top, as a figure-fraction point."""
            x, top, w, h = rect
            return (fx(x + u * w), fy(top + v * h))

        def callout(x, y, text, tip, ha="center", va="bottom"):
            """A 7pt bold label at (x, y) inches with a hairline leader to `tip`."""
            ax.text(fx(x), fy(y), text, ha=ha, va=va, fontsize=7.0, fontweight="bold",
                    color=DARK, zorder=4, linespacing=1.2)
            pad = 0.043 if va == "top" else (-0.043 if va == "bottom" else 0)
            anchor = (fx(x + (0.026 if ha == "left" else -0.026 if ha == "right" else 0)),
                      fy(y + pad))
            ax.add_patch(FancyArrowPatch(anchor, tip, arrowstyle="-", linewidth=1.0,
                                          color=DARK, shrinkA=3, shrinkB=2, zorder=4))

        # --- Panel (a) -----------------------------------------------------
        group_style = dict(boxstyle="round,pad=0.004,rounding_size=0.02", linewidth=1.0,
                            edgecolor=GRAY, facecolor="none", linestyle=(0, (4, 3)), zorder=0)
        ax.add_patch(FancyBboxPatch((fx(0.048), fy(2.14)), fx(1.533), (2.14 - 0.33) / fig_h,
                                    **group_style))
        ax.add_patch(FancyBboxPatch((fx(1.662), fy(2.14)), fx(1.517), (2.14 - 0.33) / fig_h,
                                    **group_style))
        ax.text(fx(0.123), fy(0.33), "USER", fontsize=6.6, fontweight="bold", color=GRAY,
                family="monospace", va="center", backgroundcolor="white", zorder=1)
        ax.text(fx(1.737), fy(0.33), "GRIPPER", fontsize=6.6, fontweight="bold", color=GRAY,
                family="monospace", va="center", backgroundcolor="white", zorder=1)
        ax.text(fx(0.048), fy(0.05), "(a)", fontsize=7.5, fontweight="bold", color=DARK,
                va="top")

        hand = photo("wearable_hand", 0.175, 0.490, 0.850)
        cam = photo("camera", 0.300, 1.800, 0.950)
        # x=1.75 rather than hard against the GRIPPER box's 1.662 edge: at the
        # old 1.685 the gripper's shadow all but touched the dashed rule.
        grip = photo("gripper", 1.810, 0.550, 0.850)
        photo("touch_sensor", 2.720, 1.418, 0.291)

        callout(0.980, 0.620, "wearable\ndevice", at(hand, 0.55, 0.30), ha="left", va="center")
        callout(0.700, 1.690, "hand-tracking\ncamera", at(cam, 0.10, 0.10), ha="left", va="bottom")
        callout(2.500, 0.500, "fixture", at(grip, 0.33, 0.05), ha="left", va="top")
        callout(2.500, 0.800, "object", at(grip, 0.43, 0.38), ha="left", va="top")
        # The sensor is called out by the inset itself, so the leader runs from
        # the inset to the fingertip it magnifies and the label just titles the
        # inset.
        ax.text(fx(2.855), fy(1.350), "touch\nsensor", ha="center", va="bottom", fontsize=7.0,
                fontweight="bold", color=DARK, zorder=4, linespacing=1.2)
        ax.add_patch(FancyArrowPatch((fx(2.760), fy(1.574)), at(grip, 0.62, 0.46),
                                      arrowstyle="-", linewidth=1.0, color=DARK,
                                      shrinkA=3, shrinkB=2, zorder=4))

        # --- Panel (b) -----------------------------------------------------
        # Two rows per actuator: worn on the hand, then the part(s) it is made
        # of. The EM needs three photos because it only exists assembled --
        # base, magnet and cap are separate pieces -- while the LRA is a
        # single sealed module, so the asymmetry is the point rather than an
        # inconsistency.
        ax.plot([fx(0.048), fx(3.180)], [fy(2.236)] * 2, color=GRAY, linewidth=0.8,
                linestyle=(0, (4, 3)), clip_on=False)
        ax.text(fx(0.048), fy(2.350), "(b)", fontsize=7.5, fontweight="bold", color=DARK,
                va="top")
        ax.text(fx(0.888), fy(2.400), "LRA", fontsize=7.5, fontweight="bold", color=DARK,
                ha="center", va="top")
        ax.text(fx(2.340), fy(2.400), "EM", fontsize=7.5, fontweight="bold", color=DARK,
                ha="center", va="top")
        photo("lra_hand", 0.355, 2.650, 1.065)
        photo("em_hand", 1.808, 2.670, 1.065)

        # One shared inches-per-pixel scale across all four component crops,
        # for the same reason fig4 shares one: they were shot together, so
        # sizing each to fill its own slot would invent size differences. The
        # magnet really is that much smaller than the base.
        part_scale = 0.45 / 328          # tallest part (em_base) -> 0.45in
        parts_top = 3.664
        ax.text(fx(0.920), fy(4.130), "vibration motor", fontsize=6.5, fontweight="bold", color=DARK,
                ha="center", va="top")
        photo("lra_module", 0.888 - 688 * part_scale / 2,
              parts_top + (0.45 - 288 * part_scale), 728 * part_scale)

        # base -> magnet -> cap, left to right, in assembly order. Every
        # number here is an explicit inch coordinate so each part and each
        # word can be nudged on its own -- an earlier version swept them out
        # of one loop with a shared gap, where moving one part shifted the
        # two after it and the labels came along for the ride.
        #
        # The widths below all came from part_scale above, i.e. ONE shared
        # inches-per-pixel factor, which is what makes the magnet look as
        # small as it really is next to the base. Resizing a single part by
        # hand breaks that comparison -- to rescale the row, change
        # part_scale and re-derive all three.
        #
        # Tops differ because the row is bottom-aligned on 3.664 + 0.45: the
        # parts sat on the same surface, and a shared baseline is what lets
        # the eye read their heights against each other.
        em_parts = [
            # stem,        photo x, photo top, photo w, label,    label x, label y
            ("em_base",      1.720,     3.660,   0.495, "base",     1.875,   4.135),
            ("em_magnet",    2.340,     3.800,   0.165, "magnet",   2.430,   4.135),
            ("em_cap",       2.711,     3.660,   0.285, "cap",      2.850,   4.135),
        ]
        for name, px, ptop, pw, label, lx, ly in em_parts:
            photo(name, px, ptop, pw)
            ax.text(fx(lx), fy(ly), label, ha="center", va="top",
                    fontsize=6.6, fontweight="bold", color=DARK, zorder=4)

        # dpi matters here even though fig1/fig3 don't pass one: those two are
        # pure vector shapes, but fig2 embeds raster photos, and savefig's
        # default dpi (rcParams["figure.dpi"], 100) is what matplotlib
        # rasterises them at inside the .eps -- well below print quality.
        # \includegraphics names the .eps, not the .png, so leaving this off
        # left the photos LaTeX actually places noticeably blurrier than the
        # .png sibling ever was.
        fig.savefig(f"{OUT}/preprint_fig2.eps", dpi=400)
        fig.savefig(f"{OUT}/preprint_fig2.png", dpi=400)
        plt.close(fig)


# ---------------------------------------------------------------------------
# preprint_fig3: method flow
# ---------------------------------------------------------------------------

def draw_method_flow():
    """Three boxes down the trunk, then one fork.

    The earlier seven-box version spent four of them on arithmetic (22
    participants -> 3 conditions -> 2 objects x 5 grasps -> 660 trials), which
    a reader can do in their head from one line, and it left the fork looking
    like an afterthought. The fork is the actual shape of the study -- every
    trial produces a number AND a rating, and the Results section is written
    in exactly those two halves -- so the two branches are named OBJECTIVE and
    SUBJECTIVE outright and keep the pale LRA/EM condition tints that set them
    apart from the shared trunk.

    Each branch carries WHEN it is collected, because the fork otherwise reads
    as though both happen at the same moment: the objective numbers come off
    every grasp, but the survey is filled in once, at the very end, after a
    participant has been through all three conditions. Without that line the
    chart is a decomposition of the study wearing a flowchart's arrows, and a
    reader following it as a sequence in time is misled at exactly the point
    the arrows split.
    """
    with plt.rc_context(DIAGRAM_RC):
        # y is kept at the same units-per-inch as x (10 units / COLUMN_WIDTH_IN)
        # so the boxes are not silently squashed when the canvas height changes.
        fig, ax = new_fig(COLUMN_WIDTH_IN, 2.37, (0, 10), (0.15, 7.5))

        b1 = box(ax, 0.6, 5.60, 8.8, 1.45,
                 "22 participants, each trying\nall 3 conditions in this order:\n"
                 "Vision only → LRA → EM")
        b2 = box(ax, 0.6, 3.60, 8.8, 1.45,
                 "Per condition: 2 object classes\n(fragile, deformable) × 5 grasps\n"
                 "→ 660 trials in total")

        # Both branches stay at six lines, the timing subtitle paying for
        # itself out of wording the subtitle makes redundant -- so naming when
        # each is collected costs the figure no height.
        b3 = box(ax, 0.3, 0.60, 4.35, 2.40,
                 "OBJECTIVE\n(every grasp)\n\nDeformation volume\n"
                 "(total and excess),\ndent depth, survival",
                 fontsize=6.9, facecolor="#eaf1f8")
        b4 = box(ax, 5.35, 0.60, 4.35, 2.40,
                 "SUBJECTIVE\n(after all trials)\n\nRated all 3 conditions\n"
                 "on 4 questions, then\nchose a favorite",
                 fontsize=6.9, facecolor="#f2ede7")

        arrow(ax, edge_point(b1, "bottom"), edge_point(b2, "top"))
        arrow(ax, (2.5, 3.60), edge_point(b3, "top"))
        arrow(ax, (7.5, 3.60), edge_point(b4, "top"))

        fig.savefig(f"{OUT}/preprint_fig3.eps")
        fig.savefig(f"{OUT}/preprint_fig3.png", dpi=200)
        plt.close(fig)


# ---------------------------------------------------------------------------
# preprint_fig4: the two object classes
# ---------------------------------------------------------------------------

def draw_object_plate():
    """What "fragile" and "deformable" actually looked like on the bench.

    Two panels go to the fragile class and one to the deformable class
    because fragile is the class with a failure to show: (a) and (b) are the
    same egg before and after, which is the entire meaning of "survival rate"
    in the Results. The cube has no equivalent second state -- that IS the
    finding -- so it gets one panel.

    Captions sit above their photo. (c) has no wording of its own --
    "DEFORMABLE" directly above it already names the class, and the object
    is unambiguous on sight, so "foam cube" repeated the group label without
    adding information.

    Laid out in INCHES FROM THE TOP-LEFT, like draw_hardware_plate(): every
    photo gets its own (x, top, pixel width, pixel height) and every caption
    its own (x, y), so any one of them can be nudged without the others
    moving. Widths still come from ONE shared inches-per-pixel scale
    (PHOTO_SCALE_IN_PER_PX), so the cube is honestly smaller on the page, not
    just photographed smaller -- resizing a single photo's PIXEL dims here
    would break that comparison. Only POSITION is free to move per photo.

    Grouped with the same dashed-GRAY boxes fig1 and fig2 use for USER /
    GRIPPER, so the plate reads as part of the same set.
    """
    with plt.rc_context(DIAGRAM_RC):
        # A photo's own INCH size is its pixel count x PHOTO_SCALE_IN_PER_PX,
        # fixed regardless of fig_h -- so fig_h alone controls how much
        # breathing room surrounds the same-sized photos. 1.30in previously
        # tried left the egg with plenty of room but wasted canvas below the
        # box and clipped the group label at the top; 1.14in below is sized
        # to the actual margins laid out beneath it, with none left over.
        fig_h = 1.14
        fig = plt.figure(figsize=(COLUMN_WIDTH_IN, fig_h))
        ax = fig.add_axes([0, 0, 1, 1], zorder=10)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")
        ax.patch.set_visible(False)

        def fx(d):
            """Inches from the left edge -> figure fraction."""
            return d / COLUMN_WIDTH_IN

        def fy(d):
            """Inches BELOW the top edge -> figure fraction."""
            return 1.0 - d / fig_h

        # stem,                 x,     top,   px_w, px_h, caption,      cap_x,  cap_y
        panels = [
            ("object_fragile",    0.469,  0.300, 511, 750, "(a) intact",  0.719,  0.160),
            ("object_broken",     1.244,  0.300, 515, 753, "(b) broken",  1.496,  0.160),
            ("object_deformable", 2.298,  0.520, 471, 494, "(c)",         2.528,  0.160),
        ]

        for stem, x, top, px_w, px_h, text, cap_x, cap_y in panels:
            w_in = px_w * PHOTO_SCALE_IN_PER_PX
            h_in = px_h * PHOTO_SCALE_IN_PER_PX
            a = fig.add_axes([fx(x), fy(top + h_in), fx(w_in), h_in / fig_h], zorder=1)
            a.axis("off")
            a.imshow(plt.imread(f"{OUT}/photos/{stem}.png"), interpolation="antialiased")
            ax.text(fx(cap_x), fy(cap_y), text, ha="center", va="top", fontsize=7.0,
                    fontweight="bold", color=DARK, zorder=4)

        # Each group's dashed box, sized by hand to clear the tallest photo
        # in it plus its caption -- not computed, since every position above
        # is now a literal too. Widen these four numbers per group if a photo
        # or caption is moved and starts touching its border.
        group_style = dict(boxstyle="round,pad=0.004,rounding_size=0.02", linewidth=1.0,
                            edgecolor=GRAY, facecolor="none", linestyle=(0, (4, 3)), zorder=0)
        boxes = [
            # name,          x0,    top,   x1,    bottom   (inches)
            ("FRAGILE",      0.420, 0.050, 1.800, 1.090),
            ("DEFORMABLE",   2.250, 0.050, 2.810, 1.090),
        ]
        for name, x0, top, x1, bottom in boxes:
            ax.add_patch(FancyBboxPatch((fx(x0), fy(bottom)), fx(x1 - x0), (bottom - top) / fig_h,
                                        **group_style))
            # Explicit tight pad rather than backgroundcolor=: that shortcut
            # pads the white rectangle by 0.3*fontsize on every side, which
            # is enough to paint over the photo below -- the label lives on
            # the zorder=10 annotation axes, above the photos.
            ax.text(fx(x0 + 0.06), fy(top), name, fontsize=6.6, fontweight="bold",
                    color=GRAY, family="monospace", va="center", zorder=1,
                    bbox=dict(facecolor="white", edgecolor="none", pad=0.5))

        # See draw_hardware_plate()'s note on this: fig4 also embeds raster
        # photos, so the .eps needs an explicit dpi to match its .png sibling
        # -- matplotlib's unset default (100) is what LaTeX had actually been
        # printing until this was added.
        fig.savefig(f"{OUT}/preprint_fig4.eps", dpi=400)
        fig.savefig(f"{OUT}/preprint_fig4.png", dpi=400)
        plt.close(fig)


# ---------------------------------------------------------------------------
# preprint_fig5 / preprint_fig6 — drawn from trial data by the analysis
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
    """Preprint Fig. 5 — fragile objects, the OBJECTIVE half of the Results:
    (a) pooled survival rate per condition, (b) per-participant excess
    deformation (deformation volume that kept rising after the dent had
    already stopped getting deeper).

    Labelled "deformation" rather than "force" throughout: the underlying
    column is a deformation-volume proxy that was never calibrated against a
    load cell, so naming it force would claim newtons the rig cannot supply.
    Fig. 6's "Force perception" is deliberately NOT renamed -- that is a
    survey item asking what the participant felt, not a sensor reading.

    Args:
        breakage: {condition: (survival rate, n trials)} from
            write_fragile_breakage_summary().
        reduced_df: Per-participant medians from
            reduce_to_participant_condition_object().
        out_dir: Directory to write preprint_fig5.png into.
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
    # No axis title on either panel: at this size the rotated label ate width
    # the plot needed, and each panel's own title plus the caption already
    # name the quantity and its units. The tick numbers stay.
    ax_a.set_title("(a) Survival rate (%)", fontsize=6.5)

    # +1 offset keeps exact-zero excess-force trials visible on a log axis.
    excess = [fragile.loc[fragile["condition"] == c, "force_overshoot_proxy"]
              .dropna().to_numpy() + 1.0 for c in CONDITIONS]
    box_ = ax_b.boxplot(excess, widths=0.55, showfliers=False, patch_artist=True)
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
    for i, values in enumerate(excess, start=1):
        ax_b.plot([i] * len(values), values, "o", ms=1.8,
                  color=_blend("black", 0.45), mew=0)
    ax_b.set_yscale("log")
    # Units live in the caption, not here: "(b) Excess deformation (a.u.)"
    # left only ~4px of right margin on this panel, close enough to the
    # edge that a different matplotlib could clip it outright.
    ax_b.set_title("(b) Excess deformation", fontsize=6.5)

    for ax in (ax_a, ax_b):
        ax.set_xticks(range(1, len(CONDITIONS) + 1) if ax is ax_b else range(len(CONDITIONS)))
        ax.set_xticklabels([LABELS[c].replace("\n", " ") for c in CONDITIONS], fontsize=6.5)
        ax.tick_params(length=2, pad=1.5)
        ax.tick_params(axis="y", labelsize=6.5)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
    _save(fig, os.path.join(out_dir, "preprint_fig5.png"))


def plot_preprint_likert(long_df, holm_by_pair, preference, out_dir):
    """Preprint Fig. 6 — the SUBJECTIVE half of the Results: (a) per-item
    ratings as violins with the individual participants over them, bracketed
    where a haptic condition beat visual-only, (b) how many participants named
    each condition their favorite.

    Violins rather than bare strips: with 22 participants on a 1-5 scale the
    points pile up on five discrete levels, so a strip plot shows WHERE the
    answers are but not HOW MANY are stacked at each level -- which is the
    whole claim being made. The points stay drawn on top, because a violin
    alone over 22 discrete samples implies a smooth distribution that is not
    really there.

    Args:
        long_df: Long-format ratings from load_likert_long().
        holm_by_pair: {(item, comparison): corrected p} from
            write_likert_friedman().
        preference: {question: (counts, chi-square p)} from
            write_likert_preference().
        out_dir: Directory to write preprint_fig6.png into.
    """
    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(COLUMN_WIDTH_IN, 1.15),
                                     gridspec_kw={"width_ratios": [2.85, 1.2]})
    rng = np.random.default_rng(0)

    for group, (item, _) in enumerate(PREPRINT_ITEMS):
        for condition in CONDITIONS:
            values = long_df.loc[(long_df["item"] == item)
                                 & (long_df["condition"] == condition),
                                 "value"].dropna().to_numpy(dtype=float)
            if len(values) == 0:
                continue
            centre = group + _OFFSETS[condition]
            # An item everyone answered identically has no width to draw and
            # makes violinplot raise on the singular covariance.
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
    # Floor dropped below the 1 of the scale purely to open an empty band for
    # the legend: nobody can rate below 1, so the strip under the data is
    # dead space the legend can have without covering a single point.
    ax_a.set_ylim(-0.35, 6.6)
    # No rotated axis title, as in fig5 -- the tick numbers plus the panel
    # title carry it, and the label only cost the plot width.
    # "Holm-corrected" named the procedure without telling a reader outside
    # the field what it buys them; all they need is that the stars already
    # account for four items being tested at once.
    ax_a.set_title("(a) Rating (1\N{EN DASH}5) vs. visual only", fontsize=6.5)
    # Inside the axes, not above it. Sitting the legend over the panel pushed
    # (a)'s title up by its full height, leaving the two panel titles on
    # different lines; the plot's own top-left is empty (nobody rates below
    # ~1 on every item at once) so the legend costs nothing there.
    ax_a.legend(handles=[plt.Line2D([], [], marker="s", ls="", ms=3,
                                    color=COLORS[c], label=LABELS[c].replace("\n", " "))
                         for c in CONDITIONS],
                fontsize=5.5, loc="lower left", ncol=3, frameon=False,
                handletextpad=0.2, columnspacing=0.8, borderaxespad=0.0)

    # One question, one bar per condition. The stacked two-question version
    # this replaces asked the reader to decode a stack, a second question
    # ("best contact") the body text never discusses, and the phrase "forced
    # choice" -- three pieces of overhead for a panel whose whole content is
    # "17 of 22 picked the LRA".
    counts, chi2_p = preference[PREPRINT_PREFERENCES[0][0]]
    present = [c for c in CONDITIONS if c in counts]
    ax_b.bar(range(len(present)), [counts[c] for c in present],
             color=[COLORS[c] for c in present], width=0.62)
    for i, condition in enumerate(present):
        ax_b.text(i, counts[condition] + 0.5, str(counts[condition]),
                  ha="center", va="bottom", fontsize=6)

    ax_b.set_xticks(range(len(present)))
    # Two lines for "Visual only", as in fig5: three labels across ~1in run
    # together on one line.
    ax_b.set_xticklabels([LABELS[c] for c in present], fontsize=5.5)
    ax_b.set_ylim(0, max(counts.values()) * 1.28)
    # Short enough not to run off the narrow panel, and plainer than the
    # "forced choice" it replaces.
    ax_b.set_title("(b) Favorite", fontsize=6.5)
    for ax in (ax_a, ax_b):
        ax.tick_params(length=2, pad=1.5)
        ax.tick_params(axis="y", labelsize=6.5)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
    _save(fig, os.path.join(out_dir, "preprint_fig6.png"))


def _save(fig, path, pad=0.15):
    """Write `path` (.png, 300dpi) and its .eps sibling from one figure."""
    fig.tight_layout(pad=pad)
    base = os.path.splitext(path)[0]
    for out_path in (f"{base}.png", f"{base}.eps"):
        fig.savefig(out_path, dpi=300)
        print(f"Wrote {out_path}")


if __name__ == "__main__":
    # Only the four hand-authored figures: fig5/fig6 need real trial data
    # and are drawn by the analysis pipeline, not this script.
    draw_system_dataflow()
    draw_hardware_plate()
    draw_method_flow()
    draw_object_plate()
    print("done")
