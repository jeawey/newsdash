from collections import defaultdict
from datetime import datetime

import pytz
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import JobRun, Story
from app.settings import get_settings
from worker.types import ScoredStory


class RunLogger:
    def __init__(self, db: Session, run_type: str):
        self.db = db
        self.run_type = run_type
        self.job_run = JobRun(
            run_type=run_type,
            started_at=datetime.now(pytz.utc),
            status="running",
            message="",
        )
        db.add(self.job_run)
        db.commit()
        db.refresh(self.job_run)

    def finish(self, status: str, message: str = "") -> None:
        self.job_run.status = status
        self.job_run.message = message[:500]
        self.job_run.finished_at = datetime.now(pytz.utc)
        self.db.add(self.job_run)
        self.db.commit()


def persist_scored_stories(db: Session, stories: list[ScoredStory], run_type: str) -> list[Story]:
    settings = get_settings()
    tz = pytz.timezone(settings.timezone)
    snapshot_date = datetime.now(tz).date()

    per_sector: dict[str, list[ScoredStory]] = defaultdict(list)
    for story in stories:
        per_sector[story.sector].append(story)

    inserted: list[Story] = []
    for sector, sector_stories in per_sector.items():
        for story in sorted(sector_stories, key=lambda s: s.score, reverse=True)[: settings.max_items_per_sector]:
            exists = db.scalar(
                select(Story.id).where(
                    Story.url == story.url,
                    Story.snapshot_date == snapshot_date,
                )
            )
            if exists:
                continue

            model = Story(
                title=story.title,
                url=story.url,
                source_name=story.source_name,
                source_domain=story.source_domain,
                sector=story.sector,
                subtopic=story.subtopic,
                summary=story.summary,
                published_at=story.published_at,
                fetched_at=datetime.now(pytz.utc),
                snapshot_date=snapshot_date,
                score=story.score,
                heat_score=story.heat_score,
                run_type=run_type,
                fingerprint=story.fingerprint,
            )
            db.add(model)
            inserted.append(model)

    db.commit()
    return inserted
