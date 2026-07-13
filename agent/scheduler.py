"""Optional daily scheduler for automated prospect runs."""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from agent.config import get_settings
from agent.pipeline import run_prospect

logger = logging.getLogger(__name__)
_scheduler: BackgroundScheduler | None = None


def start_scheduler(default_query: str | None = None) -> BackgroundScheduler:
    global _scheduler
    if _scheduler and _scheduler.running:
        return _scheduler

    settings = get_settings()
    query = default_query or (
        "CIOs and Heads of Alternatives at sovereign wealth holding companies "
        "in UAE, KSA, Kuwait, Bahrain"
    )
    _scheduler = BackgroundScheduler()

    def _job() -> None:
        logger.info("Scheduled prospect starting")
        try:
            result = run_prospect(query)
            logger.info("Scheduled prospect finished: %s", result)
        except Exception:  # noqa: BLE001
            logger.exception("Scheduled prospect failed")

    # Daily at 09:00 local time (server TZ)
    _scheduler.add_job(_job, "cron", hour=9, minute=0, id="daily_prospect")
    _scheduler.start()
    logger.info("Scheduler started (daily 09:00), dry_run default=%s", settings.dry_run)
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
