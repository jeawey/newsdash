import math
from collections import defaultdict
from datetime import datetime, timezone

from worker.types import RawStory, ScoredStory
from worker.utils import fingerprint_title


def _recency_score(published_at: datetime, now: datetime) -> float:
    age_hours = max((now - published_at).total_seconds() / 3600.0, 0.0)
    return 6.0 * math.exp(-age_hours / 14.0)


def _keyword_boost(sector: str, title: str) -> float:
    t = title.lower()
    keywords = {
        "AI": ["launch", "release", "model", "open source", "regulation"],
        "Crypto": ["etf", "hack", "approval", "regulation", "stablecoin"],
        "Biotechnology": ["clinical", "trial", "fda", "phase", "crispr"],
        "Sustainability": ["emissions", "renewable", "storage", "decarbonization"],
        "Cannabis": ["legalization", "medical", "regulation", "licensing"],
        "Kenya": ["parliament", "policy", "election", "startup", "cbk"],
    }
    sector_terms = keywords.get(sector, [])
    return min(sum(0.2 for k in sector_terms if k in t), 1.0)


def score_stories(raw_stories: list[RawStory], trusted_domains: dict[str, float]) -> list[ScoredStory]:
    now = datetime.now(timezone.utc)

    grouped: dict[tuple[str, str], list[RawStory]] = defaultdict(list)
    for story in raw_stories:
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
