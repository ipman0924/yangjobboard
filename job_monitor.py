"""
Job Monitor — main entry point.

Usage:
    python job_monitor.py          # run once immediately, then schedule
    python job_monitor.py --once   # run once and exit (useful for testing)
"""

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
import pytz
from dotenv import load_dotenv
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

load_dotenv(Path(__file__).parent / ".env", override=True)

# Validate required env vars early
_REQUIRED_ENV = ["APIFY_API_TOKEN", "NOTION_API_KEY", "NOTION_DATABASE_ID", "ANTHROPIC_API_KEY"]
_missing = [k for k in _REQUIRED_ENV if not os.environ.get(k)]
if _missing:
    print(f"ERROR: missing environment variables: {', '.join(_missing)}")
    print("Copy .env.example to .env and fill in the values.")
    sys.exit(1)

from config import RUN_INTERVAL_HOURS
from scrapers import indeed, seek, apsjobs, adzuna, workday
from llm_scorer import llm_score_jobs
from resume_optimizer import optimise_jobs
from notion_writer import write_new_jobs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("job_monitor")


_SYDNEY = pytz.timezone("Australia/Sydney")


def _is_weekend() -> bool:
    """Return True if it's Saturday or Sunday in Sydney time."""
    return datetime.now(_SYDNEY).weekday() >= 5  # 5=Sat, 6=Sun


def run_once(force: bool = False) -> None:
    """Run one full scrape-score-write cycle.

    Args:
        force: if True, skip the weekend check (used by the manual Run Now button).
    """
    if not force and _is_weekend():
        day = datetime.now(_SYDNEY).strftime("%A")
        logger.info(f"Skipping scheduled run — today is {day} (weekend). Use --force to override.")
        return

    database_id = os.environ["NOTION_DATABASE_ID"]
    logger.info("=" * 60)
    logger.info("Job Monitor run started")

    # --- 1. Scrape ---
    all_jobs = []
    source_counts = {}

    SCRAPER_LABELS = {
        indeed: "SEEK-niche", seek: "SEEK-broad", apsjobs: "APSJobs",
        adzuna: "Adzuna", workday: "Workday",
    }
    for scraper_module in (seek, indeed, adzuna, apsjobs, workday):
        name = SCRAPER_LABELS.get(scraper_module, scraper_module.__name__.split(".")[-1].upper())
        try:
            jobs = scraper_module.fetch_jobs()
            source_counts[name] = len(jobs)
            all_jobs.extend(jobs)
            logger.info(f"{name}: {len(jobs)} raw jobs fetched")
        except Exception as exc:
            logger.error(f"{name} scraper failed: {exc}")
            source_counts[name] = 0

    logger.info(f"Total raw jobs: {len(all_jobs)}")

    # --- 2. Score (Haiku semantic pass — all jobs, no keyword pre-filter) ---
    scored_jobs = llm_score_jobs(all_jobs)

    writable = [j for j in scored_jobs if j.get("should_write")]
    optimisable = [j for j in scored_jobs if j.get("should_optimise")]

    logger.info(
        f"Scoring: {len(writable)} above write threshold, "
        f"{len(optimisable)} above optimise threshold"
    )

    # --- 3. Optimise resumes (only for high-score jobs) ---
    if optimisable:
        logger.info(f"Running resume optimisation for {len(optimisable)} jobs...")
        optimise_jobs(optimisable)

    # --- 4. Write to Notion ---
    written = write_new_jobs(writable, database_id)

    # --- 5. Summary ---
    logger.info("=" * 60)
    print("\n--- JOB MONITOR SUMMARY ---")
    for src, count in source_counts.items():
        print(f"  {src}: {count} fetched")
    print(f"  Passed relevance filter : {len(writable)}")
    print(f"  Resume optimised        : {len(optimisable)}")
    print(f"  Written to Notion       : {written}")

    high_matches = [j for j in writable if j.get("match_flag") == "HIGH MATCH"]
    if high_matches:
        print(f"\n  HIGH MATCH jobs ({len(high_matches)}):")
        for j in high_matches:
            score_str = f"score={j['score']}"
            llm_str = f"llm={j['llm_score']}/10" if j.get("llm_score") is not None else ""
            resume_str = f"resume={j.get('ResumeMatchScore','n/a')}%" if j.get("should_optimise") else ""
            parts = " | ".join(p for p in [score_str, llm_str, resume_str] if p)
            print(f"    [{j['source']}] {j['title']} @ {j['company']} ({parts})")
            if j.get("llm_reason"):
                print(f"         → {j['llm_reason']}")
    print("-" * 30)
    logger.info("Run complete")


def main() -> None:
    parser = argparse.ArgumentParser(description="Yang's Job Monitor")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single scrape cycle and exit (no scheduler)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Run immediately even on weekends (skips the weekend check)",
    )
    args = parser.parse_args()

    if args.once or args.force:
        run_once(force=args.force)
        return

    # Run immediately on startup, then on schedule
    run_once()

    scheduler = BlockingScheduler(timezone="Australia/Sydney")
    scheduler.add_job(
        run_once,
        trigger=IntervalTrigger(hours=RUN_INTERVAL_HOURS),
        id="job_monitor",
        name="Job Monitor",
        misfire_grace_time=300,
    )
    logger.info(f"Scheduler started — polling every {RUN_INTERVAL_HOURS} hours (Sydney time)")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped")


if __name__ == "__main__":
    main()
