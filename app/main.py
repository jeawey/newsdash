from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from functools import lru_cache
import re
from typing import Any, Optional

import pytz
from fastapi import Depends, FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from slowapi.middleware import SlowAPIMiddleware

# Rate limiter instance
limiter = Limiter(key_func=get_remote_address, default_limits=["100 per minute"])

# Rate limit decorator - simple pass-through for compatibility
# The middleware handles the default limits
def limit(limit_str):
    """Decorator placeholder - actual limiting via middleware defaults."""
    def decorator(func):
        return func
    return decorator
from starlette.middleware.gzip import GZipMiddleware
from sqlalchemy import and_, desc, or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Base, JobRun, Story
from app.database import engine
from app.presentation import SECTOR_COLORS
from app.schemas import DashboardResponse, StoryOut
from app.settings import get_settings
from worker.astrophysics import AstrophysicsData
from worker.config import load_source_config
from worker.utils import strip_html


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="Constructive News", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=500)
app.add_middleware(SlowAPIMiddleware)

# CORS middleware - restrict to same origin by default
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure based on your needs
    allow_credentials=False,
    allow_methods=["GET"],  # Only GET for public API
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=3600,
)

# Add rate limiter to app
app.state.limiter = limiter


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    return response
templates = Jinja2Templates(directory="app/templates")
settings = get_settings()
app.mount("/static", StaticFiles(directory="app/static"), name="static")

_SOURCE_DOMAIN_NAME_OVERRIDES = {
    "nytimes.com": "The New York Times",
    "wsj.com": "The Wall Street Journal",
    "ft.com": "Financial Times",
    "bbc.com": "BBC",
    "cnn.com": "CNN",
}

_SOURCE_NAME_NORMALIZATION_OVERRIDES = {
    "nyt": "The New York Times",
    "ny times": "The New York Times",
    "new york times": "The New York Times",
    "el pais": "EL PAÍS",
    "elpais": "EL PAÍS",
}


def _normalize_sector_name(sector: str) -> str:
    aliases = {
        "Biotechnology": "Biotechnologie",
    }
    return aliases.get(sector, sector)


def _title_from_domain(domain: str) -> str:
    host = (domain or "").lower().removeprefix("www.").strip()
    if not host:
        return "Unknown source"
    if host in _SOURCE_DOMAIN_NAME_OVERRIDES:
        return _SOURCE_DOMAIN_NAME_OVERRIDES[host]
    root = host.split(".", 1)[0]
    root = re.sub(r"[-_]+", " ", root).strip()
    if not root:
        return "Unknown source"
    parts = [p.upper() if len(p) <= 3 else p.capitalize() for p in root.split()]
    return " ".join(parts)


def _normalize_source_name(source_name: str, source_domain: str) -> str:
    raw = (source_name or "").strip()
    if not raw:
        return _title_from_domain(source_domain)

    cleaned = re.sub(r"\s+", " ", raw).strip()

    lowered = cleaned.lower()

    if lowered.startswith("feedspot"):
        if ")" in cleaned:
            tail = cleaned.split(")", 1)[1].strip(" -:|")
            if tail:
                return tail
        cleaned = re.sub(r"^feedspot\s+[^\d]*\d+\s*(\([^)]*\))?\s*", "", cleaned, flags=re.IGNORECASE).strip(" -:|")
        if cleaned and not cleaned.lower().startswith("www."):
            return cleaned
        return _title_from_domain(source_domain)

    # Normalize wrappers like "Countries/Spain: EL PAÍS: el periódico global"
    if lowered.startswith("countries/") or lowered.startswith("de rssv"):
        if ":" in cleaned:
            cleaned = cleaned.split(":", 1)[1].strip()
        if ":" in cleaned:
            cleaned = cleaned.split(":", 1)[0].strip()
        if " - " in cleaned:
            cleaned = cleaned.split(" - ", 1)[0].strip()
        if " > " in cleaned:
            cleaned = cleaned.split(" > ", 1)[0].strip()

    cleaned = re.sub(r"^\([^)]*\)\s*", "", cleaned).strip()
    key = cleaned.lower().strip()
    if key in _SOURCE_NAME_NORMALIZATION_OVERRIDES:
        return _SOURCE_NAME_NORMALIZATION_OVERRIDES[key]
    if re.fullmatch(r"(https?://)?(www\.)?[a-z0-9.-]+\.[a-z]{2,}(/.*)?", cleaned.lower()):
        return _title_from_domain(source_domain or cleaned)
    return cleaned


def _configured_sectors() -> list[str]:
    return _source_config_views()["configured_sectors"]


def _sector_subtopics() -> dict[str, list[str]]:
    return _source_config_views()["sector_subtopics"]


def _topic_sectors() -> list[str]:
    return _source_config_views()["topic_sectors"]


def _select_diverse_top_stories(stories: list[Story], *, limit: int = 10, max_per_sector: int = 3) -> list[Story]:
    if not stories:
        return []
    selected: list[Story] = []
    counts: dict[str, int] = {}

    for story in stories:
        sector = _normalize_sector_name(story.sector)
        if counts.get(sector, 0) >= max_per_sector:
            continue
        selected.append(story)
        counts[sector] = counts.get(sector, 0) + 1
        if len(selected) >= limit:
            return selected

    if len(selected) >= limit:
        return selected[:limit]

    selected_ids = {story.id for story in selected}
    for story in stories:
        if story.id in selected_ids:
            continue
        selected.append(story)
        if len(selected) >= limit:
            break
    return selected


_HOT_DEDUP_STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "über", "und", "der", "die", "das",
    "von", "mit", "auf", "für", "nach", "ist", "are", "was", "were", "news", "update", "live",
}


def _hot_similarity_key(title: str, summary: str) -> str:
    text = f"{title} {summary}".lower()
    tokens = re.findall(r"[a-zA-ZäöüÄÖÜß0-9]{4,}", text)
    cleaned = [token for token in tokens if token not in _HOT_DEDUP_STOPWORDS]
    if not cleaned:
        return re.sub(r"\s+", " ", title.lower()).strip()[:120]
    return " ".join(cleaned[:14])


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

    room_only = {"Kenya", "Hamburg", "Mallorca", "Astrophysik"}
    topic_sectors = [sector for sector in ordered if sector not in room_only]
    return {
        "configured_sectors": ordered,
        "sector_subtopics": per_sector,
        "topic_sectors": topic_sectors,
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


_ROBOTS_TXT = (
    "User-agent: *\n"
    "Allow: /\n"
    "Sitemap: https://constructive-news.com/sitemap.xml\n"
)

_SITEMAP_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    "  <url>\n"
    "    <loc>https://constructive-news.com/</loc>\n"
    "    <changefreq>hourly</changefreq>\n"
    "    <priority>1.0</priority>\n"
    "  </url>\n"
    "</urlset>\n"
)


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots_txt() -> str:
    return _ROBOTS_TXT


@app.get("/sitemap.xml", response_class=PlainTextResponse)
def sitemap_xml() -> PlainTextResponse:
    return PlainTextResponse(content=_SITEMAP_XML, media_type="application/xml")


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


_astrophysics_data = AstrophysicsData()


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
            update={
                "sector": _normalize_sector_name(story.sector),
                "source_name": _normalize_source_name(story.source_name, story.source_domain),
                "title": strip_html(story.title),
                "summary": strip_html(story.summary),
            }
        )
        sectors.setdefault(story_out.sector, []).append(story_out)

    top_story_pool = _select_diverse_top_stories(filtered_stories, limit=10, max_per_sector=3)
    top_stories = [
        StoryOut.model_validate(s).model_copy(
            update={
                "sector": _normalize_sector_name(s.sector),
                "source_name": _normalize_source_name(s.source_name, s.source_domain),
                "title": strip_html(s.title),
                "summary": strip_html(s.summary),
            }
        )
        for s in top_story_pool
    ]
    return DashboardResponse(snapshot_date=target_date, sectors=sectors, top_stories=top_stories)


def _get_last_update_time(db: Session) -> Optional[str]:
    last_run = db.scalars(
        select(JobRun)
        .where(JobRun.status == "success")
        .order_by(desc(JobRun.started_at))
        .limit(1)
    ).first()
    if not last_run or not last_run.finished_at:
        return None
    tz = pytz.timezone(settings.timezone)
    local_time = last_run.finished_at.astimezone(tz)
    return local_time.strftime("%H:%M")


@app.get("/api/astrophysics/live")
@limit("30 per minute")
def get_astrophysics_live_data() -> dict[str, object]:
    """Get all live astrophysics data including KP index, aurora, solar activity, earthquakes, videos, events, and warnings."""
    data_fetcher = AstrophysicsData()
    return data_fetcher.get_all_live_data()


@app.get("/api/astrophysics/map")
@limit("30 per minute")
def get_astrophysics_map_data() -> dict[str, object]:
    """Get earthquake and volcano data for map visualization."""
    data_fetcher = AstrophysicsData()
    return data_fetcher.get_all_map_data()


@app.get("/api/mapbox/config")
@limit("60 per minute")
def get_mapbox_config() -> dict[str, object]:
    """Get Mapbox configuration (public token)."""
    return {
        "token": settings.mapbox_token or "",
    }


@app.get("/api/astrophysics/events")
@limit("30 per minute")
def get_astrophysics_events(days: int = Query(default=7, ge=1, le=30)) -> dict[str, object]:
    """Get upcoming astronomical events within the specified number of days."""
    data_fetcher = AstrophysicsData()
    events = data_fetcher.get_upcoming_events(days=days)
    return {"events": events, "days": days, "count": len(events)}


@app.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    snapshot_date: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    payload = get_dashboard_data(snapshot_date=snapshot_date, db=db)
    last_update_time = _get_last_update_time(db)

    hot_candidates: list[StoryOut] = []
    hot_candidates.extend(payload.top_stories)
    for stories in payload.sectors.values():
        hot_candidates.extend(stories)

    best_hot_by_key: dict[str, StoryOut] = {}
    for story in hot_candidates:
        if story.score <= settings.hot_badge_threshold:
            continue
        key = _hot_similarity_key(story.title, story.summary)
        existing = best_hot_by_key.get(key)
        if existing is None:
            best_hot_by_key[key] = story
            continue
        if story.score > existing.score:
            best_hot_by_key[key] = story
            continue
        if story.score == existing.score and story.published_at > existing.published_at:
            best_hot_by_key[key] = story

    latest_story_ids: set[int] = {story.id for story in best_hot_by_key.values()}

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "snapshot_date": payload.snapshot_date.isoformat(),
            "last_update_time": last_update_time,
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
