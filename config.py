"""
Central configuration for the job monitoring agent.
Tune keywords, scoring thresholds, and run intervals here.
"""

# ---------------------------------------------------------------------------
# Search parameters
# ---------------------------------------------------------------------------

LOCATION = "Sydney NSW"
MAX_RESULTS_PER_SOURCE = 50  # Per-scraper cap; scorer filters down from here

# ---------------------------------------------------------------------------
# Search queries — exact job-title phrases that AU banks actually use
#
# Rule: phrase must appear in real SEEK/Jora job titles for Yang's target roles.
# Too broad ("credit risk") = noise. Too niche ("hindsight review") = 0 results.
# Sweet spot: role-title level phrases that banks use publicly.
# ---------------------------------------------------------------------------

SEARCH_QUERY_TERMS = [
    "credit risk",              # credit risk analyst/manager at banks
    "operational risk",         # operational risk analyst roles in banking
    "risk controls",            # risk and controls analyst/officer roles
    "residential lending",      # lending assessment, review, mortgage ops roles
    "credit analyst",           # credit analyst roles (personal/retail focus)
]

# ---------------------------------------------------------------------------
# Keyword lists — used by the scorer (not the search queries)
# ---------------------------------------------------------------------------

# +3 per title hit, +1 per description hit (capped at +5)
HIGH_PRIORITY_KEYWORDS = [
    # Exact niche Yang operated in
    "hindsight review",
    "post approval review",
    "post-approval review",
    "lending quality",
    "credit assurance",
    "loan quality",
    "lending review",

    # Risk & controls roles
    "risk and controls",
    "controls assurance",
    "risk in change",
    "control testing",
    "line 1 risk",
    "line 2 risk",
    "second line",
    "control effectiveness",
    "control gap",

    # Credit risk — banking specific
    "credit risk",
    "credit policy",
    "credit analyst",
    "residential lending",
    "personal lending",
    "retail lending",
    "consumer credit",
    "mortgage risk",
    "lending operations",
    "mortgage operations",

    # Operational risk — banking context
    "operational risk",
    "issue management",
    "APRA",

    # Governance & reporting
    "risk governance",
    "portfolio monitoring",
    "arrears",
]

# +1 per title hit
MEDIUM_PRIORITY_KEYWORDS = [
    "loan assessment",
    "credit assessment",
    "lending support",
    "mortgage",
    "personal banking",
    "retail banking",
    "home loan",
    "broker",
    "serviceability",
    "governance",
    "risk reporting",
    "stakeholder",
    "banking operations",
    "verification",
    "loan processing",
]

# -5 whenever found in title OR description
EXCLUDE_KEYWORDS = [
    # Technical / wrong domain
    "data science",
    "machine learning",
    "deep learning",
    "python developer",
    "software engineer",
    "sql developer",
    "data engineer",
    "financial modelling",
    "financial model",
    "quantitative",
    "quant ",

    # Wrong risk type
    "cyber risk",
    "information security",
    "technology risk",
    "it risk",
    "model risk",

    # Wrong banking segment
    "agribusiness",
    "large corporate",
    "institutional",
    "investment banking",
    "markets risk",
    "market risk",
    "trading",
    "derivatives",

    # Seniority mismatch
    "graduate program",
    "graduate opportunity",
    "junior analyst",
    "entry level",
    "intern",
    "cadet",

    # Other irrelevant
    "internal audit",
    "external audit",
    "insurance",
    "superannuation",
    "wealth management",
    "financial planning",
    "financial planner",
    "storeperson",
    "warehouse",
    "brand ambassador",
    "sales representative",
]

# ---------------------------------------------------------------------------
# Scoring logic
# ---------------------------------------------------------------------------

SCORE_TITLE_HIGH   = 3   # title matches a HIGH_PRIORITY keyword
SCORE_DESC_HIGH    = 1   # each description HIGH hit
SCORE_DESC_HIGH_CAP = 5  # cap on description HIGH points
SCORE_TITLE_MEDIUM = 1   # title matches a MEDIUM_PRIORITY keyword
SCORE_EXCLUDE      = -5  # any EXCLUDE keyword anywhere
SCORE_MAJOR_BANK   = 2   # employer is a named major AU bank
SCORE_TOO_JUNIOR   = -2  # role signals graduate / entry-level

NOTION_WRITE_THRESHOLD    = 3  # raised from 2 — must be a real match
RESUME_OPTIMISE_THRESHOLD = 5  # trigger Haiku optimisation
HIGH_MATCH_THRESHOLD      = 7  # flag as HIGH MATCH in Notion

MAJOR_BANKS = [
    "commonwealth bank", "cba", "commbank",
    "anz", "australia and new zealand",
    "nab", "national australia bank",
    "westpac",
    "macquarie",
    "ing direct", "ing bank",
    "bendigo bank", "bendigo and adelaide",
    "bank of queensland", "boq",
    "suncorp",
    "bankwest",
    "st george",
    "citibank", "citi ",
    "hsbc",
    "ubank",
    "amp bank",
    "me bank",
    "rabobank",
    "bank of china",
    "icbc",
]

JUNIOR_SIGNALS = [
    "graduate", "entry level", "entry-level",
    "junior analyst", "cadet", "intern",
    "aps1", "aps2",
]

# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------

RUN_INTERVAL_HOURS = 24

# ---------------------------------------------------------------------------
# Resume template paths  (relative to project root)
# ---------------------------------------------------------------------------

RESUME_GENERAL_PATH       = "data/resume_general.txt"
RESUME_CONTROL_RISK_PATH  = "data/resume_control_risk.txt"

# Signals that favour the control-risk template
CONTROL_RISK_SIGNALS = [
    "risk in change", "operational risk", "control", "governance",
    "apra", "risk and controls", "controls assurance", "policy",
    "second line", "line 2", "hindsight", "post approval",
    "credit assurance", "lending quality",
]

# ---------------------------------------------------------------------------
# Claude model
# ---------------------------------------------------------------------------

CLAUDE_MODEL = "claude-haiku-4-5-20251001"

# ---------------------------------------------------------------------------
# Runtime overrides from data/settings.json (edited via the Settings UI)
# Keys here shadow the defaults above when present.
# ---------------------------------------------------------------------------

import json as _json
from pathlib import Path as _Path

_settings_path = _Path(__file__).parent / "data" / "settings.json"
if _settings_path.exists():
    try:
        _ov = _json.loads(_settings_path.read_text(encoding="utf-8"))
        if "search_query_terms"      in _ov: SEARCH_QUERY_TERMS      = _ov["search_query_terms"]
        if "notion_write_threshold"  in _ov: NOTION_WRITE_THRESHOLD  = int(_ov["notion_write_threshold"])
        if "resume_optimise_threshold" in _ov: RESUME_OPTIMISE_THRESHOLD = int(_ov["resume_optimise_threshold"])
        if "high_match_threshold"    in _ov: HIGH_MATCH_THRESHOLD    = int(_ov["high_match_threshold"])
        if "run_interval_hours"      in _ov: RUN_INTERVAL_HOURS      = int(_ov["run_interval_hours"])
    except Exception:
        pass
