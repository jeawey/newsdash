from collections import defaultdict
from datetime import datetime, timedelta
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

_SECTOR_CONTENT_SIMILARITY_THRESHOLD: dict[str, float] = {
    # Politics tends to have many paraphrases for the same event.
    "Politics": 0.34,
    "default": 0.52,
}

_SECTOR_MAX_SIMILAR_PER_CLUSTER: dict[str, int] = {
    # Keep politics highly diverse by allowing only one story per event-cluster.
    "Politics": 1,
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


def _content_tokens(title: str, summary: str) -> set[str]:
    text = strip_html(f"{title} {summary}").lower()
    tokens = re.findall(r"[a-zA-ZäöüÄÖÜß0-9]{4,}", text)
    return {token for token in tokens if token not in _CONTENT_CLUSTER_STOPWORDS}


def _jaccard_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def _similarity_threshold_for_sector(sector: str) -> float:
    return _SECTOR_CONTENT_SIMILARITY_THRESHOLD.get(
        sector,
        _SECTOR_CONTENT_SIMILARITY_THRESHOLD["default"],
    )


def _max_similar_per_cluster_for_sector(sector: str, default_limit: int) -> int:
    return _SECTOR_MAX_SIMILAR_PER_CLUSTER.get(sector, default_limit)


def _find_similar_cluster(
    *,
    clusters: list[dict[str, object]],
    tokens: set[str],
    sector: str,
) -> int | None:
    threshold = _similarity_threshold_for_sector(sector)
    best_idx: int | None = None
    best_similarity = 0.0
    for idx, cluster in enumerate(clusters):
        cluster_tokens = cluster["tokens"]  # type: ignore[index]
        similarity = _jaccard_similarity(tokens, cluster_tokens)
        if similarity >= threshold and similarity > best_similarity:
            best_similarity = similarity
            best_idx = idx
    return best_idx


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
    snapshot_cutoff = datetime.now(pytz.utc) - timedelta(hours=max(1, settings.snapshot_max_story_age_hours))

    # Keep today's snapshot fresh: remove very old published stories even if they
    # are re-fetched by feeds.
    removed_old = db.execute(
        delete(Story).where(
            Story.snapshot_date == snapshot_date,
            Story.published_at < snapshot_cutoff,
        )
    ).rowcount or 0
    if removed_old:
        logger.warning(
            "Store freshness cleanup: removed_old_snapshot_rows=%s cutoff=%s",
            removed_old,
            snapshot_cutoff.isoformat(),
        )
    db.commit()

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
            select(
                Story.id,
                Story.url,
                Story.fingerprint,
                Story.title,
                Story.summary,
                Story.source_domain,
                Story.score,
                Story.published_at,
            ).where(
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
        content_clusters: list[dict[str, object]] = []
        domain_counts: dict[str, int] = defaultdict(int)
        for row in existing_rows:
            domain_counts[row.source_domain] += 1
            cluster_key = _content_cluster_key(row.title or "", row.summary or "")
            content_cluster_counts[cluster_key] += 1
            row_tokens = _content_tokens(row.title or "", row.summary or "")
            match_idx = _find_similar_cluster(clusters=content_clusters, tokens=row_tokens, sector=sector)
            if match_idx is None:
                content_clusters.append({"tokens": row_tokens, "count": 1})
            else:
                content_clusters[match_idx]["count"] = int(content_clusters[match_idx]["count"]) + 1

        sorted_sector_stories = sorted(sector_stories, key=lambda s: s.score, reverse=True)

        existing_count = len(existing_rows)
        sector_limit_remaining = max(0, settings.max_items_per_sector - existing_count)
        replacement_mode = sector_limit_remaining == 0 and existing_count > 0
        max_replacements = max(0, settings.max_replacements_per_sector_per_run)
        replacement_candidates = sorted(
            existing_rows,
            key=lambda row: (row.score if row.score is not None else 0.0, row.published_at, row.id),
        )
        replacements_done = 0

        sector_limit = sector_limit_remaining
        if replacement_mode:
            sector_limit = max_replacements
            if sector_limit <= 0:
                continue

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
            raw_title = (story.title or "").lower()
            if "<a" in raw_title or "href=" in raw_title or "</a>" in raw_title:
                return False, "malformed_title"
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
            cluster_limit = _max_similar_per_cluster_for_sector(
                sector,
                settings.max_similar_stories_per_cluster,
            )
            cluster_key = _content_cluster_key(story.title, story.summary)
            if content_cluster_counts[cluster_key] >= cluster_limit:
                return False, "duplicate_content_cluster"
            tokens = _content_tokens(story.title, story.summary)
            match_idx = _find_similar_cluster(clusters=content_clusters, tokens=tokens, sector=sector)
            if match_idx is not None and int(content_clusters[match_idx]["count"]) >= cluster_limit:
                return False, "duplicate_content_similarity"
            return True, None

        def _insert_story(story: ScoredStory) -> None:
            nonlocal sector_inserted
            url_key = canonicalize_url(story.url)
            loose_fp = fingerprint_title_loose(story.title)
            cluster_key = _content_cluster_key(story.title, story.summary)
            tokens = _content_tokens(story.title, story.summary)
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
            match_idx = _find_similar_cluster(clusters=content_clusters, tokens=tokens, sector=sector)
            if match_idx is None:
                content_clusters.append({"tokens": tokens, "count": 1})
            else:
                content_clusters[match_idx]["count"] = int(content_clusters[match_idx]["count"]) + 1
            domain_counts[story.source_domain] += 1
            sector_inserted += 1
            insert_counts[sector] += 1

        def _replace_lowest_existing(story: ScoredStory) -> tuple[bool, str | None]:
            nonlocal replacements_done, sector_inserted
            if not replacement_mode:
                return False, "replacement_mode_disabled"
            if replacements_done >= sector_limit or not replacement_candidates:
                return False, "replacement_limit_reached"

            target = replacement_candidates[0]
            target_score = target.score if target.score is not None else 0.0
            if story.score < (target_score + settings.min_replacement_score_delta):
                return False, "replacement_not_stronger"

            removed = replacement_candidates.pop(0)
            db.execute(delete(Story).where(Story.id == removed.id))
            drop_reason_counts[sector]["replaced_low_score_existing"] += 1

            removed_url = canonicalize_url(removed.url)
            seen_urls.discard(removed_url)
            seen_fingerprints.discard(removed.fingerprint)
            seen_loose_fingerprints.discard(fingerprint_title_loose(removed.title or ""))
            removed_cluster_key = _content_cluster_key(removed.title or "", removed.summary or "")
            if content_cluster_counts[removed_cluster_key] > 0:
                content_cluster_counts[removed_cluster_key] -= 1
            if domain_counts[removed.source_domain] > 0:
                domain_counts[removed.source_domain] -= 1

            _insert_story(story)
            replacements_done += 1
            return True, None

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
                    if replacement_mode:
                        replaced, replace_reason = _replace_lowest_existing(story)
                        if not replaced:
                            if replace_reason:
                                drop_reason_counts[sector][replace_reason] += 1
                            continue
                    else:
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
            if replacement_mode:
                replaced, replace_reason = _replace_lowest_existing(story)
                if not replaced:
                    if replace_reason:
                        drop_reason_counts[sector][replace_reason] += 1
                    continue
            else:
                _insert_story(story)

        if (not replacement_mode) and sector_inserted < sector_target:
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
