"""
Step 2 - clean and harmonize the column-shift-repaired MileSplit data

Covers the MileSplit-side cleaning/harmonization steps described in
Section 4 of the manuscript:

  * remove rows with no usable performance (FOUL, DNS, DNF, SCR, ...)
  * strip trailing record/hand-time annotations (24.5SR, 58.6h) before
    parsing the numeric value, while keeping a flag for hand-timed marks
  * parse Time (MM:SS.ss or SS.ss) and Mark (meters, or feet-inches like
    20-06) to numeric seconds / numeric meters, so every distance event is
    on one measurement system
  * normalize grade to a single 9-12 scale, regardless of whether the meet
    recorded it as a number, a class-year code (FR/SO/JR/SR), or an age
    range - and document the judgment call for the age-range case
  * standardize event names into (gender, competition_level, event) parts
    so "Boys' JV 200m" and "Girls Junior Varsity 200 Meter Dash" collapse
    to the same underlying event
  * drop exact duplicate performances (same athlete + canonical event +
    meet), keeping the best mark - done *after* event-name harmonization
    so near-duplicates that only differ in event-string formatting are
    still caught
  * flag statistical outliers per event without discarding field-event
    rows that have no time, or track-event rows that have no mark

Input:  data/interim/milesplit_colfix.csv
Output: data/processed/milesplit_clean.csv

Usage:  python scripts/02_clean_milesplit.py
"""
import os
import re

import numpy as np
import pandas as pd

from common import (
    CLASS_YEAR_TO_GRADE,
    HAND_TIME_PATTERN,
    INVALID_PERFORMANCE_MARKERS,
    NUMERIC_GRADES,
    RECORD_ANNOTATION_PATTERN,
    categorize_event,
    coarse_event_type,
)

IN_PATH = os.path.join("data", "interim", "milesplit_colfix.csv")
OUT_PATH = os.path.join("data", "processed", "milesplit_clean.csv")

# judgment call, documented per the manuscript's guidance that "when
# judgment calls are necessary, it is important to document the decision
# and be consistent... across the entire data set": a small number of
# meets record only an age range (e.g. "14-15") instead of a grade. We map
# the lower bound of the range to the modal US grade for that age
# (14 -> 9th, 15 -> 10th, 16 -> 11th, 17 -> 12th), on the reasoning that a
# meet reporting an age range for a school-age competitor is describing
# a fall/winter roster where the athlete has not yet had a fall birthday.
# This is applied consistently to every age-range value in the dataset.
AGE_TO_GRADE = {14: "9", 15: "10", 16: "11", 17: "12"}
AGE_RANGE_PATTERN = re.compile(r"^(\d{1,2})\s*-\s*(\d{1,2})$")


def normalize_grade(raw_grade):
    """Collapse 9/10/11/12, FR/SO/JR/SR, and age-range values to one
    9-12 numeric-grade scale. Returns (grade_str_or_None, method_used)."""
    if pd.isna(raw_grade) or str(raw_grade).strip() == "":
        return None, "missing"

    val = str(raw_grade).strip()

    if val in NUMERIC_GRADES:
        return val, "numeric"

    upper = val.upper()
    if upper in CLASS_YEAR_TO_GRADE:
        return CLASS_YEAR_TO_GRADE[upper], "class_year"

    m = AGE_RANGE_PATTERN.match(val)
    if m:
        low = int(m.group(1))
        if low in AGE_TO_GRADE:
            return AGE_TO_GRADE[low], "age_range_judgment_call"

    return None, "unrecognized"


def strip_performance_annotations(raw_value):
    """Remove trailing SR/PR/MR/NR and hand-time 'h' markers from a raw
    time/mark string. Returns (clean_string, is_hand_timed)."""
    if pd.isna(raw_value) or str(raw_value).strip() == "":
        return None, False
    s = str(raw_value).strip()
    is_hand_timed = bool(HAND_TIME_PATTERN.search(s))
    s = HAND_TIME_PATTERN.sub("", s)
    s = RECORD_ANNOTATION_PATTERN.sub("", s)
    return s.strip(), is_hand_timed


def parse_time_to_seconds(time_str):
    if time_str is None or time_str == "":
        return None
    m = re.match(r"^(\d+):(\d+(?:\.\d+)?)$", time_str)
    if m:
        return float(m.group(1)) * 60 + float(m.group(2))
    try:
        return float(time_str)
    except ValueError:
        return None


FEET_INCHES_PATTERN = re.compile(r"^(\d+)-(\d+(?:\.\d+)?)$")
METERS_SUFFIX_PATTERN = re.compile(r"^(\d+(?:\.\d+)?)\s*m$", re.IGNORECASE)


def parse_mark_to_meters(mark_str):
    """Convert a mark to meters regardless of whether it was recorded in
    meters ('6.10m') or feet-inches ('20-06'), matching the manuscript's
    Algorithm 1 step "convert all distance measures to metric units"."""
    if mark_str is None or mark_str == "":
        return None

    m = METERS_SUFFIX_PATTERN.match(mark_str)
    if m:
        return round(float(m.group(1)), 3)

    m = FEET_INCHES_PATTERN.match(mark_str)
    if m:
        feet, inches = float(m.group(1)), float(m.group(2))
        total_feet = feet + inches / 12.0
        return round(total_feet * 0.3048, 3)

    try:
        return round(float(mark_str), 3)
    except ValueError:
        return None


LEVEL_KEYWORDS = {
    "junior varsity": "JV", "jv": "JV", "varsity": "Varsity",
    "freshman": "Freshman",
}


def standardize_event(raw_event, raw_gender_hint=None):
    """Split a free-text event string like "Girls Junior Varsity 200 Meter
    Dash" or "Boys' JV 200m" into (gender, competition_level, event_clean).

    This is the harmonization step for the manuscript's example of
    "Women's Junior Varsity 200m" vs. "Girl's JV 200m" describing the same
    underlying race.
    """
    if pd.isna(raw_event) or str(raw_event).strip() == "":
        return None, None, None

    s = str(raw_event).strip()
    s_lower = s.lower().replace("'", "")

    gender = raw_gender_hint
    if gender is None:
        if re.search(r"\bboys?\b|\bmen\b", s_lower):
            gender = "Boys"
        elif re.search(r"\bgirls?\b|\bwomen\b", s_lower):
            gender = "Girls"

    level = None
    for kw, label in LEVEL_KEYWORDS.items():
        if kw in s_lower:
            level = label
            break

    # Strip gender and level tokens, plus filler words, to leave just the
    # event itself (e.g. "200 Meter Dash" / "200m Dash" -> "200 Meters").
    cleaned = re.sub(
        r"\b(boys?|girls?|men|women|junior varsity|jv|varsity|freshman)\b",
        "", s_lower,
    )
    cleaned = re.sub(r"(\d+)\s*m\b", r"\1 meters", cleaned)
    cleaned = re.sub(r"meter\b(?!s)", "meters", cleaned)
    cleaned = re.sub(r"\b(dash|run)\b", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = cleaned.title() if cleaned else None

    return gender, level, cleaned


def main():
    df = pd.read_csv(IN_PATH, dtype=str, keep_default_na=False)
    df = df.where(df != "", np.nan)
    n0 = len(df)
    print(f"Loaded {n0:,} rows from {IN_PATH}")

    # standardize column names
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

    # remove rows with no usable performance 
    def is_invalid_marker(v):
        return isinstance(v, str) and v.strip().upper() in INVALID_PERFORMANCE_MARKERS

    invalid_mask = df["time"].apply(is_invalid_marker) | df["mark"].apply(is_invalid_marker)
    removed_invalid = int(invalid_mask.sum())
    df = df.loc[~invalid_mask].copy()

    no_perf_mask = df["time"].isna() & df["mark"].isna()
    removed_missing = int(no_perf_mask.sum())
    df = df.loc[~no_perf_mask].copy()
    print(f"Removed {removed_invalid} rows with an invalid performance marker (FOUL/DNS/...)")
    print(f"Removed {removed_missing} rows with no performance recorded at all")

    # strip annotations then parse performances
    time_clean, hand_timed = zip(*df["time"].apply(strip_performance_annotations))
    df["time_clean"] = time_clean
    df["hand_timed"] = list(hand_timed)
    df["time_seconds"] = df["time_clean"].apply(parse_time_to_seconds)

    mark_clean, _ = zip(*df["mark"].apply(strip_performance_annotations))
    df["mark_clean"] = mark_clean
    df["mark_meters"] = df["mark_clean"].apply(parse_mark_to_meters)

    # grade normalization 
    grade_and_method = df["ath_yr"].apply(normalize_grade)
    df["grade"] = [g for g, _ in grade_and_method]
    df["grade_normalization_method"] = [m for _, m in grade_and_method]
    df["grade_level"] = df["grade"].map(
        lambda g: "Middle School" if g in {"7", "8"}
        else ("High School" if g in {"9", "10", "11", "12"} else "Unknown")
    )
    print("\nGrade normalization method counts:")
    print(df["grade_normalization_method"].value_counts().to_string())

    # event name standardization 
    parsed = df["event"].apply(standardize_event)
    df["event_gender"] = [p[0] for p in parsed]
    df["competition_level"] = [p[1] for p in parsed]
    df["event_clean"] = [p[2] for p in parsed]
    df["event_category"] = df["event_clean"].apply(categorize_event)
    df["event_type"] = df["event_category"].apply(coarse_event_type)

    # deduplicate on the canonical event after harmonization 
    n_before_dedup = len(df)
    perf_for_sort = df["time_seconds"].where(df["time_seconds"].notna(), -df["mark_meters"])
    df = (
        df.assign(_perf_sort=perf_for_sort)
        .sort_values("_perf_sort")
        .drop_duplicates(subset=["first_name", "last_name", "event_clean", "meet_name"], keep="first")
        .drop(columns="_perf_sort")
    )
    print(f"\nRemoved {n_before_dedup - len(df)} duplicate performances "
          f"(same athlete + canonical event + meet)")

    # outlier flag per event/gender z-score, keep NaNs
    def flag_outliers(group, col):
        vals = group[col]
        mu, sd = vals.mean(), vals.std()
        if not sd or pd.isna(sd):
            return pd.Series(False, index=group.index)
        return (vals - mu).abs() / sd > 4

    df["perf_outlier"] = False
    for col in ("time_seconds", "mark_meters"):
        mask = df[col].notna()
        if mask.any():
            flags = (
                df.loc[mask]
                .groupby(["event_clean", "event_gender"], group_keys=False)
                .apply(lambda g: flag_outliers(g, col), include_groups=False)
            )
            df.loc[flags.index, "perf_outlier"] = df.loc[flags.index, "perf_outlier"] | flags

    print(f"Flagged {int(df['perf_outlier'].sum())} statistical outliers "
          f"(kept in the data, flagged for review rather than dropped)")

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    df.to_csv(OUT_PATH, index=False)
    print(f"\nWrote {len(df):,} rows ({n0 - len(df)} fewer than the input) to {OUT_PATH}")


if __name__ == "__main__":
    main()
