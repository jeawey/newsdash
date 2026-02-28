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
class SourceConfig:
    queries: list[QueryConfig]
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

    return SourceConfig(
        queries=queries,
        trusted_domains={k.lower(): float(v) for k, v in raw.get("trusted_domains", {}).items()},
        excluded_domains={d.lower() for d in raw.get("excluded_domains", [])},
    )


def iter_queries(config: SourceConfig) -> Iterator[QueryConfig]:
    yield from config.queries
