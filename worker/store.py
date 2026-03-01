from collections import defaultdict
from datetime import datetime

import pytz
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import JobRun, Story
from app.settings import get_settings
from worker.types import ScoredStory
from worker.utils import canonicalize_url, fingerprint_title_loose


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

    local_quota_sectors = {"Hamburg", "Mallorca"}
    inserted: list[Story] = []
    for sector, sector_stories in per_sector.items():
        existing_rows = db.execute(
            select(Story.url, Story.fingerprint, Story.title, Story.source_domain).where(
                Story.snapshot_date == snapshot_date,
                Story.sector == sector,
            )
        ).all()
        seen_urls = {canonicalize_url(row.url) for row in existing_rows}
        seen_fingerprints = {row.fingerprint for row in existing_rows}
        seen_loose_fingerprints = {fingerprint_title_loose(row.title) for row in existing_rows}
        domain_counts: dict[str, int] = defaultdict(int)
        for row in existing_rows:
            domain_counts[row.source_domain] += 1

        sorted_sector_stories = sorted(sector_stories, key=lambda s: s.score, reverse=True)

        sector_limit = settings.max_items_per_sector
        if sector in local_quota_sectors:
            subtopics = {story.subtopic for story in sorted_sector_stories}
            sector_limit = max(sector_limit, len(subtopics) * settings.min_items_per_local_subtopic)

        sector_inserted = 0

        def _can_insert(story: ScoredStory, *, enforce_domain_cap: bool) -> bool:
            url_key = canonicalize_url(story.url)
            loose_fp = fingerprint_title_loose(story.title)
            if url_key in seen_urls:
                return False
            if story.fingerprint in seen_fingerprints:
                return False
            if loose_fp in seen_loose_fingerprints:
                return False
            if enforce_domain_cap and domain_counts[story.source_domain] >= settings.max_items_per_domain_per_sector:
                return False
            return True

        def _insert_story(story: ScoredStory) -> None:
            nonlocal sector_inserted
            url_key = canonicalize_url(story.url)
            loose_fp = fingerprint_title_loose(story.title)

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
            seen_urls.add(url_key)
            seen_fingerprints.add(story.fingerprint)
            seen_loose_fingerprints.add(loose_fp)
            domain_counts[story.source_domain] += 1
            sector_inserted += 1

        if sector in local_quota_sectors:
            by_subtopic: dict[str, list[ScoredStory]] = defaultdict(list)
            for story in sorted_sector_stories:
                by_subtopic[story.subtopic].append(story)

            for candidates in by_subtopic.values():
                subtopic_inserted = 0
                for story in candidates:
                    if sector_inserted >= sector_limit:
                        break
                    if not _can_insert(story, enforce_domain_cap=False):
                        continue
                    _insert_story(story)
                    subtopic_inserted += 1
                    if subtopic_inserted >= settings.min_items_per_local_subtopic:
                        break

        for story in sorted_sector_stories:
            if sector_inserted >= sector_limit:
                break
            if not _can_insert(story, enforce_domain_cap=True):
                continue
            _insert_story(story)

    db.commit()
    return inserted
