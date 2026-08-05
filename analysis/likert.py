"""
Section 5.6 — qualitative survey results.

Parses the raw Google Forms export directly (participant + three repeated
per-condition blocks of six Likert items + two nominal preference questions +
free-text comments) — the form's wide layout IS the schema, there is no long
format to hand this script. Runs the same Friedman/Wilcoxon/Holm treatment used
for the trial metrics, plus a chi-square goodness-of-fit on the two
forced-choice questions.
"""

import os
import re
import csv

import numpy as np
import pandas as pd
from scipy import stats

from . import CONDITIONS
from .tests import holm_bonferroni


# Column labels for the 6 items in each per-condition block, in form order.
# Renamed from the survey's literal question text (below) to short slugs for
# use as DataFrame/CSV columns.
LIKERT_ITEM_COLUMNS = [
    "ease_of_manipulation", "contact_detection", "grasp_confidence",
    "force_perception", "mental_effort_low", "physical_effort_low",
]


# The exact question text Google Forms exports for each item, used ONLY to
# sanity-check that a given CSV's columns are laid out as expected (see
# load_likert_long). Scale is 1 (strongly disagree) - 5 (strongly agree) for
# all six items, INCLUDING the two effort items — "low effort" is the
# agree-is-good direction, same as the other four, so no items need reverse
# coding. The form itself did not label the scale endpoints (flagged by a
# respondent's free-text comment); note this as a methods limitation.
LIKERT_ITEM_QUESTION_TEXT = [
    "It was easy to manipulate objects using the teleoperation system.",
    "I could clearly tell when the robot hand made contact with an object.",
    "I felt confident that the object was securely grasped in the robot hand.",
    "I could perceive how much force I was applying to the object.",
    "Mental effort required for this task was low.",
    "Physical effort required for this task was low.",
]


# The three per-condition blocks are IDENTICAL in header text (Google Forms
# repeats the section's question text verbatim per section) — condition is
# encoded ONLY by which block position a column falls in, so this order must
# match the live form's actual section order or every response is silently
# mislabeled. Confirmed against the form as visual_only -> lra -> em
# (the same order as CONDITIONS/experiment.py's condition cycle) on
# 2026-07-22 — re-confirm against the form itself if you re-export.
LIKERT_BLOCK_CONDITIONS = ["visual_only", "lra", "em"]


# 0-indexed column offsets of each block in data/likert/likert_responses.csv.
# The form added a "Do you have any visual, auditory, or tactile sensory
# impairments relevant to this study?" question at column 10 after the
# initial export, shifting the three blocks from [10, 16, 22] to this.
LIKERT_BLOCK_STARTS = [11, 17, 23]


# Keys are the literal option text Google Forms exported, i.e. what
# participants actually saw on the form — do NOT "modernize" them in
# data/likert/likert_responses.csv to match the em/lra vocabulary. That CSV is
# the verbatim survey record; rewriting it would falsify what was administered.
# The rename lives here instead, which is the only place the two vocabularies
# need to meet.
PREFERENCE_LABEL_TO_CONDITION = {
    "Vibration Motor": "lra", "Pin Actuator": "em", "No Feedback": "visual_only",
}


def load_likert_long(likert_csv_path):
    """Loads the raw Google Forms export and reshapes it into a long-format
    DataFrame (one row per participant x condition x item) plus a separate
    per-participant preference DataFrame for the two nominal questions.

    Args:
        likert_csv_path: Path to the raw Google Forms CSV export.

    Returns:
        None if the file doesn't exist. Otherwise (long_df, prefs_df):
        long_df has columns participant/condition/item/value;
        prefs_df has columns participant/best_contact_condition/
        preferred_condition (None where a response's label wasn't
        recognized — printed as a warning).

    Raises:
        ValueError: If the CSV's block columns don't match
            LIKERT_ITEM_QUESTION_TEXT at the expected positions — the form
            was probably edited, so LIKERT_ITEM_QUESTION_TEXT/
            LIKERT_BLOCK_STARTS need updating to match before this can be
            trusted not to mislabel data.
    """
    if not os.path.exists(likert_csv_path):
        return None

    raw = pd.read_csv(likert_csv_path)
    header = list(raw.columns)
    # pandas dedupes repeated header text (three identical per-condition
    # blocks) by appending ".1", ".2" — strip that back off before comparing
    # against the expected question text.
    dedupe_suffix = re.compile(r"\.\d+$")
    normalized_header = [dedupe_suffix.sub("", h) for h in header]

    for start in LIKERT_BLOCK_STARTS:
        block_text = normalized_header[start:start + len(LIKERT_ITEM_QUESTION_TEXT)]
        if block_text != LIKERT_ITEM_QUESTION_TEXT:
            raise ValueError(
                f"Likert CSV columns {start}-{start + len(LIKERT_ITEM_QUESTION_TEXT) - 1} "
                f"don't match the expected question text. Expected "
                f"{LIKERT_ITEM_QUESTION_TEXT}, got {block_text}. The form was likely "
                f"edited — update LIKERT_ITEM_QUESTION_TEXT/LIKERT_BLOCK_STARTS in "
                f"analysis/likert.py to match before trusting this parse.")

    pid_col = header[1]
    rows = []
    for _, r in raw.iterrows():
        participant = str(r[pid_col]).strip()
        if not participant or participant.lower() == "nan":
            continue
        for condition, start in zip(LIKERT_BLOCK_CONDITIONS, LIKERT_BLOCK_STARTS):
            for item, col_idx in zip(LIKERT_ITEM_COLUMNS, range(start, start + 6)):
                rows.append({
                    "participant": participant, "condition": condition, "item": item,
                    "value": pd.to_numeric(r.iloc[col_idx], errors="coerce"),
                })
    long_df = pd.DataFrame(rows)

    best_col, pref_col = header[29], header[30]
    prefs = raw[[pid_col, best_col, pref_col]].copy()
    prefs.columns = ["participant", "best_contact_label", "preferred_label"]
    prefs = prefs[prefs["participant"].astype(str).str.strip().ne("")]
    prefs["best_contact_condition"] = prefs["best_contact_label"].map(PREFERENCE_LABEL_TO_CONDITION)
    prefs["preferred_condition"] = prefs["preferred_label"].map(PREFERENCE_LABEL_TO_CONDITION)

    for label_col, cond_col in [("best_contact_label", "best_contact_condition"),
                                 ("preferred_label", "preferred_condition")]:
        unmapped = prefs[prefs[cond_col].isna() & prefs[label_col].notna()]
        if len(unmapped) > 0:
            print(f"WARNING: {len(unmapped)} response(s) for '{label_col}' don't match a "
                  f"known label in PREFERENCE_LABEL_TO_CONDITION: "
                  f"{unmapped[label_col].tolist()} — left unmapped (None).")

    return long_df, prefs


def write_likert_summary(long_df, out_dir):
    """Section 5.6: per-item median/IQR per condition, all six items."""
    path = os.path.join(out_dir, "section_5_6_likert_summary.csv")
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["item", "condition", "n", "median", "iqr_low", "iqr_high"])
        for item in LIKERT_ITEM_COLUMNS:
            for condition in CONDITIONS:
                vals = long_df[(long_df["item"] == item)
                               & (long_df["condition"] == condition)]["value"].dropna()
                if len(vals) == 0:
                    continue
                writer.writerow([item, condition, len(vals),
                                  f"{vals.median():.2f}",
                                  f"{np.percentile(vals, 25):.2f}",
                                  f"{np.percentile(vals, 75):.2f}"])
    print(f"Wrote {path}")


def write_likert_friedman(long_df, out_dir):
    """Section 5.6: Friedman across all three conditions for each item, then
    pairwise Wilcoxon signed-rank with Holm correction — same
    complete-cases/zero-variance handling as friedman_and_pairwise()
    (Section 5.3), applied to the six survey items instead of the four
    trial metrics. Returns the Holm-corrected p-value per
    (item, "<a>_vs_<b>") pair, for the preprint figure's brackets."""
    holm_by_pair = {}
    path = os.path.join(out_dir, "section_5_6_likert_friedman.csv")
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["item", "n", "friedman_stat", "friedman_p",
                          "comparison", "wilcoxon_stat", "wilcoxon_p", "holm_p"])

        for item in LIKERT_ITEM_COLUMNS:
            sub = long_df[long_df["item"] == item]
            pivot = sub.pivot(index="participant", columns="condition", values="value")
            complete = pivot.dropna(subset=CONDITIONS, how="any")
            n_dropped = len(pivot) - len(complete)
            if n_dropped > 0:
                print(f"NOTE: Likert item '{item}': dropping {n_dropped} participant(s) "
                      f"missing a response in at least one condition.")
            if len(complete) < 3:
                print(f"WARNING: Likert item '{item}': only {len(complete)} complete "
                      f"participant(s) — too few for Friedman/Wilcoxon. Skipping.")
                writer.writerow([item, len(complete), "", "", "", "", "", ""])
                continue

            visual, lra, em = (complete[c].to_numpy() for c in CONDITIONS)
            fr_stat, fr_p = stats.friedmanchisquare(visual, lra, em)

            pairs = [("visual_only", "lra", visual, lra),
                     ("visual_only", "em", visual, em),
                     ("lra", "em", lra, em)]
            raw_p = []
            pairwise = []
            for name_a, name_b, a, b in pairs:
                if np.all(a - b == 0):
                    print(f"WARNING: Likert item '{item}': {name_a} vs {name_b} has zero "
                          f"variance — Wilcoxon undefined, skipping pair.")
                    pairwise.append((name_a, name_b, None, None))
                    raw_p.append(1.0)
                    continue
                w_stat, w_p = stats.wilcoxon(a, b)
                pairwise.append((name_a, name_b, w_stat, w_p))
                raw_p.append(w_p)
            holm_p = holm_bonferroni(raw_p)

            for (name_a, name_b, w_stat, w_p), hp in zip(pairwise, holm_p):
                holm_by_pair[(item, f"{name_a}_vs_{name_b}")] = hp
                writer.writerow([
                    item, len(complete), f"{fr_stat:.4f}", f"{fr_p:.4f}",
                    f"{name_a}_vs_{name_b}",
                    f"{w_stat:.4f}" if w_stat is not None else "",
                    f"{w_p:.4f}" if w_p is not None else "",
                    f"{hp:.4f}",
                ])
    print(f"Wrote {path}")
    return holm_by_pair


def write_likert_preference(prefs, out_dir):
    """Section 5.6: descriptive counts/proportions for the two nominal
    preference questions ('best sense of contact/grasp state', 'preferred
    overall'), plus a chi-square goodness-of-fit test against a uniform 1/3
    split per question — flagged as underpowered (reported, not relied on)
    whenever any expected cell count is below the conventional threshold
    of 5, which is virtually guaranteed at this sample size. Returns
    {question: (counts per condition, chi-square p)} for the preprint
    figure."""
    preference = {}
    path = os.path.join(out_dir, "section_5_6_likert_preference.csv")
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["question", "condition", "n", "proportion",
                          "chi2_stat", "chi2_p", "chi2_reliable"])
        for question, col in [("best_contact_state", "best_contact_condition"),
                               ("preferred_overall", "preferred_condition")]:
            vals = prefs[col].dropna()
            n_total = len(vals)
            if n_total == 0:
                writer.writerow([question, "", 0, "", "", "", ""])
                continue
            counts = vals.value_counts().reindex(CONDITIONS, fill_value=0)
            expected = n_total / len(CONDITIONS)
            reliable = expected >= 5
            if not reliable:
                print(f"NOTE: Likert preference '{question}': expected cell count "
                      f"{expected:.1f} < 5 (n={n_total}) — chi-square reported but "
                      f"underpowered; treat as descriptive only.")
            chi2, p = stats.chisquare(counts.to_numpy())
            preference[question] = ({c: int(counts[c]) for c in CONDITIONS}, p)
            for condition in CONDITIONS:
                writer.writerow([
                    question, condition, int(counts[condition]),
                    f"{counts[condition] / n_total:.4f}",
                    f"{chi2:.4f}", f"{p:.4f}", reliable,
                ])
    print(f"Wrote {path}")
    return preference


def analyze_likert(likert_csv_path, out_dir):
    """Section 5.6: loads the raw Google Forms export and writes the three
    survey report CSVs — per-item summary, per-item Friedman/Wilcoxon across
    all three conditions, and the two nominal preference questions.

    Args:
        likert_csv_path: Path to the raw Google Forms CSV export. If
            missing, prints a note and returns without writing anything.
        out_dir: Directory to write the three Section 5.6 CSVs into.

    Returns:
        (long_df, holm_by_pair, preference) for plot_preprint_likert(), or
        None if the CSV is missing.
    """
    loaded = load_likert_long(likert_csv_path)
    if loaded is None:
        print(f"NOTE: Likert CSV not found at {likert_csv_path} — skipping Section 5.6.")
        return None
    long_df, prefs = loaded

    n_participants = long_df["participant"].nunique()
    print(f"Loaded {n_participants} participant(s) from the Likert survey.")

    write_likert_summary(long_df, out_dir)
    holm_by_pair = write_likert_friedman(long_df, out_dir)
    preference = write_likert_preference(prefs, out_dir)
    return long_df, holm_by_pair, preference
