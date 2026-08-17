# Defense Q&A Practice Bank

Practice questions for the oral defense / preprint presentation of *Tactile-Feedback
Teleoperation: Grip Force and Grasping Performance Across Haptic Actuator Types for
Fragile and Deformable Objects*.

Each question is followed by an **anchor** — the facts in this repository you should reach
for when answering. Anchors are not scripts; they are the evidence you should not have to
hunt for while standing at the podium.

Sources: `README.md`, `thesis/presentation_preprint.tex`, `thesis/thesis.tex`,
`analysis/results/*.csv`, `kernel/`, `firmware/`, `run/experiment.py`.

**How to drill:** pick a tier, answer out loud in under 60 seconds, then check the anchor.
Tier 1 questions will almost certainly be asked. Tier 6 are the ones that can sink a
defense — rehearse those verbatim.

---

## Tier 1 — Framing and motivation

1. In one sentence, what question does this thesis answer?
   *Anchor:* Two questions, not one — (a) does tactile feedback help in teleoperated
   grasping of fragile/deformable objects, and (b) does the actuator *type* matter. The
   literature mostly answers (a) for a single actuator (Thomas et al., 2019).

2. Why is this worth doing at all — haven't vibrotactile teleoperation studies been done
   for decades?
   *Anchor:* The gap is the head-to-head comparison under a *matched sensing pipeline*.
   Both conditions share the same 9DTact → depth → intensity chain; only the actuator
   differs. Most prior work compares "feedback vs. no feedback" for one device.

3. Why these two actuators specifically — LRA and EM pin?
   *Anchor:* LRA is the commodity baseline (Pacchierotti et al., 2017 — smartwatch-class
   vibration). The EM bistable pin is adapted from Vechev et al. (2019), and it latches
   mechanically, so it can render *sustained contact at zero holding power*. Continuous
   vibration vs. bistable contact is the design axis.

4. Why a gel-based vision tactile sensor instead of a load cell or the gripper's own
   force reading?
   *Anchor:* The Robotiq 2F-85 exposes no F/T channel and its `gCU` current register reads
   0 mA regardless of contact (README, Setup step 8) — the planned "peak motor current"
   proxy is simply dead on this hardware. 9DTact also gives a spatial depth map, not a
   scalar, which the future work builds on.

5. Who is this for? Name a concrete application.
   *Anchor:* Remote manipulation where the operator cannot see contact directly —
   lab/handling automation, remote inspection, assistive teleoperation. Keep it modest;
   the study is a within-subjects lab study, not a fielded system.

6. Why fragile *and* deformable objects? Weren't the deformable results null?
   *Anchor:* They are two different failure modes — abrupt fracture vs. progressive yield.
   The null on deformable objects is itself a finding: feedback helps where the penalty
   for overshoot is a cliff, not a slope.

---

## Tier 2 — System and engineering

7. Walk me through the signal path from object contact to the operator's skin.
   *Anchor:* Object → gel deformation → 9DTact camera (MJPG, buffer pinned to 1 frame) →
   height map − baseline → `compute_metrics()` volume/depth → intensity =
   `deform_mm / DEPTH_SATURATION_MM[object_class]`, clamped to [0,1] → serial
   `"{left:.4f},{right:.4f}\n"` at ~15 Hz (`HAPTIC_HZ`) → ESP32-C6 `stream.py` → per-channel
   driver (LRA PWM / EM burst) → thumb and index.

8. Why is the gripper commanded by hand tracking rather than a joystick or a slider?
   *Anchor:* Preserves the teleoperation framing — the operator's own pinch aperture is the
   command. MediaPipe HandLandmarker maps thumb-tip↔index-tip pixel distance to gripper
   position between `PINCH_DIST_PX` and `SPREAD_DIST_PX` (`kernel/tracking.py`).

9. Your control input is a *2D, uncalibrated* pixel distance. Doesn't that inject noise
   straight into your dependent variables?
   *Anchor:* Yes, and it is a stated limitation. Mitigation: within-subjects design (each
   participant is their own control), fixed camera geometry, fixed object height
   (16.5 cm), practice block before recording. But it is not metric hand tracking and you
   should say so.

10. Both actuators are driven from the same intensity scalar. So what actually differs?
    *Anchor:* Three things at once, and you must say all three: (a) actuator physics
    (resonant mass vs. bistable pin), (b) *placement* — LRA at the proximal joints, EM at
    the fingertips, and (c) consequent hand-tracking robustness. This is the single biggest
    confound in the study (README, "Actuator Placement").

11. Why is the EM condition rendered as repeated bursts rather than as a single latch?
    *Anchor:* To match the LRA's "buzzes whenever intensity > 0" percept under one
    continuous-feedback strategy. `EMVibrationDriver` sets the inter-burst *gap* from
    intensity (short gap = high intensity), floored at `EM_VIBRATE_GAP_MIN_MS = 35` to stay
    under the ~120 switches/minute thermal limit. The binary latch design point exists
    separately as `em2` / `EMLatchDriver`.

12. Then your "continuous vs. discrete" contrast collapses — both conditions gate a
    waveform on and off. Is the comparison meaningful?
    *Anchor:* Concede the narrowing (thesis Limitations, first point). The ESP32's standard
    PWM peripheral cannot produce the phase-locked antiphase pair needed for true amplitude
    modulation of the bipolar H-bridge drive, so LRA intensity is envelope/on-fraction
    modulated within a ~50 ms window. What remains is a real difference in temporal
    granularity, placement, and physical percept — but not a strict continuous/discrete
    dichotomy. A dedicated LRA driver IC is named future work.

13. The LRA carrier is 200 Hz. Is that the actuator's resonance?
    *Anchor:* No — set empirically, not tuned to a measured resonance. Off-resonance drive
    may under-drive the actuator and compress the perceptual dynamic range of the intensity
    signal in the LRA condition. Stated limitation.

14. What is your end-to-end latency, sensor to skin?
    *Anchor:* **Not measured.** This is the honest answer and it is already flagged as
    future work in both the preprint and thesis. What you *can* state: the control loop
    runs at ~30 Hz logging / ~15 Hz haptic update, the firmware fails safe (all motors stop
    if no packet arrives within 200 ms), and the planned measurement is a bench test with a
    photodiode or oscilloscope trigger per actuator type. Do not invent a number.

15. Why did you have to lower MediaPipe's confidence thresholds?
    *Anchor:* The EM actuator body sits on landmarks 4 and 8 (thumb/index tips) — the very
    points being tracked. At defaults (0.6/0.75/0.75) hand presence was lost entirely in
    the `em` condition. Now 0.4/0.5/0.5. Note the asymmetry: the LRA condition never needed
    this, which is exactly the placement confound in question 10.

16. `PINCH_DIST_PX` went from 30 px to 45 px. Why, and did that change the task?
    *Anchor:* The EM body adds physical standoff at the fingertips, so fingers cannot reach
    the bare-finger pinch distance — the gripper undershot `MAX_POS` and never fully
    closed. Raising the floor restores full travel. It rescales the command mapping, so it
    was fixed across all conditions once set, not toggled per condition.

17. What stops a participant from destroying the sensor or the fixture?
    *Anchor:* Two limits — `MAX_POS = 195` (below the Robotiq's true closed position of 225)
    and `MAX_SAFE_DEPTH_MM = 1.0`, a runtime cutoff in `motion_loop` that blocks *further
    closing* (never opening) once either sensor reaches that depth.

18. Why is `DEPTH_SATURATION_MM` different per object class?
    *Anchor:* 2.0 mm fragile / 0.6 mm deformable. Deformable objects barely indent the gel;
    at a single 2.0 mm saturation they hit the safety cutoff while intensity was still
    ~0.35, so the feedback felt weak regardless of grip force. Per-class saturation makes
    the deformable condition reach full intensity with margin below the cutoff.

---

## Tier 3 — Method and protocol

19. How many participants, trials, conditions?
    *Anchor:* N = 22, within-subjects; 110 fragile trials per condition
    (`section_5_7_fragile_breakage.csv`); conditions visual-only / LRA / EM, two object
    classes.

20. How was condition order controlled?
    *Anchor:* **Answer this carefully — see Tier 6, question 55.** The thesis chapter
    specifies a complete 3×3 Latin square; the preprint's Discussion lists *fixed trial
    order* as a limitation. Know which one describes the data you actually collected and
    say only that.

21. Why within-subjects rather than between-subjects?
    *Anchor:* Controls individual differences in dexterity, prior teleoperation experience,
    and grip-force perception — variance that would swamp an effect expected a priori to be
    modest, at this sample size.

22. Why the median across repeated trials rather than the mean?
    *Anchor:* Robustness to a single unusually clumsy or unusually careful grasp; consistent
    with the rank-based tests used downstream.

23. How did you decide an object "broke"?
    *Anchor:* Experimenter judgment at the end of each fragile trial, recorded via the
    `[Y]es/[N]o` "survived intact?" prompt in `experiment.py`. It is a binary human call,
    not an instrumented one — a real weakness worth pre-empting (see question 57).

24. What was the object, physically?
    *Anchor:* A hollow plastic egg with separable halves for fragile (preprint Fig. 4a–b),
    a foam cube for deformable (Fig. 4c). Note the thesis chapter text still names raw eggs
    / silicone spheres as examples — describe what you actually used.

25. Why is the gripper mounted vertically, grasping upward?
    *Anchor:* Objects sit in a cradle on a fixed horizontal arm at h = 16.5 cm, laterally
    aligned with the open-jaw centre, so the post never obstructs the fingers. Fixed for
    the whole study, so approach geometry does not vary across trials or conditions.

26. Participants can't see the gripper directly?
    *Anchor:* Correct — visual feedback is a fixed second camera feed only, preserving the
    teleoperation framing. The "visual_only" baseline is genuinely vision-through-a-camera,
    not naked-eye viewing.

27. What did the questionnaire measure, and when?
    *Anchor:* 7-point Likert items administered immediately after *each* condition
    (including visual-only, so the baseline is on the same scale). Items analyzed:
    ease of manipulation, contact detection, grasp confidence, force perception, mental
    effort (reverse-scored), physical effort. Plus forced-choice preference questions.

28. Was there a practice block?
    *Anchor:* Yes — one untimed practice trial per condition, in the participant's own
    condition order, before any recording. Plus rest breaks between conditions.

---

## Tier 4 — Statistics

29. Why Friedman and Wilcoxon rather than a repeated-measures ANOVA?
    *Anchor:* Within-subjects, ordinal (Likert) and non-normal, heavy-tailed force
    distributions at N = 22; the study is specifically designed to detect occasional
    high-force outliers, which is exactly what parametric means smear.

30. How did you correct for multiple comparisons?
    *Anchor:* Holm across the three pairwise comparisons within each metric — both
    `wilcoxon_p` and `holm_p` are reported in every results CSV.

31. Your headline number: survival went 62% → 81% (LRA) / 78% (EM). Is that significant?
    *Anchor:* Depends on the level of analysis, and you must present both.
    Per-participant survival **rate**: Friedman χ² = 11.24, p = 0.0036; visual vs. LRA
    Holm-p = 0.018, visual vs. EM Holm-p = 0.037, LRA vs. EM p = 0.69 (n.s.).
    Per-participant **binary** (survived-all vs. not): Cochran's Q p = 0.097, all pairwise
    McNemar n.s. So the rate analysis is significant, the binarized one is not.

32. Why report both the rate and the binary analyses at all? Isn't that cherry-picking?
    *Anchor:* The opposite — reporting only the rate would be the cherry-pick. Binarizing
    5 trials into one bit discards most of the information and loses power; the rate keeps
    it. Both are in `section_5_7_fragile_survival_tests.csv` and both are disclosed.

33. Can you distinguish LRA from EM on *anything*?
    *Anchor:* On no single confirmatory test. Survival LRA vs. EM p = 0.69; McNemar
    p = 0.22 (b = 5, c = 1); peak depth p = 0.55; time to contact p = 0.95; approach rate
    p = 0.77 fragile / 0.09 deformable; no Likert item separates them after Holm. The one
    place they separate is the forced-choice preference — 17/22 picked LRA overall
    (χ² p = 0.0001) and 16/22 for best contact-state sensing (p = 0.0001).

34. Then isn't "the LRA was the clear favorite" overstated?
    *Anchor:* No, if stated precisely: *preference* is significant, *performance* is not.
    That is exactly the sentence in the preprint conclusion — "a larger, better-controlled
    study is needed to tell the two actuators apart."

35. Why is peak dent depth nearly identical across conditions (0.98 / 0.95 / 0.98 mm)?
    *Anchor:* Ceiling artifact. `MAX_SAFE_DEPTH_MM = 1.0` blocks further closing at 1.0 mm,
    so the metric is censored right where any difference would appear. Friedman p = 0.093,
    n.s. This is disclosed in the table caption — say it before the examiner does.

36. If depth is censored, is deformation volume censored too?
    *Anchor:* No, and that is the point — the jaws stop advancing but the operator can keep
    loading, so volume keeps accumulating. That is what "excess deformation" captures, and
    why volume separates conditions (V 1530 → LRA 170 a.u.) where depth cannot.

37. What is TOST doing in your analysis, and what did it show?
    *Anchor:* Two one-sided tests for *equivalence* — a non-significant difference is not
    evidence of no difference, so TOST asks whether LRA and EM fall inside a ±0.5 SD margin.
    Result (`section_5_9_tost_equivalence.csv`): equivalent for peak depth on deformable
    (p < 0.001) and time-to-contact on fragile (p = 0.045); **not** equivalent for peak
    depth fragile (0.127), time-to-contact deformable (0.064), approach rate (0.054 / 0.283).
    So: underpowered, not equivalent. Do not claim "the actuators are the same."

38. Is N = 22 enough?
    *Anchor:* It exceeds the comparable literature the design was sized against (Luo et al.
    N = 10; Abdi et al. N = 12) and it detected the vision-vs-haptic effect. It is clearly
    *not* enough for the LRA-vs-EM contrast, which the TOST result makes explicit rather
    than hides.

39. Your unit of analysis is the participant, but you quote "110 trials per condition."
    Which is it?
    *Anchor:* Both, deliberately: 110 trials is the descriptive survival denominator
    (22 × 5); every inferential test uses one median value per participant per condition per
    object class, n = 22. Never run a test on 110 trials as if they were independent.

40. Deformable objects showed nothing. Is that a null result or a floor effect?
    *Anchor:* Honest answer: cannot fully separate them. Deformable objects never break, so
    the outcome variable with the most power (survival) does not exist for them, and depth
    is small and near the noise floor. Frame it as "no reliable change detected," not "no
    effect."

41. Some metrics in your results CSVs are empty — peak force proxy, force overshoot,
    reversals. Why?
    *Anchor:* Those columns are populated only under the collapse mode that matches the
    calibration state of the data. `--collapse sum_n` sums calibrated `force_N`, which is
    blank on uncalibrated data; `--collapse max` uses the raw proxies. The preprint's
    volume and grip-adjustment numbers come from the `max` run. **Regenerate and archive
    both runs before the defense so no reviewer opens a CSV with holes in it.**

---

## Tier 5 — Results interpretation

42. What is your single most defensible claim?
    *Anchor:* For fragile objects, adding tactile feedback reduced wasted grip effort and
    improved survival relative to a vision-only baseline, under a within-subjects design
    with N = 22. Everything about *which* actuator is weaker.

43. Excess deformation dropped roughly ninefold with the LRA (1530 → 170 a.u.). Isn't that
    implausibly large?
    *Anchor:* It is a ratio of medians on an uncalibrated, unbounded accumulator, plotted on
    a log scale for exactly that reason (Fig. 5b). It measures loading that continues after
    the sensor stops reporting change — a behavior that is near-zero when feedback exists
    and unbounded when it does not. Report it as a large effect, not as a precise 9×.

44. Grip adjustments fell most with the EM (7 → 2) but excess deformation fell most with
    the LRA. Are those consistent?
    *Anchor:* They describe different behaviors: excess deformation is *how much* wasted
    load, adjustments are *how much searching*. A plausible reading is that the EM's sharp
    onset marks contact crisply (fewer hunts) while the LRA's graded buzz communicates
    magnitude (less overshoot). Offer it as a hypothesis, not a conclusion — no test
    separates the two actuators.

45. Participants preferred the LRA. Is that about the haptics or about the hand tracking?
    *Anchor:* Cannot be separated — this is the confound you must volunteer. The EM
    condition had degraded tracking (fingertip occlusion, question 15) and added standoff,
    so preference may reflect smoother *control* rather than a better *sensation*. Already
    stated in the preprint Discussion.

46. Force perception had the strongest Likert effect (Friedman p < 0.0001, Holm-p = 0.0003
    both haptic conditions). Does subjective force perception track objective force?
    *Anchor:* The per-participant correlation between subjective ratings and the
    overshoot/excess metric is specified in the thesis plan but is not among the generated
    result tables. Say what exists; offer it as the immediate next analysis.

47. Mental and physical effort didn't reach significance. Doesn't that undercut the
    usability story?
    *Anchor:* Mental effort: Friedman p = 0.053, pairwise p = 0.018/0.041 raw but
    0.055/0.083 after Holm. Physical effort p = 0.069. Directionally favorable, not
    confirmatory. Say "trending, not significant" and leave it there.

48. What would you have found if the safety cutoff hadn't existed?
    *Anchor:* Speculative — but the mechanism is clear: peak depth would have been free to
    separate, and the fragile break rate in the visual-only condition would likely have been
    higher, widening the gap. The cutoff makes the study *conservative*, biasing toward the
    null.

49. Does the `em2` condition appear in your results?
    *Anchor:* No. It was added after the first 19 participants, who ran only
    visual_only/lra/em; it is a documented design point in the codebase, not a study
    condition. Do not present it as a fourth arm.

---

## Tier 6 — Hostile questions (rehearse these verbatim)

50. "Your force measure is uncalibrated. Why should I believe any of these numbers?"
    *Anchor:* Because every inferential test is rank-based. A monotonic rescaling cannot
    reorder trials, so no Friedman or Wilcoxon p-value moves under calibration. Absolute
    a.u. magnitudes are *not* claimed as newtons anywhere. The calibration path exists
    (README Setup step 8) and is needed only to report absolute force.

51. "Your millimetre scale rests on one ball radius you typed into a YAML file."
    *Anchor:* Correct, and disclosed. Depth is anchored to `BallRad` (4.0 mm) with no
    independent gauge check, so absolute mm carry unquantified error. Same defense as
    above — monotonic, so rank tests are unaffected — plus one caveat you should state
    yourself: `MAX_SAFE_DEPTH_MM` is applied in the same units the sensor reports, so the
    safety behavior is self-consistent even if the scale is off.

52. "You changed the hardware and the tracking parameters partway through. Are all 22
    participants comparable?"
    *Anchor:* Be precise about which changes preceded data collection (`PINCH_DIST_PX`,
    MediaPipe thresholds, per-class saturation, EM pulse tuning) and which came after
    (`em2`, added post-P19 and excluded). Any parameter that changed mid-study must be
    disclosed with the participant index at which it changed. **Verify this against your
    lab notebook before the defense — it is the question most likely to expose an
    undocumented change.**

53. "You compare two actuators that differ in technology *and* placement *and* tracking
    quality. That's not a controlled comparison."
    *Anchor:* Agree without hedging — it is stated in the README, the preprint Discussion,
    and here. The correct framing is that the study compares two *complete feedback
    designs*, not two actuator technologies in isolation. The conclusion is written to
    match: no claim that one actuator technology beats the other survives.

54. "If nothing distinguishes LRA from EM, what is the contribution of half your title?"
    *Anchor:* Three things: (a) a working, documented, matched-pipeline platform where the
    actuator is the only swapped block; (b) an empirical bound — with N = 22 and this task,
    the two designs are *not* distinguishable on performance, and TOST shows they are not
    equivalent either, so the honest result is "underpowered, here is how much"; (c) the
    preference asymmetry (17/22 LRA) as a concrete target for a follow-up that fixes the
    placement confound.

55. "Your thesis chapter says the condition order was counterbalanced with a Latin square.
    Your preprint lists fixed trial order as a limitation. Which is true?"
    *Anchor:* **You must resolve this before the defense.** These two documents contradict
    each other. Determine what was actually run, correct whichever document is wrong, and
    have the answer ready in one sentence. Also note the thesis chapter still says
    N = 10–12 with 2 trials per object and `current_mA` as the force proxy, while the study
    ran N = 22 with 5 trials and the deformation-volume proxy — the chapter predates the
    data and needs updating throughout.

56. "How do you know participants weren't just getting better at the task?"
    *Anchor:* Practice block before recording, rest breaks, and — depending on the answer to
    question 55 — counterbalancing. If order was fixed, the honest answer is that practice
    and condition are partly confounded and the fix is a post-hoc order effect check, which
    you should run and be able to quote.

57. "Survival was scored by the experimenter, who knew the condition. That's an unblinded
    outcome on your headline result."
    *Anchor:* True and unavoidable in this rig — the participant feels the actuator, so
    neither participant nor experimenter can be blinded. Mitigations to offer: the failure
    mode is binary and visible (the egg halves separate), not a judgment call; the
    quantitative metrics (excess deformation) are instrument-recorded and point the same
    way. Offer video-scored blind rating as the fix.

58. "Your thesis proposes a port-Hamiltonian analysis and then doesn't do one."
    *Anchor:* It is explicitly scoped as future work, not a contribution. It is motivated
    by a real property of the hardware — the bistable actuator stores magnetic energy to
    hold state at zero power, which is a natural port. Do not oversell it.

59. "What would you do differently with another year?"
    *Anchor:* In priority order: (1) bench-measure end-to-end latency; (2) equalize actuator
    placement, or run placement as its own factor; (3) dedicated LRA driver IC for true
    amplitude modulation; (4) load-cell force calibration for newtons; (5) power the
    LRA-vs-EM contrast properly, sized from the effects observed here; (6) spatial
    multi-region feedback instead of one scalar per finger.

60. "Give me your result in one sentence, with the caveat included."
    *Anchor:* "Tactile feedback made fragile-object teleoperation measurably safer — survival
    rose from 62% to about 80% and wasted grip effort fell sharply — but with N = 22 and two
    actuator designs that differed in placement as well as technology, this study cannot say
    which actuator is better, only that operators preferred the LRA."

---

## Pre-defense checklist

These are open items this bank surfaced. Close them before the defense, not during it.

- [ ] Resolve the counterbalancing contradiction between `thesis.tex` and the preprint (Q55).
- [ ] Update `thesis/thesis.tex` Chapters 4–5 to the study as run: N = 22, 5 trials per
      object per condition, deformation-volume proxy instead of `current_mA`, dual-sensor
      column schema.
- [ ] Re-run `python -m analysis` under both `--collapse max` and `--collapse sum_n` into
      separate output directories and confirm the significant findings agree (Q41).
- [ ] Run a post-hoc order/practice effect check on the fragile survival data (Q56).
- [ ] Run the subjective-vs-objective per-participant correlation the thesis plan
      specifies (Q46).
- [ ] Record which parameter changes (`PINCH_DIST_PX`, MediaPipe thresholds,
      `DEPTH_SATURATION_MM`, EM pulse timings) occurred at which participant index (Q52).
- [ ] Bench-measure end-to-end latency, or have the one-sentence "not measured, here is the
      planned protocol" answer rehearsed (Q14).
