"""One-off script: static schematic diagrams for the presentation handout.

These are hand-authored block diagrams (system data flow, feedback mapping,
method flow), not generated from trial data, so they don't go through the
analysis/figures.py data pipeline or its --preprint-figures CLI flag -- same
convention as the existing (script-less) thesis/figures/system_architecture.png.
Run directly: python analysis/make_diagrams.py

Writes into thesis/figures regardless of the current working directory.
"""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO_ROOT, "thesis", "figures")

GRAY = "#9e9e9e"
BLUE = "#3b6ea5"
RED = "#c1543a"
DARK = "#333333"

plt.rcParams.update({
    "font.size": 7.5,
    "axes.edgecolor": DARK,
    "text.color": DARK,
})


def box(ax, x, y, w, h, text, facecolor="white", edgecolor=DARK, fontsize=7.5, fontweight="bold"):
    b = FancyBboxPatch((x, y), w, h,
                        boxstyle="round,pad=0.02,rounding_size=0.08",
                        linewidth=1.1, edgecolor=edgecolor, facecolor=facecolor, zorder=2)
    ax.add_patch(b)
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
            fontsize=fontsize, fontweight=fontweight, color=DARK, zorder=3)
    return (x, y, w, h)


def arrow(ax, p0, p1, label=None, label_dx=0, label_dy=0.12, color=DARK, fontsize=6.6, style="-|>"):
    a = FancyArrowPatch(p0, p1, arrowstyle=style, mutation_scale=9,
                         linewidth=1.1, color=color, zorder=1, shrinkA=0, shrinkB=0)
    ax.add_patch(a)
    if label:
        mx, my = (p0[0] + p1[0]) / 2 + label_dx, (p0[1] + p1[1]) / 2 + label_dy
        ax.text(mx, my, label, ha="center", va="center", fontsize=fontsize,
                color=color, style="italic")


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


COLUMN_WIDTH_IN = 3.228

# ---------------------------------------------------------------------------
# Figure 1: system data flow
# ---------------------------------------------------------------------------
fig, ax = new_fig(COLUMN_WIDTH_IN, 2.05, (0, 10), (0, 6.35))

pc = box(ax, 3.6, 2.55, 2.8, 1.25, "HOST PC")
cam = box(ax, 0.2, 4.75, 3.5, 1.35, "Camera +\nhand tracking")
grip = box(ax, 6.3, 4.75, 3.5, 1.35, "Robot\ngripper")
sens = box(ax, 0.2, 0.25, 3.5, 1.35, "Touch sensors\n(fingertips)")
act = box(ax, 6.3, 0.25, 3.5, 1.35, "Wearable\nactuator\n(LRA or EM)", facecolor="#f2ede7")

arrow(ax, edge_point(cam, "bottom"), edge_point(pc, "top"), label="hand gap", label_dx=-0.75, label_dy=0.15)
arrow(ax, edge_point(pc, "top"), edge_point(grip, "bottom"), label="open/\nclose", label_dx=0.85, label_dy=0.15)
arrow(ax, edge_point(sens, "top"), edge_point(pc, "bottom"), label="dent\ndepth", label_dx=-0.75, label_dy=-0.15)
arrow(ax, edge_point(pc, "bottom"), edge_point(act, "top"), label="0\N{EN DASH}1\nintensity", label_dx=0.85, label_dy=-0.15)

fig.savefig(f"{OUT}/system_dataflow.eps")
fig.savefig(f"{OUT}/system_dataflow.png", dpi=200)
plt.close(fig)

# ---------------------------------------------------------------------------
# Figure 2: sensing-to-feedback mapping
# ---------------------------------------------------------------------------
fig, ax = new_fig(COLUMN_WIDTH_IN, 1.55, (0, 10), (0, 4.8))

dent = box(ax, 0.2, 1.7, 2.55, 1.4, "Dent depth\nmeasured\n(mm)")
norm = box(ax, 3.15, 1.7, 2.9, 1.4, "Mapped to a\n0\N{EN DASH}1 intensity\nvalue")
lra = box(ax, 6.5, 2.85, 3.3, 1.25, "LRA:\nstronger buzz", facecolor="#eaf1f8")
em = box(ax, 6.5, 0.6, 3.3, 1.25, "EM:\nfaster tapping", facecolor="#f2ede7")

arrow(ax, edge_point(dent, "right"), edge_point(norm, "left"))
arrow(ax, edge_point(norm, "right"), edge_point(lra, "left"))
arrow(ax, edge_point(norm, "right"), edge_point(em, "left"))
ax.text(5.6, 0.35, "capped at 1.0 mm (safety limit)", ha="center", va="center",
        fontsize=6.3, style="italic", color=DARK)

fig.savefig(f"{OUT}/feedback_mapping.eps")
fig.savefig(f"{OUT}/feedback_mapping.png", dpi=200)
plt.close(fig)

# ---------------------------------------------------------------------------
# Figure 3: method flow
# ---------------------------------------------------------------------------
fig, ax = new_fig(COLUMN_WIDTH_IN, 3.85, (0, 10), (2.2, 15.3))

b1 = box(ax, 1.0, 13.9, 8.0, 1.1, "22 participants", fontsize=8)
b2 = box(ax, 0.6, 11.6, 8.8, 1.5,
         "Each tries all 3 conditions,\nalways in this order:\nVision only → LRA → EM")
b3 = box(ax, 0.6, 9.3, 8.8, 1.5,
         "Each condition × 2 object classes\n(fragile, deformable) × 5 grasps")
b4 = box(ax, 2.4, 7.6, 5.2, 1.1, "660 trials total", fontsize=8)
b5 = box(ax, 0.4, 5.1, 9.2, 1.85,
         "From each trial: peak grip force,\npeak dent depth, excess force,\nforce reversals, and (fragile only)\nwhether it survived",
         fontsize=6.9)
b6 = box(ax, 0.3, 2.55, 4.35, 1.75, "Compare conditions:\ndifferent, or close\nenough to call\nequivalent?", fontsize=6.9, facecolor="#eaf1f8")
b7 = box(ax, 5.35, 2.55, 4.35, 1.75, "Participant ratings\n+ preferred\ncondition", fontsize=6.9, facecolor="#f2ede7")

arrow(ax, edge_point(b1, "bottom"), edge_point(b2, "top"))
arrow(ax, edge_point(b2, "bottom"), edge_point(b3, "top"))
arrow(ax, edge_point(b3, "bottom"), edge_point(b4, "top"))
arrow(ax, edge_point(b4, "bottom"), edge_point(b5, "top"))
arrow(ax, (2.5, 5.1), edge_point(b6, "top"))
arrow(ax, (7.5, 5.1), edge_point(b7, "top"))

fig.savefig(f"{OUT}/method_flow.eps")
fig.savefig(f"{OUT}/method_flow.png", dpi=200)
plt.close(fig)

print("done")
