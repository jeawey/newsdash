from datetime import datetime
from typing import Optional

import pytz
from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Base, Story
from app.database import engine
from app.presentation import SECTOR_COLORS
from app.schemas import DashboardResponse, StoryOut
from app.settings import get_settings

app = FastAPI(title="Internal News Dashboard")
templates = Jinja2Templates(directory="app/templates")
settings = get_settings()
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.on_event("startup")
def create_schema() -> None:
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


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
        .where(Story.snapshot_date == target_date)
        .order_by(desc(Story.score))
    ).all()

    sectors: dict[str, list[StoryOut]] = {}
    for story in stories:
        sectors.setdefault(story.sector, []).append(StoryOut.model_validate(story))

    top_stories = [StoryOut.model_validate(s) for s in stories[:10]]
    return DashboardResponse(snapshot_date=target_date, sectors=sectors, top_stories=top_stories)


@app.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    snapshot_date: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    payload = get_dashboard_data(snapshot_date=snapshot_date, db=db)
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "snapshot_date": payload.snapshot_date.isoformat(),
            "top_stories": payload.top_stories,
            "sectors": payload.sectors,
            "sector_colors": SECTOR_COLORS,
            "asset_prefix": "/static",
        },
    )
