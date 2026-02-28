from datetime import datetime, timezone
from typing import Optional

import feedparser
from dateutil import parser as date_parser

from worker.config import QueryConfig, SourceConfig, iter_queries
from worker.types import RawStory
from worker.utils import build_summary, extract_domain, google_news_rss_url


def _parse_published(entry: dict) -> datetime:
    raw = entry.get("published") or entry.get("updated")
    if not raw:
        return datetime.now(timezone.utc)

    try:
        parsed = date_parser.parse(raw)
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _to_story(query: QueryConfig, entry: dict, excluded_domains: set[str]) -> Optional[RawStory]:
    title = (entry.get("title") or "").strip()
    url = (entry.get("link") or "").strip()
    if not title or not url:
        return None

    source_name = entry.get("source", {}).get("title", "Unknown source")
    source_domain = extract_domain(url)
    if source_domain in excluded_domains:
        return None

    summary = build_summary(entry.get("summary", ""))
    published_at = _parse_published(entry)

    return RawStory(
        sector=query.sector,
        subtopic=query.subtopic,
        title=title,
        url=url,
        source_name=source_name,
        source_domain=source_domain,
        summary=summary,
        published_at=published_at,
    )


def fetch_all_stories(config: SourceConfig) -> list[RawStory]:
    collected: list[RawStory] = []

    for query in iter_queries(config):
        feed_url = google_news_rss_url(query.query)
        feed = feedparser.parse(feed_url)

        for entry in feed.entries:
            story = _to_story(query, entry, config.excluded_domains)
            if story is not None:
                collected.append(story)

    return collected
