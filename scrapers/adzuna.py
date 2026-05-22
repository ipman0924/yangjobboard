"""
Adzuna scraper — Australian jobs via the Adzuna public API.

Free tier: 250 calls/day. Sign up at https://developer.adzuna.com/
Set ADZUNA_APP_ID and ADZUNA_APP_KEY in .env

Searches AU banking/risk roles across all of Australia (not just Sydney)
since Adzuna's geo filter is less granular than SEEK's.
"""

import logging
import os
import time
from typing import List, Optional
import requests
from config import MAX_RESULTS_PER_SOURCE

logger = logging.getLogger(__name__)

ADZUNA_BASE = "https://api.adzuna.com/v1/api/jobs/au/search/1"

ADZUNA_QUERIES = [
    "credit risk analyst banking",
    "operational risk analyst bank",
    "risk controls banking",
    "residential lending credit",
    "credit assurance lending",
    "hindsight review",
    "post approval review",
]


def fetch_jobs() -> List[dict]:
    app_id  = os.environ.get("ADZUNA_APP_ID", "")
    app_key = os.environ.get("ADZUNA_APP_KEY", "")

    if not app_id or not app_key:
        logger.warning("Adzuna: ADZUNA_APP_ID or ADZUNA_APP_KEY not set — skipping")
        return []

    all_jobs: List[dict] = []
    seen_ids: set = set()

    for query in ADZUNA_QUERIES:
        if len(all_jobs) >= MAX_RESULTS_PER_SOURCE:
            break

        params = {
            "app_id": app_id,
            "app_key": app_key,
            "results_per_page": 20,
            "what": query,
            "where": "Sydney",
            "distance": 30,
            "content-type": "application/json",
        }

        try:
            logger.info(f"Adzuna: searching for '{query}'")
            resp = requests.get(ADZUNA_BASE, params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json()

            for item in data.get("results", []):
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
            logger.error(f"Adzuna error for query '{query}': {exc}")

        time.sleep(0.5)

    logger.info(f"Adzuna: fetched {len(all_jobs)} jobs")
    return all_jobs[:MAX_RESULTS_PER_SOURCE]


def _normalise(item: dict) -> Optional[dict]:
    title = (item.get("title") or "").strip()
    url   = (item.get("redirect_url") or "").strip()

    if not title or not url:
        return None

    company  = (item.get("company", {}).get("display_name") or "").strip()
    location = (item.get("location", {}).get("display_name") or "Sydney, NSW").strip()
    desc     = (item.get("description") or "").strip()
    created  = (item.get("created") or "")[:10]

    return {
        "title": title,
        "company": company,
        "location": location,
        "url": url,
        "description": desc,
        "date_posted": created,
        "source": "Adzuna",
    }
