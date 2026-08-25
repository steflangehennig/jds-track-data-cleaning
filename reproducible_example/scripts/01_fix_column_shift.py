"""
Step 1 - repair scraper column-shifts in the MileSplit CSV

Why this exists
----------------
Section 4 of the manuscript notes that HTML layout inconsistencies across
MileSplit meet pages sometimes caused the txt->CSV extraction step to
shift a row's values one or two columns to the left (e.g., the athlete's
grade ends up in the "Last Name" field, and a performance value ends up in
the "Event" field, etc.). This script detects the three shift patterns found 
in the real data and re-aligns the affected rows before any other cleaning
runs since every subsequent step assumes columns mean what their header
says.

Input:  data/raw/milesplit_scraped_raw.csv
Output: data/interim/milesplit_colfix.csv (adds a `column_shift_status` column)

Usage:  python scripts/01_fix_column_shift.py
"""
import os
import re

import pandas as pd

from common import ALL_GRADE_LIKE

RAW_PATH = os.path.join("data", "raw", "milesplit_scraped_raw.csv")
OUT_PATH = os.path.join("data", "interim", "milesplit_colfix.csv")

US_STATE_CODES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
    "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC",
}

EVENT_KEYWORDS = (
    "meter", "mile", "run", "dash", "hurdle", "relay", "jump", "throw",
    "put", "vault", "discus", "javelin", "hammer", "walk", "steeple",
    "marathon", "heptathlon", "decathlon", "pentathlon", "boys", "girls",
    "men", "women", "4x",
)

# matches the leading digits of a time (4:54.30, 58.67) or a mark (20-06).
PERF_PATTERN = re.compile(r"^\d+[:.\-]")

SHIFT_COLS = [
    "First Name", "Last Name", "Ath Yr", "School", "Ath Home",
    "State", "Ath Number", "Event", "Time", "Mark",
]


def _is_empty(val):
    return pd.isna(val) or str(val).strip() == ""


def _is_grade_like(val):
    return not _is_empty(val) and str(val).strip() in ALL_GRADE_LIKE


def _looks_like_school(val):
    if _is_empty(val):
        return False
    s = str(val).strip()
    if s in ALL_GRADE_LIKE:
        return False
    try:
        float(s)
        return False
    except ValueError:
        pass
    return bool(re.search(r"[A-Za-z]", s))


def _looks_like_state(val):
    return not _is_empty(val) and str(val).strip().upper() in US_STATE_CODES


def _looks_like_event(val):
    if _is_empty(val):
        return False
    s = str(val).strip().lower()
    return any(kw in s for kw in EVENT_KEYWORDS)


def _looks_like_performance(val):
    return not _is_empty(val) and bool(PERF_PATTERN.match(str(val).strip()))


def detect_shift_pattern(row):
    """Classify a row as 'normal', one of the three shift patterns, or
    'unclear'. See the docstrings on fix_shift_1 / fix_shift_2 below for a
    worked example of what each pattern looks like on disk."""
    last_name = row.get("Last Name")
    ath_yr = row.get("Ath Yr")
    school = row.get("School")
    event = row.get("Event")

    ath_yr_s = "" if pd.isna(ath_yr) else str(ath_yr).strip()
    if ath_yr_s in ALL_GRADE_LIKE:
        return "normal"

    # Pattern A: grade landed in Last Name, school landed in Ath Yr.
    if _is_grade_like(last_name) and _looks_like_school(ath_yr):
        return "shift_1_with_grade"

    # Pattern C: same 1-column shift, but grade was never scraped at all.
    if _is_empty(last_name) and _looks_like_school(ath_yr):
        if _looks_like_event(row.get("Ath Number")) or _looks_like_performance(event):
            return "shift_1_no_grade"

    # Pattern B: 2-column shift - grade in Last Name, state in School.
    if _is_grade_like(last_name) and _is_empty(ath_yr) and _looks_like_state(school):
        return "shift_2"

    if _is_empty(ath_yr) and _looks_like_event(event):
        return "normal"

    return "unclear"


def _route_performance(new_row, perf_value):
    """A shifted row's performance value lands in the Event column. Decide
    whether it belongs in Time or Mark based on its format (':' => a
    running time; '-' => a feet-inches mark; otherwise assume seconds)."""
    if _looks_like_performance(perf_value):
        if ":" in perf_value:
            new_row["Time"], new_row["Mark"] = perf_value, ""
        elif "-" in perf_value:
            new_row["Time"], new_row["Mark"] = "", perf_value
        else:
            new_row["Time"], new_row["Mark"] = perf_value, ""
    else:
        new_row["Time"], new_row["Mark"] = perf_value, ""
    return new_row


def fix_shift_1(row):
    """Undo a 1-column left shift.

    On disk (shift_1_with_grade / Pattern A), a normal
    ``Last, Grade, School, State, ..., Event=<perf>`` row was scraped as::

        First Name=<last>, Last Name=<grade>, Ath Yr=<school>,
        School='', Ath Home=<state>, State='', Ath Number='',
        Event=<performance value>

    First Name can't be recovered (it was never captured) and is left blank.
    """
    new_row = row.copy()
    orig = {c: ("" if pd.isna(row[c]) else str(row[c]).strip()) for c in SHIFT_COLS}

    new_row["First Name"] = ""
    new_row["Last Name"] = orig["First Name"]
    new_row["Ath Yr"] = orig["Last Name"]
    new_row["School"] = orig["Ath Yr"]
    new_row["Ath Home"] = orig["School"]
    new_row["State"] = orig["Ath Home"]
    new_row["Ath Number"] = orig["State"]
    new_row["Event"] = orig["Ath Number"]
    return _route_performance(new_row, orig["Event"])


def fix_shift_2(row):
    """Undo a 2-column left shift (Pattern B). Both First Name and School
    are unrecoverable and are left blank."""
    new_row = row.copy()
    orig = {c: ("" if pd.isna(row[c]) else str(row[c]).strip()) for c in SHIFT_COLS}

    new_row["First Name"] = ""
    new_row["Last Name"] = orig["First Name"]
    new_row["Ath Yr"] = orig["Last Name"]
    new_row["School"] = ""
    new_row["Ath Home"] = ""
    new_row["State"] = orig["School"]
    new_row["Ath Number"] = orig["State"]
    new_row["Event"] = orig["Ath Number"]
    return _route_performance(new_row, orig["Event"])


def main():
    df = pd.read_csv(RAW_PATH, dtype=str, keep_default_na=False)
    print(f"Loaded {len(df):,} rows from {RAW_PATH}")

    patterns = df.apply(detect_shift_pattern, axis=1)
    print("\nShift pattern counts:")
    print(patterns.value_counts().to_string())

    df_fixed = df.copy()
    for pattern_name, fix_fn in (
        ("shift_1_with_grade", fix_shift_1),
        ("shift_1_no_grade", fix_shift_1),
        ("shift_2", fix_shift_2),
    ):
        mask = patterns == pattern_name
        if mask.any():
            fixed = df.loc[mask].apply(fix_fn, axis=1)
            for col in SHIFT_COLS:
                df_fixed.loc[mask, col] = fixed[col]

    df_fixed["column_shift_status"] = patterns.values

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    df_fixed.to_csv(OUT_PATH, index=False)
    n_fixed = patterns.isin(["shift_1_with_grade", "shift_1_no_grade", "shift_2"]).sum()
    print(f"\nFixed {n_fixed} shifted rows.")
    print(f"Wrote {len(df_fixed):,} rows to {OUT_PATH}")


if __name__ == "__main__":
    main()
