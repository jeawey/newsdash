from collections.abc import Iterator
from dataclasses import dataclass

import yaml

from app.settings import get_settings


@dataclass
class QueryConfig:
    sector: str
    subtopic: str
    query: str


@dataclass
class DirectFeedConfig:
    sector: str
    subtopic: str
    url: str
    source_name: str = ""


@dataclass
class SourceConfig:
    queries: list[QueryConfig]
    direct_feeds: list[DirectFeedConfig]
    trusted_domains: dict[str, float]
    excluded_domains: set[str]


def load_source_config() -> SourceConfig:
    settings = get_settings()
    path = settings.resolved_source_config_path()
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    queries: list[QueryConfig] = []
    for sector, items in raw.get("sectors", {}).items():
        for item in items:
            queries.append(
                QueryConfig(
                    sector=sector,
                    subtopic=item["name"],
                    query=item["query"],
                )
            )

    direct_feeds: list[DirectFeedConfig] = []
    for item in raw.get("direct_feeds", []):
        direct_feeds.append(
            DirectFeedConfig(
                sector=item["sector"],
                subtopic=item["subtopic"],
                url=item["url"],
                source_name=item.get("source_name", ""),
            )
        )

    return SourceConfig(
        queries=queries,
        direct_feeds=direct_feeds,
        trusted_domains={k.lower(): float(v) for k, v in raw.get("trusted_domains", {}).items()},
        excluded_domains={d.lower() for d in raw.get("excluded_domains", [])},
    )


def iter_queries(config: SourceConfig) -> Iterator[QueryConfig]:
    yield from config.queries


def iter_direct_feeds(config: SourceConfig) -> Iterator[DirectFeedConfig]:
    yield from config.direct_feeds
