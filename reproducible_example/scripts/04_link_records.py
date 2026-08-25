"""
Step 4 - probabilistic record linkage between cleaned MileSplit (high
school) and TFRRS (collegiate) athletes

Section 4 of the manuscript motivates this step: athlete records differ
across sources because of nickname vs. formal-name usage ("Benjamin"
in high school, "Ben" in college), truncated hyphenated names, and other
non-standardized data entry which is why the paper uses probabilistic
rather than deterministic matching, and why a derived birth year
(``Birth Year = Date_YEAR - (Grade + 5)``) is used as corroborating
evidence alongside the name itself.

This script:

  1. Aggregates each cleaned dataset to one row per athlete (MileSplit:
     grouped by name + school; TFRRS: grouped by the athlete_key built in
     step 3, which already excludes relays).
  2. Derives a birth-year estimate for each athlete on both sides, using
     the manuscript's formula - extended to college class years via the
     grade-equivalent scale in common.py (FR=13th grade equivalent, etc.),
     since a true freshman is normally the same age (18) that the formula
     would predict for a 13th grade competitor.
  3. Scores every MileSplit-vs-TFRRS athlete pair with a transparent
     composite of (a) name similarity and (b) birth-year agreement, rather
     than a black-box matcher, so every accepted or rejected link can be
     inspected directly in candidate_links.csv.
  4. Accepts the best-scoring candidate per MileSplit athlete above a
     fixed threshold as a link.

This is illustrative, not the exact production matcher (which used a
larger, non-public feature set); it demonstrates the concept end-to-end,
including a genuine nickname match, a genuine truncated-hyphenated-name
match, and a same-name-different-person pair that the birth-year check
correctly rejects.

Inputs:  data/processed/milesplit_clean.csv, data/processed/tfrrs_clean.csv
Outputs: data/processed/candidate_links.csv (every pair considered)
         data/processed/linked_athletes.csv (accepted links only)

Usage:   python scripts/04_link_records.py
"""
import os
from difflib import SequenceMatcher

import pandas as pd

from common import COLLEGE_CLASS_TO_GRADE_EQUIVALENT

MS_PATH = os.path.join("data", "processed", "milesplit_clean.csv")
TF_PATH = os.path.join("data", "processed", "tfrrs_clean.csv")
CANDIDATES_OUT = os.path.join("data", "processed", "candidate_links.csv")
LINKED_OUT = os.path.join("data", "processed", "linked_athletes.csv")

# A pair must clear this composite score to be accepted as a link.
MATCH_THRESHOLD = 0.60
# Pairs are only worth scoring (and reporting) if the raw name match is
# at least plausible - this keeps candidate_links.csv readable and mirrors
# the "blocking" step of a real probabilistic linkage pipeline (Fellegi &
# Sunter 1969), which only compares records that agree on some cheap field
# before spending effort on the expensive comparison.
NAME_BLOCK_THRESHOLD = 0.45
# A derived birth year that disagrees by more than this many years is
# treated as disqualifying, no matter how strong the name match is. This
# is what lets the pipeline correctly reject a same-name, different-person
# pair (see the Chris Nguyen example in the README) instead of linking on
# name alone, consistent with the manuscript's point that name matching
# by itself is not sufficient for this population.
MAX_BIRTH_YEAR_DIFF = 1
# A weak name match should never be accepted just because a coincidental
# birth-year agreement pushed the composite score over MATCH_THRESHOLD.
# This is the mirror image of MAX_BIRTH_YEAR_DIFF above: both fields have
# to independently look like a real match before the pair is accepted.
MIN_NAME_SIMILARITY = 0.65


def name_similarity(first_a, last_a, first_b, last_b):
    def norm(s):
        return (s or "").strip().lower().replace("-", " ").replace("'", "")

    full_a = f"{norm(first_a)} {norm(last_a)}".strip()
    full_b = f"{norm(first_b)} {norm(last_b)}".strip()
    if not full_a or not full_b:
        return 0.0
    return SequenceMatcher(None, full_a, full_b).ratio()


def birth_year_score(year_a, year_b):
    """1.0 for an exact match, 0.6 for +/-1 year (redshirt/late birthday
    tolerance), 0.0 beyond that or if either estimate is missing."""
    if pd.isna(year_a) or pd.isna(year_b):
        return 0.0, None
    diff = abs(int(year_a) - int(year_b))
    if diff == 0:
        return 1.0, diff
    if diff == 1:
        return 0.6, diff
    return 0.0, diff


def build_ms_athletes(ms):
    ms = ms.copy()
    ms["grade_num"] = pd.to_numeric(ms["grade"], errors="coerce")
    ms["meet_year_num"] = pd.to_numeric(ms["meet_year"], errors="coerce")
    ms["birth_year_est"] = ms["meet_year_num"] - (ms["grade_num"] + 5)

    grouped = (
        ms.groupby(["first_name", "last_name", "school"], dropna=False)
        .agg(
            state=("state", "first"),
            birth_year=("birth_year_est", "median"),
            n_records=("event_clean", "size"),
        )
        .reset_index()
    )
    grouped = grouped[grouped["last_name"].notna() & grouped["first_name"].notna()]
    return grouped


def build_tf_athletes(tf):
    tf = tf[~tf["is_relay"]].copy()
    tf["competition_year"] = pd.to_datetime(tf["Date"], errors="coerce").dt.year
    tf["grade_equiv"] = tf["Year_Class"].map(COLLEGE_CLASS_TO_GRADE_EQUIVALENT)
    tf["birth_year_est"] = tf["competition_year"] - (tf["grade_equiv"] + 5)

    grouped = (
        tf.groupby("athlete_key", dropna=True)
        .agg(
            first_name=("first_name", "first"),
            last_name=("last_name", "first"),
            team=("Team", "first"),
            state=("State", "first"),
            birth_year=("birth_year_est", "median"),
            n_records=("Event", "size"),
        )
        .reset_index()
    )
    return grouped


def main():
    ms = pd.read_csv(MS_PATH)
    tf = pd.read_csv(TF_PATH)

    ms_athletes = build_ms_athletes(ms)
    tf_athletes = build_tf_athletes(tf)
    print(f"MileSplit athletes (grouped): {len(ms_athletes)}")
    print(f"TFRRS athletes (grouped, relays excluded): {len(tf_athletes)}")

    candidates = []
    for _, hs in ms_athletes.iterrows():
        for _, col in tf_athletes.iterrows():
            n_sim = name_similarity(hs["first_name"], hs["last_name"],
                                     col["first_name"], col["last_name"])
            if n_sim < NAME_BLOCK_THRESHOLD:
                continue
            by_score, by_diff = birth_year_score(hs["birth_year"], col["birth_year"])
            state_bonus = 0.1 if (
                pd.notna(hs["state"]) and pd.notna(col["state"])
                and str(hs["state"]).strip().upper() == str(col["state"]).strip().upper()
            ) else 0.0
            total = 0.6 * n_sim + 0.3 * by_score + state_bonus

            candidates.append({
                "hs_first_name": hs["first_name"], "hs_last_name": hs["last_name"],
                "hs_school": hs["school"], "hs_state": hs["state"],
                "hs_birth_year_est": hs["birth_year"],
                "college_athlete_key": col["athlete_key"],
                "college_first_name": col["first_name"], "college_last_name": col["last_name"],
                "college_team": col["team"], "college_state": col["state"],
                "college_birth_year_est": col["birth_year"],
                "name_similarity": round(n_sim, 3),
                "birth_year_diff": by_diff,
                "match_score": round(total, 3),
            })

    candidates_df = pd.DataFrame(candidates).sort_values("match_score", ascending=False)
    os.makedirs(os.path.dirname(CANDIDATES_OUT), exist_ok=True)
    candidates_df.to_csv(CANDIDATES_OUT, index=False)
    print(f"\nWrote {len(candidates_df)} candidate pairs to {CANDIDATES_OUT}")

    birth_year_ok = candidates_df["birth_year_diff"].fillna(99) <= MAX_BIRTH_YEAR_DIFF
    score_ok = candidates_df["match_score"] >= MATCH_THRESHOLD
    rejected_on_birth_year = candidates_df[score_ok & ~birth_year_ok]
    if len(rejected_on_birth_year):
        print(f"\n{len(rejected_on_birth_year)} pair(s) had a strong name match but were "
              f"REJECTED because the derived birth years disagree by more than "
              f"{MAX_BIRTH_YEAR_DIFF} year(s) - name similarity alone is not enough:")
        cols = ["hs_first_name", "hs_last_name", "college_first_name", "college_last_name",
                "name_similarity", "birth_year_diff", "match_score"]
        print(rejected_on_birth_year[cols].to_string(index=False))

    name_ok = candidates_df["name_similarity"] >= MIN_NAME_SIMILARITY
    accepted = candidates_df[score_ok & birth_year_ok & name_ok]
    linked = accepted.sort_values("match_score", ascending=False).drop_duplicates(
        subset=["hs_first_name", "hs_last_name", "hs_school"], keep="first"
    )
    linked.to_csv(LINKED_OUT, index=False)

    print(f"\nAccepted {len(linked)} links: composite score >= {MATCH_THRESHOLD}, "
          f"name similarity >= {MIN_NAME_SIMILARITY}, "
          f"AND birth-year difference <= {MAX_BIRTH_YEAR_DIFF}:")
    if len(linked):
        cols = ["hs_first_name", "hs_last_name", "hs_school", "college_first_name",
                "college_last_name", "college_team", "name_similarity",
                "birth_year_diff", "match_score"]
        print(linked[cols].to_string(index=False))

    print(f"\nWrote accepted links to {LINKED_OUT}")


if __name__ == "__main__":
    main()
