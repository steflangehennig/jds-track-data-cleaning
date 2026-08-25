# Reproduction Repository for the Journal of Data Science
## cleaning, harmonization, and record linkage for track and field data

This is repo contains a executable example of the data cleaning,
harmonization, and record-linkage workflow described in Section 4
("Data Cleaning") and Appendix Algorithms 1-2 of the manuscript
*"Ethical and Technical Lessons from Harmonizing Unstructured Athletic
Performance Records."* It was prepared in response to the reviewer request
for "a small, self-contained example, using representative or synthetic
data, with executable code covering the main cleaning, harmonization, and,
if applicable, linkage steps." It also includes the prompt (`prompt.md`) used 
to initially clean the data using ChatGPT.

## Why synthetic data

The full datasets described in the manuscript are not shared for two reasons:

1. **Human-subjects constraints.** The MileSplit and Athletic.net records
   contain the names, school affiliations, and hometowns of minors. Our use
   of that data is covered by IRB approval (SMU #25-083; University of
   Denver #2332889-1) that authorizes our own analysis, not public
   redistribution of the underlying records.
2. **Terms-of-use constraints.** Permission to scrape MileSplit and TFRRS
   was granted by FloSports for this research project specifically; it does
   not extend to republishing the raw or lightly-cleaned corpus.

What we can share here is executable code that reproduces every category of 
the structural problems described in Section 4 -column-shift artifacts, 
inconsistent grade encodings, non-numeric performance annotations, mixed measurement 
units, messy event-name strings, and cross-source name variation - running against 
small, fabricated data (invented names, schools, and times). No row in
`data/raw/` corresponds to a real person.

One additional note: the manuscript's very first extraction step
(Section 4, third paragraph) used the OpenAI API to convert heterogeneous
raw `.txt` meet results into an initial CSV, at a cost of roughly 40 hours
of compute and $500 in API fees over ~850,000 records. That step depends on
the original non-shareable `.txt` files and a paid API key, so it is not
reproduced here. This example begins one stage downstream of it, at the
already-parsed-but-structurally-messy CSV stage - which is where the
cleaning and harmonization work described in Section 4 actually happens.

## File structure

```
reproducible_example/
├── README.md                      <- this file
├── requirements.txt
├── data/
│   ├── raw/
│   │   ├── milesplit_scraped_raw.csv   synthetic, pre-cleaning MileSplit export
│   │   └── tfrrs_scraped_raw.csv       synthetic, pre-cleaning TFRRS export
│   ├── interim/                    <- created by step 1
│   └── processed/                  <- created by steps 2-4
└── scripts/
    ├── common.py                   shared grade/event vocabulary
    ├── 01_fix_column_shift.py      MileSplit column-shift repair
    ├── 02_clean_milesplit.py       MileSplit cleaning + harmonization
    ├── 03_clean_tfrrs.py           TFRRS cleaning + harmonization
    ├── 04_link_records.py          cross-source probabilistic record linkage
    └── run_all.py                  runs all four steps in order
```

## Software required

- Python 3.9 or later
- `pandas` and `numpy` (see `requirements.txt`)

No other packages, API keys, or external services are needed.

## How to run

From inside this `reproducible_example/` directory:

```bash
pip install -r requirements.txt
python scripts/run_all.py
```

Or run each step individually in order to view the output of each
stage:

```bash
python scripts/01_fix_column_shift.py
python scripts/02_clean_milesplit.py
python scripts/03_clean_tfrrs.py
python scripts/04_link_records.py
```

## What each step does + where it maps to the manuscript

| Script | Manuscript link | What it demonstrates |
|---|---|---|
| `01_fix_column_shift.py` | Sec. 4, para. 2 ("identifier misalignment, where values appeared in incorrect columns"); Algorithm 1, Step 3 | Detects and repairs the three column-shift patterns caused by inconsistent MileSplit HTML layouts (grade shifted into the Last-Name field; a 1-column shift with the grade never scraped; a 2-column shift). One of the three patterns leaves the event name unrecoverable, which the script surfaces rather than hides - a concrete instance of the "not always a simple fix" point in Section 6. |
| `02_clean_milesplit.py` | Sec. 4, paras. 1-2; Algorithm 1, Step 3 | Removes rows with invalid performance markers (FOUL/DNS/...); strips trailing record/hand-time annotations (`24.5SR`, `58.6h`) before parsing; normalizes grade across numeric (9-12), class-year (FR/SO/JR/SR), and age-range ("14-15") encodings onto one scale, with the judgment call documented in code; standardizes free-text event names (e.g. "Girls Junior Varsity 200 Meter Dash" and "Boys' JV 200m" both resolve to the same event); converts field-event marks recorded in feet-inches to meters; deduplicates after event-name standardization so near-duplicates that only differ in formatting are still caught; flags (rather than discards) statistical outliers. |
| `03_clean_tfrrs.py` | Sec. 4, para. "Best_Mark_type bug"-equivalent discussion; Algorithm 1, Step 3 | Replaces TFRRS's missing-data placeholders (`--`) with true NA; harmonizes the college class-year field (`JR-3` -> `JR`); re-derives the performance type (time/distance/points) from the event's taxonomy instead of trusting the source site's field, which mislabels every row as "distance"; builds a stable per-athlete key (falling back to Name+Team when no athlete URL was scraped) and flags relay rows so they can be excluded from athlete-level analysis. |
| `04_link_records.py` | Sec. 4, final two paragraphs (probabilistic record linkage; `Birth Year = Date_YEAR - (Grade + 5)`) | Aggregates each dataset to one row per athlete, derives a birth-year estimate on both sides (extending the manuscript's formula to college class years via a grade-equivalent scale), and scores every high-school/college pair on name similarity plus birth-year agreement. Demonstrates a genuine nickname match ("Benjamin" vs. "Ben"), a genuine truncated-hyphenated-name match ("Mary-Kate" vs. "Mary"), and a same-name/different-person pair that is correctly rejected once the birth-year evidence contradicts it - illustrating why the manuscript uses probabilistic rather than deterministic linkage. |

The illustrative scorer in `04_link_records.py` is a transparent stand-in
for the production linkage step - it is not the full non-public matcher -
chosen so every accepted or rejected pair can be inspected directly in
`candidate_links.csv` rather than trusting a black-box library.

## Expected output

Running `python scripts/run_all.py` against the bundled synthetic data
prints a running log and produces:

- `data/interim/milesplit_colfix.csv` - 21 rows; 3 rows repaired (one from
  each shift pattern), 1 row left `unclear` (an age-range grade value that
  the shift detector correctly declines to touch).
- `data/processed/milesplit_clean.csv` - 17 rows (21 minus 2 invalid
  markers minus 2 duplicate performances caught after event-name
  standardization). Includes `grade`, `event_clean`, `event_category`,
  `time_seconds`, and `mark_meters` columns.
- `data/processed/tfrrs_clean.csv` - 14 rows (16 minus 2 invalid markers).
  Includes `Year_Class`, `Best_Mark_type_fixed`, `Best_Mark_numeric`, and
  `athlete_key` columns; 12 of 14 rows have a corrected `Best_Mark_type`.
- `data/processed/candidate_links.csv` - 15 scored MileSplit-vs-TFRRS
  athlete pairs, including the one pair with a perfect name match that is
  flagged as rejected on birth-year grounds.
- `data/processed/linked_athletes.csv` - 2 accepted links: Benjamin
  Carter/Ben Carter and Mary-Kate Reynolds/Mary Reynolds.


## Relationship to the full production pipeline

The functions in `scripts/` are simplified, de-identified re-implementations
of the internal cleaning notebooks used on the full dataset (grade
normalization, event taxonomy, the TFRRS Best_Mark_type fix, and the
MileSplit column-shift repair), rewritten to run standalone against small
synthetic inputs rather than the actual files. The overall sequence of operations, 
the specific data problems addressed, and the linkage formula are unchanged from 
what was actually run.
