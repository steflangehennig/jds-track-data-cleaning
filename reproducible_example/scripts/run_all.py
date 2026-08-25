"""
Run all cleaning steps end to end in order:

    01_fix_column_shift.py  ->  02_clean_milesplit.py
    03_clean_tfrrs.py
    04_link_records.py

Usage: python scripts/run_all.py
(run from the reproducible_example/ directory)
"""
import runpy
import sys
import os

STEPS = [
    "01_fix_column_shift.py",
    "02_clean_milesplit.py",
    "03_clean_tfrrs.py",
    "04_link_records.py",
]


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, script_dir)
    for step in STEPS:
        path = os.path.join(script_dir, step)
        print("\n" + "=" * 70)
        print(f"Running {step}")
        print("=" * 70)
        runpy.run_path(path, run_name="__main__")


if __name__ == "__main__":
    main()
