"""
Relevance scorer for job listings.

Applies the scoring rules from config.py and returns an annotated job dict
with extra keys: score, keywords_matched, match_flag.
"""

import re
from typing import List
from config import (
    HIGH_PRIORITY_KEYWORDS,
    MEDIUM_PRIORITY_KEYWORDS,
    EXCLUDE_KEYWORDS,
    MAJOR_BANKS,
    JUNIOR_SIGNALS,
    SCORE_TITLE_HIGH,
    SCORE_DESC_HIGH,
    SCORE_DESC_HIGH_CAP,
    SCORE_TITLE_MEDIUM,
    SCORE_EXCLUDE,
    SCORE_MAJOR_BANK,
    SCORE_TOO_JUNIOR,
    HIGH_MATCH_THRESHOLD,
    NOTION_WRITE_THRESHOLD,
    RESUME_OPTIMISE_THRESHOLD,
)


def _word_match(keyword: str, text: str) -> bool:
    """
    Return True if keyword appears in text as a whole-word match.
    Uses word boundaries so 'it risk' won't match inside 'credit risk'.
    """
    pattern = r'\b' + re.escape(keyword.lower()) + r'\b'
    return bool(re.search(pattern, text))


def score_job(job: dict) -> dict:
    """Return the job dict augmented with score, keywords_matched, match_flag."""
    title = (job.get("title") or "").lower()
    description = (job.get("description") or "").lower()
    company = (job.get("company") or "").lower()

    score = 0
    keywords_matched: List[str] = []

    # --- Exclude signals ---
    for kw in EXCLUDE_KEYWORDS:
        if _word_match(kw, title) or _word_match(kw, description):
            score += SCORE_EXCLUDE
            keywords_matched.append(f"[EXCLUDE] {kw}")

    # --- High-priority title hits ---
    for kw in HIGH_PRIORITY_KEYWORDS:
        if _word_match(kw, title):
            score += SCORE_TITLE_HIGH
            keywords_matched.append(f"[H-title] {kw}")

    # --- High-priority description hits (capped) ---
    desc_high_points = 0
    for kw in HIGH_PRIORITY_KEYWORDS:
        if _word_match(kw, description) and not _word_match(kw, title):
            if desc_high_points < SCORE_DESC_HIGH_CAP:
                score += SCORE_DESC_HIGH
                desc_high_points += SCORE_DESC_HIGH
                keywords_matched.append(f"[H-desc] {kw}")

    # --- Medium-priority title hits ---
    for kw in MEDIUM_PRIORITY_KEYWORDS:
        if _word_match(kw, title):
            score += SCORE_TITLE_MEDIUM
            keywords_matched.append(f"[M-title] {kw}")

    # --- Major bank employer bonus ---
    for bank in MAJOR_BANKS:
        if bank.lower() in company:
            score += SCORE_MAJOR_BANK
            keywords_matched.append(f"[BANK] {bank}")
            break

    # --- Junior role penalty ---
    for signal in JUNIOR_SIGNALS:
        if _word_match(signal, title) or _word_match(signal, description):
            score += SCORE_TOO_JUNIOR
            keywords_matched.append(f"[JUNIOR] {signal}")
            break

    match_flag = ""
    if score >= HIGH_MATCH_THRESHOLD:
        match_flag = "HIGH MATCH"

    return {
        **job,
        "score": score,
        "keywords_matched": keywords_matched,
        "match_flag": match_flag,
        "should_write": score >= NOTION_WRITE_THRESHOLD,
        "should_optimise": score >= RESUME_OPTIMISE_THRESHOLD,
    }
