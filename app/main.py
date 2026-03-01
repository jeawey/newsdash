from datetime import datetime, timedelta
from functools import lru_cache
from typing import Optional

import pytz
from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import and_, desc, or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Base, JobRun, Story
from app.database import engine
from app.presentation import SECTOR_COLORS
from app.schemas import DashboardResponse, StoryOut
from app.settings import get_settings
from worker.config import load_source_config

app = FastAPI(title="Constructive News")
templates = Jinja2Templates(directory="app/templates")
settings = get_settings()
app.mount("/static", StaticFiles(directory="app/static"), name="static")


def _normalize_sector_name(sector: str) -> str:
    aliases = {
        "Biotechnology": "Biotechnologie",
    }
    return aliases.get(sector, sector)


def _configured_sectors() -> list[str]:
    return _source_config_views()["configured_sectors"]


def _sector_subtopics() -> dict[str, list[str]]:
    return _source_config_views()["sector_subtopics"]


def _topic_sectors() -> list[str]:
    return _source_config_views()["topic_sectors"]


@lru_cache(maxsize=1)
def _source_config_views() -> dict[str, object]:
    config = load_source_config()
    ordered: list[str] = []
    per_sector: dict[str, list[str]] = {}

    for query in config.queries:
        sector = _normalize_sector_name(query.sector)
        if sector not in ordered:
            ordered.append(sector)
        bucket = per_sector.setdefault(sector, [])
        if query.subtopic not in bucket:
            bucket.append(query.subtopic)

    room_only = {"Kenya", "Hamburg", "Mallorca"}
    topic_sectors = [sector for sector in ordered if sector not in room_only]
    return {
        "configured_sectors": ordered,
        "sector_subtopics": per_sector,
        "topic_sectors": topic_sectors,
    }


@app.on_event("startup")
def create_schema() -> None:
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/job-runs")
def get_job_runs(
    limit: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    runs = db.scalars(select(JobRun).order_by(desc(JobRun.started_at)).limit(limit)).all()
    return {
        "count": len(runs),
        "runs": [
            {
                "id": run.id,
                "run_type": run.run_type,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                "status": run.status,
                "message": run.message,
            }
            for run in runs
        ],
    }


@app.get("/api/stories", response_model=DashboardResponse)
def get_dashboard_data(
    snapshot_date: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
) -> DashboardResponse:
    tz = pytz.timezone(settings.timezone)
    target_date = (
        datetime.strptime(snapshot_date, "%Y-%m-%d").date()
        if snapshot_date
        else datetime.now(tz).date()
    )

    now_utc = datetime.now(pytz.utc)
    normal_cutoff = now_utc - timedelta(hours=settings.normal_story_window_hours)
    hot_cutoff = now_utc - timedelta(hours=settings.hot_story_window_hours)
    filtered_stories = db.scalars(
        select(Story)
        .where(
            Story.snapshot_date == target_date,
            or_(
                and_(
                    Story.score >= settings.hourly_breaking_threshold,
                    Story.published_at >= hot_cutoff,
                ),
                and_(
                    Story.score < settings.hourly_breaking_threshold,
                    Story.published_at >= normal_cutoff,
                ),
            ),
        )
        .order_by(desc(Story.score))
    ).all()

    configured_sectors = _configured_sectors()
    sectors: dict[str, list[StoryOut]] = {sector: [] for sector in configured_sectors}
    for story in filtered_stories:
        story_out = StoryOut.model_validate(story).model_copy(
            update={"sector": _normalize_sector_name(story.sector)}
        )
        sectors.setdefault(story_out.sector, []).append(story_out)

    top_stories = [
        StoryOut.model_validate(s).model_copy(update={"sector": _normalize_sector_name(s.sector)})
        for s in filtered_stories[:10]
    ]
    return DashboardResponse(snapshot_date=target_date, sectors=sectors, top_stories=top_stories)


@app.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    snapshot_date: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    payload = get_dashboard_data(snapshot_date=snapshot_date, db=db)
    now_utc = datetime.now(pytz.utc)
    latest_cutoff = now_utc - timedelta(hours=6)

    latest_story_ids: set[int] = set()
    for story in payload.top_stories:
        published = story.published_at
        if published.tzinfo is None:
            published = published.replace(tzinfo=pytz.utc)
        else:
            published = published.astimezone(pytz.utc)
        if published >= latest_cutoff:
            latest_story_ids.add(story.id)

    for stories in payload.sectors.values():
        for story in stories:
            published = story.published_at
            if published.tzinfo is None:
                published = published.replace(tzinfo=pytz.utc)
            else:
                published = published.astimezone(pytz.utc)
            if published >= latest_cutoff:
                latest_story_ids.add(story.id)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "snapshot_date": payload.snapshot_date.isoformat(),
            "latest_story_ids": latest_story_ids,
            "top_stories": payload.top_stories,
            "sectors": payload.sectors,
            "configured_sectors": _configured_sectors(),
            "configured_topics": _topic_sectors(),
            "sector_subtopics": _sector_subtopics(),
            "sector_colors": SECTOR_COLORS,
            "asset_prefix": "/static",
        },
    )
