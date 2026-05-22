"""
SEEK scraper (second pass) — searches for Yang's niche role titles directly.

Runs alongside scrapers/seek.py but uses different, more specific search terms
that target hindsight review, risk & controls, and lending quality roles.

Source label is "SEEK2" so Notion dedup treats it as a separate source.
"""

import logging
import time
from typing import List, Optional
import requests
from config import LOCATION, MAX_RESULTS_PER_SOURCE

logger = logging.getLogger(__name__)

SEEK_API = "https://www.seek.com.au/api/jobsearch/v5/search"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.seek.com.au/jobs",
    "Accept-Language": "en-AU,en;q=0.9",
}

# Niche role-title queries specifically for Yang's target positions
NICHE_QUERIES = [
    "risk and controls",         # Risk & Controls Analyst / Officer
    "lending quality",           # Lending Quality / Hindsight Review roles
    "credit assurance",          # Credit Assurance Analyst
    "post approval",             # Post-Approval / Hindsight Review Officer
    "mortgage risk",             # Mortgage Risk roles
]


def fetch_jobs() -> List[dict]:
    all_jobs: List[dict] = []
    seen_ids: set = set()

    for query in NICHE_QUERIES:
        if len(all_jobs) >= MAX_RESULTS_PER_SOURCE:
            break

        params = {
            "siteKey": "AU-Main",
            "keywords": query,
            "where": LOCATION,
            "page": 1,
            "pageSize": MAX_RESULTS_PER_SOURCE,
            "locale": "en-AU",
            "zone": "anz-1",
        }

        try:
            logger.info(f"SEEK2: searching for '{query}'")
            resp = requests.get(SEEK_API, params=params, headers=HEADERS, timeout=20)
            resp.raise_for_status()
            data = resp.json()

            for item in data.get("data", []):
                job_id = str(item.get("id", ""))
                if job_id in seen_ids:
                    continue
                job = _normalise(item)
                if job:
                    seen_ids.add(job_id)
                    all_jobs.append(job)
                if len(all_jobs) >= MAX_RESULTS_PER_SOURCE:
                    break

        except Exception as exc:
            logger.error(f"SEEK2 error for query '{query}': {exc}")

        time.sleep(0.5)

    logger.info(f"SEEK2: fetched {len(all_jobs)} jobs")
    return all_jobs[:MAX_RESULTS_PER_SOURCE]


def _normalise(item: dict) -> Optional[dict]:
    title = (item.get("title") or "").strip()
    job_id = item.get("id", "")
    url = f"https://www.seek.com.au/job/{job_id}" if job_id else ""

    if not title or not url:
        return None

    company = (item.get("companyName") or item.get("advertiser", {}).get("description", "")).strip()
    locations = item.get("locations", [])
    location = locations[0].get("label", LOCATION) if locations else LOCATION

    teaser = item.get("teaser", "")
    bullets = item.get("bulletPoints", [])
    description = teaser
    if bullets:
        description += " | " + " | ".join(bullets)

    date_posted = (item.get("listingDate") or "")[:10]

    return {
        "title": title,
        "company": company,
        "location": location,
        "url": url,
        "description": description,
        "date_posted": date_posted,
        "source": "SEEK",  # same source label — dedup hash uses title+company+source
    }
