"""
APSJobs scraper — placeholder.

APSJobs.gov.au is now a JavaScript-rendered Salesforce Experience Cloud site
and cannot be scraped with requests + BeautifulSoup. This module returns an
empty list and logs a notice. Enable a headless-browser approach (Playwright)
if APS public-sector roles become relevant for Yang.
"""

import logging
from typing import List

logger = logging.getLogger(__name__)


def fetch_jobs() -> List[dict]:
    logger.info(
        "APSJobs: skipped — site requires JavaScript rendering. "
        "Replace with a Playwright-based scraper if APS roles are needed."
    )
    return []
