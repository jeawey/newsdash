from collections import defaultdict
from datetime import datetime
import logging
import re

import pytz
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import JobRun, Story
from app.settings import get_settings
from worker.translate import translate_to_german
from worker.types import ScoredStory
from worker.utils import canonicalize_url, fingerprint_title_loose, strip_html

logger = logging.getLogger(__name__)


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
        "krypt",
        "wallet",
        "coin",
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
        "biotechnologie",
        "klinisch",
        "studie",
        "therapie",
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
        "hanf",
        "legalisierung",
        "medizinisches cannabis",
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
        "frequenz",
        "spektrum",
        "funk",
        "mobilfunk",
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
        "nachhaltig",
        "klima",
        "erneuerbar",
        "emissionen",
        "energiewende",
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
    "AI": 1,
    "Crypto": 1,
    "Biotechnologie": 1,
    "Cannabis": 1,
    "Frequenzen": 1,
    "Sustainability": 1,
    "Hamburg": 1,
    "Mallorca": 1,
    "Kenya": 1,
    "Politics": 1,
}

_SECTOR_MIN_STORY_SCORE: dict[str, float] = {
    "AI": 2.1,
    "Crypto": 2.4,
    "Biotechnologie": 1.65,
    "Sustainability": 1.5,
    "Frequenzen": 1.2,
    "Kenya": 1.2,
    "Cannabis": 1.2,
    "Mallorca": 2.1,
    "Hamburg": 1.8,
}

_SECTOR_MIN_SOCIAL_STORY_SCORE: dict[str, float] = {
    "AI": 7.2,
    "Sustainability": 7.2,
    "Cannabis": 6.6,
    "Frequenzen": 5.4,
}

_SECTOR_MIN_SOCIAL_MENTIONS: dict[str, int] = {
    "AI": 2,
    "Sustainability": 2,
    "Cannabis": 2,
    "Frequenzen": 1,
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

_POLITICS_PRIORITY_TERMS: tuple[str, ...] = (
    "war",
    "krieg",
    "conflict",
    "konflikt",
    "attack",
    "angriff",
    "invasion",
    "ceasefire",
    "waffenstillstand",
    "sanction",
    "sanktion",
    "diplomacy",
    "military",
    "defense",
    "verteidigung",
    "tariff",
    "export controls",
    "missile",
    "rakete",
    "navy",
)

_POLITICS_GEO_ANCHORS: tuple[str, ...] = (
    "iran",
    "israel",
    "gaza",
    "ukraine",
    "russia",
    "russland",
    "china",
    "taiwan",
    "usa",
    "united states",
    "eu",
    "european union",
    "nato",
    "un ",
    "middle east",
)

_POLITICS_LOW_SIGNAL_TERMS: tuple[str, ...] = (
    "voter day",
    "voters day",
    "campaign",
    "municipal",
    "local election",
    "by-election",
    "opinion",
    "editorial",
    "sports",
    "festival",
    "celebrity",
)

_CONTENT_CLUSTER_STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "their", "will", "after", "amid",
    "der", "die", "das", "und", "für", "mit", "von", "nach", "bei", "eine", "einer",
    "news", "update", "updates", "live", "today", "latest", "report", "reports",
}


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


def _is_high_signal_politics_story(text: str) -> bool:
    priority_hits = sum(1 for term in _POLITICS_PRIORITY_TERMS if term in text)
    geo_hits = sum(1 for term in _POLITICS_GEO_ANCHORS if term in text)
    low_signal_hits = sum(1 for term in _POLITICS_LOW_SIGNAL_TERMS if term in text)

    if priority_hits >= 2:
        return True
    if priority_hits >= 1 and geo_hits >= 1:
        return True
    if low_signal_hits > 0 and priority_hits == 0:
        return False
    return False


def _passes_hard_relevance_gate(story: ScoredStory, enabled: bool) -> bool:
    if not enabled:
        return True
    # Keep hard lexical gate only for Politics to avoid suppressing local sector volume.
    if story.sector != "Politics":
        return True
    required = _SECTOR_MIN_HITS.get(story.sector, 1)
    text = f"{story.title} {story.summary}".lower()
    if story.sector == "Hamburg":
        if any(term in text for term in _HAMBURG_REJECT_TERMS):
            return False
    if story.sector == "Politics":
        return _is_high_signal_politics_story(text)
    return _count_sector_hits(story.sector, text) >= required


def _passes_hard_relevance_gate_text(*, sector: str, title: str, summary: str, enabled: bool) -> bool:
    if not enabled:
        return True
    if sector != "Politics":
        return True
    text = f"{title} {summary}".lower()
    if sector == "Hamburg":
        if any(term in text for term in _HAMBURG_REJECT_TERMS):
            return False
    if sector == "Politics":
        return _is_high_signal_politics_story(text)
    required = _SECTOR_MIN_HITS.get(sector, 1)
    return _count_sector_hits(sector, text) >= required


def _content_cluster_key(title: str, summary: str) -> str:
    text = f"{title} {summary}".lower()
    tokens = re.findall(r"[a-zA-ZäöüÄÖÜß0-9]{4,}", text)
    cleaned = [token for token in tokens if token not in _CONTENT_CLUSTER_STOPWORDS]
    if not cleaned:
        return fingerprint_title_loose(title)
    # Stable cluster key: first unique tokens preserve headline semantics.
    unique_tokens: list[str] = []
    seen: set[str] = set()
    for token in cleaned:
        if token in seen:
            continue
        seen.add(token)
        unique_tokens.append(token)
        if len(unique_tokens) >= 14:
            break
    return " ".join(unique_tokens)


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
    relaxed_dedupe_sectors = {"Biotechnologie", "Frequenzen", "Cannabis", "Kenya", "Sustainability"}
    expanded_domain_cap_sectors = {"AI", "Crypto", "Biotechnologie", "Frequenzen", "Cannabis", "Sustainability", "Kenya", "Mallorca", "Hamburg"}
    social_domains = {"x.com", "reddit.com", "linkedin.com", "substack.com"}
    sector_minimum_targets: dict[str, int] = {
        "AI": 12,
        "Crypto": 10,
        "Sustainability": 12,
        "Biotechnologie": 10,
        "Cannabis": 12,
        "Frequenzen": 10,
        "Politics": 8,
        "Kenya": 10,
        "Hamburg": 8,
        "Mallorca": 10,
    }
    inserted_ids: list[int] = []
    sectors_to_process = set(per_sector.keys()) | set(sector_minimum_targets.keys())
    drop_reason_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    insert_counts: dict[str, int] = defaultdict(int)
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
            drop_reason_counts[sector]["removed_stale_existing"] += len(stale_ids)
            existing_rows = [r for r in existing_rows if r.id not in stale_ids]

        seen_urls = {canonicalize_url(row.url) for row in existing_rows}
        seen_fingerprints = {row.fingerprint for row in existing_rows}
        seen_loose_fingerprints = {fingerprint_title_loose(row.title) for row in existing_rows}
        content_cluster_counts: dict[str, int] = defaultdict(int)
        domain_counts: dict[str, int] = defaultdict(int)
        for row in existing_rows:
            domain_counts[row.source_domain] += 1
            content_cluster_counts[_content_cluster_key(row.title or "", row.summary or "")] += 1

        sorted_sector_stories = sorted(sector_stories, key=lambda s: s.score, reverse=True)

        existing_count = len(existing_rows)
        sector_limit_remaining = max(0, settings.max_items_per_sector - existing_count)
        if sector_limit_remaining == 0:
            # Sector already full for current snapshot; skip costly insert/prune churn.
            continue

        sector_limit = sector_limit_remaining
        sector_target = sector_minimum_targets.get(sector, settings.min_items_per_sector_target)
        sector_target_remaining = max(0, sector_target - existing_count)
        sector_target = min(sector_target_remaining, sector_limit)
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
        ) -> tuple[bool, str | None]:
            if not _passes_hard_relevance_gate(story, settings.hard_relevance_gate_enabled):
                return False, "hard_relevance_gate"
            min_story_score = _SECTOR_MIN_STORY_SCORE.get(sector, settings.min_story_score)
            if story.score < min_story_score:
                return False, "min_story_score"
            if story.source_domain in social_domains:
                min_social_story_score = _SECTOR_MIN_SOCIAL_STORY_SCORE.get(
                    sector,
                    settings.min_social_story_score,
                )
                min_social_mentions = _SECTOR_MIN_SOCIAL_MENTIONS.get(
                    sector,
                    settings.min_social_mentions,
                )
                if story.score < min_social_story_score:
                    return False, "min_social_story_score"
                if story.mentions < min_social_mentions:
                    return False, "min_social_mentions"
            url_key = canonicalize_url(story.url)
            loose_fp = fingerprint_title_loose(story.title)
            if url_key in seen_urls:
                return False, "duplicate_url"
            if story.fingerprint in seen_fingerprints:
                return False, "duplicate_fingerprint"
            if enforce_loose_dedupe and sector not in relaxed_dedupe_sectors and loose_fp in seen_loose_fingerprints:
                return False, "duplicate_loose_fingerprint"
            domain_cap = settings.max_items_per_domain_per_sector
            if sector in expanded_domain_cap_sectors:
                domain_cap += 4
            if enforce_domain_cap and domain_counts[story.source_domain] >= domain_cap:
                return False, "domain_cap"
            cluster_key = _content_cluster_key(story.title, story.summary)
            if content_cluster_counts[cluster_key] >= settings.max_similar_stories_per_cluster:
                return False, "duplicate_content_cluster"
            return True, None

        def _insert_story(story: ScoredStory) -> None:
            nonlocal sector_inserted
            url_key = canonicalize_url(story.url)
            loose_fp = fingerprint_title_loose(story.title)
            cluster_key = _content_cluster_key(story.title, story.summary)
            title_de = strip_html(translate_to_german(story.title))
            summary_de = strip_html(translate_to_german(story.summary))

            model = Story(
                title=title_de,
                url=story.url,
                source_name=story.source_name,
                source_domain=story.source_domain,
                sector=story.sector,
                subtopic=story.subtopic,
                summary=summary_de,
                published_at=story.published_at,
                fetched_at=datetime.now(pytz.utc),
                snapshot_date=snapshot_date,
                score=story.score,
                heat_score=story.heat_score,
                run_type=run_type,
                fingerprint=story.fingerprint,
            )
            db.add(model)
            # Persist identity immediately so we can safely re-query surviving rows
            # even if ORM instances are expired/deleted by later pruning.
            db.flush()
            inserted_ids.append(model.id)
            seen_urls.add(url_key)
            seen_fingerprints.add(story.fingerprint)
            seen_loose_fingerprints.add(loose_fp)
            content_cluster_counts[cluster_key] += 1
            domain_counts[story.source_domain] += 1
            sector_inserted += 1
            insert_counts[sector] += 1

        if sector in local_quota_sectors:
            by_subtopic: dict[str, list[ScoredStory]] = defaultdict(list)
            for story in sorted_sector_stories:
                by_subtopic[story.subtopic].append(story)

            for candidates in by_subtopic.values():
                subtopic_inserted = 0
                for story in candidates:
                    if sector_inserted >= sector_limit:
                        break
                    ok, reason = _can_insert(story, enforce_domain_cap=False)
                    if not ok:
                        if reason:
                            drop_reason_counts[sector][reason] += 1
                        continue
                    _insert_story(story)
                    subtopic_inserted += 1
                    if subtopic_inserted >= settings.min_items_per_local_subtopic:
                        break

        for story in sorted_sector_stories:
            if sector_inserted >= sector_limit:
                break
            ok, reason = _can_insert(story, enforce_domain_cap=True)
            if not ok:
                if reason:
                    drop_reason_counts[sector][reason] += 1
                continue
            _insert_story(story)

        if sector_inserted < sector_target:
            for story in sorted_sector_stories:
                if sector_inserted >= sector_target or sector_inserted >= sector_limit:
                    break
                ok, reason = _can_insert(
                    story,
                    enforce_domain_cap=False,
                    enforce_loose_dedupe=False,
                )
                if not ok:
                    if reason:
                        drop_reason_counts[sector][reason] += 1
                    continue
                _insert_story(story)

    db.commit()

    # Enforce hard per-sector daily cap on stored rows (not only per-run inserts).
    # This keeps dashboard distribution stable over many hourly runs.
    for sector in sectors_to_process:
        rows = db.execute(
            select(Story.id)
            .where(
                Story.snapshot_date == snapshot_date,
                Story.sector == sector,
            )
            .order_by(Story.score.desc(), Story.published_at.desc(), Story.id.desc())
        ).all()
        if len(rows) <= settings.max_items_per_sector:
            continue
        keep_ids = {row.id for row in rows[: settings.max_items_per_sector]}
        prune_ids = [row.id for row in rows if row.id not in keep_ids]
        if prune_ids:
            db.execute(delete(Story).where(Story.id.in_(prune_ids)))
            drop_reason_counts[sector]["pruned_by_sector_cap"] += len(prune_ids)
    db.commit()

    for sector in sorted(sectors_to_process):
        inserted = insert_counts.get(sector, 0)
        drops = dict(sorted(drop_reason_counts.get(sector, {}).items()))
        if inserted > 0 or drops:
            logger.warning("Store sector outcome [%s]: inserted=%s drops=%s", sector, inserted, drops)

    # Some freshly inserted rows can be pruned by the hard per-sector cap above.
    # Return only rows that still exist to avoid ObjectDeletedError downstream.
    if not inserted_ids:
        return []
    existing_inserted = db.scalars(
        select(Story).where(Story.id.in_(inserted_ids)).order_by(Story.score.desc(), Story.published_at.desc(), Story.id.desc())
    ).all()
    return existing_inserted
