# Graduation study — 10-minute presentation script

**Tactile-Feedback Teleoperation: Grip Force and Grasping Performance Across Haptic Actuator Types for Fragile and Deformable Objects**  
Adriel Imaran Santoso · Intelligent Control Systems Laboratory, Tohoku University

Audience: 18 students from outside the lab (aerospace, biomedical, fine mechanics, mechanical). Assume no robotics background: every robotics term is unpacked on first use, but the sensing, actuation and statistics are kept at full technical strength.

Target 10:00. The cue in each heading is the elapsed time at which that slide should go up. Section dividers are one breath each — do not stop on them.

---

## Slide 1 — Title  ·  0:00

Good afternoon. I am Adriel Santoso, from the Intelligent Control Systems Lab.

My graduation study asks a simple question: if you are driving a robot hand from a distance, does giving your own fingers a sense of touch make you better at picking up fragile things — and does it matter which kind of buzzer you use?

## Slide 2 — Contents  ·  0:23

Here is where we are going: the problem, the system, how the experiment was run, what came out of it, and what it does and does not prove.

## Slide 3 — Section: Introduction  ·  0:36

Let me start with why this is hard.

## Slide 4 — The missing sense  ·  0:40

Think about picking up an egg. You do not calculate anything: receptors in your skin report how hard you are squeezing within milliseconds, and you stop short of cracking the shell.

Now take that away. In teleoperation — a surgeon at a console, a technician in a glovebox — you see the object but feel nothing, so grip force has to be inferred from how it looks. That works right up until the object does not visibly change before it fails. Too little force and it slips; too much and you get the picture on the right.

And the gripper cannot rescue you. The Robotiq 2F-85 estimates force from one aggregate motor current — no contact distribution at all — and on my unit that register reads zero milliamps regardless of contact.

## Slide 5 — Two questions  ·  1:34

So the study asks two questions.

First: does touch feedback change how people grasp fragile and deformable objects, compared with vision alone?

Second, and this is asked less often: does the actuator type matter? Most published work picks one haptic device and compares it against a no-feedback baseline. Here the whole sensing and control pipeline is held fixed, and the only thing that changes is the hardware on the skin — a vibration motor at the finger joints, or an electromagnetic pin at the fingertip.

## Slide 6 — Section: System  ·  2:09

Here is the system.

## Slide 7 — The control loop  ·  2:11

It is one closed loop with a human inside it.

Going down: a camera watches the operator's hand, MediaPipe gives me the pixel distance between thumb tip and index tip, and that maps to a gripper opening sent over Modbus at 25 hertz. The gripper mirrors your pinch — there is no joystick.

Coming back up: each jaw carries a soft tactile sensor. Fifteen times a second I read how deeply the gel is dented, turn it into one number between zero and one, and stream it to an ESP32 on the wrist.

The loop closes through the person: they feel the intensity rise and ease off.

Two guards. Closing is blocked once either sensor reads one millimetre of indentation, which protects the sensor mount; and the actuators cut out if no packet arrives for 200 milliseconds.

## Slide 8 — Apparatus  ·  3:07

The hardware. On the left, the operator: a wrist unit carrying the driver board, and the hand-tracking camera. On the right, the gripper with a plastic egg in the fixture, and one tactile sensor pulled out so you can see it — about the size of a sugar cube.

## Slide 9 — Gel to intensity  ·  3:27

This is where the engineering actually lives: turning a squishy gel into a number.

The sensor is a camera looking at the back of a soft gel pad under a calibrated illumination pattern. Every frame it reconstructs a height map of the gel surface; subtract the height map recorded with nothing touching it and you have the deformation field. I take two quantities from that one field.

The first is the sum of absolute deformation over every pixel actually in contact — more than a tenth of a millimetre. That is my grip-force proxy: monotonic in normal force, but uncalibrated, because the gripper exposes no force sensor. So I report arbitrary units, not newtons.

The second is the 99th-percentile depth in millimetres, and that is what the operator feels: divide by a saturation depth, clip to zero-to-one. That saturation depth is per object class — two millimetres for the egg, six tenths for foam, which barely dents the gel and otherwise felt dead.

One consequence: the force scale is uncalibrated but monotonic, and every test here is rank-based, so a scaling error cannot move a single p-value.

## Slide 10 — Two actuators  ·  4:43

Two actuators render that number.

The LRA is a linear resonant actuator — the vibration motor in your phone. I drive it with a bipolar carrier at 200 hertz and let intensity set the envelope, so it buzzes harder as you squeeze. It sits on the proximal joints of the thumb and index finger.

The EM is a bistable pin actuator on an H-bridge. A four-millisecond pulse throws a pin into the skin and it latches mechanically, so it draws no power while held. For continuous feedback I fire bursts and let intensity set the gap between them, with a 35 millisecond floor to stay under the coil's thermal limit of about 120 switches a minute. It sits on the fingertips.

Note what I just said: the two conditions differ in technology and in placement. That was deliberate — each is mounted where it works best — but hold on to it, because it comes back in the discussion.

## Slide 11 — Section: Method  ·  5:48

The experiment.

## Slide 12 — Protocol  ·  5:50

Twenty-two participants, each doing all three conditions in the fixed order: vision only, then LRA, then EM. Two object classes, five grasps each — 660 trials in total.

Fragile is a hollow plastic egg that pops apart at the seam: it fails suddenly, like the real thing, but I can reassemble it. Deformable is a foam cube, which yields gradually and never breaks. Afterwards each participant rated the three conditions and picked a favourite.

## Slide 13 — Metrics and statistics  ·  6:20

Four objective measures. Peak deformation volume is how hard they squeezed at the worst moment.

Excess deformation is the interesting one. Once the gel is fully dented the depth signal plateaus, and from that moment squeezing harder changes nothing the operator can feel. Excess deformation is the force that goes in after that point: wasted, and potentially destructive, effort.

Grip adjustments counts direction reversals in the force after that plateau — squeeze, ease, squeeze again — somebody hunting for a grip instead of holding steady. And survival: did the egg come out intact.

Statistically: Friedman across the three conditions, then Wilcoxon signed-rank pairwise with Holm correction. Medians, not means — one crushed egg should not move the average.

## Slide 14 — Section: Results  ·  7:09

Results.

## Slide 15 — Objective results  ·  7:10

Fragile objects. Each column is the median participant, and for the first three rows lower is better.

Peak squeeze drops with feedback. Excess deformation — the wasted squeezing — falls from about 1500 units to 170 with the LRA, roughly ninefold, at p equals 0.019 after correction. Grip adjustments drop from seven to two with the EM, p equals 0.021. The two actuators help in different ways: the LRA stops you squeezing, the EM stops you fidgeting.

And the outcome people care about: egg survival rises from 62 percent with vision only to 81 with the LRA and 78 with the EM, Friedman p equals 0.004, both beating the baseline after correction.

Two honest negatives. Peak dent depth barely moves, because my one-millimetre safety cutoff caps it first. And deformable objects showed no reliable change on anything — foam gives you no sharp failure to avoid.

## Slide 16 — Subjective results  ·  8:09

Subjectively it is not close. On force perception, grasp confidence and contact detection, both haptic conditions beat vision only at p below 0.001, surviving Holm correction.

But no single question separated the LRA from the EM — every pairwise comparison between them sits above 0.2. And yet, asked to pick a favourite, 17 of 22 chose the LRA. People had a clear preference they could not articulate on any of my rating items.

## Slide 17 — Section: Discussion  ·  8:40

So what does this mean.

## Slide 18 — Limitations  ·  8:43

What I am comfortable claiming: tactile feedback reduces the squeezing the operator cannot feel, reduces regrip hunting, and raises survival on fragile objects — and users perceive it and want it.

What I am not comfortable claiming is that the LRA is the better actuator. Technology and placement are bundled: I never tested a fingertip LRA or a joint-mounted EM. Worse, the fingertip EM hardware sits on the very landmarks the hand tracker uses, so I had to lower the detection thresholds, and its thickness changed the usable pinch range — the LRA preference may be smoother control, not better sensation. And the condition order was fixed, so practice and fatigue are inseparable from condition.

On measurement: force is in arbitrary units, the millimetre scale rests on one ball calibration never checked against a gauge, and latency still needs a bench measurement.

## Slide 19 — Section: Conclusion  ·  9:40

To close.

## Slide 20 — Conclusion  ·  9:42

Three things. Touch feedback made remote grasping of fragile objects measurably safer: about nine times less unfelt squeezing, and survival up from 62 to around 80 percent. It is what operators want — 21 of 22 preferred a haptic condition over vision alone. And which actuator is better is still open; answering it needs a study that separates technology from placement.

Next: spatial feedback instead of one number per finger, force calibrated into newtons, and a bench-measured latency figure.

Thank you — happy to take questions.

---

Word count: 1495, which runs about 10.3 minutes at 150 words per minute including slide changes. That is a brisk but normal delivery pace; if you speak nearer 135 wpm it lands closer to 11 minutes, so rehearse against a clock before deciding whether to make the cuts below.

Timing notes:

- Slides 9 and 15 are the two that run long; if you are behind, cut the rank-statistics aside on slide 9 and the deformable-object negative on slide 15.

- Do not read the table on slide 15. Point at three numbers: 1530 → 170, 7 → 2, and 62 → 81.

- Expect questions on why force is uncalibrated and why the condition order was fixed. Both are on slide 18 — answer from there rather than defending them earlier.

Provenance of the numbers on slides 15 and 16:

- The slide 15 table is the preprint's Table 1 verbatim, and its p-values come from the same pipeline run. Reproduce both with `python -m analysis --trials-dir data/experiment_logs --likert-csv data/likert/likert_responses.csv --out analysis/results --collapse max`. The `max` collapse is the one that matches: `sum_n` needs the per-side force calibration (Setup step 8), which was never run, so it leaves every force metric blank.

- Excess deformation and grip adjustments are `force_overshoot_proxy` and `n_force_reversals_post_plateau` in section_5_3_cross_condition.csv; survival is in section_5_7_fragile_survival_tests.csv. Slide 16 comes from section_5_6_likert_friedman.csv and section_5_6_likert_preference.csv.
