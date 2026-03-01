from datetime import datetime, timedelta
from typing import Optional

import pytz
from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, select
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
    config = load_source_config()
    ordered: list[str] = []
    for query in config.queries:
        normalized = _normalize_sector_name(query.sector)
        if normalized not in ordered:
            ordered.append(normalized)
    return ordered


def _sector_subtopics() -> dict[str, list[str]]:
    config = load_source_config()
    per_sector: dict[str, list[str]] = {}
    for query in config.queries:
        sector = _normalize_sector_name(query.sector)
        bucket = per_sector.setdefault(sector, [])
        if query.subtopic not in bucket:
            bucket.append(query.subtopic)
    return per_sector


def _topic_sectors() -> list[str]:
    room_only = {"Kenya", "Hamburg", "Mallorca"}
    return [sector for sector in _configured_sectors() if sector not in room_only]


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

    stories = db.scalars(
        select(Story)
        .where(
            Story.snapshot_date == target_date,
            Story.published_at >= datetime.now(pytz.utc) - timedelta(hours=settings.max_story_age_hours),
        )
        .order_by(desc(Story.score))
    ).all()

    now_utc = datetime.now(pytz.utc)
    normal_cutoff = now_utc - timedelta(hours=settings.normal_story_window_hours)
    hot_cutoff = now_utc - timedelta(hours=settings.hot_story_window_hours)
    filtered_stories: list[Story] = []
    for story in stories:
        published = story.published_at
        if published.tzinfo is None:
            published = published.replace(tzinfo=pytz.utc)
        else:
            published = published.astimezone(pytz.utc)

        is_hot = story.score >= settings.hourly_breaking_threshold
        if is_hot and published >= hot_cutoff:
            filtered_stories.append(story)
        elif (not is_hot) and published >= normal_cutoff:
            filtered_stories.append(story)

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
