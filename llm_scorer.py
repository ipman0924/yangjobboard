"""
LLM-based job scorer using Claude Haiku.

Every scraped job goes through Haiku — no keyword pre-filter.
Haiku reads the full candidate profile and up to 4000 chars of the JD,
then returns a score (0-10) and a short reason.

That score becomes the job's score directly. The existing thresholds
in config.py (3 / 5 / 7) map cleanly onto the 0-10 scale:
  < 3  → not written to Notion
  3-4  → written, not optimised (weak match — visible but low priority)
  5-6  → written + resume tailored (moderate match)
  7+   → written + resume tailored + HIGH MATCH flag
"""

import json
import logging
import os
from pathlib import Path
from typing import List, Optional
import anthropic
from config import CLAUDE_MODEL, HIGH_MATCH_THRESHOLD, NOTION_WRITE_THRESHOLD, RESUME_OPTIMISE_THRESHOLD

logger = logging.getLogger(__name__)

_client: Optional[anthropic.Anthropic] = None
_candidate_profile: Optional[str] = None

CANDIDATE_PROFILE_PATH = Path(__file__).parent / "data" / "candidate_profile.txt"

# How much of the job description to send — more context = better scoring accuracy
JD_CHAR_LIMIT = 4000


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


def _get_candidate_profile() -> str:
    global _candidate_profile
    if _candidate_profile is None:
        if CANDIDATE_PROFILE_PATH.exists():
            _candidate_profile = CANDIDATE_PROFILE_PATH.read_text(encoding="utf-8")
            logger.info("LLM scorer: loaded candidate profile")
        else:
            _candidate_profile = (
                "Yang Yang — 8 years in Australian banking. "
                "Core expertise: post-approval/hindsight review, credit assurance, lending quality, "
                "risk & controls (Line 1/2), residential lending, operational risk, APRA compliance. "
                "Open to: risk & controls, lending operations, credit assessment, personal/retail banking. "
                "Not suitable for: data science, cyber/IT risk, investment banking, external audit, derivatives."
            )
            logger.warning("LLM scorer: candidate_profile.txt not found, using fallback")
    return _candidate_profile


_SCORE_PROMPT = """\
You are a specialist banking recruiter in Australia assessing job fit for a candidate.

Read the candidate profile carefully — pay close attention to the "What Roles Suit Her"
section which lists best match, also suitable, possible, and not suitable role types.

Candidate Profile:
{background}

Job to assess:
Title: {title}
Company: {company}
Description:
{description}

Score how well this job fits this candidate (0–10):

10 — Perfect. Title and requirements are an exact match for her best-fit role types.
     Her experience directly covers the core duties. Right seniority. Banking/finance.
8-9 — Strong. Also-suitable role type, or best-fit role with minor gaps. Skills transfer clearly.
6-7 — Moderate. Possible fit — right industry but adjacent function, or right function but different industry.
4-5 — Weak. Banking-adjacent but significant skill or domain mismatch.
2-3 — Poor. Some overlap but wrong domain, wrong seniority, or wrong industry.
0-1 — Irrelevant. Not suitable category, excluded role type, or clearly wrong field.

IMPORTANT — automatically score 0-2 for:
- Technology / cyber / AI / IT risk roles (she has no tech risk background)
- Data science, machine learning, quantitative, software engineering roles
- Investment banking, markets, trading, derivatives
- External or internal audit
- Insurance, superannuation, wealth management, financial planning
- Graduate / entry-level / cadet programs
- Roles outside banking and financial services

Respond ONLY with JSON:
{{"score": <integer 0-10>, "reason": "<20 words max — specific, name the role type and key factor>"}}"""


def llm_score_jobs(jobs: List[dict]) -> List[dict]:
    """
    Score every job via Haiku. Sets job["score"] directly from Haiku's 0-10 rating.
    Also sets job["llm_score"], job["llm_reason"], job["keywords_matched"],
    job["match_flag"], job["should_write"], job["should_optimise"].
    """
    if not jobs:
        return jobs

    logger.info(f"LLM scorer: scoring {len(jobs)} jobs via Haiku")

    client  = _get_client()
    profile = _get_candidate_profile()

    for job in jobs:
        title       = job.get("title", "")
        company     = job.get("company", "")
        description = (job.get("description") or "")[:JD_CHAR_LIMIT]

        try:
            resp = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=100,
                messages=[{
                    "role": "user",
                    "content": _SCORE_PROMPT.format(
                        background=profile,
                        title=title,
                        company=company,
                        description=description,
                    ),
                }],
            )
            raw = resp.content[0].text.strip()
            if "```" in raw:
                raw = raw.split("```")[1].lstrip("json").strip()
            result     = json.loads(raw)
            llm_score  = max(0, min(10, int(result.get("score", 0))))
            llm_reason = result.get("reason", "")

        except Exception as exc:
            logger.warning(f"LLM scorer failed for '{title}': {exc}")
            llm_score  = 0
            llm_reason = ""

        # Haiku's score IS the score — no keyword base to add to
        job["score"]            = llm_score
        job["llm_score"]        = llm_score
        job["llm_reason"]       = llm_reason
        job["keywords_matched"] = []   # keyword pass removed; ai_reason replaces this
        job["match_flag"]       = "HIGH MATCH" if llm_score >= HIGH_MATCH_THRESHOLD else ""
        job["should_write"]     = llm_score >= NOTION_WRITE_THRESHOLD
        job["should_optimise"]  = llm_score >= RESUME_OPTIMISE_THRESHOLD

        logger.debug(
            f"[{llm_score}/10] {title} @ {company}"
            + (f" — {llm_reason}" if llm_reason else "")
        )

    written  = sum(1 for j in jobs if j["should_write"])
    high     = sum(1 for j in jobs if j["match_flag"] == "HIGH MATCH")
    logger.info(f"LLM scorer: {written}/{len(jobs)} above write threshold, {high} HIGH MATCH")

    return jobs
