"""
LLM-based semantic scorer using Claude Haiku.

Runs AFTER the keyword scorer as a second pass. For any job that isn't
clearly irrelevant (keyword score >= LLM_PREFILTER_THRESHOLD), Haiku
evaluates fit against Yang's background and returns a semantic score 0-10.

The semantic score is multiplied into the final score so the pipeline
thresholds remain unchanged. Jobs with very low semantic scores get
penalised; high semantic scores add a bonus.
"""

import json
import logging
import os
from pathlib import Path
from typing import List, Optional
import anthropic
from config import CLAUDE_MODEL

logger = logging.getLogger(__name__)

# Jobs with keyword score below this are skipped entirely (clear rejects)
LLM_PREFILTER_THRESHOLD = -3

# Semantic score >= this adds a bonus; below penalises
LLM_BONUS_THRESHOLD = 6  # out of 10
LLM_BONUS_POINTS   = 2   # added to keyword score when semantic is strong
LLM_PENALTY_POINTS = -3  # added when semantically irrelevant

_client: Optional[anthropic.Anthropic] = None
_candidate_profile: Optional[str] = None

CANDIDATE_PROFILE_PATH = Path(__file__).parent / "data" / "candidate_profile.txt"


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
            logger.info("LLM scorer: loaded candidate profile from file")
        else:
            # Fallback if file is missing
            _candidate_profile = (
                "Yang Yang — 8 years in Australian banking. "
                "Core expertise: post-approval/hindsight review, credit assurance, lending quality, "
                "risk & controls (Line 1/2), residential lending, operational risk, APRA compliance. "
                "Open to: risk & controls, lending operations, credit assessment, personal/retail banking roles. "
                "Not suitable for: data science, cyber/IT risk, investment banking, external audit, derivatives."
            )
            logger.warning("LLM scorer: candidate_profile.txt not found, using fallback summary")
    return _candidate_profile


_SCORE_PROMPT = """\
You are a recruiter matching candidates to banking roles in Australia.

Use the candidate profile below to assess how well this job fits.
Pay attention to the "Suitable Job Types" section — it lists best match, also suitable, possible, and less suitable categories.

Candidate Profile:
{background}

Job to evaluate:
Title: {title}
Company: {company}
Description: {description}

Rate how relevant this job is for this candidate on a scale of 0–10:
- 9-10: Exact match (best match role type, right seniority, banking/financial services)
- 7-8: Strong match (also suitable role type, right industry, skills clearly transfer)
- 5-6: Moderate match (possible but not strongest fit, or right role type but wrong industry/seniority)
- 3-4: Weak match (banking adjacent but wrong function or too far from her background)
- 0-2: Irrelevant (less suitable category, wrong domain, excluded role type)

Respond ONLY with JSON: {{"score": <integer 0-10>, "reason": "<10 words max>"}}"""


def llm_score_jobs(jobs: List[dict]) -> List[dict]:
    """
    Augments each job dict with:
        llm_score      - int 0-10 (or None if skipped)
        llm_reason     - short rationale string
    Also adjusts job["score"] by LLM_BONUS/PENALTY_POINTS.

    Modifies jobs in-place and returns the list.
    """
    eligible = [j for j in jobs if j.get("score", 0) >= LLM_PREFILTER_THRESHOLD]
    skipped  = len(jobs) - len(eligible)

    if not eligible:
        logger.info("LLM scorer: no eligible jobs (all below prefilter threshold)")
        return jobs

    logger.info(
        f"LLM scorer: evaluating {len(eligible)} jobs "
        f"({skipped} skipped as clear rejects)"
    )

    client  = _get_client()
    profile = _get_candidate_profile()

    for job in eligible:
        title       = job.get("title", "")
        company     = job.get("company", "")
        description = (job.get("description") or "")[:1500]  # keep tokens low

        try:
            resp = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=80,
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
            result      = json.loads(raw)
            llm_score   = int(result.get("score", 5))
            llm_reason  = result.get("reason", "")

            job["llm_score"]  = llm_score
            job["llm_reason"] = llm_reason

            if llm_score >= LLM_BONUS_THRESHOLD:
                job["score"] += LLM_BONUS_POINTS
                logger.debug(
                    f"[+{LLM_BONUS_POINTS}] {title} @ {company} "
                    f"— LLM {llm_score}/10: {llm_reason}"
                )
            elif llm_score < 4:
                job["score"] += LLM_PENALTY_POINTS
                logger.debug(
                    f"[{LLM_PENALTY_POINTS}] {title} @ {company} "
                    f"— LLM {llm_score}/10: {llm_reason}"
                )
            else:
                logger.debug(
                    f"[±0] {title} @ {company} "
                    f"— LLM {llm_score}/10: {llm_reason}"
                )

        except Exception as exc:
            logger.warning(f"LLM scorer failed for '{title}': {exc}")
            job["llm_score"]  = None
            job["llm_reason"] = ""

    # Re-evaluate flags after score adjustments
    from config import HIGH_MATCH_THRESHOLD, NOTION_WRITE_THRESHOLD, RESUME_OPTIMISE_THRESHOLD
    for job in jobs:
        score = job.get("score", 0)
        job["match_flag"]     = "HIGH MATCH" if score >= HIGH_MATCH_THRESHOLD else ""
        job["should_write"]   = score >= NOTION_WRITE_THRESHOLD
        job["should_optimise"] = score >= RESUME_OPTIMISE_THRESHOLD

    return jobs
