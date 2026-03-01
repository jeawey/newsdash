from datetime import datetime, timedelta
import logging

import pytz
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Base, JobRun
from app.database import engine
from app.settings import get_settings
from worker.config import load_source_config
from worker.fetcher import fetch_all_stories
from worker.scoring import score_stories
from worker.store import RunLogger, persist_scored_stories
from worker.telegram import send_digest


settings = get_settings()
logger = logging.getLogger(__name__)


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=pytz.utc)
    return dt.astimezone(pytz.utc)


def _cleanup_stale_running_jobs(db, *, stale_after_minutes: int) -> int:
    cutoff = datetime.now(pytz.utc) - timedelta(minutes=stale_after_minutes)
    running = db.execute(select(JobRun).where(JobRun.status == "running")).scalars().all()
    stale = [run for run in running if _to_utc(run.started_at) < cutoff]
    for run in stale:
        run.status = "failed"
        run.finished_at = datetime.now(pytz.utc)
        run.message = "auto-cleanup stale running job lock"
    if stale:
        db.commit()
    return len(stale)


def _cleanup_all_running_jobs(db, *, reason: str) -> int:
    running = db.execute(select(JobRun).where(JobRun.status == "running")).scalars().all()
    for run in running:
        run.status = "failed"
        run.finished_at = datetime.now(pytz.utc)
        run.message = reason[:500]
    if running:
        db.commit()
    return len(running)


def run_pipeline(run_type: str) -> None:
    db = SessionLocal()
    cleaned = _cleanup_stale_running_jobs(db, stale_after_minutes=settings.job_stale_after_minutes)
    if cleaned:
        logger.warning("Auto-cleaned %s stale running job(s) before new run", cleaned)

    active_run = db.execute(
        select(JobRun.id).where(JobRun.status == "running").order_by(JobRun.started_at.asc())
    ).first()
    if active_run is not None:
        logger.warning(
            "Skipping run_type=%s because another run is already active (job_run_id=%s)",
            run_type,
            active_run[0],
        )
        db.close()
        return

    run_logger = RunLogger(db, run_type)

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

        run_logger.finish("success", f"inserted={len(inserted)}")
    except BaseException as exc:  # noqa: BLE001
        try:
            run_logger.finish("failed", f"{exc.__class__.__name__}: {exc}")
        except Exception:  # noqa: BLE001
            logger.exception("Failed to persist failed status for run_type=%s", run_type)
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

    with SessionLocal() as db:
        # On process start, any running row from earlier process/container is orphaned.
        cleaned_all = _cleanup_all_running_jobs(
            db,
            reason="auto-cleanup running job after worker restart",
        )
        if cleaned_all:
            logger.warning("Auto-cleaned %s orphaned running job(s) on scheduler start", cleaned_all)
        cleaned = _cleanup_stale_running_jobs(db, stale_after_minutes=settings.job_stale_after_minutes)
        if cleaned:
            logger.warning("Auto-cleaned %s stale running job(s) on scheduler start", cleaned)

    if settings.run_ingestion_on_startup:
        try:
            logger.info("Running startup ingestion once before scheduler loop")
            run_hourly_breaking()
        except Exception:  # noqa: BLE001
            logger.exception("Startup ingestion failed; scheduler will continue running")

    for job in scheduler.get_jobs():
        next_run = getattr(job, "next_run_time", None)
        logger.info("Scheduler job registered: id=%s next_run=%s", job.id, next_run)

    scheduler.start()


def run_once() -> None:
    Base.metadata.create_all(bind=engine)
    now = datetime.now(pytz.timezone(settings.timezone))
    if now.hour == 8:
        run_morning_snapshot()
    else:
        run_hourly_breaking()
