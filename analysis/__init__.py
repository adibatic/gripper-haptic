"""
Thesis Chapter 5 analysis pipeline (Sections 5.1-5.6).

    python -m analysis --trials-dir data/experiment_logs --out analysis/results \\
        [--likert-csv ...] [--collapse sum_n|max] [--preprint-figures thesis/figures]

--collapse combines the two sensors into one force + one depth series per trial:
    sum_n  grip force = left_force_N + right_force_N (Newtons). Needs
           calibration (setup.py calibrate-force); the headline once you have it.
    max    grip force = max of the raw force proxies (uncalibrated). Works now.
The tests are rank-based, so only sum_n vs max can reorder trials. Run both and
confirm the findings agree.

Section 5.7 (latency) is NOT computed here — it needs a separate bench
measurement; the 15 Hz trial CSV cannot capture true sensor-to-actuator latency.

Module map:
    trials.py       5.1  loading, per-trial metrics, per-participant reduction
    tests.py             statistical primitives (Holm, TOST, Cochran's Q, McNemar)
    comparisons.py  5.2/5.3/5.4  cross-condition, LRA vs EM, equivalence
    survival.py     5.2  fragile-object survival (paired binary outcome)
    robustness.py   5.2  saturation rate; practice-adjusted survival model
    likert.py       5.6  qualitative survey
    visualization.py     5.5  time-series figures
    __main__.py          CLI entry point
"""

CONDITIONS = ["visual_only", "lra", "em"]
OBJECTS = ["fragile", "deformable"]
