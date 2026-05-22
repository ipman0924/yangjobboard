"""
Cover letter generator using Claude Haiku.

Australian professional standard — hard-specced format, never improvised.
Haiku fills the content; this module enforces the structure.
"""

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional
import anthropic
from config import CLAUDE_MODEL

_client: Optional[anthropic.Anthropic] = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


_CANDIDATE_PROFILE_PATH = Path(__file__).parent / "data" / "candidate_profile.txt"


def _load_profile() -> str:
    if _CANDIDATE_PROFILE_PATH.exists():
        return _CANDIDATE_PROFILE_PATH.read_text(encoding="utf-8")
    return ""


# Hard-specced Australian cover letter rules — never changes
_COVER_LETTER_PROMPT = """\
You are writing a professional cover letter for Yang Yang applying for a banking role in Australia.

STRICT FORMAT RULES — follow exactly, no exceptions:
- Do NOT start with "Dear", "To Whom It May Concern", or any salutation
- Open directly with a confident, specific first sentence about why this role
- Maximum 3 paragraphs
- Paragraph 1 (2-3 sentences): Why this specific role at this specific company
- Paragraph 2 (3-4 sentences): What Yang brings that is directly relevant — use the job's own language, mirror their keywords, be specific
- Paragraph 3 (1-2 sentences): Express interest in discussing further, keep it direct and confident
- Close with exactly: "Kind regards," then a blank line then "Yang Yang"
- Australian spelling throughout (organisation, recognised, behaviour, etc.)
- Never mention anything not supported by the candidate profile
- Never use hollow phrases like "I am passionate about", "I would be a great fit", "I am excited to"
- Be direct, specific, and professional — Australian tone, not American

Candidate Profile:
{profile}

Job Details:
Title: {title}
Company: {company}
Description: {description}

Write the cover letter body now (no date, no address header — just the letter text starting from the first paragraph):"""


def generate(job: dict) -> str:
    """
    Generate a cover letter for the given job dict.
    Returns the full cover letter as a string, including date header.
    """
    client = _get_client()
    profile = _load_profile()

    title = job.get("title", "")
    company = job.get("company", "")
    description = (job.get("description") or "")[:2000]

    resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=600,
        messages=[{
            "role": "user",
            "content": _COVER_LETTER_PROMPT.format(
                profile=profile[:3000],
                title=title,
                company=company,
                description=description,
            ),
        }],
    )

    body = resp.content[0].text.strip()

    # Prepend date and subject line
    date_str = datetime.now().strftime("%-d %B %Y")
    header = f"{date_str}\n\nRe: {title} — {company}\n\n"
    return header + body
