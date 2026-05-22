"""
Resume optimisation using Claude Haiku.

For each job that meets RESUME_OPTIMISE_THRESHOLD:
  1. Pick the best base resume template (general vs control-risk).
  2. Call Haiku with a focused prompt to tailor the resume.
  3. Score the optimised resume against the job posting (0-100).
  4. Return the optimised text and match score back on the job dict.
"""

import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple
import anthropic
from config import (
    CLAUDE_MODEL,
    RESUME_GENERAL_PATH,
    RESUME_CONTROL_RISK_PATH,
    CONTROL_RISK_SIGNALS,
)

CANDIDATE_PROFILE_PATH = Path(__file__).parent / "data" / "candidate_profile.txt"

logger = logging.getLogger(__name__)

_client: Optional[anthropic.Anthropic] = None

# Cache resume text and candidate profile so we read files only once
_resume_cache: dict[str, str] = {}
_candidate_profile: Optional[str] = None


def _get_candidate_profile() -> str:
    global _candidate_profile
    if _candidate_profile is None:
        if CANDIDATE_PROFILE_PATH.exists():
            _candidate_profile = CANDIDATE_PROFILE_PATH.read_text(encoding="utf-8")
        else:
            _candidate_profile = ""
    return _candidate_profile


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


def _load_resume(path: str) -> str:
    if path not in _resume_cache:
        full_path = Path(__file__).parent / path
        _resume_cache[path] = full_path.read_text(encoding="utf-8")
    return _resume_cache[path]


def _pick_template(job: dict) -> Tuple[str, str]:
    """Return (template_name, resume_text) based on job signals."""
    combined = (
        (job.get("title") or "") + " " + (job.get("description") or "")
    ).lower()

    for signal in CONTROL_RISK_SIGNALS:
        if signal.lower() in combined:
            return "control_risk", _load_resume(RESUME_CONTROL_RISK_PATH)

    return "general", _load_resume(RESUME_GENERAL_PATH)


_OPTIMISE_PROMPT = """\
You are an expert Australian banking resume writer. Your task is to tailor the candidate's existing resume to better match a specific job posting, WITHOUT inventing any experience that isn't already present.

## Rules
- Keep all facts, dates, employers, and qualifications exactly as they are.
- Reorder and reword bullet points to surface the most relevant experience first.
- Mirror terminology from the job posting where it accurately reflects what the candidate did.
- Ensure the Professional Summary directly addresses the key requirements of the role.
- Use the candidate profile below to understand what background and strengths to emphasise.
- Do NOT add skills, certifications, or responsibilities that are not in the original resume.
- Output ONLY the tailored resume text — no commentary, no headings like "Here is your resume".

## Candidate Profile (for context — do not copy verbatim into resume)
{candidate_profile}

## Job Posting
Title: {title}
Company: {company}
Description:
{description}

## Candidate's Base Resume
{resume}

Write the tailored resume now:"""

_SCORE_PROMPT = """\
You are a senior Australian banking recruiter reviewing a tailored resume against a job posting.

Use the candidate profile to understand the candidate's background and what kinds of roles suit them best.

Score how well this resume matches the job posting on a scale of 0–100, where:
- 90-100: Exceptional match, would shortlist immediately
- 70-89: Strong match, would consider for interview
- 50-69: Moderate match, possible but not priority
- 0-49: Weak match

Candidate Profile:
{candidate_profile}

Job Posting:
Title: {title}
Company: {company}
Description: {description}

Tailored Resume:
{resume}

Respond with ONLY a JSON object in this exact format:
{{"score": <integer 0-100>, "rationale": "<one sentence>"}}"""


def _save_resume(job: dict) -> None:
    """Save the optimised resume to data/optimised_resumes/ as a .txt file."""
    try:
        out_dir = Path(__file__).parent / "data" / "optimised_resumes"
        out_dir.mkdir(parents=True, exist_ok=True)

        # Build a safe filename
        slug = re.sub(r"[^\w\s-]", "", f"{job.get('title','')} {job.get('company','')}").strip()
        slug = re.sub(r"[\s]+", "_", slug)[:60]
        date_str = datetime.now().strftime("%Y%m%d")
        filename = out_dir / f"{date_str}_{slug}.txt"

        with open(filename, "w", encoding="utf-8") as f:
            f.write(f"Role: {job.get('title')} @ {job.get('company')}\n")
            f.write(f"URL: {job.get('url','')}\n")
            f.write(f"Score: {job.get('score')} | LLM: {job.get('llm_score','n/a')}/10\n")
            f.write("-" * 60 + "\n\n")
            f.write(job["OptimisedResume"])

        logger.info(f"Saved optimised resume → {filename.name}")
    except Exception as exc:
        logger.warning(f"Could not save resume file: {exc}")


def optimise_jobs(jobs: List[dict]) -> List[dict]:
    """
    Mutate jobs that qualify for optimisation in-place, adding:
        OptimisedResume, ResumeMatchScore, ResumeTemplate
    Returns the same list for convenience.
    """
    client           = _get_client()
    candidate_profile = _get_candidate_profile()
    to_optimise      = [j for j in jobs if j.get("should_optimise")]

    if not to_optimise:
        logger.info("Resume optimiser: no jobs met the threshold")
        return jobs

    logger.info(f"Resume optimiser: processing {len(to_optimise)} job(s)")

    for job in to_optimise:
        title = job.get("title", "")
        company = job.get("company", "")
        description = (job.get("description") or "")[:3000]  # cap tokens

        template_name, base_resume = _pick_template(job)
        job["ResumeTemplate"] = template_name

        # --- Step 1: Optimise ---
        try:
            optimise_msg = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=1500,
                messages=[{
                    "role": "user",
                    "content": _OPTIMISE_PROMPT.format(
                        candidate_profile=candidate_profile[:2000],
                        title=title,
                        company=company,
                        description=description,
                        resume=base_resume,
                    ),
                }],
            )
            optimised_resume = optimise_msg.content[0].text.strip()
            job["OptimisedResume"] = optimised_resume
            logger.info(f"Optimised resume for: {title} @ {company}")
        except Exception as exc:
            logger.error(f"Optimisation failed for '{title}': {exc}")
            job["OptimisedResume"] = base_resume
            job["ResumeMatchScore"] = None
            continue

        # --- Step 1b: Save optimised resume for HIGH MATCH jobs ---
        if job.get("match_flag") == "HIGH MATCH" and job.get("OptimisedResume"):
            _save_resume(job)

        # --- Step 2: Score ---
        try:
            score_msg = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=150,
                messages=[{
                    "role": "user",
                    "content": _SCORE_PROMPT.format(
                        candidate_profile=candidate_profile[:1500],
                        title=title,
                        company=company,
                        description=description,
                        resume=optimised_resume[:2500],
                    ),
                }],
            )
            import json
            raw = score_msg.content[0].text.strip()
            # Extract JSON even if wrapped in backticks
            if "```" in raw:
                raw = raw.split("```")[1].lstrip("json").strip()
            result = json.loads(raw)
            job["ResumeMatchScore"] = int(result.get("score", 0))
            job["ResumeRationale"] = result.get("rationale", "")
            logger.info(
                f"Match score for '{title}': {job['ResumeMatchScore']} — {job.get('ResumeRationale','')}"
            )
        except Exception as exc:
            logger.error(f"Scoring failed for '{title}': {exc}")
            job["ResumeMatchScore"] = None

    return jobs
