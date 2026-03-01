import argparse
import json
import shutil
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import pytz
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.presentation import SECTOR_COLORS
from app.settings import get_settings
from worker.config import load_source_config
from worker.fetcher import fetch_all_stories
from worker.scoring import score_stories
from worker.types import ScoredStory


def _story_to_json(story: ScoredStory) -> Dict[str, Any]:
    return {
        "sector": story.sector,
        "subtopic": story.subtopic,
        "title": story.title,
        "url": story.url,
        "source_name": story.source_name,
        "source_domain": story.source_domain,
        "summary": story.summary,
        "published_at": story.published_at.isoformat(),
        "score": story.score,
        "heat_score": story.heat_score,
        "mentions": story.mentions,
    }


def _group_by_sector(stories: List[ScoredStory], per_sector_limit: int) -> Dict[str, List[ScoredStory]]:
    grouped: Dict[str, List[ScoredStory]] = defaultdict(list)
    for story in stories:
        bucket = grouped[story.sector]
        if len(bucket) < per_sector_limit:
            bucket.append(story)
    return dict(grouped)


def _render_index(
    output_dir: Path,
    snapshot_date: str,
    top_stories: List[ScoredStory],
    sectors: Dict[str, List[ScoredStory]],
    configured_sectors: List[str],
    configured_topics: List[str],
    sector_subtopics: Dict[str, List[str]],
    asset_prefix: str,
) -> None:
    env = Environment(
        loader=FileSystemLoader("app/templates"),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template("index.html")
    html = template.render(
        snapshot_date=snapshot_date,
        top_stories=top_stories,
        sectors=sectors,
        configured_sectors=configured_sectors,
        configured_topics=configured_topics,
        sector_subtopics=sector_subtopics,
        latest_story_ids=[],
        sector_colors=SECTOR_COLORS,
        asset_prefix=asset_prefix,
    )
    (output_dir / "index.html").write_text(html, encoding="utf-8")


def _write_data_json(
    output_dir: Path,
    snapshot_date: str,
    top_stories: List[ScoredStory],
    sectors: Dict[str, List[ScoredStory]],
) -> None:
    payload = {
        "snapshot_date": snapshot_date,
        "generated_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "top_stories": [_story_to_json(story) for story in top_stories],
        "sectors": {
            sector: [_story_to_json(story) for story in stories]
            for sector, stories in sectors.items()
        },
    }
    (output_dir / "data.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _copy_assets(output_dir: Path) -> None:
    assets_dir = output_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2("app/static/styles.css", assets_dir / "styles.css")
    shutil.copy2("app/static/logo.svg", assets_dir / "logo.svg")


def _write_cname(output_dir: Path, custom_domain: str) -> None:
    if not custom_domain:
        return
    domain = custom_domain.strip()
    if domain:
        (output_dir / "CNAME").write_text(domain + "\n", encoding="utf-8")


def build_site(output_dir: Path, asset_prefix: str, custom_domain: str) -> None:
    settings = get_settings()
    timezone = pytz.timezone(settings.timezone)
    snapshot_date = datetime.now(timezone).date().isoformat()

    try:
        source_config = load_source_config()
        raw_stories = fetch_all_stories(source_config)
        scored_stories = score_stories(raw_stories, source_config.trusted_domains)
        configured_sectors: List[str] = []
        sector_subtopics: Dict[str, List[str]] = {}
        for query in source_config.queries:
            if query.sector not in configured_sectors:
                configured_sectors.append(query.sector)
            subtopics = sector_subtopics.setdefault(query.sector, [])
            if query.subtopic not in subtopics:
                subtopics.append(query.subtopic)
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: News build failed, publishing empty dashboard: {exc}")
        scored_stories = []
        configured_sectors = []
        sector_subtopics = {}

    top_stories = scored_stories[:10]
    sectors = _group_by_sector(scored_stories, settings.max_items_per_sector)
    room_only = {"Kenya", "Hamburg", "Mallorca"}
    configured_topics = [sector for sector in configured_sectors if sector not in room_only]

    output_dir.mkdir(parents=True, exist_ok=True)
    _copy_assets(output_dir)
    _render_index(
        output_dir,
        snapshot_date,
        top_stories,
        sectors,
        configured_sectors,
        configured_topics,
        sector_subtopics,
        asset_prefix,
    )
    _write_data_json(output_dir, snapshot_date, top_stories, sectors)
    _write_cname(output_dir, custom_domain)

    print(
        "Built static dashboard:",
        f"stories={len(scored_stories)}",
        f"top={len(top_stories)}",
        f"sectors={len(sectors)}",
        f"output={output_dir}",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build static site output for GitHub Pages")
    parser.add_argument("--output-dir", default="site", help="Directory for generated site files")
    parser.add_argument(
        "--asset-prefix",
        default="./assets",
        help="Asset path prefix injected into the HTML template",
    )
    parser.add_argument(
        "--custom-domain",
        default="",
        help="Optional custom domain to write as CNAME file",
    )
    args = parser.parse_args()

    build_site(
        output_dir=Path(args.output_dir),
        asset_prefix=args.asset_prefix,
        custom_domain=args.custom_domain,
    )


if __name__ == "__main__":
    main()
