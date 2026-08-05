"""Rebuilds the graduation-study presentation from the slide template.

    python thesis/build_slides.py

Reads thesis/template/deck_template.pptx — the pristine three-slide template
(title, contents, section divider) — duplicates its divider slide out to the
full deck, and writes:

    thesis/presentation_slide.pptx
    thesis/presentation_script.md

Both are generated from the SCRIPT table below, so the spoken script and the
slide notes can never drift apart. All geometry, palette and type come from the
template's own three slides; edit the template to restyle the whole deck.

Figure sources are thesis/figures/ — preprint_fig1 and 3-6 are used whole, and
the hardware plate (preprint_fig2) is cropped into its panels at build time, so
nothing here depends on generated files that are not in the repository.

Requires: python-pptx, Pillow.
"""
import os
import re
import shutil
import tempfile
import zipfile
from xml.dom import minidom

from PIL import Image
from pptx import Presentation
from pptx.util import Emu, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR
from pptx.enum.dml import MSO_LINE_DASH_STYLE

THESIS = os.path.dirname(os.path.abspath(__file__))
FIG = os.path.join(THESIS, "figures")
TEMPLATE = os.path.join(THESIS, "template", "deck_template.pptx")
OUT = os.path.join(THESIS, "presentation_slide.pptx")
SCRIPT_OUT = os.path.join(THESIS, "presentation_script.md")

N_SLIDES = 20               # 3 template slides + 17 duplicated dividers
DIVIDER_SLIDE = "slide3.xml"   # the template slide every content slide starts from

# ---------------------------------------------------------------- palette ---
DEEP = RGBColor(0x2C, 0x0E, 0x63)   # template title purple
MID = RGBColor(0x3E, 0x14, 0x85)    # template accent purple
INK = RGBColor(0x1A, 0x0A, 0x3D)    # template body ink
LAV = RGBColor(0xD9, 0xC9, 0xF5)    # template light lavender
CARD = RGBColor(0xF4, 0xF0, 0xFC)   # card fill, derived from LAV
GREY = RGBColor(0xF2, 0xF2, 0xF4)
MUTE = RGBColor(0x6B, 0x66, 0x7B)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
FONT = "Calibri"

# ------------------------------------------------------- template geometry ---
CL, CW = 900450, 7343100            # content band, from the template body box
CT, CB = 1405800, 4690000
GAP = 228600
COLW = (CW - GAP) // 2
CR = CL + CW

# =============================================================== script ======
# One source of truth: these become the slide notes and presentation_script.md.
SCRIPT = {}

SCRIPT[1] = ("Title", "0:00", """
Good afternoon. I am Adriel Santoso, from the Intelligent Control Systems Lab.

My graduation study asks a simple question: if you are driving a robot hand from
a distance, does giving your own fingers a sense of touch make you better at
picking up fragile things — and does it matter which kind of buzzer you use?
""")

SCRIPT[2] = ("Contents", "", """
Here is where we are going: the problem, the system, how the experiment was run,
what came out of it, and what it does and does not prove.
""")

SCRIPT[3] = ("Section: Introduction", "0:20", """
Let me start with why this is hard.
""")

SCRIPT[4] = ("The missing sense", "0:25", """
Think about picking up an egg. You do not calculate anything: receptors in your
skin report how hard you are squeezing within milliseconds, and you stop short of
cracking the shell.

Now take that away. In teleoperation — a surgeon at a console, a technician in a
glovebox — you see the object but feel nothing, so grip force has to be inferred
from how it looks. That works right up until the object does not visibly change
before it fails. Too little force and it slips; too much and you get the picture
on the right.

And the gripper cannot rescue you. The Robotiq 2F-85 estimates force from one
aggregate motor current — no contact distribution at all — and on my unit that
register reads zero milliamps regardless of contact.
""")

SCRIPT[5] = ("Two questions", "1:25", """
So the study asks two questions.

First: does touch feedback change how people grasp fragile and deformable
objects, compared with vision alone?

Second, and this is asked less often: does the actuator type matter? Most
published work picks one haptic device and compares it against a no-feedback
baseline. Here the whole sensing and control pipeline is held fixed, and the only
thing that changes is the hardware on the skin — a vibration motor at the finger
joints, or an electromagnetic pin at the fingertip.
""")

SCRIPT[6] = ("Section: System", "2:05", """
Here is the system.
""")

SCRIPT[7] = ("The control loop", "2:10", """
It is one closed loop with a human inside it.

Going down: a camera watches the operator's hand, MediaPipe gives me the pixel
distance between thumb tip and index tip, and that maps to a gripper opening sent
over Modbus at 25 hertz. The gripper mirrors your pinch — there is no joystick.

Coming back up: each jaw carries a soft tactile sensor. Fifteen times a second I
read how deeply the gel is dented, turn it into one number between zero and one,
and stream it to an ESP32 on the wrist.

The loop closes through the person: they feel the intensity rise and ease off.

Two guards. Closing is blocked once either sensor reads one millimetre of
indentation, which protects the sensor mount; and the actuators cut out if no
packet arrives for 200 milliseconds.
""")

SCRIPT[8] = ("Apparatus", "3:10", """
The hardware. On the left, the operator: a wrist unit carrying the driver board,
and the hand-tracking camera. On the right, the gripper with a plastic egg in the
fixture, and one tactile sensor pulled out so you can see it — about the size of
a sugar cube.
""")

SCRIPT[9] = ("Gel to intensity", "3:45", """
This is where the engineering actually lives: turning a squishy gel into a
number.

The sensor is a camera looking at the back of a soft gel pad under a calibrated
illumination pattern. Every frame it reconstructs a height map of the gel
surface; subtract the height map recorded with nothing touching it and you have
the deformation field. I take two quantities from that one field.

The first is the sum of absolute deformation over every pixel actually in contact
— more than a tenth of a millimetre. That is my grip-force proxy: monotonic in
normal force, but uncalibrated, because the gripper exposes no force sensor. So I
report arbitrary units, not newtons.

The second is the 99th-percentile depth in millimetres, and that is what the
operator feels: divide by a saturation depth, clip to zero-to-one. That
saturation depth is per object class — two millimetres for the egg, six tenths
for foam, which barely dents the gel and otherwise felt dead.

One consequence: the force scale is uncalibrated but monotonic, and every test
here is rank-based, so a scaling error cannot move a single p-value.
""")

SCRIPT[10] = ("Two actuators", "4:55", """
Two actuators render that number.

The LRA is a linear resonant actuator — the vibration motor in your phone. I
drive it with a bipolar carrier at 200 hertz and let intensity set the envelope,
so it buzzes harder as you squeeze. It sits on the proximal joints of the thumb
and index finger.

The EM is a bistable pin actuator on an H-bridge. A four-millisecond pulse throws
a pin into the skin and it latches mechanically, so it draws no power while held.
For continuous feedback I fire bursts and let intensity set the gap between them,
with a 35 millisecond floor to stay under the coil's thermal limit of about 120
switches a minute. It sits on the fingertips.

Note what I just said: the two conditions differ in technology and in placement.
That was deliberate — each is mounted where it works best — but hold on to it,
because it comes back in the discussion.
""")

SCRIPT[11] = ("Section: Method", "6:00", """
The experiment.
""")

SCRIPT[12] = ("Protocol", "6:05", """
Twenty-two participants, each doing all three conditions in the fixed order:
vision only, then LRA, then EM. Two object classes, five grasps each — 660 trials
in total.

Fragile is a hollow plastic egg that pops apart at the seam: it fails suddenly,
like the real thing, but I can reassemble it. Deformable is a foam cube, which
yields gradually and never breaks. Afterwards each participant rated the three
conditions and picked a favourite.
""")

SCRIPT[13] = ("Metrics and statistics", "6:50", """
Four objective measures. Peak deformation volume is how hard they squeezed at the
worst moment.

Excess deformation is the interesting one. Once the gel is fully dented the depth
signal plateaus, and from that moment squeezing harder changes nothing the
operator can feel. Excess deformation is the force that goes in after that point:
wasted, and potentially destructive, effort.

Grip adjustments counts direction reversals in the force after that plateau —
squeeze, ease, squeeze again — somebody hunting for a grip instead of holding
steady. And survival: did the egg come out intact.

Statistically: Friedman across the three conditions, then Wilcoxon signed-rank
pairwise with Holm correction. Medians, not means — one crushed egg should not
move the average.
""")

SCRIPT[14] = ("Section: Results", "7:40", """
Results.
""")

SCRIPT[15] = ("Objective results", "7:45", """
Fragile objects. Each column is the median participant, and for the first three
rows lower is better.

Peak squeeze drops with feedback. Excess deformation — the wasted squeezing —
falls from about 1500 units to 170 with the LRA, roughly ninefold, at p equals
0.019 after correction. Grip adjustments drop from seven to two with the EM, p
equals 0.021. The two actuators help in different ways: the LRA stops you
squeezing, the EM stops you fidgeting.

And the outcome people care about: egg survival rises from 62 percent with vision
only to 81 with the LRA and 78 with the EM, Friedman p equals 0.004, both beating
the baseline after correction.

Two honest negatives. Peak dent depth barely moves, because my one-millimetre
safety cutoff caps it first. And deformable objects showed no reliable change on
anything — foam gives you no sharp failure to avoid.
""")

SCRIPT[16] = ("Subjective results", "8:50", """
Subjectively it is not close. On force perception, grasp confidence and contact
detection, both haptic conditions beat vision only at p below 0.001, surviving
Holm correction.

But no single question separated the LRA from the EM — every pairwise comparison
between them sits above 0.2. And yet, asked to pick a favourite, 17 of 22 chose
the LRA. People had a clear preference they could not articulate on any of my
rating items.
""")

SCRIPT[17] = ("Section: Discussion", "9:20", """
So what does this mean.
""")

SCRIPT[18] = ("Limitations", "9:25", """
What I am comfortable claiming: tactile feedback reduces the squeezing the
operator cannot feel, reduces regrip hunting, and raises survival on fragile
objects — and users perceive it and want it.

What I am not comfortable claiming is that the LRA is the better actuator.
Technology and placement are bundled: I never tested a fingertip LRA or a
joint-mounted EM. Worse, the fingertip EM hardware sits on the very landmarks the
hand tracker uses, so I had to lower the detection thresholds, and its thickness
changed the usable pinch range — the LRA preference may be smoother control, not
better sensation. And the condition order was fixed, so practice and fatigue are
inseparable from condition.

On measurement: force is in arbitrary units, the millimetre scale rests on one
ball calibration never checked against a gauge, and latency still needs a bench
measurement.
""")

SCRIPT[19] = ("Section: Conclusion", "10:00", """
To close.
""")

SCRIPT[20] = ("Conclusion", "10:05", """
Three things. Touch feedback made remote grasping of fragile objects measurably
safer: about nine times less unfelt squeezing, and survival up from 62 to around
80 percent. It is what operators want — 21 of 22 preferred a haptic condition
over vision alone. And which actuator is better is still open; answering it needs
a study that separates technology from placement.

Next: spatial feedback instead of one number per finger, force calibrated into
newtons, and a bench-measured latency figure.

Thank you — happy to take questions.
""")


# =============================================================== helpers =====
def tidy(s):
    """Collapses the triple-quoted script blocks into paragraphs."""
    paras = [" ".join(p.split()) for p in s.strip().split("\n\n")]
    return "\n\n".join(p for p in paras if p)


def title_shape(slide):
    return slide.shapes[0]


def body_shape(slide):
    return slide.shapes[4]


def set_title(slide, text):
    """Replaces the title run text, keeping the template's run formatting."""
    tf = title_shape(slide).text_frame
    p = tf.paragraphs[0]
    runs = p.runs
    runs[0].text = text
    for r in runs[1:]:
        r._r.getparent().remove(r._r)


def drop_body(slide):
    sp = body_shape(slide)._element
    sp.getparent().remove(sp)


def notes(slide, text):
    slide.notes_slide.notes_text_frame.text = text


def textbox(slide, x, y, w, h, anchor=MSO_ANCHOR.TOP):
    tb = slide.shapes.add_textbox(Emu(x), Emu(y), Emu(w), Emu(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    return tb


def para(tf, first, runs, size=13, color=INK, bold=False, space_before=0,
         space_after=4, align=PP_ALIGN.LEFT, line=100, hang=0):
    """Adds a paragraph made of (text, bold, color, size) run tuples."""
    p = tf.paragraphs[0] if first else tf.add_paragraph()
    p.alignment = align
    p.space_before = Pt(space_before)
    p.space_after = Pt(space_after)
    p.line_spacing = line / 100.0
    if hang:
        pPr = p._p.get_or_add_pPr()
        pPr.set("marL", str(hang))
        pPr.set("indent", str(-hang))
    if isinstance(runs, str):
        runs = [(runs, bold, color, size)]
    for text, b, c, s in runs:
        r = p.add_run()
        r.text = text
        f = r.font
        f.name = FONT
        f.size = Pt(s)
        f.bold = b
        f.color.rgb = c
    return p


def block(slide, x, y, w, h, items, anchor=MSO_ANCHOR.TOP):
    """items: list of dicts -> {runs|text, size, color, bold, space_*, align}."""
    tf = textbox(slide, x, y, w, h, anchor).text_frame
    for i, it in enumerate(items):
        it = dict(it)
        runs = it.pop("runs", None)
        if runs is None:
            runs = it.pop("text")
        else:
            it.pop("text", None)
        para(tf, i == 0, runs, **it)
    return tf


def card(slide, x, y, w, h, fill=CARD, line=LAV, radius=0.08):
    sh = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                                Emu(x), Emu(y), Emu(w), Emu(h))
    sh.adjustments[0] = radius
    sh.fill.solid()
    sh.fill.fore_color.rgb = fill
    if line is None:
        sh.line.fill.background()
    else:
        sh.line.color.rgb = line
        sh.line.width = Pt(0.75)
    sh.shadow.inherit = False
    sh.text_frame.text = ""
    return sh


def chip(slide, x, y, w, h, label, body, fill=CARD):
    card(slide, x, y, w, h, fill=fill)
    block(slide, x + 137160, y + 91440, w - 274320, h - 182880, [
        dict(text=label, size=12.5, bold=True, color=MID, space_after=2),
        dict(text=body, size=11, color=INK, space_after=0, line=105),
    ])


def pic(slide, path, x, y, w=None, h=None):
    """Places an image fitted into (w or h), returning the placed shape."""
    iw, ih = Image.open(path).size
    if w is None:
        w = int(h * iw / ih)
    if h is None:
        h = int(w * ih / iw)
    return slide.shapes.add_picture(path, Emu(int(x)), Emu(int(y)),
                                    Emu(int(w)), Emu(int(h)))


def pic_fit(slide, path, x, y, boxw, boxh, center=True):
    """Fits an image inside a box, centred, and returns (x, y, w, h)."""
    iw, ih = Image.open(path).size
    scale = min(boxw / iw, boxh / ih)
    w, h = int(iw * scale), int(ih * scale)
    px = x + (boxw - w) // 2 if center else x
    py = y + (boxh - h) // 2 if center else y
    slide.shapes.add_picture(path, Emu(px), Emu(py), Emu(w), Emu(h))
    return px, py, w, h


def caption(slide, x, y, w, text, align=PP_ALIGN.CENTER):
    block(slide, x, y, w, 200000, [
        dict(text=text, size=9.5, color=MUTE, align=align, space_after=0)])


def arrow(slide, x, y, w, h):
    sh = slide.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, Emu(x), Emu(y),
                                Emu(w), Emu(h))
    sh.fill.solid()
    sh.fill.fore_color.rgb = LAV
    sh.line.fill.background()
    sh.shadow.inherit = False
    return sh


def divider(slide, title, subtitle, numeral):
    set_title(slide, title)
    drop_body(slide)
    block(slide, CL, 2100000, CW - 1200000, 900000, [
        dict(text=subtitle, size=17, color=MID, bold=False, space_after=0,
             line=120)])
    block(slide, CR - 1200000, 1900000, 1200000, 1000000, [
        dict(text=numeral, size=72, color=LAV, bold=True,
             align=PP_ALIGN.RIGHT, space_after=0)])


# ================================================================ build ======
# ======================================================= deck preparation ====
# The template ships three slides; every content slide in the finished deck is
# a copy of its section-divider slide, so the title rule, the paired logos and
# the slide-number placeholder stay identical across the deck. Duplicating a
# slide means copying the part, its rels, the content-type override and the
# entry in <p:sldIdLst> — python-pptx cannot do this, so it is done here on the
# unpacked package. The notesSlide relationship is deliberately dropped from
# the copies: each new slide gets its own notes when notes are written to it.
NS_CT = "http://schemas.openxmlformats.org/package/2006/content-types"
NS_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
REL_SLIDE = ("http://schemas.openxmlformats.org/officeDocument/2006/"
             "relationships/slide")
REL_NOTES = ("http://schemas.openxmlformats.org/officeDocument/2006/"
             "relationships/notesSlide")


def _next_free(existing, pattern, start=1):
    n = start
    while pattern % n in existing:
        n += 1
    return n


def duplicate_slide(root, source):
    """Copies ppt/slides/<source> into the package, returning the new name."""
    slide_dir = os.path.join(root, "ppt", "slides")
    taken = set(os.listdir(slide_dir))
    new_name = "slide%d.xml" % _next_free(taken, "slide%d.xml")
    shutil.copyfile(os.path.join(slide_dir, source),
                    os.path.join(slide_dir, new_name))

    # slide rels: copy, minus the notes slide (each copy gets fresh notes)
    rels_dir = os.path.join(slide_dir, "_rels")
    src_rels = os.path.join(rels_dir, source + ".rels")
    if os.path.exists(src_rels):
        doc = minidom.parse(src_rels)
        for rel in list(doc.getElementsByTagNameNS(NS_REL, "Relationship")):
            if rel.getAttribute("Type") == REL_NOTES:
                rel.parentNode.removeChild(rel)
        with open(os.path.join(rels_dir, new_name + ".rels"), "wb") as fh:
            fh.write(doc.toxml("UTF-8"))

    # content-type override (attribute order in the template is not assumed)
    ct_path = os.path.join(root, "[Content_Types].xml")
    ct = open(ct_path, encoding="utf-8").read()
    override = ('<Override PartName="/ppt/slides/%s" ContentType='
                '"application/vnd.openxmlformats-officedocument.'
                'presentationml.slide+xml"/>') % new_name
    ct = ct.replace("</Types>", override + "</Types>")
    open(ct_path, "w", encoding="utf-8").write(ct)

    # presentation rels + <p:sldIdLst> entry
    pres_rels_path = os.path.join(root, "ppt", "_rels", "presentation.xml.rels")
    pres_rels = open(pres_rels_path, encoding="utf-8").read()
    rid = "rId%d" % _next_free(set(re.findall(r'Id="(rId\d+)"', pres_rels)),
                               "rId%d")
    pres_rels = pres_rels.replace(
        "</Relationships>",
        '<Relationship Id="%s" Type="%s" Target="slides/%s"/></Relationships>'
        % (rid, REL_SLIDE, new_name))
    open(pres_rels_path, "w", encoding="utf-8").write(pres_rels)

    pres_path = os.path.join(root, "ppt", "presentation.xml")
    pres = open(pres_path, encoding="utf-8").read()
    sld_id = max(int(i) for i in re.findall(r'<p:sldId id="(\d+)"', pres)) + 1
    pres = pres.replace(
        "</p:sldIdLst>",
        '<p:sldId id="%d" r:id="%s"/></p:sldIdLst>' % (sld_id, rid))
    open(pres_path, "w", encoding="utf-8").write(pres)
    return new_name


def build_base(workdir):
    """Unpacks the template, grows it to N_SLIDES, repacks it."""
    root = os.path.join(workdir, "package")
    with zipfile.ZipFile(TEMPLATE) as zf:
        zf.extractall(root)
    n_existing = len(os.listdir(os.path.join(root, "ppt", "slides"))) - 1
    for _ in range(N_SLIDES - n_existing):
        duplicate_slide(root, DIVIDER_SLIDE)
    base = os.path.join(workdir, "base.pptx")
    with zipfile.ZipFile(base, "w", zipfile.ZIP_DEFLATED) as zf:
        for folder, _, files in os.walk(root):
            for name in files:
                full = os.path.join(folder, name)
                zf.write(full, os.path.relpath(full, root))
    return base


def crop_panels(workdir):
    """Cuts the hardware plate (preprint_fig2) into the panels the deck uses.

    Slides 8 and 10 show the apparatus and the two actuators separately, so
    the plate's (a)/(b) sub-labels are cropped away here rather than being
    edited into the figure — preprint_fig2.png stays the preprint's copy.
    """
    plate = Image.open(os.path.join(FIG, "preprint_fig2.png"))
    w, _ = plate.size
    out = {}
    panels = {
        "apparatus": plate.crop((0, 88, w, 900)),          # (a), label removed
        "lra": plate.crop((95, 1015, 625, 1712)),          # (b) left half
        "em": plate.crop((655, 1015, 1225, 1712)),         # (b) right half
    }
    for name, img in panels.items():
        path = os.path.join(workdir, name + ".png")
        img.save(path)
        out[name] = path
    return out


WORK = tempfile.mkdtemp(prefix="deckbuild-")
try:
    PANEL = crop_panels(WORK)
    prs = Presentation(build_base(WORK))
    S = list(prs.slides)


    def s(n):
        return S[n - 1]


    # --- 1. title slide: untouched template ------------------------------------
    notes(s(1), tidy(SCRIPT[1][2]))

    # --- 2. contents ------------------------------------------------------------
    sl = s(2)
    drop_body(sl)
    entries = [("Introduction & Background", 3), ("System", 6), ("Method", 11),
               ("Results", 14), ("Discussion", 17), ("Conclusion", 19)]
    y = 1500000
    row_h = 470000
    for label, page in entries:
        block(sl, CL, y, CW - 700000, row_h, [
            dict(text=label, size=16, color=INK, space_after=0)])
        ln = sl.shapes.add_connector(
            MSO_CONNECTOR.STRAIGHT, Emu(CL + 2750000), Emu(y + 130000),
            Emu(CR - 620000), Emu(y + 130000))
        ln.line.color.rgb = LAV
        ln.line.width = Pt(1)
        ln.line.dash_style = MSO_LINE_DASH_STYLE.ROUND_DOT
        ln.shadow.inherit = False
        for ref in ln._element.findall(
                ".//{http://schemas.openxmlformats.org/drawingml/2006/main}"
                "effectRef"):
            ref.set("idx", "0")
        block(sl, CR - 500000, y, 500000, row_h, [
            dict(text=str(page), size=16, color=MID, bold=True,
                 align=PP_ALIGN.RIGHT, space_after=0)])
        y += row_h
    notes(sl, tidy(SCRIPT[2][2]))

    # --- 3. divider: introduction ----------------------------------------------
    divider(s(3), "Introduction & Background",
            "Why a remote hand is still clumsy with an egg", "01")
    notes(s(3), tidy(SCRIPT[3][2]))

    # --- 4. the missing sense ---------------------------------------------------
    sl = s(4)
    set_title(sl, "Teleoperation has no sense of touch")
    drop_body(sl)
    lw = 4000000
    block(sl, CL, CT, lw, 3200000, [
        dict(runs=[("Your hand already solves this. ", True, MID, 13),
                   ("Skin receptors report squeeze force in milliseconds, so you "
                    "stop short of cracking the shell.", False, INK, 13)],
             space_after=9, line=112),
        dict(runs=[("A remote operator only has video. ", True, MID, 13),
                   ("Grip force has to be inferred from how the object looks — "
                    "which fails for objects that do not visibly change before "
                    "they break.", False, INK, 13)], space_after=9, line=112),
        dict(runs=[("Both errors are expensive. ", True, MID, 13),
                   ("Too little force and the object slips; too much and it is "
                    "destroyed.", False, INK, 13)], space_after=9, line=112),
        dict(runs=[("The gripper cannot help. ", True, MID, 13),
                   ("The Robotiq 2F-85 estimates force from one aggregate motor "
                    "current — no contact distribution — and its current register "
                    "reads 0 mA regardless of contact.", False, INK, 13)],
             space_after=0, line=112),
    ])
    rx = CL + lw + GAP
    rw = CR - rx
    card(sl, rx, CT, rw, 2750000)
    half = (rw - 180000) // 2
    pic_fit(sl, os.path.join(FIG, "photos", "object_fragile.png"),
            rx + 90000, CT + 150000, half, 2000000)
    pic_fit(sl, os.path.join(FIG, "photos", "object_broken.png"),
            rx + 90000 + half, CT + 150000, half, 2000000)
    caption(sl, rx + 90000, CT + 2280000, half, "intact")
    caption(sl, rx + 90000 + half, CT + 2280000, half, "broken at the seam")
    caption(sl, rx, CT + 2830000, rw,
            "The fragile test object: a hollow shell that fails suddenly")
    notes(sl, tidy(SCRIPT[4][2]))

    # --- 5. two questions -------------------------------------------------------
    sl = s(5)
    set_title(sl, "Two questions, one fixed pipeline")
    drop_body(sl)
    chip(sl, CL, CT, CW, 830000, "Q1  Does touch feedback help?",
         "Compared with vision alone, does haptic feedback change how people grasp "
         "fragile and deformable objects?")
    chip(sl, CL, CT + 970000, CW, 830000, "Q2  Does the actuator type matter?",
         "With the whole sensing and control pipeline held fixed, does it matter "
         "which hardware delivers the sensation?")
    cy = CT + 1990000
    cw3 = (CW - 2 * 137160) // 3
    for i, (name, desc) in enumerate([
            ("Vision only", "baseline — screen and nothing else"),
            ("LRA", "vibration motor at the finger joints"),
            ("EM", "magnetic pin tapping the fingertip")]):
        x = CL + i * (cw3 + 137160)
        card(sl, x, cy, cw3, 800000, fill=WHITE, line=LAV)
        block(sl, x + 110000, cy + 150000, cw3 - 220000, 550000, [
            dict(text=name, size=13, bold=True, color=DEEP,
                 align=PP_ALIGN.CENTER, space_after=3),
            dict(text=desc, size=10.5, color=MUTE, align=PP_ALIGN.CENTER,
                 space_after=0, line=105)])
    block(sl, CL, cy + 920000, CW, 320000, [
        dict(text="Most prior work evaluates a single actuator against a "
             "no-feedback baseline; here only the hardware on the skin changes.",
             size=11, color=MUTE, space_after=0)])
    notes(sl, tidy(SCRIPT[5][2]))

    # --- 6. divider: system -----------------------------------------------------
    divider(s(6), "System", "Gel deformation in, skin sensation out", "02")
    notes(s(6), tidy(SCRIPT[6][2]))

    # --- 7. control loop --------------------------------------------------------
    sl = s(7)
    set_title(sl, "One closed loop, with a human inside it")
    drop_body(sl)
    px, py, pw, ph = pic_fit(sl, os.path.join(FIG, "preprint_fig1.png"),
                             CL, CT, 2750000, 3100000)
    tx = CL + 2750000 + GAP
    tw = CR - tx
    block(sl, tx, CT + 60000, tw, 3100000, [
        dict(runs=[("Hand → gripper.  ", True, MID, 12.5),
                   ("A USB camera plus MediaPipe HandLandmarker measures the "
                    "thumb–index pinch distance in pixels and maps it to a Robotiq "
                    "position over Modbus RTU (115200 baud) at 25 Hz.",
                    False, INK, 12.5)], space_after=8, line=112),
        dict(runs=[("Gripper → hand.  ", True, MID, 12.5),
                   ("Each jaw's gel sensor is read at 15 Hz; dent depth is "
                    "rescaled to a 0–1 intensity and streamed to a wrist-mounted "
                    "ESP32-C6.", False, INK, 12.5)], space_after=8, line=112),
        dict(runs=[("The human closes it.  ", True, MID, 12.5),
                   ("They feel the intensity rise and ease off — no force "
                    "controller in the loop.", False, INK, 12.5)],
             space_after=8, line=112),
        dict(runs=[("Two guards.  ", True, MID, 12.5),
                   ("Further closing is blocked once either sensor reads 1.0 mm "
                    "of indentation; the actuators cut out if no packet arrives "
                    "for 200 ms.", False, INK, 12.5)], space_after=0, line=112),
    ])
    notes(sl, tidy(SCRIPT[7][2]))

    # --- 8. apparatus -----------------------------------------------------------
    sl = s(8)
    set_title(sl, "The apparatus")
    drop_body(sl)
    iw = 4900000
    px, py, pw, ph = pic_fit(sl, PANEL["apparatus"],
                             CL, CT, iw, 3050000, center=False)
    tx = CL + iw + GAP
    tw = CR - tx
    specs = [
        ("Gripper", "Robotiq 2F-85, Modbus RTU at 115200 baud over USB-RS485"),
        ("Touch", "9DTact vision-based tactile sensor on each jaw"),
        ("Wearable", "ESP32-C6, five independent actuator channels"),
        ("Tracking", "USB camera + MediaPipe, 2D and uncalibrated"),
    ]
    sy = CT
    for name, desc in specs:
        card(sl, tx, sy, tw, 700000, fill=CARD, line=LAV)
        block(sl, tx + 110000, sy + 95000, tw - 220000, 520000, [
            dict(text=name, size=11.5, bold=True, color=MID, space_after=2),
            dict(text=desc, size=10, color=INK, space_after=0, line=105)])
        sy += 790000
    notes(sl, tidy(SCRIPT[8][2]))

    # --- 9. gel to intensity ----------------------------------------------------
    sl = s(9)
    set_title(sl, "From gel deformation to a felt intensity")
    drop_body(sl)
    steps = ["Camera images\nthe soft gel",
             "Reconstruct\nheight map h(x,y)",
             "Subtract baseline\nd = h − h₀",
             "Two quantities\nfrom one field"]
    n = len(steps)
    aw = 200000
    sw = (CW - (n - 1) * aw) // n
    for i, text in enumerate(steps):
        x = CL + i * (sw + aw)
        card(sl, x, CT, sw, 700000, fill=CARD if i < n - 1 else LAV, line=LAV)
        tf = textbox(sl, x + 60000, CT + 60000, sw - 120000, 580000,
                     MSO_ANCHOR.MIDDLE).text_frame
        for j, ln in enumerate(text.split("\n")):
            para(tf, j == 0, ln, size=11, color=DEEP if i == n - 1 else INK,
                 bold=(i == n - 1), align=PP_ALIGN.CENTER, space_after=0, line=112)
        if i < n - 1:
            arrow(sl, x + sw + 40000, CT + 260000, aw - 80000, 180000)
    by = CT + 900000
    bw = (CW - GAP) // 2
    bh = 1200000
    card(sl, CL, by, bw, bh, fill=WHITE, line=LAV)
    block(sl, CL + 130000, by + 130000, bw - 260000, bh - 260000, [
        dict(text="Grip-force proxy", size=12.5, bold=True, color=MID,
             space_after=4),
        dict(runs=[("volume = Σ|d| ", True, INK, 11.5),
                   ("over every pixel in contact (|d| > 0.1 mm). Monotonic in "
                    "normal force, but uncalibrated — reported in a.u., not "
                    "newtons.", False, INK, 11.5)], space_after=0, line=108)])
    card(sl, CL + bw + GAP, by, bw, bh, fill=WHITE, line=LAV)
    block(sl, CL + bw + GAP + 130000, by + 130000, bw - 260000, bh - 260000, [
        dict(text="Felt intensity", size=12.5, bold=True, color=MID,
             space_after=4),
        dict(runs=[("intensity = clip(depth / depth_sat, 0, 1) ", True, INK, 11.5),
                   ("where depth is the 99th-percentile dent in mm. depth_sat is "
                    "2.0 mm for fragile, 0.6 mm for deformable objects.",
                    False, INK, 11.5)], space_after=0, line=108)])
    block(sl, CL, by + bh + 150000, CW, 400000, [
        dict(runs=[("Why the missing calibration is survivable:  ", True, MID, 11),
                   ("every test here is rank-based, and a monotonic rescaling "
                    "cannot reorder trials — so it cannot move a p-value.",
                    False, MUTE, 11)], space_after=0, line=108)])
    notes(sl, tidy(SCRIPT[9][2]))

    # --- 10. two actuators ------------------------------------------------------
    sl = s(10)
    set_title(sl, "Two ways to render that number")
    drop_body(sl)
    ch = 2750000
    for i, (path, name, sub, lines) in enumerate([
        (PANEL["lra"], "LRA", "linear resonant actuator", [
            "Bipolar PWM carrier, 10-bit duty at 200 Hz; intensity sets the "
            "envelope",
            "Mounted at the thumb and index proximal joints",
            "Buzzes continuously — draws power the whole time"]),
        (PANEL["em"], "EM", "bistable electromagnetic pin", [
            "H-bridge latch: a 4 ms pulse throws the pin, the opposite pulse "
            "retracts it",
            "Intensity sets the burst gap (35 ms floor) to stay under ~120 "
            "switches/min",
            "Zero holding power; mounted at the fingertips"]),
    ]):
        x = CL + i * (COLW + GAP)
        card(sl, x, CT, COLW, ch, fill=CARD, line=LAV)
        pic_fit(sl, path, x + 120000, CT + 100000, 1050000, 1250000)
        block(sl, x + 1300000, CT + 180000, COLW - 1420000, 1150000, [
            dict(text=name, size=20, bold=True, color=DEEP, space_after=2),
            dict(text=sub, size=11, color=MUTE, space_after=0, line=108)])
        ty = CT + 1450000
        tf = textbox(sl, x + 130000, ty, COLW - 260000, ch - 1550000).text_frame
        for j, ln in enumerate(lines):
            para(tf, j == 0, [("— ", False, LAV, 11), (ln, False, INK, 11)],
                 space_after=6, line=106, hang=137160)
    block(sl, CL, CT + ch + 130000, CW, 420000, [
        dict(runs=[("The two conditions differ in technology and in placement.  ",
                    True, MID, 11),
                   ("Each actuator is mounted where it works best — deliberate in "
                    "the build, a confound in the analysis.", False, MUTE, 11)],
             space_after=0, line=108)])
    notes(sl, tidy(SCRIPT[10][2]))

    # --- 11. divider: method ----------------------------------------------------
    divider(s(11), "Method", "22 participants, 660 grasps, three conditions", "03")
    notes(s(11), tidy(SCRIPT[11][2]))

    # --- 12. protocol -----------------------------------------------------------
    sl = s(12)
    set_title(sl, "Protocol")
    drop_body(sl)
    lw = 3450000
    pic_fit(sl, os.path.join(FIG, "preprint_fig3.png"), CL, CT, lw, 2600000)
    tx = CL + lw + GAP
    tw = CR - tx
    block(sl, tx, CT, tw, 1700000, [
        dict(runs=[("Within-subjects.  ", True, MID, 12),
                   ("Every participant ran all three conditions, in the fixed "
                    "order vision → LRA → EM.", False, INK, 12)],
             space_after=8, line=110),
        dict(runs=[("660 trials.  ", True, MID, 12),
                   ("5 grasps × 2 object classes × 3 conditions × 22 "
                    "participants.", False, INK, 12)], space_after=8, line=110),
        dict(runs=[("Then the survey.  ", True, MID, 12),
                   ("Each condition rated on four items, then a forced choice of "
                    "favourite.", False, INK, 12)], space_after=0, line=110),
    ])
    _, iy, _, ih = pic_fit(sl, os.path.join(FIG, "preprint_fig4.png"),
                           tx, CT + 1750000, tw, 1150000)
    caption(sl, tx, iy + ih + 90000, tw,
            "Fragile: a shell that pops apart.  Deformable: foam that never breaks.")
    notes(sl, tidy(SCRIPT[12][2]))

    # --- 13. metrics ------------------------------------------------------------
    sl = s(13)
    set_title(sl, "What was measured, and how it was tested")
    drop_body(sl)
    metrics = [
        ("Peak deformation volume  (a.u.)",
         "How hard they squeezed at the hardest moment of the grasp."),
        ("Excess deformation  (a.u.)",
         "Force added after dent depth reached 95% of its peak — squeezing the "
         "operator can no longer feel."),
        ("Grip adjustments  (#)",
         "Direction reversals in the force trace after that plateau: hunting for "
         "a grip instead of holding steady."),
        ("Survival  (%)",
         "Did the object come out intact, scored per trial."),
    ]
    mh = 900000
    for i, (name, desc) in enumerate(metrics):
        x = CL + (i % 2) * (COLW + GAP)
        y = CT + (i // 2) * (mh + 140000)
        card(sl, x, y, COLW, mh, fill=CARD, line=LAV)
        block(sl, x + 130000, y + 110000, COLW - 260000, mh - 220000, [
            dict(text=name, size=12, bold=True, color=MID, space_after=3),
            dict(text=desc, size=10.5, color=INK, space_after=0, line=106)])
    sy = CT + 2 * (mh + 140000)
    block(sl, CL, sy, CW, 500000, [
        dict(runs=[("Statistics.  ", True, MID, 11),
                   ("Friedman omnibus across the three conditions, then Wilcoxon "
                    "signed-rank pairwise with Holm correction. Medians are "
                    "reported rather than means — one crushed egg should not move "
                    "the average.", False, MUTE, 11)], space_after=0, line=108)])
    notes(sl, tidy(SCRIPT[13][2]))

    # --- 14. divider: results ---------------------------------------------------
    divider(s(14), "Results", "Fragile objects moved; foam did not", "04")
    notes(s(14), tidy(SCRIPT[14][2]))

    # --- 15. objective results --------------------------------------------------
    sl = s(15)
    set_title(sl, "Fragile objects: what changed")
    drop_body(sl)
    rows = [
        ("Median per participant", "Vision", "LRA", "EM"),
        ("Peak deformation volume (a.u.)", "20100", "12300", "16000"),
        ("Excess deformation (a.u.)", "1530", "170", "260"),
        ("Grip adjustments (#)", "7", "5", "2"),
        ("Objects surviving (%)", "62", "81", "78"),
    ]
    tw_ = CW
    tbl_h = 1330000
    gt = sl.shapes.add_table(len(rows), 4, Emu(CL), Emu(CT), Emu(tw_),
                             Emu(tbl_h)).table
    gt.columns[0].width = Emu(3400000)
    for c in range(1, 4):
        gt.columns[c].width = Emu((tw_ - 3400000) // 3)
    for r in range(len(rows)):
        gt.rows[r].height = Emu(tbl_h // len(rows))
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            cell = gt.cell(r, c)
            cell.margin_left = Emu(91440)
            cell.margin_right = Emu(91440)
            cell.margin_top = Emu(27432)
            cell.margin_bottom = Emu(27432)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.fill.solid()
            if r == 0:
                cell.fill.fore_color.rgb = DEEP
            elif r == len(rows) - 1:
                cell.fill.fore_color.rgb = LAV
            else:
                cell.fill.fore_color.rgb = WHITE if r % 2 else CARD
            p = cell.text_frame.paragraphs[0]
            p.alignment = PP_ALIGN.LEFT if c == 0 else PP_ALIGN.CENTER
            run = p.add_run()
            run.text = val
            run.font.name = FONT
            run.font.size = Pt(11.5)
            run.font.bold = (r == 0) or (r == len(rows) - 1) or (c == 0)
            run.font.color.rgb = WHITE if r == 0 else INK
    fy = CT + tbl_h + 110000
    _, _, _, fh = pic_fit(sl, os.path.join(FIG, "preprint_fig5.png"),
                          CL, fy, CW, 1520000)
    block(sl, CL, fy + fh + 110000, CW, 400000, [
        dict(runs=[("Excess deformation ", True, MID, 10.5),
                   ("vision→LRA Holm p = 0.019  ·  ", False, MUTE, 10.5),
                   ("Grip adjustments ", True, MID, 10.5),
                   ("vision→EM p = 0.021  ·  ", False, MUTE, 10.5),
                   ("Survival ", True, MID, 10.5),
                   ("Friedman p = 0.004 (vision→LRA p = 0.018, vision→EM p = "
                    "0.037; LRA vs EM p = 0.69)", False, MUTE, 10.5)],
             space_after=0, line=108)])
    notes(sl, tidy(SCRIPT[15][2]))

    # --- 16. subjective results -------------------------------------------------
    sl = s(16)
    set_title(sl, "What the participants said")
    drop_body(sl)
    pic_fit(sl, os.path.join(FIG, "preprint_fig6.png"), CL, CT, CW, 2100000)
    by = CT + 2160000
    block(sl, CL, by, CW, 1200000, [
        dict(runs=[("Feedback beats no feedback.  ", True, MID, 12),
                   ("Force perception, grasp confidence and contact detection all "
                    "improved over vision only (Friedman p < 0.001; Holm-corrected "
                    "pairwise p ≤ 0.002).", False, INK, 12)],
             space_after=7, line=110),
        dict(runs=[("No item separates the actuators.  ", True, MID, 12),
                   ("Every LRA-vs-EM comparison sits above p = 0.2.",
                    False, INK, 12)], space_after=7, line=110),
        dict(runs=[("But the preference is lopsided.  ", True, MID, 12),
                   ("17 of 22 picked the LRA as their favourite, 4 the EM, 1 "
                    "vision only (χ², p < 0.001).", False, INK, 12)],
             space_after=0, line=110),
    ])
    notes(sl, tidy(SCRIPT[16][2]))

    # --- 17. divider: discussion ------------------------------------------------
    divider(s(17), "Discussion", "What the data supports — and what it does not",
            "05")
    notes(s(17), tidy(SCRIPT[17][2]))

    # --- 18. limitations --------------------------------------------------------
    sl = s(18)
    set_title(sl, "Claims, and the confounds behind them")
    drop_body(sl)
    ch = 2620000
    card(sl, CL, CT, COLW, ch, fill=CARD, line=LAV)
    block(sl, CL + 140000, CT + 130000, COLW - 280000, ch - 260000, [
        dict(text="Supported", size=14, bold=True, color=DEEP, space_after=8),
        dict(text="Tactile feedback cuts the squeezing the operator cannot feel "
             "(~9× with the LRA).", size=11.5, color=INK, space_after=7, line=108),
        dict(text="It cuts regrip hunting and lifts fragile-object survival from "
             "62% to about 80%.", size=11.5, color=INK, space_after=7, line=108),
        dict(text="Operators perceive the difference and overwhelmingly prefer "
             "having it.", size=11.5, color=INK, space_after=7, line=108),
        dict(text="The gain is in excess force, not in peak dent depth — the "
             "1.0 mm safety cutoff caps that before conditions can differ.",
             size=11.5, color=INK, space_after=0, line=108),
    ])
    x2 = CL + COLW + GAP
    card(sl, x2, CT, COLW, ch, fill=GREY, line=RGBColor(0xDD, 0xDD, 0xE2))
    block(sl, x2 + 140000, CT + 130000, COLW - 280000, ch - 260000, [
        dict(text="Not yet supported", size=14, bold=True, color=DEEP,
             space_after=8),
        dict(text="That the LRA is the better actuator: technology and placement "
             "are bundled together.", size=11.5, color=INK, space_after=7,
             line=108),
        dict(text="Fingertip EM hardware occludes the tracked landmarks and adds "
             "standoff — the preference may be smoother control, not better "
             "sensation.", size=11.5, color=INK, space_after=7, line=108),
        dict(text="Fixed condition order leaves practice and fatigue inseparable "
             "from condition.", size=11.5, color=INK, space_after=7, line=108),
        dict(text="That any of this extends to deformable objects — no metric "
             "moved reliably on foam.", size=11.5, color=INK, space_after=0,
             line=108),
    ])
    block(sl, CL, CT + ch + 120000, CW, 420000, [
        dict(runs=[("Measurement caveats.  ", True, MID, 10.5),
                   ("Force is in a.u., not newtons; the mm depth scale rests on a "
                    "single ball calibration never checked against a gauge; "
                    "end-to-end latency still needs a bench measurement.",
                    False, MUTE, 10.5)], space_after=0, line=108)])
    notes(sl, tidy(SCRIPT[18][2]))

    # --- 19. divider: conclusion ------------------------------------------------
    divider(s(19), "Conclusion", "Safer grasping, an open question on actuators",
            "06")
    notes(s(19), tidy(SCRIPT[19][2]))

    # --- 20. conclusion ---------------------------------------------------------
    sl = s(20)
    set_title(sl, "Takeaways")
    drop_body(sl)
    takeaways = [
        ("62% → 80%", "Fragile-object survival rose with either actuator, and "
         "unfelt over-squeezing fell roughly ninefold."),
        ("21 of 22", "Participants preferred a haptic condition over vision "
         "alone, and rated it higher on every perception item."),
        ("Still open", "Which actuator is better — technology and placement have "
         "to be separated before that can be answered."),
    ]
    th = 810000
    for i, (big, text) in enumerate(takeaways):
        y = CT + i * (th + 130000)
        card(sl, CL, y, CW, th, fill=CARD if i < 2 else WHITE, line=LAV)
        block(sl, CL + 140000, y + 120000, 1900000, th - 240000,
              [dict(text=big, size=19, bold=True, color=DEEP, space_after=0)],
              anchor=MSO_ANCHOR.MIDDLE)
        block(sl, CL + 2100000, y + 120000, CW - 2240000, th - 240000,
              [dict(text=text, size=12, color=INK, space_after=0, line=110)],
              anchor=MSO_ANCHOR.MIDDLE)
    block(sl, CL, CT + 3 * (th + 130000) + 20000, CW, 420000, [
        dict(runs=[("Next.  ", True, MID, 11),
                   ("Spatial feedback instead of one scalar per finger; force "
                    "calibrated into newtons; a bench-measured end-to-end latency.",
                    False, MUTE, 11)], space_after=0, line=108)])
    notes(sl, tidy(SCRIPT[20][2]))

    prs.save(OUT)
    print("wrote", OUT)

    # ============================================================ script file ====
    lines = ["# Graduation study — 10-minute presentation script", "",
             "**Tactile-Feedback Teleoperation: Grip Force and Grasping "
             "Performance Across Haptic Actuator Types for Fragile and Deformable "
             "Objects**  ",
             "Adriel Imaran Santoso · Intelligent Control Systems Laboratory, "
             "Tohoku University", "",
             "Audience: 18 students from outside the lab (aerospace, biomedical, "
             "fine mechanics, mechanical). Assume no robotics background: every "
             "robotics term is unpacked on first use, but the sensing, actuation "
             "and statistics are kept at full technical strength.", "",
             "Target 10:00. The cue in each heading is the elapsed time at which "
             "that slide should go up. Section dividers are one breath each — do "
             "not stop on them.", "", "---", ""]
    RATE = 150.0            # words per minute, brisk but unhurried
    total_words = 0
    elapsed = 0.0
    for n in sorted(SCRIPT):
        label, _, body = SCRIPT[n]
        text = tidy(body)
        words = len(text.split())
        total_words += words
        cue = f"{int(elapsed) // 60}:{int(elapsed) % 60:02d}"
        elapsed += words / RATE * 60 + 1.0     # +1s to change slide
        lines += [f"## Slide {n} — {label}  ·  {cue}", ""]
        lines += [text, "", ]
    lines += ["---", "",
              f"Word count: {total_words}, which runs about "
              f"{elapsed / 60:.1f} minutes at {RATE:.0f} words per minute "
              "including slide changes. That is a brisk but normal delivery pace; "
              "if you speak nearer 135 wpm it lands closer to 11 minutes, so "
              "rehearse against a clock before deciding whether to make the cuts "
              "below.", "",
              "Timing notes:", "",
              "- Slides 9 and 15 are the two that run long; if you are behind, "
              "cut the rank-statistics aside on slide 9 and the deformable-object "
              "negative on slide 15.", "",
              "- Do not read the table on slide 15. Point at three numbers: "
              "1530 → 170, 7 → 2, and 62 → 81.", "",
              "- Expect questions on why force is uncalibrated and why the "
              "condition order was fixed. Both are on slide 18 — answer from "
              "there rather than defending them earlier.", "",
              "Provenance of the numbers on slides 15 and 16:", "",
              "- The slide 15 table is the preprint's Table 1 verbatim, and "
              "its p-values come from the same pipeline run. Reproduce both "
              "with `python -m analysis --trials-dir data/experiment_logs "
              "--likert-csv data/likert/likert_responses.csv --out "
              "analysis/results --collapse max`. The `max` collapse is the "
              "one that matches: `sum_n` needs the per-side force "
              "calibration (Setup step 8), which was never run, so it leaves "
              "every force metric blank.", "",
              "- Excess deformation and grip adjustments are "
              "`force_overshoot_proxy` and `n_force_reversals_post_plateau` "
              "in section_5_3_cross_condition.csv; survival is in "
              "section_5_7_fragile_survival_tests.csv. Slide 16 comes from "
              "section_5_6_likert_friedman.csv and "
              "section_5_6_likert_preference.csv.", ""]
    with open(SCRIPT_OUT, "w") as f:
        f.write("\n".join(lines))
    print("wrote", SCRIPT_OUT, total_words, "words")

finally:
    shutil.rmtree(WORK, ignore_errors=True)
