from collections import defaultdict
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
import hashlib
import logging
import re
import time
from typing import Optional
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

import feedparser
from dateutil import parser as date_parser

from app.settings import get_settings
from worker.config import DirectFeedConfig, QueryConfig, SourceConfig, iter_direct_feeds, iter_queries
from worker.types import RawStory
from worker.utils import build_summary, canonicalize_url, extract_domain, google_news_rss_url

_RSS_VERZEICHNIS_HOST = "www.rss-verzeichnis.de"
_RSS_HINT_RE = re.compile(r"RSS-Feed-URL.*?href=[\"']([^\"']+)[\"']", re.IGNORECASE | re.DOTALL)
_HREF_RE = re.compile(r"href=[\"']([^\"']+)[\"']", re.IGNORECASE)
logger = logging.getLogger(__name__)
settings = get_settings()
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

_QUERY_SECTOR_MIN_FLOORS: dict[str, int] = {
    "Sustainability": 70,
    "Biotechnologie": 70,
    "Cannabis": 50,
}

_DIRECT_SECTOR_MIN_FLOORS: dict[str, int] = {
    "Sustainability": 45,
    "Biotechnologie": 45,
    "Cannabis": 35,
}

_DIRECT_SECTOR_MAX_SHARE: dict[str, float] = {
    "Politics": 0.45,
}

_SECTOR_QUERY_EXPANSIONS: dict[str, tuple[str, ...]] = {
    "AI": (
        "model release frontier model open weights benchmark eval",
        "chief scientist appointed resigns joins head of research",
        "ai act enforcement executive order export controls",
        "ai funding acquisition merger datacenter gpu compute water cooling",
    ),
    "Crypto": (
        "altcoin rally crash plunge liquidations volatility",
        "hack exploit rug pull insider trading market manipulation wash trading",
        "sec doj enforcement lawsuit stablecoin etf regulation",
        "exchange outage custody proof of reserves infrastructure",
    ),
    "Sustainability": (
        "water reuse wastewater sludge water scarcity drought",
        "csrd esg disclosure scope 3 supply chain compliance",
        "circular economy recycling organic waste compost anaerobic digestion",
        "pfas non-toxic chemical ban climate adaptation resilience infrastructure",
        "public tender rfp eoi ppp grant funding pilot rollout framework contract",
    ),
    "Biotechnologie": (
        "fermentation biomanufacturing industrial biotech microbial consortium enzymes",
        "biofilm wastewater microbiology odor management biosurfactant surfactin",
        "biostimulant inoculant soil microbiome nutrient efficiency",
        "pilot plant scale-up manufacturing regulatory approval distribution deal qa qc",
    ),
    "Cannabis": (
        "legalization licensing medical cannabis framework law enforcement",
        "gmp gacp testing contamination quality lab certification",
        "hemp hempcrete hempwood textiles packaging soil applications",
        "social club tourism raids licensing changes acquisitions taxation",
    ),
    "Frequenzen": (
        "spectrum auctions 5g 6g regulator decision allocation",
        "rf hardware antenna mmwave satellite interference jamming radar",
        "solfeggio sound healing trend watch wellness signal",
    ),
    "Hamburg": (
        "hamburg senat buergerschaft gesetz verordnung beschluss",
        "hamburg ausschreibung vergabe rahmenvertrag tender rfp leistungsverzeichnis",
        "hamburg hotel hospitality housekeeping kueche abfluss fettabscheider",
        "hamburg quartier hafencity klimaresilienz regenwassermanagement schwammstadt",
        "hamburg hafen streik ausfall stoerung ueberschwemmung logistik",
    ),
    "Mallorca": (
        "mallorca consell ajuntament decreto normativa inspeccion sancion",
        "mallorca licitacion concurso adjudicacion pliego contrato marco tender",
        "mallorca licencia vacacional alquiler turistico airbnb enforcement",
        "mallorca hotel apertura reforma operador lavanderia cocina facility management",
        "mallorca sequia restriccion reutilizacion depuradora aguas residuales lodos",
    ),
    "Kenya": (
        "kenya water wastewater sanitation non-revenue water leak detection metering",
        "kenya procurement tender ifb rfp eoi donor-funded grant ppp",
        "kenya agriculture soil health drought irrigation fertilizer subsidy cooperative",
        "kenya ports marine oil spill grease trap industrial effluent",
        "kenya hospitality facility management housekeeping kitchen laundry hygiene",
    ),
    "Politics": (
        "war conflict sanctions ceasefire diplomacy military defense",
        "trade policy export controls procurement subsidy infrastructure bill",
        "water policy fertilizer policy supply chain disruption shipping lane",
    ),
}

_SUBTOPIC_QUERY_EXPANSIONS: dict[str, tuple[str, ...]] = {
    "Global Regulations": (
        "regulation compliance directive standard enforcement",
        "public procurement tender framework contract grant",
    ),
    "Innovations & Startups": (
        "pilot rollout startup partnership funding deployment",
        "water agri facility industrial innovation",
    ),
    "Disasters & Response": (
        "drought flood blackout emergency response infrastructure",
    ),
    "ESG Finance & Disclosure": (
        "csrd esg disclosure scope 3 auditability",
    ),
    "Energy Transition": (
        "grid stability battery hydrogen renewable infrastructure",
    ),
    "Circular Economy": (
        "recycling reuse compost anaerobic digestion waste-to-value",
    ),
    "Effective Microorganisms": (
        "microbial consortium inoculant fermentation soil microbiome",
    ),
    "Biotech Devices": (
        "biotech device diagnostics qa qc biomanufacturing",
    ),
    "Biotech Breakthroughs": (
        "industrial biotech scale-up pilot plant distribution deal",
    ),
    "Biotech Funding & M&A": (
        "acquisition merger funding partnership distribution",
    ),
    "Regulatory & Safety": (
        "regulatory approval biosafety labeling compliance standards",
    ),
    "Legalization Tracker": (
        "framework law licensing enforcement court ruling",
    ),
    "Industrial Hemp": (
        "hempcrete hempwood textiles packaging industrial hemp",
    ),
    "Spain Germany Policy": (
        "social club licensing raids inspection spain germany",
    ),
    "Medical Cannabis": (
        "medical cannabis gmp gacp testing contamination",
    ),
    "Industry & Retail": (
        "consolidation acquisitions taxation supply chain pricing",
    ),
    "HF Technology": (
        "rf mmwave antenna wireless hardware deployment",
    ),
    "Spectrum Policy": (
        "spectrum allocation auction regulator decision interference",
    ),
    "Resonance & Applications": (
        "radar satellite jamming interference security applications",
    ),
    "Telecom Infrastructure": (
        "5g 6g deployment infrastructure backhaul tower",
    ),
    "Defense & Space Spectrum": (
        "defense spectrum satellite communications jamming",
    ),
    "Labs & Models": (
        "model release frontier benchmark open weights eval",
    ),
    "Leadership Moves": (
        "chief scientist appointed joins resigns head of research",
    ),
    "AI Product Launches": (
        "launch rollout enterprise api copilot deployment",
    ),
    "Policy & Regulation": (
        "ai act enforcement executive order export controls",
    ),
    "AI in Enterprise": (
        "enterprise adoption procurement operations automation",
    ),
    "AI Chips & Infra": (
        "datacenter gpu compute chip cooling water cooling",
    ),
    "Open Source & Research": (
        "open source model weights benchmark evaluation research",
    ),
    "Lokale Politik & Gesetze": (
        "senat buergerschaft verordnung beschluss gesetz urteil",
        "decreto normativa aprobado sentencia inspeccion sancion",
    ),
    "Ausschreibungen & Vergaben": (
        "ausschreibung vergabe rahmenvertrag leistungsverzeichnis tender rfp",
        "licitacion concurso adjudicacion pliego contrato marco",
    ),
    "Hotels & Hospitality": (
        "hotel opening renovation operator housekeeping kitchen drains",
    ),
    "Nachhaltigkeit & Quartiere": (
        "quartier klimaresilienz schwammstadt regenwassermanagement kreislaufwirtschaft",
    ),
    "Events & Kultur": (
        "fachmesse kongress wasser agrar nachhaltigkeit",
    ),
    "St. Pauli & Kiez": (
        "st pauli kiez reperbahn tourism pressure regulation",
    ),
    "Schlagzeilen & Brennpunkte": (
        "streik hafen ausfall stoerung ueberschwemmung evakuierung",
    ),
    "Wirtschaft & Stadtleben": (
        "hafenwirtschaft logistik inflation housing tourism demand",
    ),
    "Immobilienrecht & Neubau": (
        "urbanismo obra nueva licencia moratoria zoning permits",
    ),
    "Ferienlizenzen & Airbnb": (
        "licencia vacacional alquiler turistico inspeccion sancion",
    ),
    "Hoteleroeffnungen & Hospitality": (
        "apertura hotel reforma operador housekeeping lavanderia cocina",
    ),
    "Nachhaltigkeit & Inselprojekte": (
        "sequia restriccion reutilizacion depuradora economia circular",
    ),
    "Events & Gesellschaft": (
        "fachmesse congreso turismo sostenibilidad water",
    ),
    "Ostküste & Gemeinden": (
        "cala millor sa coma manacor depuradora restricciones",
    ),
    "Wirtschaft & Tourismus": (
        "ocupacion temporada turismo reservas costes huelga",
    ),
    "Politics": (
        "kenya policy parliament county government regulation",
    ),
    "Agriculture & Mount Kenya": (
        "soil health irrigation drought fertilizer subsidy cooperative",
    ),
    "Startup Ecosystem": (
        "agritech watertech cleantech funding partnership expansion",
    ),
    "Infrastructure & Public Projects": (
        "wwtp upgrade procurement ppp operator contract pilot",
    ),
    "Business & Markets": (
        "distribution agreement import permit investment joint venture",
    ),
    "Geopolitical Conflicts": (
        "war conflict ceasefire sanctions military operation",
    ),
    "Global Power Moves": (
        "trade policy export controls diplomacy coalition",
    ),
    "Elections & Summits": (
        "parliament vote coalition election summit policy",
    ),
    "Trade & Sanctions": (
        "tariff sanctions export controls supply chain disruption",
    ),
    "Security & Defense": (
        "defense doctrine naval operation missile security incident",
    ),
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
    "Hamburg": 1,
    "Mallorca": 1,
    "Kenya": 1,
    "Politics": 2,
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
        # If Hamburg is explicitly present, keep the story.
        if re.search(r"\bhamburg\b", text):
            return True
        strong_hamburg_context = _term_hits(
            text, ("hamburger senat", "hamburger bürgerschaft", "bezirk hamburg", "hafen hamburg", "st pauli", "reeperbahn")
        ) >= 1
        if not strong_hamburg_context:
            return False

    return True


def _is_high_signal_politics_story(text: str) -> bool:
    priority_hits = _term_hits(text, _POLITICS_PRIORITY_TERMS)
    geo_hits = _term_hits(text, _POLITICS_GEO_ANCHORS)
    low_signal_hits = _term_hits(text, _POLITICS_LOW_SIGNAL_TERMS)

    if priority_hits >= 2:
        return True
    if priority_hits >= 1 and geo_hits >= 1:
        return True
    if low_signal_hits > 0 and priority_hits == 0:
        return False
    return False


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

    if best_sector != "Politics" and politics_score >= 3 and best_score < max(4, politics_score):
        best_sector = "Politics"
        best_score = politics_score
        min_required = _SECTOR_MIN_SCORE["Politics"]

    if best_score < min_required:
        best_sector = base_sector

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
        with urlopen(req, timeout=settings.feed_fetch_timeout_seconds) as resp:
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
    elif query.sector in {"Mallorca", "Kenya"}:
        # Keep room-specific sector mapping for location rooms.
        inferred_sector = query.sector
        inferred_subtopic = query.subtopic
    else:
        # For sector queries, keep configured sector to avoid politics over-dominance.
        inferred_sector = query.sector
        inferred_subtopic = query.subtopic

    if inferred_sector in {"Hamburg", "Mallorca"} and query.sector not in {"Hamburg", "Mallorca"}:
        inferred_subtopic = _select_local_subtopic(
            inferred_sector,
            text,
            _SECTOR_DEFAULT_SUBTOPIC[inferred_sector],
        )
    if inferred_sector == "Politics" and not _is_high_signal_politics_story(text):
        return None
    published_at = _parse_published(entry)

    return RawStory(
        sector=inferred_sector,
        subtopic=inferred_subtopic,
        title=title,
        url=url,
        source_name=source_name,
        source_domain=source_domain,
        summary=summary,
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
    if inferred_sector == "Politics" and not _is_high_signal_politics_story(text):
        return None
    if inferred_sector == feed_cfg.sector:
        inferred_subtopic = feed_cfg.subtopic
    elif inferred_sector in {"Hamburg", "Mallorca"}:
        inferred_subtopic = _select_local_subtopic(
            inferred_sector,
            text,
            _SECTOR_DEFAULT_SUBTOPIC[inferred_sector],
        )
    published_at = _parse_published(entry)

    return RawStory(
        sector=inferred_sector,
        subtopic=inferred_subtopic,
        title=title,
        url=url,
        source_name=source_name,
        source_domain=source_domain,
        summary=summary,
        published_at=published_at,
    )


def _stories_from_query(query: QueryConfig, config: SourceConfig) -> list[RawStory]:
    def locale_for_sector(sector: str) -> tuple[str, str]:
        if sector == "Hamburg":
            return ("de", "DE")
        if sector == "Mallorca":
            return ("es", "ES")
        if sector == "Kenya":
            return ("en", "KE")
        return ("en", "US")

    def query_variants(q: QueryConfig) -> list[str]:
        base = [q.query]
        sector_expansions = list(_SECTOR_QUERY_EXPANSIONS.get(q.sector, ()))
        subtopic_expansions = list(_SUBTOPIC_QUERY_EXPANSIONS.get(q.subtopic, ()))
        combined = sector_expansions + subtopic_expansions
        if not combined:
            return base

        # Add up to two deterministic expansions per configured query to broaden
        # coverage while keeping runtime/load bounded.
        digest = hashlib.sha1(f"{q.sector}:{q.subtopic}:{q.query}".encode("utf-8")).hexdigest()
        first_idx = int(digest[:8], 16) % len(combined)
        picks = [combined[first_idx]]
        if len(combined) > 1:
            second_idx = int(digest[8:16], 16) % len(combined)
            if second_idx == first_idx:
                second_idx = (second_idx + 1) % len(combined)
            picks.append(combined[second_idx])
        for extra in picks:
            candidate = f"{q.query} {extra}".strip()
            if candidate not in base:
                base.append(candidate)
        return base

    lang, region = locale_for_sector(query.sector)
    stories: list[RawStory] = []
    seen_urls: set[str] = set()
    for q_text in query_variants(query):
        feed_url = google_news_rss_url(q_text, lang=lang, region=region)
        feed = _parse_feed_with_timeout(feed_url)
        for entry in feed.entries[: settings.max_entries_per_feed]:
            story = _to_story(query, entry, config.excluded_domains)
            if story is None:
                continue
            canonical = canonicalize_url(story.url)
            if canonical in seen_urls:
                continue
            seen_urls.add(canonical)
            stories.append(story)
    return stories


def _stories_from_direct_feed(feed_cfg: DirectFeedConfig, config: SourceConfig) -> list[RawStory]:
    resolved_url = _resolve_direct_feed_url(feed_cfg.url)
    if not resolved_url:
        return []
    feed = _parse_feed_with_timeout(resolved_url)
    stories: list[RawStory] = []
    for entry in feed.entries[: settings.max_entries_per_feed]:
        story = _to_story_from_feed(feed_cfg, entry, config.excluded_domains)
        if story is not None:
            stories.append(story)
    return stories


def _build_sector_limits(
    *,
    budget: int,
    sector_task_counts: dict[str, int],
    min_floors: dict[str, int] | None = None,
    max_share_caps: dict[str, float] | None = None,
) -> dict[str, int]:
    if budget <= 0 or not sector_task_counts:
        return {}
    min_floors = min_floors or {}
    max_share_caps = max_share_caps or {}

    total_tasks = sum(max(count, 0) for count in sector_task_counts.values())
    if total_tasks <= 0:
        return {sector: 0 for sector in sector_task_counts}

    limits: dict[str, int] = {}
    for sector, count in sector_task_counts.items():
        proportional = int((budget * count) / total_tasks)
        limits[sector] = max(1, proportional)

    # Enforce floors for strategically important sectors.
    for sector, floor in min_floors.items():
        if sector in limits:
            limits[sector] = min(budget, max(limits[sector], floor))

    # Enforce max shares for dominant sectors (e.g., Politics direct feeds).
    for sector, share in max_share_caps.items():
        if sector in limits:
            cap = max(1, int(budget * max(0.0, min(1.0, share))))
            limits[sector] = min(limits[sector], cap)

    total_limits = sum(limits.values())
    if total_limits <= budget:
        return limits

    # Scale down non-floor sectors first until total fits budget.
    protected = {sector for sector in limits if limits[sector] <= min_floors.get(sector, 0)}
    overflow = total_limits - budget
    adjustable = [sector for sector in limits if sector not in protected]
    idx = 0
    while overflow > 0 and adjustable:
        sector = adjustable[idx % len(adjustable)]
        floor = min_floors.get(sector, 1)
        if limits[sector] > floor:
            limits[sector] -= 1
            overflow -= 1
        idx += 1
        if idx > len(adjustable) * budget:
            break
    return limits


def _partition_stories_with_sector_limits(
    stories: list[RawStory],
    *,
    remaining_for_kind: int,
    sector_limits: dict[str, int],
    accepted_by_sector: dict[str, int],
) -> tuple[list[RawStory], list[RawStory]]:
    if remaining_for_kind <= 0:
        return [], stories
    accepted: list[RawStory] = []
    rejected: list[RawStory] = []
    for story in stories:
        if len(accepted) >= remaining_for_kind:
            rejected.append(story)
            continue
        sector = story.sector
        sector_limit = sector_limits.get(sector, remaining_for_kind)
        if accepted_by_sector[sector] >= sector_limit:
            rejected.append(story)
            continue
        accepted.append(story)
        accepted_by_sector[sector] += 1
    return accepted, rejected


def fetch_all_stories(config: SourceConfig, *, max_runtime_seconds: int | None = None) -> list[RawStory]:
    collected_queries: list[RawStory] = []
    collected_direct: list[RawStory] = []
    overflow_queries: list[RawStory] = []
    overflow_direct: list[RawStory] = []
    started = time.monotonic()
    query_count = len(config.queries)
    direct_count = len(config.direct_feeds)
    processed_queries = 0
    processed_direct = 0
    max_runtime = max_runtime_seconds if max_runtime_seconds is not None else settings.fetch_max_runtime_seconds
    max_raw = settings.max_raw_stories_per_run
    direct_share = min(max(settings.direct_feed_raw_share, 0.0), 1.0)
    direct_floor = max(0, settings.min_direct_feed_raw_stories if direct_count else 0)
    direct_budget = min(max_raw, max(int(max_raw * direct_share), direct_floor)) if direct_count else 0
    query_budget = max_raw - direct_budget
    if query_count == 0 and direct_budget < max_raw:
        direct_budget = max_raw
        query_budget = 0

    query_task_counts: dict[str, int] = defaultdict(int)
    for query in config.queries:
        query_task_counts[query.sector] += 1
    direct_task_counts: dict[str, int] = defaultdict(int)
    for feed in config.direct_feeds:
        direct_task_counts[feed.sector] += 1

    query_sector_limits = _build_sector_limits(
        budget=query_budget,
        sector_task_counts=query_task_counts,
        min_floors=_QUERY_SECTOR_MIN_FLOORS,
    )
    direct_sector_limits = _build_sector_limits(
        budget=direct_budget,
        sector_task_counts=direct_task_counts,
        min_floors=_DIRECT_SECTOR_MIN_FLOORS,
        max_share_caps=_DIRECT_SECTOR_MAX_SHARE,
    )
    accepted_query_by_sector: dict[str, int] = defaultdict(int)
    accepted_direct_by_sector: dict[str, int] = defaultdict(int)

    def _time_left() -> float:
        if max_runtime is None:
            return float("inf")
        return max_runtime - (time.monotonic() - started)

    futures: dict = {}
    executor = ThreadPoolExecutor(max_workers=max(1, settings.fetch_max_workers))
    try:
        for query in iter_queries(config):
            fut = executor.submit(_stories_from_query, query, config)
            futures[fut] = ("query", query_count)
        for feed_cfg in iter_direct_feeds(config):
            fut = executor.submit(_stories_from_direct_feed, feed_cfg, config)
            futures[fut] = ("direct", direct_count)

        for fut in as_completed(futures):
            kind, total = futures[fut]
            if _time_left() <= 0:
                logger.warning(
                    "Fetch runtime limit reached; stopping with partial result (stories=%s)",
                    len(collected_queries) + len(collected_direct),
                )
                break
            try:
                stories = fut.result()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Fetch task failed for kind=%s: %s", kind, exc)
                stories = []

            if kind == "query":
                remaining_for_kind = query_budget - len(collected_queries)
                if remaining_for_kind > 0:
                    accepted, rejected = _partition_stories_with_sector_limits(
                        stories,
                        remaining_for_kind=remaining_for_kind,
                        sector_limits=query_sector_limits,
                        accepted_by_sector=accepted_query_by_sector,
                    )
                    collected_queries.extend(accepted)
                    overflow_queries.extend(rejected)
                else:
                    overflow_queries.extend(stories)
            else:
                remaining_for_kind = direct_budget - len(collected_direct)
                if remaining_for_kind > 0:
                    accepted, rejected = _partition_stories_with_sector_limits(
                        stories,
                        remaining_for_kind=remaining_for_kind,
                        sector_limits=direct_sector_limits,
                        accepted_by_sector=accepted_direct_by_sector,
                    )
                    collected_direct.extend(accepted)
                    overflow_direct.extend(rejected)
                else:
                    overflow_direct.extend(stories)

            if kind == "query":
                processed_queries += 1
                if processed_queries % 20 == 0:
                    logger.warning(
                        "Fetch progress (queries): %s/%s processed, stories=%s",
                        processed_queries,
                        total,
                        len(collected_queries) + len(collected_direct),
                    )
            else:
                processed_direct += 1
                if processed_direct % 25 == 0:
                    logger.warning(
                        "Fetch progress (direct): %s/%s processed, stories=%s",
                        processed_direct,
                        total,
                        len(collected_queries) + len(collected_direct),
                    )
    finally:
        for fut in futures:
            if not fut.done():
                fut.cancel()
        executor.shutdown(wait=False, cancel_futures=True)

    total_collected = len(collected_queries) + len(collected_direct)
    if total_collected < max_raw:
        remaining_slots = max_raw - total_collected
        if remaining_slots > 0 and overflow_direct:
            direct_fill, direct_reject = _partition_stories_with_sector_limits(
                overflow_direct,
                remaining_for_kind=remaining_slots,
                sector_limits=direct_sector_limits,
                accepted_by_sector=accepted_direct_by_sector,
            )
            collected_direct.extend(direct_fill)
            overflow_direct = direct_reject
            remaining_slots -= len(direct_fill)
        if remaining_slots > 0 and overflow_queries:
            query_fill, query_reject = _partition_stories_with_sector_limits(
                overflow_queries,
                remaining_for_kind=remaining_slots,
                sector_limits=query_sector_limits,
                accepted_by_sector=accepted_query_by_sector,
            )
            collected_queries.extend(query_fill)
            overflow_queries = query_reject

    collected = collected_direct + collected_queries
    if len(collected) > max_raw:
        collected = collected[:max_raw]

    duration = time.monotonic() - started
    logger.warning(
        "Fetch finished: queries=%s/%s direct=%s/%s stories=%s duration=%.1fs budgets(query=%s,direct=%s) accepted(query=%s,direct=%s)",
        processed_queries,
        query_count,
        processed_direct,
        direct_count,
        len(collected),
        duration,
        query_budget,
        direct_budget,
        len(collected_queries),
        len(collected_direct),
    )
    logger.warning("Fetch sector split (query): %s", dict(sorted(accepted_query_by_sector.items())))
    logger.warning("Fetch sector split (direct): %s", dict(sorted(accepted_direct_by_sector.items())))
    final_sector_counts: dict[str, int] = defaultdict(int)
    for story in collected:
        final_sector_counts[story.sector] += 1
    logger.warning("Fetch sector split (final): %s", dict(sorted(final_sector_counts.items())))

    return collected
