"""
Step 3 - clean and harmonize the scraped TFRRS (collegiate) data

Covers the TFRRS-side cleaning/harmonization steps described in Section 4
of the manuscript:

  * replace placeholder missingness ("--", "-", blank) with true NA
    (Algorithm 1, Step 3)
  * remove rows with no usable performance (DNS/FOUL/...)
  * harmonize the college class-year field: TFRRS records it as e.g.
    "JR-3" (class + season number on file); split that into a clean
    Year_Class ("JR") the same vocabulary MileSplit grades are normalized
    into on the high-school side
  * parse Best_Mark to a numeric value on one measurement system (seconds
    for running events, meters for field events)
  * fix the site-wide "every Best_Mark_type says distance" bug by
    re-deriving the type from the event's taxonomy category
  * build a stable per-athlete key (Athlete_ID URL, falling back to
    Name + Team for the ~1% of rows missing an Athlete_ID), and exclude
    relay rows from that athlete-level key, since a relay's "Name" is a
    team, not a person

Input:  data/raw/tfrrs_scraped_raw.csv
Output: data/processed/tfrrs_clean.csv

Usage:  python scripts/03_clean_tfrrs.py
"""
import os
import re

import numpy as np
import pandas as pd

from common import (
    COLLEGE_CLASS_PATTERN,
    INVALID_PERFORMANCE_MARKERS,
    MISSING_PLACEHOLDERS,
    categorize_event,
    coarse_event_type,
    performance_type_for_category,
)

IN_PATH = os.path.join("data", "raw", "tfrrs_scraped_raw.csv")
OUT_PATH = os.path.join("data", "processed", "tfrrs_clean.csv")


def parse_time_to_seconds(time_str):
    if pd.isna(time_str) or str(time_str).strip() == "":
        return None
    s = str(time_str).strip()
    m = re.match(r"^(\d+):(\d+(?:\.\d+)?)$", s)
    if m:
        return float(m.group(1)) * 60 + float(m.group(2))
    try:
        return float(s)
    except ValueError:
        return None


def harmonize_year_class(raw_year):
    """'JR-3' -> 'JR'; already-bare 'SR' -> 'SR'; anything else -> NA."""
    if pd.isna(raw_year) or str(raw_year).strip() == "":
        return None
    m = COLLEGE_CLASS_PATTERN.match(str(raw_year).strip())
    return m.group(1).upper() if m else None


def split_name(full_name):
    if pd.isna(full_name) or str(full_name).strip() == "":
        return None, None
    parts = str(full_name).strip().split()
    if len(parts) == 1:
        return parts[0], None
    return parts[0], " ".join(parts[1:])


def main():
    df = pd.read_csv(IN_PATH, dtype=str, keep_default_na=False)
    df = df.where(~df.isin(MISSING_PLACEHOLDERS), np.nan)
    n0 = len(df)
    print(f"Loaded {n0:,} rows from {IN_PATH}")

    # remove rows with no usable performance
    def is_invalid_marker(v):
        return isinstance(v, str) and v.strip().upper() in INVALID_PERFORMANCE_MARKERS

    invalid_mask = df["Best_Mark"].apply(is_invalid_marker)
    removed_invalid = int(invalid_mask.sum())
    df = df.loc[~invalid_mask].copy()

    no_perf_mask = df["Best_Mark"].isna()
    removed_missing = int(no_perf_mask.sum())
    df = df.loc[~no_perf_mask].copy()
    print(f"Removed {removed_invalid} rows with an invalid performance marker (FOUL/DNS/...)")
    print(f"Removed {removed_missing} rows with no performance recorded at all")

    # harmonize class year 
    df["Year_Class"] = df["Year"].apply(harmonize_year_class)

    # event taxonomy + fix the Best_Mark_type bug 
    df["event_category"] = df["Event"].apply(categorize_event)
    df["event_type"] = df["event_category"].apply(coarse_event_type)
    df["Best_Mark_type_fixed"] = df["event_category"].apply(performance_type_for_category)
    n_bug_rows = int((df["Best_Mark_type"] != df["Best_Mark_type_fixed"]).sum())
    print(f"Corrected Best_Mark_type on {n_bug_rows} rows "
          f"(source site had labeled every row 'distance')")

    # parse Best_Mark to one numeric scale per type 
    def parse_by_type(value, mark_type):
        if pd.isna(value):
            return None
        if mark_type == "time":
            return parse_time_to_seconds(value)
        try:
            return round(float(value), 3)
        except ValueError:
            return None

    df["Best_Mark_numeric"] = [
        parse_by_type(v, t) for v, t in zip(df["Best_Mark"], df["Best_Mark_type_fixed"])
    ]

    # split athlete name into parts 
    first_last = df["Name"].apply(split_name)
    df["first_name"] = [p[0] for p in first_last]
    df["last_name"] = [p[1] for p in first_last]

    # build a stable athlete key, excluding relays 
    df["is_relay"] = df["event_category"] == "Relay"
    df["athlete_key"] = df["Athlete_ID"]
    fallback_mask = df["athlete_key"].isna() & ~df["is_relay"]
    df.loc[fallback_mask, "athlete_key"] = (
        df.loc[fallback_mask, "Name"].fillna("UNKNOWN")
        + " @ "
        + df.loc[fallback_mask, "Team"].fillna("UNKNOWN")
    )
    n_relay = int(df["is_relay"].sum())
    print(f"Flagged {n_relay} relay rows (excluded from athlete-level linkage in step 4)")

    # outlier flag per event/gender z-score, keep NaNs 
    def flag_outliers(group):
        vals = group["Best_Mark_numeric"]
        mu, sd = vals.mean(), vals.std()
        if not sd or pd.isna(sd):
            return pd.Series(False, index=group.index)
        return (vals - mu).abs() / sd > 4

    mask = df["Best_Mark_numeric"].notna()
    df["perf_outlier"] = False
    if mask.any():
        flags = (
            df.loc[mask]
            .groupby(["Event", "Gender"], group_keys=False)
            .apply(flag_outliers, include_groups=False)
        )
        df.loc[flags.index, "perf_outlier"] = flags

    print(f"Flagged {int(df['perf_outlier'].sum())} statistical outliers "
          f"(kept in the data, flagged for review rather than dropped)")

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    df.to_csv(OUT_PATH, index=False)
    print(f"\nWrote {len(df):,} rows ({n0 - len(df)} fewer than the input) to {OUT_PATH}")


if __name__ == "__main__":
    main()
