"""
Workday scraper for Australian banks and financial institutions.

Hits the public Workday CXS JSON API directly — no Apify credits needed.
Covers: CBA, ING Australia, Latitude Financial.

API pattern:
  POST https://<tenant>.wd3.myworkdayjobs.com/wday/cxs/<tenant>/<site>/jobs
  GET  https://<tenant>.wd3.myworkdayjobs.com/wday/cxs/<tenant>/<site>/job/<path>
"""

import logging
import re
import time
from typing import List, Optional
import httpx
from config import MAX_RESULTS_PER_SOURCE

logger = logging.getLogger(__name__)

_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}

# Search terms — broad enough to catch all of Yang's target roles
_SEARCH_TERMS = ["risk", "credit", "lending", "controls", "compliance"]

# Location strings that clearly indicate overseas — skip these
_OVERSEAS_SIGNALS = [
    "bangalore", "chennai", "mumbai", "hyderabad", "india",
    "london", "new york", "singapore", "hong kong", "auckland",
    "wellington", "new zealand",
]

# Institution definitions — each maps to one Workday career site
_INSTITUTIONS = [
    {
        "name": "Commonwealth Bank",
        "tenant": "cba",
        "site": "CommBank_Careers",
        "subdomain": "wd3",
        # Lock to the AU legal entity — excludes CBA Services India (id differs)
        "hiring_company_id": "31796cc3cc8701e5236d7209fa425059",
    },
    {
        "name": "ING Australia",
        "tenant": "ing",
        "site": "ICSAUSDIR",
        "subdomain": "wd3",
        "hiring_company_id": None,  # AU-only employer
    },
    {
        "name": "Latitude Financial",
        "tenant": "latitudefinancial",
        "site": "careers",
        "subdomain": "wd3",
        "hiring_company_id": None,  # AU-only employer
    },
]


def _is_overseas(location_text: str) -> bool:
    """Return True if the location clearly points to an overseas office."""
    lower = location_text.lower()
    return any(sig in lower for sig in _OVERSEAS_SIGNALS)


def _strip_html(html: str) -> str:
    """Remove HTML tags and decode common entities."""
    text = re.sub(r"<[^>]+>", " ", html)
    for entity, char in [
        ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
        ("&nbsp;", " "), ("&#39;", "'"), ("&quot;", '"'),
    ]:
        text = text.replace(entity, char)
    return re.sub(r"\s+", " ", text).strip()


def _fetch_description(detail_base: str, external_path: str) -> str:
    """Fetch full job description from the Workday detail endpoint."""
    try:
        url = f"{detail_base}{external_path}"
        resp = httpx.get(url, headers=_HEADERS, timeout=15)
        if resp.status_code == 200:
            info = resp.json().get("jobPostingInfo", {})
            html = info.get("jobDescription", "")
            return _strip_html(html)[:4000]
    except Exception as exc:
        logger.debug(f"Description fetch failed ({external_path}): {exc}")
    return ""


def _fetch_institution(inst: dict) -> List[dict]:
    tenant  = inst["tenant"]
    site    = inst["site"]
    sub     = inst["subdomain"]
    name    = inst["name"]
    cid     = inst.get("hiring_company_id")

    list_url    = f"https://{tenant}.{sub}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
    detail_base = f"https://{tenant}.{sub}.myworkdayjobs.com/wday/cxs/{tenant}/{site}"
    public_base = f"https://{tenant}.{sub}.myworkdayjobs.com/en-US/{site}"

    seen: set = set()
    jobs: List[dict] = []

    for term in _SEARCH_TERMS:
        if len(jobs) >= MAX_RESULTS_PER_SOURCE:
            break

        body: dict = {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": term}
        if cid:
            body["appliedFacets"]["hiringCompany"] = [cid]

        try:
            resp = httpx.post(list_url, headers=_HEADERS, json=body, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning(f"{name}: listing error for '{term}': {exc}")
            time.sleep(1)
            continue

        for posting in data.get("jobPostings", []):
            ext_path = posting.get("externalPath", "")
            if not ext_path or ext_path in seen:
                continue

            loc_text = posting.get("locationsText", "")
            # Skip roles with a clearly overseas single location
            if loc_text and loc_text not in ("2 Locations", "Multiple Locations"):
                if _is_overseas(loc_text):
                    continue

            seen.add(ext_path)

            title     = posting.get("title", "").strip()
            posted_on = posting.get("postedOn", "")

            description = _fetch_description(detail_base, ext_path)
            time.sleep(0.3)

            jobs.append({
                "title":       title,
                "company":     name,
                "location":    loc_text,
                "url":         f"{public_base}{ext_path}",
                "date_posted": posted_on,
                "description": description,
                "source":      f"Workday-{name}",
            })

            if len(jobs) >= MAX_RESULTS_PER_SOURCE:
                break

        time.sleep(0.5)

    logger.info(f"Workday/{name}: {len(jobs)} jobs fetched")
    return jobs


def fetch_jobs() -> List[dict]:
    """Scrape all configured Workday institutions and return combined job list."""
    all_jobs: List[dict] = []
    for inst in _INSTITUTIONS:
        try:
            jobs = _fetch_institution(inst)
            all_jobs.extend(jobs)
        except Exception as exc:
            logger.error(f"Workday scraper failed for {inst['name']}: {exc}")
    logger.info(f"Workday: {len(all_jobs)} total jobs across all institutions")
    return all_jobs
