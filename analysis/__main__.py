"""
Pipeline entry point — python -m analysis.

Runs every section in order and writes each table and figure into --out. See
the package docstring (analysis/__init__.py) for the CLI and the --collapse
modes.
"""

import os
import argparse

from .trials import load_all_trials, reduce_to_participant_condition_object
from .comparisons import (friedman_and_pairwise, write_cross_condition_report,
                          lra_vs_tactiles, write_lra_vs_tactiles_report,
                          lra_vs_tactiles_tost, write_tost_equivalence_report)
from .survival import (write_fragile_breakage_summary, mcnemar_fragile_survival,
                       write_fragile_mcnemar_report,
                       fragile_survival_across_conditions,
                       write_fragile_survival_tests_report)
from .likert import analyze_likert
from .figures import (plot_representative_trials, plot_preprint_results,
                      plot_preprint_likert)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    """Parses args and runs the full Chapter 5 pipeline: loads and reduces
    trial data (5.1), cross-condition and LRA-vs-TacTiles comparisons
    (5.3/5.4), representative time-series figures (5.5), and — if
    --likert-csv is given — the survey analysis (5.6)."""
    parser = argparse.ArgumentParser(description="Run thesis Chapter 5 analysis on real trial data.")
    parser.add_argument("--trials-dir", required=True, help="Directory of trial CSVs from experiment.py.")
    parser.add_argument("--likert-csv", default=None, help="Path to the raw Google Forms Likert "
                         "questionnaire CSV export (see load_likert_long() for the expected "
                         "column layout). Optional.")
    parser.add_argument("--out", required=True, help="Output directory for tables and figures.")
    parser.add_argument("--preprint-figures", default=None, metavar="DIR",
                         help="Also write the two preprint figures (preprint_results.png, "
                              "preprint_likert.png) into DIR — pass thesis/figures to "
                              "refresh what thesis/preprint.tex includes. The Likert figure "
                              "needs --likert-csv.")
    parser.add_argument("--contact-threshold-mm", type=float, default=0.05,
                         help="Depth threshold for 'first contact' (Section 5.1). "
                              "Default 0.05mm — adjust based on your sensor's measured "
                              "no-contact noise floor (Section 3.2.1) before real analysis.")
    parser.add_argument("--collapse", choices=["sum_n", "max"], default="sum_n",
                         help="How to combine the left/right sensors into each metric. "
                              "sum_n: grip force = left_force_N + right_force_N (calibrated "
                              "Newtons) — the headline once calibrated. max: max of the raw "
                              "force proxies (uncalibrated) — works pre-calibration. Depth is "
                              "max(L,R) either way. Run both and confirm findings agree.")
    parser.add_argument("--equiv-margin-sd", type=float, default=0.5,
                         help="Section 5.9 TOST equivalence margin, as a multiple of each "
                              "metric's pooled SD (effect-size-scaled). Default 0.5 (a "
                              "'medium' Cohen's d) — this is a judgment call about the "
                              "smallest difference you'd consider practically meaningful; "
                              "state and justify your choice in the thesis text.")
    parser.add_argument("--equiv-alpha", type=float, default=0.05,
                         help="Per-side significance level for the Section 5.9 TOST test "
                              "(default 0.05, the conventional two-one-sided-tests level).")
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)

    print(f"Loading trials from {args.trials_dir} (collapse={args.collapse}) ...")
    trial_df = load_all_trials(args.trials_dir, args.contact_threshold_mm, args.collapse)
    trial_df.to_csv(os.path.join(args.out, "section_5_1_per_trial_metrics.csv"), index=False)
    print(f"Wrote {os.path.join(args.out, 'section_5_1_per_trial_metrics.csv')} "
          f"({len(trial_df)} trials)")

    breakage = write_fragile_breakage_summary(trial_df, args.out)

    reduced_df = reduce_to_participant_condition_object(trial_df)
    reduced_df.to_csv(os.path.join(args.out, "section_5_1_reduced_metrics.csv"), index=False)
    print(f"Wrote {os.path.join(args.out, 'section_5_1_reduced_metrics.csv')} "
          f"({len(reduced_df)} participant x condition x object rows)")

    print("\nRunning Section 5.3 (cross-condition Friedman + Wilcoxon)...")
    metrics = ["peak_force_proxy", "peak_depth_mm", "time_to_first_contact_s", "force_overshoot_proxy"]
    trajectory_metrics = ["approach_rate_mm_s", "n_force_reversals_post_plateau",
                           "time_above_90pct_peak_s"]
    all_metrics = metrics + trajectory_metrics
    cross_condition_results = {}
    for metric in all_metrics:
        cross_condition_results[metric] = friedman_and_pairwise(reduced_df, metric, args.out)
    write_cross_condition_report(cross_condition_results, args.out)

    print("\nRunning Section 5.4 (LRA vs TacTiles direct comparison)...")
    lra_tactiles_results = {}
    for metric in all_metrics:
        lra_tactiles_results[metric] = lra_vs_tactiles(reduced_df, metric)
    write_lra_vs_tactiles_report(lra_tactiles_results, args.out)

    print("\nRunning Section 5.4 (fragile breakage: McNemar lra vs tactiles)...")
    mcnemar_result = mcnemar_fragile_survival(reduced_df)
    write_fragile_mcnemar_report(mcnemar_result, args.out)

    print(f"\nRunning Section 5.9 (TOST equivalence, lra vs tactiles, "
          f"margin={args.equiv_margin_sd} pooled SD, alpha={args.equiv_alpha})...")
    tost_results = {}
    for metric in all_metrics:
        tost_results[metric] = lra_vs_tactiles_tost(
            reduced_df, metric, args.equiv_margin_sd, args.equiv_alpha)
    write_tost_equivalence_report(tost_results, args.equiv_margin_sd, args.equiv_alpha, args.out)

    print("\nRunning Section 5.7 (fragile survival across conditions: rate-level "
          "Friedman/Wilcoxon + binary Cochran's Q/McNemar, incl. vision vs haptic)...")
    survival_tests = fragile_survival_across_conditions(trial_df, reduced_df)
    write_fragile_survival_tests_report(survival_tests, args.out)

    print("\nGenerating Section 5.5 time-series figures...")
    plot_representative_trials(args.trials_dir, args.out, args.collapse)

    likert = None
    if args.likert_csv:
        print("\nRunning Section 5.6 (Likert survey analysis)...")
        likert = analyze_likert(args.likert_csv, args.out)
    else:
        print("\nNOTE: --likert-csv not provided, skipping Section 5.6.")

    if args.preprint_figures:
        print(f"\nGenerating preprint figures into {args.preprint_figures}/ ...")
        os.makedirs(args.preprint_figures, exist_ok=True)
        plot_preprint_results(breakage, reduced_df, args.preprint_figures)
        if likert is None:
            print("NOTE: no Likert data — skipping preprint_likert.png.")
        else:
            plot_preprint_likert(*likert, args.preprint_figures)

    print(f"\nAll Section 5.1/5.3/5.4/5.5/5.6 outputs written to {args.out}/ (collapse={args.collapse})")
    print("ROBUSTNESS: re-run with the other --collapse mode into a separate --out and")
    print("confirm the significant findings hold under both (sum_n and max are the only")
    print("two collapses that can reorder trials) — report that in Section 5.1.")
    print("Section 5.2 (sensor-to-actuator latency) requires a separate bench")
    print("measurement and is NOT computed by this script — see thesis Section 5.2.")


if __name__ == "__main__":
    main()
