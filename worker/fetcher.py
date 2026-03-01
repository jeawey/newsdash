from datetime import datetime, timedelta, timezone
from functools import lru_cache
import re
from typing import Optional
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

import feedparser
from dateutil import parser as date_parser

from worker.config import DirectFeedConfig, QueryConfig, SourceConfig, iter_direct_feeds, iter_queries
from worker.translate import translate_to_german
from worker.types import RawStory
from worker.utils import build_summary, extract_domain, google_news_rss_url

_RSS_VERZEICHNIS_HOST = "www.rss-verzeichnis.de"
_RSS_HINT_RE = re.compile(r"RSS-Feed-URL.*?href=[\"']([^\"']+)[\"']", re.IGNORECASE | re.DOTALL)
_HREF_RE = re.compile(r"href=[\"']([^\"']+)[\"']", re.IGNORECASE)
_FEED_FETCH_TIMEOUT_SECONDS = 8
_TZINFOS = {
    "UTC": timezone.utc,
    "GMT": timezone.utc,
    "EST": timezone(timedelta(hours=-5)),
    "EDT": timezone(timedelta(hours=-4)),
    "CST": timezone(timedelta(hours=-6)),
    "CDT": timezone(timedelta(hours=-5)),
    "MST": timezone(timedelta(hours=-7)),
    "MDT": timezone(timedelta(hours=-6)),
    "PST": timezone(timedelta(hours=-8)),
    "PDT": timezone(timedelta(hours=-7)),
}

_SECTOR_DEFAULT_SUBTOPIC: dict[str, str] = {
    "Sustainability": "Global Regulations",
    "Biotechnologie": "Biotech Breakthroughs",
    "Cannabis": "Legalization Tracker",
    "Frequenzen": "Spectrum Policy",
    "Crypto": "Policy & Market Impact",
    "AI": "Labs & Models",
    "Hamburg": "Schlagzeilen & Brennpunkte",
    "Mallorca": "Wirtschaft & Tourismus",
    "Kenya": "Politics",
    "Politics": "Global Power Moves",
}

_SECTOR_KEYWORDS: dict[str, tuple[str, ...]] = {
    "AI": (
        "ai",
        "ki",
        "artificial intelligence",
        "machine learning",
        "openai",
        "anthropic",
        "llm",
        "gpt",
        "chatgpt",
        "claude",
        "gemini",
        "ai model",
        "copilot",
        "deep learning",
        "neural network",
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
    ),
    "Biotechnologie": (
        "biotech",
        "biotechnology",
        "pharma",
        "clinical trial",
        "gene",
        "crispr",
        "medical research",
        "genomic",
    ),
    "Cannabis": (
        "cannabis",
        "marijuana",
        "hemp",
        "cbd",
        "thc",
        "cannabis legal",
    ),
    "Frequenzen": (
        "spectrum",
        "rf ",
        "wireless",
        "telecom",
        "5g",
        "6g",
        "mmwave",
        "antenna",
        "satellite",
        "radar",
    ),
    "Sustainability": (
        "sustainab",
        "climate",
        "renewable",
        "emission",
        "net zero",
        "esg",
        "green energy",
        "decarbon",
    ),
    "Hamburg": (
        "hamburg",
        "st pauli",
        "reeperbahn",
        "elbphilharmonie",
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
        "cala ratjada",
    ),
    "Kenya": (
        "kenya",
        "nairobi",
        "mombasa",
        "kisumu",
        "east africa",
    ),
    "Politics": (
        "election",
        "wahl",
        "parliament",
        "regierung",
        "government",
        "policy",
        "minister",
        "sanction",
        "diplomacy",
        "war",
        "krieg",
        "conflict",
        "iran",
        "russia",
        "russland",
        "ukraine",
        "tanker",
        "beschlagnah",
        "seized",
        "navy",
        "military",
        "defense",
        "verteidigung",
    ),
}

_SECTOR_MIN_SCORE: dict[str, int] = {
    "AI": 3,
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

_HAMBURG_ANCHOR_TERMS: tuple[str, ...] = (
    "hamburg",
    "hamburger senat",
    "hamburger bürgerschaft",
    "bezirk hamburg",
    "st pauli",
    "kiez",
    "reeperbahn",
    "altona",
    "blankenese",
    "winterhude",
    "eppendorf",
    "schanze",
    "hafencity",
    "landungsbrücken",
    "elbphilharmonie",
    "hafen hamburg",
)

_HAMBURG_FOREIGN_GEO_TERMS: tuple[str, ...] = (
    "hannover",
    "lübeck",
    "kassel",
    "bonn",
    "dubai",
    "sao paulo",
    "são paulo",
    "berlin",
    "münchen",
    "munich",
    "köln",
    "cologne",
    "frankfurt",
    "stuttgart",
)

_HAMBURGER_FOOD_TERMS: tuple[str, ...] = (
    "burger",
    "cheeseburger",
    "hamburger rezept",
    "patty",
    "pommes",
    "grillen",
    "küche",
    "kitchen",
    "restaurantkette",
)

_LOCAL_SUBTOPIC_KEYWORDS: dict[str, dict[str, tuple[str, ...]]] = {
    "Hamburg": {
        "Lokale Politik & Gesetze": ("senat", "bürgerschaft", "gesetz", "verordnung", "bezirk", "wahl", "polit"),
        "Ausschreibungen & Vergaben": ("ausschreibung", "vergabe", "bieter", "bekanntmachung", "tender", "submiss"),
        "Hotels & Hospitality": ("hotel", "hostel", "hospitality", "gastro", "übernachtung", "beherberg"),
        "Nachhaltigkeit & Quartiere": ("klima", "wärmewende", "energie", "quartier", "sanierung", "nachhaltig", "umwelt"),
        "Events & Kultur": ("event", "veranstaltung", "festival", "konzert", "theater", "museum", "kultur", "messe"),
        "St. Pauli & Kiez": ("st pauli", "kiez", "reeperbahn", "schanzenviertel", "fc st pauli"),
        "Schlagzeilen & Brennpunkte": ("brand", "feuer", "unfall", "polizei", "kriminal", "razzia", "prozess"),
        "Wirtschaft & Stadtleben": ("wirtschaft", "hafen", "handel", "arbeitsmarkt", "verkehr", "wohnen", "miete", "infrastruktur"),
    },
    "Mallorca": {
        "Lokale Politik & Gesetze": ("govern", "consell", "parlament", "ayuntamiento", "gesetz", "decreto"),
        "Ausschreibungen & Vergaben": ("licitación", "ausschreibung", "concurso", "vergabe", "tender"),
        "Immobilienrecht & Neubau": ("bau", "neubau", "urbanismo", "baurecht", "immobil"),
        "Ferienlizenzen & Airbnb": ("airbnb", "ferienlizenz", "vacacional", "vermietung", "holiday rental"),
        "Hoteleroeffnungen & Hospitality": ("hotel", "resort", "hostal", "hospitality", "aparthotel"),
        "Nachhaltigkeit & Inselprojekte": ("sostenib", "nachhaltig", "solar", "wasser", "energie", "inselprojekt"),
        "Events & Gesellschaft": ("evento", "fiesta", "festival", "kultur", "gesellschaft", "veranstaltung"),
        "Ostküste & Gemeinden": ("manacor", "cala ratjada", "santanyi", "felanitx", "arta", "ostküste"),
        "Wirtschaft & Tourismus": ("tourismus", "wirtschaft", "aena", "flughafen", "kreuzfahrt", "season"),
    },
}


def _term_hits(text: str, terms: tuple[str, ...]) -> int:
    score = 0
    for term in terms:
        t = term.strip().lower()
        if not t:
            continue
        if len(t) <= 3:
            pattern = r"\b" + re.escape(t) + r"\b"
            if re.search(pattern, text):
                score += 1
        elif " " in t:
            if t in text:
                score += 1
        else:
            pattern = r"\b" + re.escape(t) + r"\b"
            if re.search(pattern, text):
                score += 1
    return score


def _select_local_subtopic(sector: str, text: str, fallback: str) -> str:
    mapping = _LOCAL_SUBTOPIC_KEYWORDS.get(sector, {})
    if not mapping:
        return fallback
    best = fallback
    best_score = 0
    for subtopic, terms in mapping.items():
        hits = _term_hits(text, terms)
        if hits > best_score:
            best_score = hits
            best = subtopic
    return best


def _is_hamburg_local_story(text: str) -> bool:
    has_anchor = _term_hits(text, _HAMBURG_ANCHOR_TERMS) > 0
    if not has_anchor:
        return False

    # Reject "hamburger" as food context unless there is explicit city context.
    if re.search(r"\bhamburger\b", text) and _term_hits(text, _HAMBURGER_FOOD_TERMS) > 0:
        has_city_context = _term_hits(text, ("hamburg", "senat", "bürgerschaft", "st pauli", "altona", "hafen")) > 0
        if not has_city_context:
            return False

    # Reject non-Hamburg local coverage that leaks in via broad feeds/queries.
    if _term_hits(text, _HAMBURG_FOREIGN_GEO_TERMS) > 0:
        strong_hamburg_context = _term_hits(
            text, ("hamburger senat", "hamburger bürgerschaft", "bezirk hamburg", "hafen hamburg", "st pauli", "reeperbahn")
        ) >= 1
        if not strong_hamburg_context:
            return False

    return True


def _classify_sector_and_subtopic(*, base_sector: str, title: str, summary: str, url: str, source_name: str) -> tuple[str, str]:
    # Do not use source_name for semantic classification, it biases by publisher naming.
    text = f"{title} {summary} {url}".lower()

    # Location rooms override global thematic sectors when explicit.
    hamburg_hits = _term_hits(text, _SECTOR_KEYWORDS["Hamburg"])
    mallorca_hits = _term_hits(text, _SECTOR_KEYWORDS["Mallorca"])
    kenya_hits = _term_hits(text, _SECTOR_KEYWORDS["Kenya"])
    if hamburg_hits >= _SECTOR_MIN_SCORE["Hamburg"] and _is_hamburg_local_story(text):
        subtopic = _select_local_subtopic("Hamburg", text, _SECTOR_DEFAULT_SUBTOPIC["Hamburg"])
        return "Hamburg", subtopic
    if mallorca_hits >= _SECTOR_MIN_SCORE["Mallorca"]:
        subtopic = _select_local_subtopic("Mallorca", text, _SECTOR_DEFAULT_SUBTOPIC["Mallorca"])
        return "Mallorca", subtopic
    if kenya_hits >= _SECTOR_MIN_SCORE["Kenya"]:
        return "Kenya", _SECTOR_DEFAULT_SUBTOPIC["Kenya"]

    scores: dict[str, int] = {}
    for sector, terms in _SECTOR_KEYWORDS.items():
        if sector in {"Hamburg", "Mallorca", "Kenya"}:
            continue
        scores[sector] = _term_hits(text, terms)

    # Tie-break toward Politics for ambiguous geopolitical stories.
    politics_score = scores.get("Politics", 0)
    best_sector = max(scores, key=scores.get) if scores else base_sector
    best_score = scores.get(best_sector, 0)
    min_required = _SECTOR_MIN_SCORE.get(best_sector, 1)

    if best_sector != "Politics" and politics_score >= 2 and best_score < max(3, politics_score):
        best_sector = "Politics"
        best_score = politics_score
        min_required = _SECTOR_MIN_SCORE["Politics"]

    if best_score < min_required:
        best_sector = "Politics"

    return best_sector, _SECTOR_DEFAULT_SUBTOPIC.get(best_sector, "Global Power Moves")


def _looks_like_feed_url(url: str) -> bool:
    lowered = url.lower()
    return (
        lowered.endswith(".xml")
        or lowered.endswith(".rss")
        or "/feed" in lowered
        or "rss" in lowered
        or "atom" in lowered
    )


@lru_cache(maxsize=1024)
def _resolve_direct_feed_url(raw_url: str) -> str:
    """
    Supports rss-verzeichnis detail pages by resolving the embedded RSS feed URL.
    For all other URLs, it returns the original value unchanged.
    """
    parsed = urlparse(raw_url)
    if parsed.netloc.lower() != _RSS_VERZEICHNIS_HOST:
        return raw_url
    if parsed.fragment:
        return ""
    if _looks_like_feed_url(raw_url):
        return raw_url

    try:
        req = Request(raw_url, headers={"User-Agent": "newsdash-worker/1.0"})
        with urlopen(req, timeout=10) as resp:
            content = resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return raw_url

    match = _RSS_HINT_RE.search(content)
    if match:
        resolved = urljoin(raw_url, match.group(1).strip())
        if resolved:
            return resolved

    for href in _HREF_RE.findall(content):
        candidate = urljoin(raw_url, href.strip())
        host = urlparse(candidate).netloc.lower()
        if host != _RSS_VERZEICHNIS_HOST and _looks_like_feed_url(candidate):
            return candidate

    return raw_url


def _parse_feed_with_timeout(url: str) -> feedparser.FeedParserDict:
    try:
        req = Request(url, headers={"User-Agent": "newsdash-worker/1.0"})
        with urlopen(req, timeout=_FEED_FETCH_TIMEOUT_SECONDS) as resp:
            payload = resp.read()
        return feedparser.parse(payload)
    except Exception:
        # Return empty feed on fetch/parse errors so one bad source can't block the whole run.
        return feedparser.parse(b"")


def _infer_sector_from_content(
    *,
    base_sector: str,
    title: str,
    summary: str,
    url: str,
    source_name: str,
) -> tuple[str, str]:
    """
    Reclassify imported bulk feeds on article level instead of hard feed-level buckets.
    This is intentionally scoped to synthetic source groups to avoid changing curated feeds.
    """
    if not (
        source_name.startswith("DE RSSV")
        or source_name.startswith("Countries/")
        or source_name.startswith("Feedspot World ")
    ):
        return base_sector, _SECTOR_DEFAULT_SUBTOPIC.get(base_sector, "Global Power Moves")

    return _classify_sector_and_subtopic(
        base_sector=base_sector,
        title=title,
        summary=summary,
        url=url,
        source_name=source_name,
    )


def _parse_published(entry: dict) -> datetime:
    raw = entry.get("published") or entry.get("updated")
    if not raw:
        return datetime.now(timezone.utc)

    try:
        parsed = date_parser.parse(raw, tzinfos=_TZINFOS)
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

    source_meta = entry.get("source", {}) or {}
    source_name = source_meta.get("title", "Unknown source")
    source_href = source_meta.get("href", "")
    source_domain = extract_domain(url)
    if source_domain == "news.google.com" and source_href:
        source_domain = extract_domain(source_href)
    if source_domain in excluded_domains:
        return None

    summary = build_summary(entry.get("summary", ""))
    inferred_sector, inferred_subtopic = _classify_sector_and_subtopic(
        base_sector=query.sector,
        title=title,
        summary=summary,
        url=url,
        source_name=source_name,
    )
    text = f"{title} {summary} {url}".lower()
    if query.sector == "Hamburg":
        if inferred_sector != "Hamburg":
            return None
        if not _is_hamburg_local_story(text):
            return None
    if inferred_sector == query.sector:
        inferred_subtopic = query.subtopic
    elif inferred_sector in {"Hamburg", "Mallorca"}:
        inferred_subtopic = _select_local_subtopic(
            inferred_sector,
            text,
            _SECTOR_DEFAULT_SUBTOPIC[inferred_sector],
        )
    title_de = translate_to_german(title)
    summary_de = translate_to_german(summary)
    published_at = _parse_published(entry)

    return RawStory(
        sector=inferred_sector,
        subtopic=inferred_subtopic,
        title=title_de,
        url=url,
        source_name=source_name,
        source_domain=source_domain,
        summary=summary_de,
        published_at=published_at,
    )


def _to_story_from_feed(feed_cfg: DirectFeedConfig, entry: dict, excluded_domains: set[str]) -> Optional[RawStory]:
    title = (entry.get("title") or "").strip()
    url = (entry.get("link") or "").strip()
    if not title or not url:
        return None

    source_name = (feed_cfg.source_name or "").strip()
    if not source_name:
        source_meta = entry.get("source", {}) or {}
        source_name = source_meta.get("title", "")
    source_domain = extract_domain(url)
    if source_domain in excluded_domains:
        return None

    if not source_name:
        source_name = source_domain or "Unknown source"

    summary = build_summary(entry.get("summary", ""))
    inferred_sector, inferred_subtopic = _infer_sector_from_content(
        base_sector=feed_cfg.sector,
        title=title,
        summary=summary,
        url=url,
        source_name=source_name,
    )
    text = f"{title} {summary} {url}".lower()
    if inferred_sector == "Hamburg" and not _is_hamburg_local_story(text):
        return None
    if inferred_sector == feed_cfg.sector:
        inferred_subtopic = feed_cfg.subtopic
    elif inferred_sector in {"Hamburg", "Mallorca"}:
        inferred_subtopic = _select_local_subtopic(
            inferred_sector,
            text,
            _SECTOR_DEFAULT_SUBTOPIC[inferred_sector],
        )
    title_de = translate_to_german(title)
    summary_de = translate_to_german(summary)
    published_at = _parse_published(entry)

    return RawStory(
        sector=inferred_sector,
        subtopic=inferred_subtopic,
        title=title_de,
        url=url,
        source_name=source_name,
        source_domain=source_domain,
        summary=summary_de,
        published_at=published_at,
    )


def fetch_all_stories(config: SourceConfig) -> list[RawStory]:
    collected: list[RawStory] = []

    def locale_for_sector(sector: str) -> tuple[str, str]:
        if sector == "Hamburg":
            return ("de", "DE")
        if sector == "Mallorca":
            return ("es", "ES")
        if sector == "Kenya":
            return ("en", "KE")
        return ("en", "US")

    for query in iter_queries(config):
        lang, region = locale_for_sector(query.sector)
        feed_url = google_news_rss_url(query.query, lang=lang, region=region)
        feed = _parse_feed_with_timeout(feed_url)

        for entry in feed.entries:
            story = _to_story(query, entry, config.excluded_domains)
            if story is not None:
                collected.append(story)

    for feed_cfg in iter_direct_feeds(config):
        resolved_url = _resolve_direct_feed_url(feed_cfg.url)
        if not resolved_url:
            continue
        feed = _parse_feed_with_timeout(resolved_url)
        for entry in feed.entries:
            story = _to_story_from_feed(feed_cfg, entry, config.excluded_domains)
            if story is not None:
                collected.append(story)

    return collected
