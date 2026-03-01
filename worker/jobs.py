from datetime import datetime
import logging

import pytz
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from app.database import SessionLocal
from app.models import Base
from app.database import engine
from app.settings import get_settings
from worker.config import load_source_config
from worker.fetcher import fetch_all_stories
from worker.scoring import score_stories
from worker.store import RunLogger, persist_scored_stories
from worker.telegram import send_digest


settings = get_settings()
logger = logging.getLogger(__name__)


def run_pipeline(run_type: str) -> None:
    db = SessionLocal()
    logger = RunLogger(db, run_type)

    try:
        source_config = load_source_config()
        raw = fetch_all_stories(source_config)
        scored = score_stories(raw, source_config.trusted_domains)
        inserted = persist_scored_stories(db, scored, run_type)

        if run_type == "morning":
            send_digest(inserted, title="Morning Sector Briefing")
        elif run_type == "hourly":
            breaking = [s for s in inserted if s.heat_score >= settings.hourly_breaking_threshold]
            send_digest(breaking, title="Breaking Sector Updates")

        logger.finish("success", f"inserted={len(inserted)}")
    except Exception as exc:  # noqa: BLE001
        logger.finish("failed", str(exc))
        raise
    finally:
        db.close()


def run_morning_snapshot() -> None:
    run_pipeline("morning")


def run_hourly_breaking() -> None:
    run_pipeline("hourly")


def start_scheduler() -> None:
    tz = pytz.timezone(settings.timezone)
    scheduler = BlockingScheduler(timezone=tz)

    scheduler.add_job(
        run_morning_snapshot,
        trigger=CronTrigger(hour=8, minute=0, timezone=tz),
        id="morning_snapshot",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        run_hourly_breaking,
        trigger=CronTrigger(minute=5, timezone=tz),
        id="hourly_breaking",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    Base.metadata.create_all(bind=engine)

    if settings.run_ingestion_on_startup:
        try:
            logger.info("Running startup ingestion once before scheduler loop")
            run_hourly_breaking()
        except Exception:  # noqa: BLE001
            logger.exception("Startup ingestion failed; scheduler will continue running")

    for job in scheduler.get_jobs():
        logger.info("Scheduler job registered: id=%s next_run=%s", job.id, job.next_run_time)

    scheduler.start()


def run_once() -> None:
    Base.metadata.create_all(bind=engine)
    now = datetime.now(pytz.timezone(settings.timezone))
    if now.hour == 8:
        run_morning_snapshot()
    else:
        run_hourly_breaking()
