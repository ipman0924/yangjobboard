"""
One-off script: re-score all existing Notion jobs using the updated candidate profile.

For each page in the database:
  1. Pull title, company, description, existing score.
  2. Re-run keyword scorer + LLM scorer.
  3. If score or match_flag changed, PATCH the Notion page.

Run once:  python3 rescore_notion.py
"""

import logging
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env", override=True)

_REQUIRED = ["NOTION_API_KEY", "NOTION_DATABASE_ID", "ANTHROPIC_API_KEY"]
_missing = [k for k in _REQUIRED if not os.environ.get(k)]
if _missing:
    print(f"ERROR: missing env vars: {', '.join(_missing)}")
    sys.exit(1)

import httpx
from scorer import score_job
from llm_scorer import llm_score_jobs
from config import NOTION_WRITE_THRESHOLD

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("rescore")

NOTION_VERSION = "2022-06-28"
DB_ID = os.environ["NOTION_DATABASE_ID"]

# Format DB ID to UUID
d = DB_ID.replace("-", "")
if len(d) == 32:
    DB_UUID = f"{d[:8]}-{d[8:12]}-{d[12:16]}-{d[16:20]}-{d[20:]}"
else:
    DB_UUID = DB_ID

HEADERS = {
    "Authorization": f"Bearer {os.environ['NOTION_API_KEY']}",
    "Notion-Version": NOTION_VERSION,
    "Content-Type": "application/json",
}


def fetch_all_pages() -> list:
    """Fetch every page from the Notion database."""
    pages = []
    cursor = None
    url = f"https://api.notion.com/v1/databases/{DB_UUID}/query"

    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor

        resp = httpx.post(url, headers=HEADERS, json=body, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        pages.extend(data.get("results", []))

        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")

    logger.info(f"Fetched {len(pages)} pages from Notion")
    return pages


def extract_text(prop: dict) -> str:
    """Pull plain text from a rich_text or title Notion property."""
    for key in ("title", "rich_text"):
        items = prop.get(key, [])
        if items:
            return "".join(i.get("plain_text", "") for i in items)
    return ""


def page_to_job(page: dict) -> dict:
    """Convert a Notion page back into a job dict the scorer understands."""
    props = page.get("properties", {})
    return {
        "title":       extract_text(props.get("Title", {})),
        "company":     extract_text(props.get("Company", {})),
        "location":    extract_text(props.get("Location", {})),
        "description": extract_text(props.get("KeywordsMatched", {})),  # best available signal
        "source":      (props.get("Source", {}).get("select") or {}).get("name", ""),
        "url":         props.get("URL", {}).get("url", ""),
        # carry through old score for comparison
        "_old_score":      props.get("Score", {}).get("number"),
        "_old_match_flag": (props.get("MatchFlag", {}).get("select") or {}).get("name", ""),
        "_page_id":        page["id"],
    }


def patch_page(page_id: str, new_score: int, new_match_flag: str, keywords: list) -> None:
    """Update Score, MatchFlag, and KeywordsMatched on the Notion page."""
    kw_str = ", ".join(keywords)[:1900]
    props = {
        "Score": {"number": new_score},
        "MatchFlag": {
            "select": {"name": new_match_flag} if new_match_flag else None
        },
        "KeywordsMatched": {
            "rich_text": [{"text": {"content": kw_str}}]
        },
    }
    url = f"https://api.notion.com/v1/pages/{page_id}"
    resp = httpx.patch(url, headers=HEADERS, json={"properties": props}, timeout=30)
    resp.raise_for_status()


def delete_page(page_id: str) -> None:
    """Archive (delete) a Notion page."""
    url = f"https://api.notion.com/v1/pages/{page_id}"
    resp = httpx.patch(url, headers=HEADERS, json={"archived": True}, timeout=30)
    resp.raise_for_status()


def main() -> None:
    pages = fetch_all_pages()

    if not pages:
        print("No pages found in database.")
        return

    # Convert pages → job dicts
    jobs = [page_to_job(p) for p in pages]
    logger.info(f"Re-scoring {len(jobs)} jobs with updated candidate profile...")

    # Keyword pass
    scored = [score_job(j) for j in jobs]

    # LLM semantic pass (uses the new candidate_profile.txt)
    scored = llm_score_jobs(scored)

    # Compare, patch, or delete
    updated = 0
    deleted = 0
    for job in scored:
        old_score = job.get("_old_score")
        new_score = job.get("score", 0)
        old_flag  = job.get("_old_match_flag", "")
        new_flag  = job.get("match_flag", "")
        page_id   = job.get("_page_id")

        # Delete if no longer suitable
        if new_score < NOTION_WRITE_THRESHOLD:
            logger.info(
                f"DELETING [{job.get('source')}] {job.get('title')} @ {job.get('company')} "
                f"(score={new_score} — below threshold)"
            )
            try:
                delete_page(page_id)
                deleted += 1
            except Exception as exc:
                logger.error(f"Failed to delete '{job.get('title')}': {exc}")
            continue

        score_changed = (old_score != new_score)
        flag_changed  = (old_flag != new_flag)

        if score_changed or flag_changed:
            change_desc = []
            if score_changed:
                change_desc.append(f"score {old_score} → {new_score}")
            if flag_changed:
                change_desc.append(f"flag '{old_flag}' → '{new_flag}'")

            logger.info(
                f"UPDATING [{job.get('source')}] {job.get('title')} @ {job.get('company')} "
                f"— {', '.join(change_desc)}"
            )
            try:
                patch_page(page_id, new_score, new_flag, job.get("keywords_matched", []))
                updated += 1
            except Exception as exc:
                logger.error(f"Failed to patch '{job.get('title')}': {exc}")
        else:
            logger.debug(
                f"No change: {job.get('title')} @ {job.get('company')} (score={new_score})"
            )

    print(f"\n--- RESCORE COMPLETE ---")
    print(f"  Total jobs reviewed : {len(scored)}")
    print(f"  Deleted (not suitable) : {deleted}")
    print(f"  Updated             : {updated}")
    print(f"  No change           : {len(scored) - updated - deleted}")

    # Print any that flipped to HIGH MATCH
    new_high = [
        j for j in scored
        if j.get("match_flag") == "HIGH MATCH" and j.get("_old_match_flag") != "HIGH MATCH"
    ]
    if new_high:
        print(f"\n  Newly flagged as HIGH MATCH ({len(new_high)}):")
        for j in new_high:
            print(
                f"    [{j['source']}] {j['title']} @ {j['company']} "
                f"(score={j['score']} | llm={j.get('llm_score','?')}/10)"
            )
            if j.get("llm_reason"):
                print(f"         → {j['llm_reason']}")

    # Print any that dropped OUT of HIGH MATCH
    dropped = [
        j for j in scored
        if j.get("_old_match_flag") == "HIGH MATCH" and j.get("match_flag") != "HIGH MATCH"
    ]
    if dropped:
        print(f"\n  Dropped from HIGH MATCH ({len(dropped)}):")
        for j in dropped:
            print(f"    [{j['source']}] {j['title']} @ {j['company']} (score now={j['score']})")

    print("-" * 30)


if __name__ == "__main__":
    main()
