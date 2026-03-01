import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import re

from app.settings import get_settings
from worker.types import RawStory, ScoredStory
from worker.utils import fingerprint_title


def _recency_score(published_at: datetime, now: datetime) -> float:
    age_hours = max((now - published_at).total_seconds() / 3600.0, 0.0)
    return 6.0 * math.exp(-age_hours / 14.0)


def _keyword_boost(sector: str, title: str) -> float:
    t = title.lower()
    keywords = {
        "AI": [
            "openai",
            "anthropic",
            "claude",
            "perplexity",
            "model",
            "ceo",
            "hiring",
            "launch",
            "ai act",
            "regulation",
            "inference",
            "datacenter",
            "gpu",
            "copilot",
            "benchmark",
            "open source",
            "github",
        ],
        "Crypto": [
            "crash",
            "liquidation",
            "altcoin",
            "etf",
            "tariff",
            "regulation",
            "bitcoin",
            "ethereum",
            "stablecoin",
            "custody",
            "hack",
            "exploit",
            "bridge",
            "treasury",
            "institutional",
        ],
        "Biotechnology": ["microorganism", "biotech", "device", "invention", "clinical", "startup"],
        "Biotechnologie": [
            "mikroorganism",
            "biotech",
            "geraet",
            "invention",
            "clinical",
            "startup",
            "fda",
            "trial",
            "gene therapy",
            "crispr",
            "diagnostics",
            "medtech",
        ],
        "Sustainability": [
            "regulation",
            "climate",
            "startup",
            "catastrophe",
            "renewable",
            "compliance",
            "csrd",
            "esg",
            "disclosure",
            "carbon",
            "battery",
            "hydrogen",
            "circular economy",
            "recycling",
            "grid",
        ],
        "Cannabis": [
            "legalization",
            "hempcrete",
            "hempwood",
            "social club",
            "germany",
            "spain",
            "medical cannabis",
            "license",
            "hemp",
            "parliament",
        ],
        "Hamburg": [
            "hamburg",
            "senat",
            "buergerschaft",
            "event",
            "veranstaltung",
            "verkehr",
            "hafen",
            "ausschreibung",
            "vergabe",
            "neubau",
            "zweckentfremdung",
            "airbnb",
            "hotel",
            "st pauli",
            "kiez",
        ],
        "Mallorca": [
            "mallorca",
            "balearen",
            "palma",
            "consell",
            "tourismus",
            "event",
            "gesetz",
            "licitacion",
            "obra nueva",
            "licencia vacacional",
            "alquiler turistico",
            "airbnb",
            "apertura hotel",
            "sostenibilidad",
            "costa este",
            "manacor",
        ],
        "Kenya": [
            "parliament",
            "agriculture",
            "mount kenya",
            "startup",
            "policy",
            "nairobi",
            "procurement",
            "tender",
            "infrastructure",
            "cbk",
            "inflation",
            "transport",
            "energy project",
        ],
        "Politics": [
            "sanctions",
            "ceasefire",
            "summit",
            "tariff",
            "election",
            "war",
            "negotiation",
            "export controls",
            "security doctrine",
            "defense aid",
            "coalition",
            "parliament vote",
            "trade policy",
        ],
        "Frequenzen": [
            "spectrum",
            "rf",
            "microwave",
            "mmwave",
            "5g",
            "6g",
            "antenna",
            "wireless",
            "allocation",
            "auction",
            "fcc",
            "ofcom",
            "bnetza",
            "radar",
            "satellite",
            "interference",
        ],
    }
    sector_terms = keywords.get(sector, [])
    hits = 0
    for k in sector_terms:
        token = k.lower().strip()
        if not token:
            continue
        if len(token) <= 3:
            if re.search(r"\b" + re.escape(token) + r"\b", t):
                hits += 1
        elif " " in token:
            if token in t:
                hits += 1
        else:
            if re.search(r"\b" + re.escape(token) + r"\b", t):
                hits += 1
    return min(hits * 0.2, 1.0)


def score_stories(raw_stories: list[RawStory], trusted_domains: dict[str, float]) -> list[ScoredStory]:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    freshness_cutoff = now - timedelta(hours=settings.max_story_age_hours)

    grouped: dict[tuple[str, str], list[RawStory]] = defaultdict(list)
    for story in raw_stories:
        if story.published_at < freshness_cutoff:
            continue
        fp = fingerprint_title(story.title)
        grouped[(story.sector, fp)].append(story)

    scored: list[ScoredStory] = []
    for (sector, fp), mentions in grouped.items():
        best = sorted(mentions, key=lambda x: x.published_at, reverse=True)[0]
        mention_count = len({m.source_domain for m in mentions})

        recency = _recency_score(best.published_at, now)
        domain_weight = trusted_domains.get(best.source_domain, 1.0)
        mention_weight = min(math.log2(mention_count + 1) * 1.8, 4.0)
        keyword_weight = _keyword_boost(sector, best.title)

        heat_score = mention_weight + recency
        score = (recency * 0.5) + (domain_weight * 0.2) + (mention_weight * 0.2) + (keyword_weight * 0.1)

        scored.append(
            ScoredStory(
                sector=best.sector,
                subtopic=best.subtopic,
                title=best.title,
                url=best.url,
                source_name=best.source_name,
                source_domain=best.source_domain,
                summary=best.summary,
                published_at=best.published_at,
                score=round(score, 4),
                heat_score=round(heat_score, 4),
                fingerprint=fp,
                mentions=mention_count,
            )
        )

    return sorted(scored, key=lambda x: x.score, reverse=True)
