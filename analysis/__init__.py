"""
Thesis Chapter 5 analysis pipeline (Sections 5.1, 5.3-5.7, 5.9).

Reads the trial CSVs written by experiment.py
(<trials-dir>/<participant>/<participant>_<condition>_<object>_trial<N>.csv)
plus a Likert CSV, and writes every table and figure:

    python -m analysis --trials-dir data/experiment_logs --out analysis/results \\
        [--likert-csv ...] [--collapse sum_n|max] [--preprint-figures thesis/figures]

--trials-dir is scanned recursively, so it also picks up flat/legacy layouts
where trial CSVs sit directly in --trials-dir instead of a per-participant
subfolder.

--collapse combines the two sensors into one force + one depth series per trial:
    sum_n  grip force = left_force_N + right_force_N (Newtons). Needs
           calibration (setup.py calibrate-force); the headline once you have it.
    max    grip force = max of the raw force proxies (uncalibrated). Works now.
Depth is max(left, right) either way, so contact time is first-of-either-finger.
The tests are rank-based, so sum and mean give identical p-values — only sum_n
vs max can reorder trials. Run both and confirm the findings agree.

--preprint-figures additionally draws the two figures thesis/preprint.tex
includes, from the same frames the CSVs are written from.

Section 5.2 (latency) is NOT computed here — it needs a separate bench
measurement; the ~30 Hz trial CSV cannot capture true sensor-to-actuator latency.

Module map:
    trials.py       5.1  loading, per-trial metrics, per-participant reduction
    tests.py             statistical primitives (Holm, TOST, Cochran's Q, McNemar)
    comparisons.py  5.3/5.4/5.9  cross-condition, LRA vs TacTiles, equivalence
    survival.py     5.4/5.7  fragile-object survival (paired binary outcome)
    likert.py       5.6  qualitative survey
    figures.py      5.5  time series, plus the preprint figures
    __main__.py          CLI entry point
"""

CONDITIONS = ["visual_only", "lra", "tactiles"]
OBJECTS = ["fragile", "deformable"]
