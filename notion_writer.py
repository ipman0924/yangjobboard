"""
Deduplication and Notion write logic.

Each job is identified by a SHA-256 hash of (title + company + source).
A Notion page is only created if that hash does not already exist in the DB.
"""

import hashlib
import logging
import os
from datetime import datetime
from typing import List, Optional
import httpx
from notion_client import Client

logger = logging.getLogger(__name__)

_client: Optional[Client] = None


def _get_client() -> Client:
    global _client
    if _client is None:
        _client = Client(auth=os.environ["NOTION_API_KEY"])
    return _client


def _make_hash(job: dict) -> str:
    raw = f"{job.get('title','').lower()}|{job.get('company','').lower()}|{job.get('source','').lower()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _format_id(database_id: str) -> str:
    """Ensure database ID has dashes (Notion API requires UUID format)."""
    d = database_id.replace("-", "")
    if len(d) == 32:
        return f"{d[:8]}-{d[8:12]}-{d[12:16]}-{d[16:20]}-{d[20:]}"
    return database_id


def _existing_hashes(database_id: str) -> set:
    """Fetch all DeduplicationHash values already in the Notion DB via direct HTTP."""
    hashes = set()
    cursor = None
    headers = {
        "Authorization": f"Bearer {os.environ['NOTION_API_KEY']}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    url = f"https://api.notion.com/v1/databases/{_format_id(database_id)}/query"

    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor

        try:
            resp = httpx.post(url, headers=headers, json=body, timeout=30)
            resp.raise_for_status()
            response = resp.json()
        except Exception as exc:
            logger.error(f"Notion query error: {exc}")
            break

        for page in response.get("results", []):
            props = page.get("properties", {})
            hash_prop = props.get("DeduplicationHash", {})
            rich_text = hash_prop.get("rich_text", [])
            if rich_text:
                hashes.add(rich_text[0]["text"]["content"])

        if not response.get("has_more"):
            break
        cursor = response.get("next_cursor")

    return hashes


def _build_page_properties(job: dict, database_id: str) -> dict:
    kw_str = ", ".join(job.get("keywords_matched", []))

    # Truncate long strings to Notion's 2000-char limit for rich_text
    def safe_text(s: str, limit: int = 1900) -> str:
        return (s or "")[:limit]

    props: dict = {
        "Title": {"title": [{"text": {"content": safe_text(job.get("title", ""), 200)}}]},
        "Company": {"rich_text": [{"text": {"content": safe_text(job.get("company", ""))}}]},
        "Source": {"select": {"name": job.get("source", "Unknown")}},
        "Location": {"rich_text": [{"text": {"content": safe_text(job.get("location", ""))}}]},
        "URL": {"url": job.get("url") or None},
        "Score": {"number": job.get("score", 0)},
        "KeywordsMatched": {"rich_text": [{"text": {"content": safe_text(kw_str)}}]},
        "MatchFlag": {"select": {"name": job["match_flag"]} if job.get("match_flag") else None},
        "Status": {"select": {"name": "New"}},
        "DocsGenerated": {"checkbox": False},
        "Seen": {"checkbox": False},
        "DeduplicationHash": {"rich_text": [{"text": {"content": job.get("_hash", "")}}]},
    }

    # DatePosted — Notion requires ISO 8601
    raw_date = job.get("date_posted", "")
    if raw_date:
        try:
            # Try to parse common formats; fall back to today
            for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%B %d, %Y", "%d %B %Y"):
                try:
                    dt = datetime.strptime(raw_date[:10], fmt)
                    props["DatePosted"] = {"date": {"start": dt.strftime("%Y-%m-%d")}}
                    break
                except ValueError:
                    continue
        except Exception:
            pass

    if "ResumeMatchScore" in job and job["ResumeMatchScore"] is not None:
        props["ResumeMatchScore"] = {"number": job["ResumeMatchScore"]}

    if "OptimisedResume" in job and job["OptimisedResume"]:
        props["OptimisedResume"] = {
            "rich_text": [{"text": {"content": safe_text(job["OptimisedResume"], 1900)}}]
        }

    return props


def write_new_jobs(jobs: List[dict], database_id: str) -> int:
    """
    Write jobs that pass the relevance threshold and haven't been seen before.
    Returns the count of newly written pages.
    """
    client = _get_client()
    existing = _existing_hashes(database_id)
    written = 0

    for job in jobs:
        if not job.get("should_write"):
            continue

        h = _make_hash(job)
        if h in existing:
            logger.debug(f"Skipping duplicate: {job.get('title')} @ {job.get('company')}")
            continue

        job["_hash"] = h
        props = _build_page_properties(job, database_id)

        try:
            client.pages.create(
                parent={"database_id": database_id},
                properties=props,
            )
            existing.add(h)
            written += 1
            logger.info(
                f"Written [{job.get('source')}] {job.get('title')} @ {job.get('company')} "
                f"(score={job.get('score')} {job.get('match_flag','')})"
            )
        except Exception as exc:
            logger.error(f"Notion write error for '{job.get('title')}': {exc}")

    return written
