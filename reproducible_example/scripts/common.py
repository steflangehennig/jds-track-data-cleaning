"""
Shared constants and helpers used by more than one cleaning step.

Kept in one place so the event taxonomy and grade vocabulary stay identical
across the MileSplit (high school) and TFRRS (collegiate) cleaning scripts,
which matters once the two datasets are linked in 04_link_records.py.
"""
import re

# ---------------------------------------------------------------------------
# Grade / class-year vocabulary (Section 4 of the manuscript: "it was listed
# as 9, 10, 11, 12 or 'FR', 'SO', 'JR', 'SR' ... depending on the meet").
# ---------------------------------------------------------------------------
NUMERIC_GRADES = {"7", "8", "9", "10", "11", "12"}
CLASS_YEAR_TO_GRADE = {"FR": "9", "SO": "10", "JR": "11", "SR": "12"}
ALL_GRADE_LIKE = NUMERIC_GRADES | set(CLASS_YEAR_TO_GRADE)

# College class years reuse the same FR/SO/JR/SR labels but sometimes carry a
# trailing season number scraped straight off TFRRS, e.g. "JR-3" (junior,
# third indoor/outdoor season on file). Strip that suffix to get the class.
COLLEGE_CLASS_PATTERN = re.compile(r"^(FR|SO|JR|SR)(-\d+)?$", re.IGNORECASE)

# A "grade equivalent" scale that extends the 9-12 high school scale into
# college so the same birth-year formula (Section 4: "Birth Year =
# Date_YEAR - (Grade + 5)") can be applied on both sides of the linkage.
# A true freshman is normally 18 in their first competition year, i.e. the
# same relationship as a 13th "grade": 18 = 13 + 5.
COLLEGE_CLASS_TO_GRADE_EQUIVALENT = {"FR": 13, "SO": 14, "JR": 15, "SR": 16}

# Markers that mean "no valid performance was recorded", not a real time or
# mark. Left as their own list (rather than folded into NA) because a FOUL/
# DNS/DNS row is informative (the athlete competed) but not usable for the
# performance-based analyses in the paper.
INVALID_PERFORMANCE_MARKERS = {
    "FOUL", "DNS", "DNF", "ND", "SCR", "SCRATCH", "DQ", "NH", "NM", "FAIL",
}

# Placeholders TFRRS (and MileSplit, less often) use for "no data" instead of
# leaving the cell blank.
MISSING_PLACEHOLDERS = {"--", "-", "–", "—", "NA", "N/A", ""}

# Trailing annotations meets attach to an otherwise-clean time: hand-timed
# ("h"), season record ("SR"), personal record ("PR"), meet/facility/national
# record ("MR"/"FR" note-form/"NR"). These must be stripped before the number
# is parsed, but are worth keeping as a separate flag rather than silently
# discarding, since "hand-timed vs. fully-automatic" is a real measurement
# difference (Section 4).
RECORD_ANNOTATION_PATTERN = re.compile(r"(SR|PR|MR|NR)$", re.IGNORECASE)
HAND_TIME_PATTERN = re.compile(r"[Hh]$")

# ---------------------------------------------------------------------------
# Event taxonomy. This intentionally mirrors the "Sprint / Mid-Distance /
# Distance / Jump / Throw / Combined / Relay" categories used to fix the
# TFRRS Best_Mark_type bug described in the manuscript (every mark was
# labeled "distance", even for running events).
# ---------------------------------------------------------------------------
SPRINT_EVENTS = {
    "55", "55 meters", "60", "60 meters", "100", "100 m", "100 meters",
    "200", "200 meters", "300 meters", "400", "400 meters",
    "55 hurdles", "60 hurdles", "100 hurdles", "110 hurdles",
    "300 hurdles", "400 hurdles",
}
MID_DISTANCE_EVENTS = {
    "500 meters", "600", "600 meters", "800", "800 meters",
    "1000", "1000 meters", "1500", "1500 meters", "mile", "1 mile",
}
DISTANCE_EVENTS = {
    "2000 steeplechase", "3000", "3000 meters", "3000 steeplechase",
    "5000", "5000 meters", "10000", "10000 meters", "10,000 meters",
    "5k", "10k",
}
JUMP_EVENTS = {"high jump", "pole vault", "long jump", "triple jump"}
THROW_EVENTS = {"shot put", "discus", "hammer", "javelin", "weight throw"}
COMBINED_EVENTS = {"decathlon", "heptathlon", "pentathlon"}


def canonical_event_key(event_name):
    """Lowercase / whitespace-collapse an event string for taxonomy lookup.

    Does NOT try to fully canonicalize the display name (that is
    ``standardize_event_name`` in 02_clean_milesplit.py) - this is just a
    normalized key for matching against the category sets above.
    """
    if event_name is None:
        return ""
    s = re.sub(r"\s+", " ", str(event_name).strip().lower())
    s = s.replace("meter run", "meters").replace("meter dash", "meters")
    s = re.sub(r"\bmeters?\b", "meters", s)
    return s.strip()


def categorize_event(event_name):
    """Map a (possibly messy) event name to a coarse taxonomy category."""
    key = canonical_event_key(event_name)
    if not key:
        return "Unknown"
    if key in SPRINT_EVENTS:
        return "Sprint"
    if key in MID_DISTANCE_EVENTS:
        return "Mid-Distance"
    if key in DISTANCE_EVENTS:
        return "Distance"
    if key in JUMP_EVENTS:
        return "Jump"
    if key in THROW_EVENTS:
        return "Throw"
    if key in COMBINED_EVENTS:
        return "Combined"
    if "relay" in key or re.search(r"\b4\s*x\s*\d", key):
        return "Relay"
    if "hurdle" in key:
        return "Sprint"
    if "jump" in key or "vault" in key:
        return "Jump"
    if any(t in key for t in ("put", "discus", "hammer", "javelin", "throw")):
        return "Throw"
    return "Other"


def coarse_event_type(category):
    if category in ("Sprint", "Mid-Distance", "Distance"):
        return "Running"
    if category in ("Jump", "Throw"):
        return "Field"
    return category


def performance_type_for_category(category):
    """What kind of number a Best_Mark/Time value should be, given its
    event category. Used to rebuild TFRRS's buggy Best_Mark_type column."""
    if category in ("Sprint", "Mid-Distance", "Distance", "Relay"):
        return "time"
    if category in ("Jump", "Throw"):
        return "distance"
    if category == "Combined":
        return "points"
    return "unknown"
