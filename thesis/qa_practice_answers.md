# Defense Q&A — Questions with Model Answers

Companion to `qa_practice_questions.md`. Same 60 questions, but with answers written out
the way you would actually say them — roughly 30–60 seconds each when spoken.

These are drafts to internalize, not scripts to recite. Where an answer says *"verify this
first"*, the honest answer depends on a fact only you have; those are collected in the
checklist at the end.

Sources: `README.md`, `thesis/presentation_preprint.tex`, `thesis/thesis.tex`,
`analysis/results/*.csv`, `kernel/`, `firmware/`, `run/experiment.py`.

---

## Tier 1 — Framing and motivation

**1. In one sentence, what question does this thesis answer?**

It answers two coupled questions: whether tactile feedback improves teleoperated grasping
of fragile and deformable objects, and whether the *type* of haptic actuator delivering
that feedback matters. Most prior work answers only the first, for a single actuator. I
built a system where the sensing and intensity pipeline is held fixed and the actuator is
the only swapped component, so both questions can be asked in one experiment.

**2. Why is this worth doing — haven't vibrotactile teleoperation studies been done for
decades?**

The "feedback versus no feedback" question has been studied extensively, and my results
largely reproduce that literature. What is much rarer is a head-to-head comparison of
actuator types under a genuinely matched pipeline. In most comparative work the two devices
differ in the sensing chain, the mapping, or the task, so any difference is hard to
attribute. Here, both haptic conditions read the same 9DTact sensor, compute the same
depth-to-intensity mapping, and stream the same packet format; only the driver and the
hardware on the finger change.

**3. Why these two actuators specifically — LRA and EM pin?**

They sit at opposite ends of a meaningful design axis. The LRA is the commodity baseline —
the smartwatch-class vibration motor that most wearable haptics research uses, well
characterized in Pacchierotti et al. (2017). The EM bistable pin, adapted from Vechev et
al. (2019), is interesting because it latches mechanically: it can hold contact against the
skin at zero power. So the comparison is continuous vibration against something that can
render sustained contact — vibration versus pressure, in effect, rather than two variants
of the same thing.

**4. Why a gel-based vision tactile sensor instead of a load cell or the gripper's own
force reading?**

Two reasons, one forced and one deliberate. The forced one: the Robotiq 2F-85 exposes no
force/torque channel, and its `gCU` current register reads 0 mA regardless of contact on my
unit — I verified this, and it is documented in the repository. So the "peak motor current"
proxy my thesis chapter originally planned around simply does not exist on this hardware.
The deliberate one: 9DTact returns a full depth map, not a scalar, so the same rig supports
the spatially-resolved feedback I name as future work. A load cell would have given me
newtons but closed that door.

**5. Who is this for? Name a concrete application.**

Any remote manipulation where the operator cannot see the contact directly and the object
punishes overshoot — remote laboratory handling, inspection and maintenance in spaces
people cannot enter, assistive teleoperation. I would not claim more than that. This is a
seated, single-object, fixed-geometry lab study; it establishes an effect, not a deployed
capability.

**6. Why fragile *and* deformable objects? The deformable results were null.**

They represent two different failure modes, and contrasting them is part of the design.
Fragile objects fail abruptly — there is a cliff, and crossing it is unrecoverable.
Deformable objects yield progressively and never break. The null on deformable objects is
itself informative: it suggests feedback matters most where the cost of overshoot is
discontinuous. When the penalty is gradual and visible in the camera feed, vision alone
appears adequate.

---

## Tier 2 — System and engineering

**7. Walk me through the signal path from object contact to the operator's skin.**

Contact deforms the gel on the sensor. A camera behind the gel captures that at MJPG with
the V4L2 queue pinned to one frame, so I always read the newest image. The 9DTact
reconstruction produces a height map; subtracting a per-trial baseline gives deformation.
From that I compute two quantities — the summed absolute deformation, which is my force
proxy in arbitrary units, and the 99th-percentile depth in millimetres. Depth is divided by
a per-object-class saturation constant and clamped to zero-to-one, giving the haptic
intensity. The host streams the two intensities, left and right, as a comma-separated line
at roughly 15 Hz to the ESP32-C6, which drives thumb and index independently — PWM duty for
the LRA, burst-and-gap timing for the EM.

**8. Why is the gripper commanded by hand tracking rather than a joystick?**

Because it preserves the teleoperation framing I care about. The operator's own pinch
aperture is the command signal, so the mapping between what their hand does and what the
gripper does is direct and needs no learning of an abstract control. MediaPipe's
HandLandmarker gives me the thumb-tip and index-tip landmarks; their pixel separation is
mapped linearly between a fully-pinched distance and a fully-spread distance onto the
gripper's position range.

**9. Your control input is a 2D, uncalibrated pixel distance. Doesn't that inject noise
straight into your dependent variables?**

Yes, and I list it as a limitation rather than defending it. It is a projective measurement
with no metric calibration, so hand rotation and distance from the camera both contaminate
it. What protects the comparison is the within-subjects design — every participant meets
every condition through the same noisy channel, and each participant serves as their own
control — plus a fixed camera geometry, a fixed object height of 16.5 cm, and a practice
block before any recording. The noise inflates variance; it does not systematically favor
one condition. The one exception is the EM condition, where tracking was genuinely worse,
and I treat that as a confound rather than as noise.

**10. Both actuators are driven from the same intensity scalar. So what actually differs?**

Three things at once, and I want to be explicit that it is three and not one. First, the
actuator physics — a resonant vibrating mass versus a bistable pin that latches. Second,
placement: the LRAs sit near the thumb and index proximal joints, while the EM pins sit at
the fingertips. Third, and consequent to the second, hand-tracking quality differed, because
the fingertip-mounted hardware occludes the landmarks being tracked. So this is a comparison
of two complete feedback *designs*, not of two actuator technologies in isolation, and my
conclusions are worded to match.

**11. Why is the EM condition rendered as repeated bursts rather than as a single latch?**

To hold the feedback *strategy* constant across the two haptic conditions. The LRA buzzes
whenever intensity is above zero, with intensity setting how strong the buzz feels. To match
that percept, the EM driver fires repeated pulses and sets the gap between them from
intensity — short gap at high intensity, long gap at low. Otherwise I would have been
comparing continuous feedback against binary contact feedback *and* two different actuators
simultaneously, which confounds mechanism with hardware. The gap has a floor of 35 ms to
keep the long-run switch rate under the actuator's roughly 120-switches-per-minute thermal
limit. The binary-latch design exists in the codebase as a separate condition, `em2`, but it
is a different design point and is not part of this comparison.

**12. Then your continuous-versus-discrete contrast collapses — both conditions gate a
waveform on and off. Is the comparison still meaningful?**

That criticism is correct and it is in my limitations. Ideally an LRA's amplitude is
modulated at a constant resonant frequency, but the ESP32's standard PWM peripheral cannot
generate the phase-locked antiphase pair that amplitude-modulating the bipolar H-bridge
drive requires. So LRA intensity is rendered by envelope modulation — on-fraction within a
roughly 50 ms window — and EM intensity by burst spacing. Both are gating. What genuinely
remains is a difference in temporal granularity, in placement, and in the physical character
of the sensation. What does not remain is a clean continuous-versus-discrete dichotomy, and I
do not claim one. A dedicated resonant-driver IC would restore it, and that is named as
future work.

**13. The LRA carrier is 200 Hz. Is that the actuator's resonance?**

No. It was set empirically by what felt strongest on the bench, not tuned to a measured
resonant frequency for these specific units. Since an LRA is efficient only in a narrow band
around resonance, an off-resonance carrier likely under-drives it and compresses the
achievable amplitude range — which would compress the perceptual dynamic range of the
intensity signal in the LRA condition specifically. If anything, that biases against the
LRA, which makes the LRA's favorable results more conservative, not less.

**14. What is your end-to-end latency, sensor to skin?**

I have not measured it, and I am not going to estimate one from the loop rate. What I can
state is what the system guarantees: the sensor-to-haptic loop runs at roughly 15 Hz, trial
logging at roughly 30 Hz, and the firmware fails safe — if no packet arrives within 200 ms,
every motor stops. The measurement that is missing is a true end-to-end one: timestamping
frame capture, the serial transmission, and the physical actuator state change with a
photodiode or oscilloscope trigger, run once per actuator type on the bench. That is
specified in my thesis chapter as a planned measurement and it remains the most concrete
piece of unfinished characterization in the work.

**15. Why did you have to lower MediaPipe's confidence thresholds?**

Because the EM actuator body physically sits on landmarks 4 and 8 — the thumb and index
fingertips, which are exactly the points the tracker needs. At MediaPipe's default
thresholds, that occlusion was enough to lose hand presence entirely; the overlay would read
"No Hand" as soon as the EM hardware entered frame. I lowered detection, presence, and
tracking confidence to 0.4, 0.5 and 0.5 respectively, which restored tracking. I want to
flag the asymmetry: the LRA condition never needed this, because those motors sit at the
proximal joints and do not cover the tracked landmarks. That asymmetry is the placement
confound in a different form.

**16. `PINCH_DIST_PX` went from 30 px to 45 px. Why, and did that change the task?**

The EM body adds physical standoff at the fingertips, so with the hardware mounted the
participant's fingers cannot come as close together as bare fingers can. With the old
30-pixel floor, the gripper never reached its commanded closed position and the whole mapped
range felt compressed. Raising the floor to 45 px restored full travel. It does rescale the
command mapping, so I set it once with the hardware mounted and held it fixed for every
condition, including visual-only — it was not toggled per condition, which would have made
conditions incomparable.

**17. What stops a participant from destroying the sensor or the fixture?**

Two independent limits. The commanded position is capped at 195 rather than the Robotiq's
true closed position of 225, leaving mechanical margin before the jaws hard-stop. On top of
that, a runtime cutoff in the motion loop blocks any further *closing* — never opening —
once either sensor reports 1.0 mm of indentation. This came from experience: driving a full
close against a rigid object puts the excess torque into tilting the sensor fixture, and it
broke the mount more than once early on.

**18. Why is the saturation depth different per object class?**

It is 2.0 mm for fragile objects and 0.6 mm for deformable ones. Deformable objects barely
indent the gel, so under a single 2.0 mm saturation they were reaching the safety cutoff
while intensity was still around 0.35 — meaning participants in the deformable trials
received weak feedback no matter how hard they squeezed, which would have made the
deformable comparison meaningless. The 0.6 mm setting reaches full intensity with margin
below the cutoff. The object class is mirrored into shared memory so the sensor processes
pick up the change on the next tick when the experimenter switches objects.

---

## Tier 3 — Method and protocol

**19. How many participants, trials, conditions?**

Twenty-two participants, within-subjects, all seeing all three conditions: visual-only, LRA,
and EM. Two object classes, fragile and deformable, five trials per object per condition —
which gives 110 fragile trials per condition across the sample. All inferential tests
operate on one median value per participant per condition per object class, so the
inferential n is 22, not 110.

**20. How was condition order controlled?**

*[Verify before answering — see question 55. The thesis chapter specifies a complete 3×3
Latin square counterbalance; the preprint lists fixed trial order as a limitation. State
only what was actually run.]* If counterbalanced: condition order followed a complete 3×3
Latin square, so across the sample every condition appeared equally often in first, second
and third position. If fixed: order was fixed across participants, practice and condition
are therefore partially confounded, it is stated as a limitation, and the mitigation is the
practice block plus a post-hoc order-effect check.

**21. Why within-subjects rather than between-subjects?**

Because the expected effect size is modest and the between-person variance is large. Manual
dexterity, prior teleoperation experience, and individual grip-force perception differ
enormously between people, and in a between-subjects design all of that lands in the error
term. Within-subjects, each participant is their own baseline. The cost is order effects,
which is what the counterbalancing and the practice block are for.

**22. Why the median across repeated trials rather than the mean?**

Robustness. With five trials per cell, one unusually clumsy grasp — or one unusually careful
one — can move a mean substantially. The median is stable against that. It is also
consistent with the rest of the analysis, which is entirely rank-based, so I am not mixing a
mean-based reduction with distribution-free tests.

**23. How did you decide an object "broke"?**

The experimenter recorded a binary judgment at the end of every fragile trial, through a
prompt in the recording software. The failure mode is visible and discrete — the egg halves
separate — so it is not a graded judgment call. But I should be clear that it is a human
call made by someone who knew the condition, and I address the blinding issue directly if
asked.

**24. What was the object, physically?**

A hollow plastic egg with separable halves for the fragile class, and a foam cube for the
deformable class — both shown in Figure 4 of the preprint. My thesis chapter still gives raw
eggs and silicone spheres as illustrative examples of the two categories; those were design
candidates, not what was run, and that text needs updating.

**25. Why is the gripper mounted vertically, grasping upward?**

Practical geometry. Objects sit in a cradle at the end of a fixed horizontal arm on a
vertical post placed to the side, so nothing obstructs the fingers as they close. The
object's centre sits at 16.5 cm above the table, laterally aligned with the centre of the
fully-open jaw gap. That height was found empirically as the plane where the fingertips
bracket the object without the gripper body or the sensor wiring touching the table or the
support arm, and it was held fixed for the entire study so approach geometry never varies
across trials, conditions, or participants.

**26. Participants couldn't see the gripper directly?**

Correct. The only view of the workspace was a fixed second camera feed on the operator
display; participants had no direct line of sight to the gripper. That matters for
interpreting the baseline — "visual only" here means vision through a camera, which is the
realistic teleoperation baseline, not naked-eye viewing, which would be a much stronger
control condition than any teleoperator actually has.

**27. What did the questionnaire measure, and when?**

Seven-point Likert items administered immediately after each condition, while that
condition's experience was still fresh, rather than once at the end of the session.
Crucially, the same items were administered after the visual-only condition too, so the
baseline sits on the same scale. The items analyzed are ease of manipulation, contact
detection, grasp confidence, force perception, and mental and physical effort — the effort
items reverse-scored. There were also forced-choice questions asking which condition was
best overall and best for sensing contact state.

**28. Was there a practice block?**

Yes — one untimed practice trial in each condition, in the same order the participant would
meet them in the main session, before any data were recorded. Short rest breaks were offered
between conditions to limit fatigue. The purpose was to get the hand-tracking control
mapping learned before it could contaminate the first recorded condition.

---

## Tier 4 — Statistics

**29. Why Friedman and Wilcoxon rather than repeated-measures ANOVA?**

Three reasons. The design is within-subjects with three levels, which is exactly what
Friedman is for. The Likert data are ordinal, so parametric means on them are not
well-defined. And the force distributions are heavy-tailed by construction — the whole point
of the study is to detect occasional large overshoots, which is precisely the signal a
parametric mean smears out. Rank-based tests also give me a second benefit I lean on
elsewhere: they are invariant to monotonic rescaling, which matters because my force measure
is uncalibrated.

**30. How did you correct for multiple comparisons?**

Holm correction across the three pairwise comparisons within each metric — visual versus
LRA, visual versus EM, and LRA versus EM. Every results table reports both the raw Wilcoxon
p and the Holm-adjusted p, so the correction is visible rather than assumed.

**31. Your headline: survival went 62% to 81% with the LRA and 78% with the EM. Is that
significant?**

It depends on the level of analysis, and I report both. On per-participant survival *rate*,
the Friedman test gives χ² = 11.24, p = 0.0036; visual versus LRA survives Holm correction at
p = 0.018, visual versus EM at p = 0.037, and LRA versus EM is nowhere near significant at
p = 0.69. If instead you binarize each participant to "survived everything or not," Cochran's
Q gives p = 0.097 and no pairwise McNemar test is significant. So the rate analysis is
significant and the binarized one is not.

**32. Why report both? Isn't presenting the significant one cherry-picking?**

Reporting only the rate would be. But the binary analysis is the weaker one on principle,
not just in outcome: collapsing five trials into a single bit throws away most of the
information and most of the power. The rate preserves it. I pre-specified the rate as the
primary analysis for that reason, and both are in the results tables, so anyone can check
that the conclusion does not rest on the choice.

**33. Can you distinguish LRA from EM on anything?**

Not on any confirmatory test. Survival rate, p = 0.69. McNemar on binary survival, p = 0.22.
Peak depth, p = 0.55. Time to first contact, p = 0.95. Approach rate, p = 0.77 on fragile and
0.09 on deformable. And no Likert item separates them after Holm correction. The single place
they do separate is forced-choice preference: 17 of 22 participants named the LRA as their
overall preference and 16 of 22 as best for sensing contact state, both at p = 0.0001.

**34. Then isn't "the LRA was the clear favorite" overstated?**

Not if stated precisely, which is how the preprint puts it: preference is significant,
performance is not. Participants reliably preferred the LRA, and no objective or item-level
subjective measure distinguishes the two. Those are compatible findings and I report them
together. The conclusion says a larger, better-controlled study is needed to tell the
actuators apart, and I stand by that phrasing.

**35. Why is peak dent depth nearly identical across conditions — 0.98, 0.95, 0.98 mm?**

Because it is censored. The safety cutoff blocks further closing at 1.0 mm, so every
condition piles up against the same ceiling and any real difference is truncated away. The
Friedman test on it is non-significant at p = 0.093, as you would expect from a censored
variable. It is stated in the table caption, and I would rather raise it myself than have it
found.

**36. If depth is censored, is deformation volume censored too?**

No, and that asymmetry is exactly what makes volume the useful metric. The cutoff stops the
jaws from advancing, but it does not stop the operator from continuing to load the object
through the compliance already in the system, and it does not stop the gel from continuing
to accumulate deformation. So volume keeps rising after depth has plateaued. That is
precisely what "excess deformation" is defined to capture — loading that continues after the
sensor has stopped telling the operator anything new.

**37. What is TOST doing in your analysis, and what did it show?**

Two one-sided tests, for equivalence. A non-significant difference is not evidence of no
difference, and since my headline LRA-versus-EM result is a null, I owe the reader a test
that can distinguish "they are the same" from "I could not tell." TOST asks whether the
difference falls inside a margin, which I set at half a standard deviation. The result is
mixed and mostly negative: equivalent for peak depth on deformable objects and time to
contact on fragile objects, but *not* equivalent for peak depth on fragile, time to contact
on deformable, or approach rate on either. So the correct conclusion is that the study is
underpowered for this contrast, not that the actuators are interchangeable.

**38. Is N = 22 enough?**

For the vision-versus-haptics contrast, evidently yes — it detected effects that survive
Holm correction, and it exceeds the comparable teleoperation user studies the design was
sized against, which ran 10 and 12 participants. For the LRA-versus-EM contrast, no. The
TOST result makes that concrete rather than leaving it as a hedge: I cannot show a
difference and I cannot show equivalence either. A properly powered follow-up should be
sized from the effects observed here.

**39. Your unit of analysis is the participant, but you quote 110 trials per condition.
Which is it?**

Both, and deliberately separated. The 110 figure is descriptive — it is the denominator for
the raw survival percentage, 22 participants times 5 trials. Every inferential test uses one
median value per participant per condition per object class, so n = 22. Treating 110 trials
as independent observations would badly inflate significance, and no test in the analysis
does that.

**40. Deformable objects showed nothing. Is that a null result or a floor effect?**

I cannot fully separate them, and I say so. Deformable objects never break, so the outcome
variable with the most statistical power simply does not exist for that class, and the depth
signal is small and closer to the sensor's noise floor. The honest framing is "no reliable
change detected," not "no effect." A study designed around deformable objects would need a
different primary outcome — a shape-recovery or residual-deformation measure rather than a
binary survival one.

**41. Some metrics in your results tables are empty — peak force proxy, force overshoot,
reversals. Why?**

Those columns populate only under the sensor-collapse mode that matches the calibration
state of the data. One mode sums the calibrated force columns in newtons, which are blank
because I did not run the load-cell calibration; the other uses the raw uncalibrated
proxies, and that is the run the preprint's volume and grip-adjustment numbers come from.
The pipeline warns when you have chosen the wrong one. The gaps are an artifact of which run
was left in the output directory, not missing data, and I am regenerating both runs into
separate directories so the archived tables are complete.

---

## Tier 5 — Results interpretation

**42. What is your single most defensible claim?**

That for fragile objects, adding tactile feedback to a camera-only teleoperation baseline
reduced wasted grip effort and improved the rate at which objects survived, in a
within-subjects study with 22 participants, with the effect surviving multiple-comparison
correction. Every claim about *which* actuator is better is substantially weaker, and I
present it as such.

**43. Excess deformation dropped roughly ninefold with the LRA, 1530 to 170. Isn't that
implausibly large?**

It is a ratio of medians on an uncalibrated, unbounded accumulator, which is why I plot it on
a log scale rather than a linear one. The quantity is loading that continues *after* the
sensor stops reporting change — a behavior that is close to zero when the operator has
feedback telling them to stop, and effectively unbounded when they do not. So a large ratio
is what the metric's construction predicts. I report it as a large effect with a clear
direction, not as a precise multiplier.

**44. Grip adjustments fell most with the EM, 7 to 2, but excess deformation fell most with
the LRA. Are those consistent?**

They measure different behaviors, so they can move independently. Excess deformation is how
much wasted load was applied; grip adjustments count how often the participant oscillated
between squeezing and easing off after the plateau — searching rather than holding. A
plausible reading is that the EM's sharp mechanical onset marks the contact event crisply,
so participants stop hunting for it, while the LRA's graded buzz communicates magnitude
better, so participants overshoot less. I offer that as a hypothesis. No statistical test in
my data separates the two actuators, so I will not present it as a finding.

**45. Participants preferred the LRA. Is that about the haptics or about the hand tracking?**

I cannot separate those, and it is the confound I would raise myself. The EM condition had
measurably degraded hand tracking because the hardware occludes the tracked landmarks, and
it added fingertip standoff that changed the control mapping. So a preference for the LRA
may reflect smoother, more responsive *control* rather than a better *sensation*. The fix is
a study that equalizes placement — either both actuators at the same location, or placement
run as an explicit factor.

**46. Force perception had the strongest Likert effect. Does subjective force perception
track objective force regulation?**

That is the right question and I have to answer it honestly: the per-participant correlation
between subjective ratings and the objective overshoot metric is specified in my analysis
plan but is not among the tables I have generated. So I can tell you that both moved in the
same direction at the group level — force perception is the strongest subjective effect,
Friedman p below 0.0001 with both haptic conditions at Holm-adjusted p = 0.0003, and excess
deformation is the strongest objective effect — but I cannot yet tell you whether the same
individuals drove both. It is the first analysis I would run next.

**47. Mental and physical effort didn't reach significance. Doesn't that undercut the
usability story?**

It weakens it, and I report it as such rather than omitting it. Mental effort gives a
Friedman p of 0.053, with raw pairwise values of 0.018 and 0.041 that do not survive Holm
correction. Physical effort is p = 0.069. Both are directionally favorable to the haptic
conditions and neither is confirmatory. The correct description is "trending, not
significant," and the usability claim rests on the items that did survive — contact
detection, grasp confidence, and force perception.

**48. What would you have found if the safety cutoff hadn't existed?**

Speculative, but the mechanism is predictable. Peak depth would have been free to separate
across conditions instead of piling up against a ceiling, and the visual-only condition
would likely have broken more objects, since that is the condition where nothing tells the
operator to stop. Both effects would have widened the gap I report. So the cutoff makes the
study conservative — it biases toward the null, not toward my conclusion.

**49. Does the `em2` binary-latch condition appear in your results?**

No, and it should not be read as a fourth arm. It was added to the codebase after the first
19 participants, who ran only visual-only, LRA, and EM. It is a documented design point that
demonstrates the platform can render binary contact, and it is the obvious next condition to
run, but no analysis in this thesis includes it.

---

## Tier 6 — Hostile questions

**50. "Your force measure is uncalibrated. Why should I believe any of these numbers?"**

Because every inferential test in the analysis is rank-based. Calibrating the force proxy
would apply a monotonic transformation, and a monotonic transformation cannot reorder trials
— so no Friedman or Wilcoxon p-value in this thesis would move. I never claim the arbitrary
units are newtons; where I quote magnitudes, they are labelled a.u. and used only for
within-metric comparison. The calibration procedure exists in the repository and is
documented; it is required only if you want to report absolute force, which is not a claim I
make.

**51. "Your millimetre scale rests on one ball radius you typed into a YAML file."**

That is accurate and it is disclosed in the repository documentation. Depth is anchored to a
single declared ball radius, with no independent gauge check, so the absolute millimetre
scale carries error I have not quantified. The same defense applies — the scale error is
monotonic, so it cannot reorder trials or move a rank-based p-value. And there is one point
in my favor worth stating: the safety cutoff is applied in the same units the sensor
reports, so the safety behavior is internally self-consistent even if the absolute scale is
off. What I must not do, and do not do, is quote absolute depths as metrology.

**52. "You changed hardware and tracking parameters partway through. Are all 22 participants
comparable?"**

*[Verify against your lab notebook before the defense.]* The parameter changes I know of —
the pinch-distance floor, the MediaPipe confidence thresholds, the per-object-class
saturation depths, and the EM pulse timings — were made during rig development, before the
recorded sessions, in response to problems that made specific conditions unusable rather
than to tune outcomes. The one change I can date precisely is `em2`, added after participant
19 and excluded from all analysis for exactly that reason. Any parameter that did change
mid-study must be disclosed with the participant index at which it changed, and if one did,
the affected participants should be checked as a sensitivity analysis.

**53. "You compare two actuators that differ in technology *and* placement *and* tracking
quality. That's not a controlled comparison."**

Agreed, without qualification. It is stated in the repository documentation, in the
preprint's discussion, and in how I frame the result. What the study compares is two
complete feedback designs, not two actuator technologies in isolation. That is why no
conclusion in this thesis says one actuator technology outperforms the other — the only
actuator-level claim I make is about stated preference, and I attach the confound to it
every time I state it.

**54. "If nothing distinguishes LRA from EM, what is the contribution of half your title?"**

Three things. First, a working, documented platform where the sensing pipeline, the mapping,
and the task are held fixed and the actuator is a swappable block — which is the apparatus
the comparison needs and which did not previously exist for these two actuator types.
Second, an empirical bound: with 22 participants on this task, the two designs are not
distinguishable on performance, and the equivalence testing shows they are not demonstrably
equivalent either — so the honest result is "underpowered, and here is by how much," which
is more useful to the next researcher than a false positive. Third, the preference
asymmetry — 17 of 22 for the LRA with no supporting performance difference — which is a
concrete, specific target for a follow-up that fixes the placement confound.

**55. "Your thesis chapter says condition order was counterbalanced with a Latin square.
Your preprint lists fixed trial order as a limitation. Which is true?"**

*[This must be resolved before the defense. The two documents contradict each other. Find
out what was actually run, correct whichever document is wrong, and be ready with one
sentence.]* Related: the thesis chapter still describes N = 10–12, two trials per object, and
motor current as the force proxy, while the study as run had 22 participants, five trials
per object, and the deformation-volume proxy. That chapter was written before data
collection and needs updating throughout — I would rather say that plainly than be caught
defending numbers I did not use.

**56. "How do you know participants weren't just getting better at the task?"**

The practice block exists precisely to absorb the steepest part of the learning curve before
recording starts, and rest breaks limit fatigue in the other direction. Beyond that, the
answer depends on whether condition order was counterbalanced — if it was, order effects are
distributed across conditions by construction. If order was fixed, practice and condition
are partially confounded, and the appropriate response is a post-hoc check for a trend
across session position, which I should run and be able to quote rather than argue about.

**57. "Survival was scored by the experimenter, who knew the condition. That's an unblinded
outcome on your headline result."**

Correct, and in this rig it is unavoidable — the participant can feel whether the actuator is
running, so neither participant nor experimenter can be blinded to condition. Three things
mitigate it. The failure mode is discrete and visually unambiguous, so there is little room
for graded judgment. The objective metrics that point the same direction — excess
deformation especially — are instrument-recorded and not subject to experimenter judgment at
all. And the fix is cheap and I would adopt it: record each trial and have survival scored
from video by a rater blind to condition.

**58. "Your thesis proposes a port-Hamiltonian analysis and then doesn't do one."**

It is scoped as future work in the discussion, not offered as a contribution. The motivation
is a real physical property of the hardware — the bistable actuator holds its state using
stored magnetic energy at zero power, which makes it a natural energy port — and
port-Hamiltonian formulations have been applied to passivity in bilateral teleoperation. But
a full treatment of the contact, sensing, and actuation ports is a separate piece of work,
and I would rather name it as a direction than gesture at it as an analysis.

**59. "What would you do differently with another year?"**

In priority order: bench-measure the end-to-end latency, because it is the one system
characterization that is simply missing. Equalize actuator placement, or promote placement to
an explicit experimental factor, because it is the confound that limits every actuator-level
claim. Move to a dedicated resonant-driver IC so the LRA gets true amplitude modulation and
the continuous-versus-discrete contrast becomes real. Add load-cell force calibration so
grip force can be reported in newtons. Power the LRA-versus-EM comparison properly, sized
from the effects I observed. And then extend from one scalar per finger to spatially
resolved feedback across the sensor's depth map, which is where the vision-based sensor
actually earns its complexity.

**60. "Give me your result in one sentence, with the caveat included."**

Tactile feedback made fragile-object teleoperation measurably safer — object survival rose
from 62% with vision alone to around 80% with either actuator, and wasted grip effort fell
sharply — but with 22 participants and two actuator designs that differed in placement as
well as in technology, this study cannot say which actuator is better, only that operators
reliably preferred the LRA.

---

## Before the defense

Six items that these answers depend on and that only you can close:

1. **Resolve the counterbalancing contradiction** between `thesis.tex` and the preprint
   (Q20, Q55, Q56). Three answers hinge on it.
2. **Update `thesis.tex` Chapters 4–5** to the study as run — N = 22, five trials per object
   per condition, deformation-volume proxy rather than motor current, dual-sensor column
   schema, and the objects actually used.
3. **Re-run the analysis under both sensor-collapse modes** into separate output
   directories, confirm the significant findings agree, and archive tables with no empty
   columns (Q41).
4. **Run the post-hoc order/practice check** on fragile survival (Q56).
5. **Run the subjective-versus-objective per-participant correlation** your analysis plan
   specifies (Q46) — it converts a hedge into a finding either way.
6. **Date the parameter changes** against your lab notebook (Q52), and either
   bench-measure end-to-end latency or rehearse the "not measured, here is the protocol"
   answer (Q14).
