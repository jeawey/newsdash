from collections import defaultdict
from datetime import datetime
import re

import pytz
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import JobRun, Story
from app.settings import get_settings
from worker.types import ScoredStory
from worker.utils import canonicalize_url, fingerprint_title_loose


_SECTOR_RELEVANCE_TERMS: dict[str, tuple[str, ...]] = {
    "AI": (
        "ai",
        "artificial intelligence",
        "machine learning",
        "openai",
        "anthropic",
        "llm",
        "gpt",
        "model",
        "inference",
        "datacenter",
        "gpu",
    ),
    "Crypto": (
        "crypto",
        "bitcoin",
        "ethereum",
        "blockchain",
        "token",
        "stablecoin",
        "defi",
        "etf",
        "exchange",
    ),
    "Biotechnologie": (
        "biotech",
        "biotechnology",
        "pharma",
        "clinical trial",
        "gene",
        "crispr",
        "genomic",
        "medtech",
        "diagnostics",
        "microbiome",
    ),
    "Cannabis": (
        "cannabis",
        "marijuana",
        "hemp",
        "cbd",
        "thc",
        "social club",
        "legalization",
        "medical cannabis",
    ),
    "Frequenzen": (
        "spectrum",
        "rf",
        "wireless",
        "telecom",
        "5g",
        "6g",
        "antenna",
        "radar",
        "satellite",
        "interference",
    ),
    "Sustainability": (
        "sustainab",
        "climate",
        "renewable",
        "emission",
        "net zero",
        "esg",
        "decarbon",
        "circular economy",
        "energy transition",
    ),
    "Hamburg": (
        "hamburg",
        "st pauli",
        "kiez",
        "reeperbahn",
        "hafen",
        "altona",
        "blankenese",
        "winterhude",
        "eppendorf",
        "schanze",
        "hafencity",
        "landungsbrücken",
        "elb",
    ),
    "Mallorca": (
        "mallorca",
        "majorca",
        "palma",
        "balearen",
        "balear",
        "manacor",
        "santanyi",
        "tourismus",
        "consell",
    ),
    "Kenya": (
        "kenya",
        "nairobi",
        "mombasa",
        "kisumu",
        "east africa",
        "parliament",
        "county",
    ),
    "Politics": (
        "election",
        "parliament",
        "government",
        "policy",
        "minister",
        "diplomacy",
        "sanction",
        "conflict",
        "war",
        "trade",
    ),
}

_SECTOR_MIN_HITS: dict[str, int] = {
    "AI": 2,
    "Crypto": 2,
    "Biotechnologie": 2,
    "Cannabis": 2,
    "Frequenzen": 2,
    "Sustainability": 2,
    "Hamburg": 2,
    "Mallorca": 1,
    "Kenya": 1,
    "Politics": 1,
}

_HAMBURG_REJECT_TERMS: tuple[str, ...] = (
    "hannover",
    "lübeck",
    "kassel",
    "bonn",
    "dubai",
    "sao paulo",
    "são paulo",
    "hamburger rezept",
    "cheeseburger",
    "patty",
)


def _count_sector_hits(sector: str, text: str) -> int:
    terms = _SECTOR_RELEVANCE_TERMS.get(sector, ())
    hits = 0
    for term in terms:
        token = term.lower().strip()
        if not token:
            continue
        if len(token) <= 3:
            if re.search(r"\b" + re.escape(token) + r"\b", text):
                hits += 1
        elif " " in token:
            if token in text:
                hits += 1
        else:
            if re.search(r"\b" + re.escape(token) + r"\b", text):
                hits += 1
    return hits


def _passes_hard_relevance_gate(story: ScoredStory, enabled: bool) -> bool:
    if not enabled:
        return True
    required = _SECTOR_MIN_HITS.get(story.sector, 1)
    text = f"{story.title} {story.summary}".lower()
    if story.sector == "Hamburg":
        if any(term in text for term in _HAMBURG_REJECT_TERMS):
            return False
    return _count_sector_hits(story.sector, text) >= required


def _passes_hard_relevance_gate_text(*, sector: str, title: str, summary: str, enabled: bool) -> bool:
    if not enabled:
        return True
    text = f"{title} {summary}".lower()
    if sector == "Hamburg":
        if any(term in text for term in _HAMBURG_REJECT_TERMS):
            return False
    required = _SECTOR_MIN_HITS.get(sector, 1)
    return _count_sector_hits(sector, text) >= required


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
    relaxed_dedupe_sectors = {"Biotechnologie", "Frequenzen", "Cannabis"}
    expanded_domain_cap_sectors = {"Biotechnologie", "Frequenzen", "Cannabis"}
    social_domains = {"x.com", "reddit.com", "linkedin.com", "substack.com"}
    sector_minimum_targets: dict[str, int] = {
        "AI": 12,
        "Crypto": 10,
        "Sustainability": 8,
        "Biotechnologie": 8,
        "Cannabis": 8,
        "Frequenzen": 8,
        "Politics": 8,
        "Kenya": 8,
        "Hamburg": 12,
        "Mallorca": 12,
    }
    inserted: list[Story] = []
    sectors_to_process = set(per_sector.keys()) | set(sector_minimum_targets.keys())
    for sector in sectors_to_process:
        sector_stories = per_sector.get(sector, [])
        existing_rows = db.execute(
            select(Story.id, Story.url, Story.fingerprint, Story.title, Story.summary, Story.source_domain).where(
                Story.snapshot_date == snapshot_date,
                Story.sector == sector,
            )
        ).all()

        stale_ids: list[int] = []
        for row in existing_rows:
            if not _passes_hard_relevance_gate_text(
                sector=sector,
                title=row.title or "",
                summary=row.summary or "",
                enabled=settings.hard_relevance_gate_enabled,
            ):
                stale_ids.append(row.id)

        if stale_ids:
            db.execute(delete(Story).where(Story.id.in_(stale_ids)))
            db.commit()
            existing_rows = [r for r in existing_rows if r.id not in stale_ids]

        seen_urls = {canonicalize_url(row.url) for row in existing_rows}
        seen_fingerprints = {row.fingerprint for row in existing_rows}
        seen_loose_fingerprints = {fingerprint_title_loose(row.title) for row in existing_rows}
        domain_counts: dict[str, int] = defaultdict(int)
        for row in existing_rows:
            domain_counts[row.source_domain] += 1

        sorted_sector_stories = sorted(sector_stories, key=lambda s: s.score, reverse=True)

        sector_limit = settings.max_items_per_sector
        sector_target = sector_minimum_targets.get(sector, settings.min_items_per_sector_target)
        sector_target = min(sector_target, sector_limit)
        if sector in local_quota_sectors:
            subtopics = {story.subtopic for story in sorted_sector_stories}
            local_quota_cap = len(subtopics) * settings.min_items_per_local_subtopic
            sector_target = min(sector_limit, max(sector_target, local_quota_cap))

        sector_inserted = 0

        def _can_insert(
            story: ScoredStory,
            *,
            enforce_domain_cap: bool,
            enforce_loose_dedupe: bool = True,
        ) -> bool:
            if not _passes_hard_relevance_gate(story, settings.hard_relevance_gate_enabled):
                return False
            if story.score < settings.min_story_score:
                return False
            if story.source_domain in social_domains:
                if story.score < settings.min_social_story_score:
                    return False
                if story.mentions < settings.min_social_mentions:
                    return False
            url_key = canonicalize_url(story.url)
            loose_fp = fingerprint_title_loose(story.title)
            if url_key in seen_urls:
                return False
            if story.fingerprint in seen_fingerprints:
                return False
            if enforce_loose_dedupe and sector not in relaxed_dedupe_sectors and loose_fp in seen_loose_fingerprints:
                return False
            domain_cap = settings.max_items_per_domain_per_sector
            if sector in expanded_domain_cap_sectors:
                domain_cap += 2
            if enforce_domain_cap and domain_counts[story.source_domain] >= domain_cap:
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

        if sector_inserted < sector_target:
            for story in sorted_sector_stories:
                if sector_inserted >= sector_target or sector_inserted >= sector_limit:
                    break
                if not _can_insert(
                    story,
                    enforce_domain_cap=False,
                    enforce_loose_dedupe=False,
                ):
                    continue
                _insert_story(story)

    db.commit()
    return inserted
