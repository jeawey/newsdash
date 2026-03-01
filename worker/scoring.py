import logging
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import re
from typing import Any

from app.settings import get_settings
from worker.types import RawStory, ScoredStory
from worker.utils import fingerprint_title

logger = logging.getLogger(__name__)

_SECTOR_BASELINE_BOOST: dict[str, float] = {
    "Biotechnologie": 0.22,
    "Sustainability": 0.20,
    "Hamburg": 0.18,
}

_POLITICS_HIGH_PRIORITY_TERMS: tuple[str, ...] = (
    "war",
    "krieg",
    "conflict",
    "konflikt",
    "ceasefire",
    "waffenstillstand",
    "missile",
    "rakete",
    "attack",
    "angriff",
    "invasion",
    "frontline",
    "front",
    "military",
    "defense",
    "verteidigung",
    "troops",
    "truppen",
)

_LOW_SIGNAL_INDIA_POLICY_TERMS: tuple[str, ...] = (
    "privacy",
    "datenschutz",
    "data protection",
    "daten",
    "dpdp",
    "compliance",
    "guideline",
    "guidelines",
    "draft bill",
)

_HIGH_IMPACT_TERMS: tuple[str, ...] = (
    "war",
    "krieg",
    "conflict",
    "konflikt",
    "attack",
    "angriff",
    "invasion",
    "sanction",
    "sanktion",
    "ceasefire",
    "emergency",
    "outage",
    "blackout",
    "recall",
    "ban",
    "lawsuit",
    "indict",
    "military",
    "defense",
    "explosion",
    "flood",
    "earthquake",
    "wildfire",
)

_SEMANTIC_STOPWORDS: set[str] = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "into",
    "und",
    "der",
    "die",
    "das",
    "eine",
    "einer",
    "einem",
    "einen",
    "nach",
    "news",
    "latest",
    "today",
    "breaking",
    "report",
    "reports",
    "update",
    "updates",
}

_FINAL_SCORE_WEIGHTS: dict[str, float] = {
    "base": 0.72,
    "comparative": 0.18,
    "coherence": 0.10,
}

_SECTOR_MAX_AGE_HOURS: dict[str, int] = {
    "AI": 96,
    "Crypto": 96,
    "Sustainability": 336,
    "Biotechnologie": 240,
    "Cannabis": 336,
    "Frequenzen": 336,
    "Hamburg": 72,
    "Mallorca": 120,
    "Kenya": 336,
    "Politics": 72,
}

_SECTOR_FALLBACK_MAX_AGE_HOURS: dict[str, int] = {
    "AI": 336,
    "Crypto": 336,
    "Sustainability": 1080,
    "Biotechnologie": 1080,
    "Cannabis": 1440,
    "Frequenzen": 1440,
    "Hamburg": 336,
    "Mallorca": 336,
    "Kenya": 1440,
}

_SECTOR_MIN_SCORABLE_ITEMS: dict[str, int] = {
    "AI": 16,
    "Crypto": 16,
    "Biotechnologie": 18,
    "Cannabis": 24,
    "Frequenzen": 20,
    "Sustainability": 18,
    "Hamburg": 12,
    "Mallorca": 18,
    "Kenya": 16,
}

_SECTOR_KEYWORDS_BASE: dict[str, tuple[str, ...]] = {
    "AI": (
        "openai",
        "anthropic",
        "claude",
        "perplexity",
        "deepmind",
        "frontier model",
        "model release",
        "new model",
        "open weights",
        "model",
        "ceo",
        "hiring",
        "appointed",
        "resigns",
        "chief scientist",
        "head of research",
        "launch",
        "ai act",
        "regulation",
        "executive order",
        "export controls",
        "inference",
        "eval",
        "evaluation",
        "safety",
        "alignment",
        "datacenter",
        "gpu",
        "compute",
        "chip",
        "nvidia",
        "water cooling",
        "funding",
        "acquisition",
        "merger",
        "copilot",
        "benchmark",
        "open source",
        "github",
    ),
    "Crypto": (
        "crash",
        "surge",
        "soars",
        "rallies",
        "plunge",
        "sell-off",
        "volatility",
        "liquidation",
        "liquidations",
        "altcoin",
        "memecoin",
        "etf",
        "tariff",
        "regulation",
        "bitcoin",
        "ethereum",
        "stablecoin",
        "custody",
        "hack",
        "exploit",
        "rug pull",
        "insider trading",
        "market manipulation",
        "wash trading",
        "front-running",
        "charges",
        "sec",
        "doj",
        "bridge",
        "exchange outage",
        "proof of reserves",
        "treasury",
        "institutional",
    ),
    "Biotechnology": ("microorganism", "biotech", "device", "invention", "clinical", "startup"),
    "Biotechnologie": (
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
        "fermentation",
        "biomanufacturing",
        "biosurfactant",
        "biofilm",
        "inoculant",
        "biostimulant",
        "soil microbiome",
        "scale-up",
        "pilot plant",
        "qa",
        "qc",
        "regulatory",
        "zulassung",
    ),
    "Sustainability": (
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
        "water reuse",
        "wastewater",
        "sludge",
        "scope 3",
        "supply chain",
        "climate adaptation",
        "drought",
        "water scarcity",
        "pfas",
        "non-toxic",
        "procurement",
        "tender",
        "grant",
        "rfp",
    ),
    "Cannabis": (
        "legalization",
        "legalisierung",
        "hempcrete",
        "hempwood",
        "social club",
        "club social",
        "germany",
        "spain",
        "medical cannabis",
        "cannabis medicinal",
        "license",
        "lizenz",
        "gmp",
        "gacp",
        "testing",
        "contamination",
        "hemp",
        "hanf",
        "parliament",
        "court ruling",
        "taxation",
    ),
    "Hamburg": (
        "hamburg",
        "hh",
        "senat",
        "buergerschaft",
        "bezirksamt",
        "hafencity",
        "altona",
        "eimsbuettel",
        "wandsbek",
        "harburg",
        "bergedorf",
        "event",
        "veranstaltung",
        "verkehr",
        "hafen",
        "port",
        "terminal",
        "logistik",
        "ausschreibung",
        "vergabe",
        "rahmenvertrag",
        "auftrag",
        "zuschlag",
        "neubau",
        "zweckentfremdung",
        "airbnb",
        "hotel",
        "facility management",
        "reinigung",
        "hygiene",
        "abwasser",
        "fettabscheider",
        "st pauli",
        "kiez",
        "reperbahn",
        "streik",
        "ausfall",
        "störung",
        "ueberschwemmung",
    ),
    "Mallorca": (
        "mallorca",
        "illes balears",
        "balearen",
        "palma",
        "consell",
        "tourismus",
        "ocupacion",
        "temporada",
        "event",
        "gesetz",
        "licitacion",
        "concurso",
        "adjudicacion",
        "pliego",
        "obra nueva",
        "licencia vacacional",
        "alquiler turistico",
        "airbnb",
        "apertura hotel",
        "housekeeping",
        "lavanderia",
        "cocina",
        "sostenibilidad",
        "sequia",
        "restriccion",
        "reutilizacion",
        "depuradora",
        "aguas residuales",
        "lodos",
        "costa este",
        "manacor",
        "cala millor",
        "sa coma",
        "son servera",
        "arta",
        "capdepera",
    ),
    "Kenya": (
        "kenya",
        "parliament",
        "agriculture",
        "mount kenya",
        "startup",
        "policy",
        "nairobi",
        "mombasa",
        "kisumu",
        "nakuru",
        "eldoret",
        "procurement",
        "tender",
        "rfp",
        "ifb",
        "eoi",
        "award",
        "grant",
        "donor-funded",
        "infrastructure",
        "cbk",
        "wasreb",
        "kebs",
        "nema",
        "kpa",
        "inflation",
        "transport",
        "energy project",
        "water",
        "wastewater",
        "wwtp",
        "sludge",
        "sanitation",
        "non-revenue water",
        "leak",
        "metering",
        "drought",
        "biofilm",
        "odor",
        "grease trap",
        "industrial effluent",
        "soil health",
        "humus",
        "regenerative",
        "biostimulant",
        "irrigation",
        "coffee",
        "tea",
        "avocado",
        "horticulture",
        "cooperative",
        "hotel",
        "resort",
        "lodge",
        "facility management",
        "housekeeping",
        "laundry",
        "kitchen",
        "drain",
        "partnership",
        "joint venture",
        "expansion",
        "power outage",
        "blackout",
    ),
    "Politics": (
        "sanctions",
        "sanktionen",
        "ceasefire",
        "summit",
        "tariff",
        "election",
        "war",
        "negotiation",
        "public procurement",
        "subsidy",
        "water policy",
        "fertilizer policy",
        "infrastructure bill",
        "ppp",
        "export controls",
        "security doctrine",
        "defense aid",
        "coalition",
        "parliament vote",
        "trade policy",
        "ban",
        "lawsuit",
        "investigation",
    ),
    "Frequenzen": (
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
    ),
}

_CONSTRUCTIVE_LENS_WEIGHTS: dict[str, float] = {
    "biofilm": 1.6,
    "wastewater": 1.4,
    "abwasser": 1.4,
    "soil health": 1.4,
    "humus": 1.6,
    "regenerative": 1.2,
    "biostimulant": 1.2,
    "probiotic": 1.2,
    "irrigation": 1.1,
    "water reuse": 1.3,
    "grease trap": 1.4,
    "fettabscheider": 1.4,
    "procurement": 1.2,
    "tender": 1.2,
    "ausschreibung": 1.2,
}

_STRATEGIC_RELEVANCE_WEIGHTS: dict[str, float] = {
    "trade policy": 1.2,
    "export controls": 1.2,
    "public procurement": 1.2,
    "procurement": 1.1,
    "tender": 1.1,
    "rfp": 1.0,
    "grant": 1.0,
    "infrastructure": 1.0,
    "water restriction": 1.1,
    "fertilizer subsidy": 1.0,
    "shipping lane": 1.0,
    "port disruption": 1.2,
    "blackout": 1.0,
}

_SUBTOPIC_BOOSTS: dict[tuple[str, str], float] = {
    ("Hamburg", "Ausschreibungen & Vergaben"): 0.24,
    ("Hamburg", "Wirtschaft & Stadtleben"): 0.12,
    ("Mallorca", "Ausschreibungen & Vergaben"): 0.24,
    ("Mallorca", "Wirtschaft & Tourismus"): 0.12,
    ("Kenya", "Infrastructure & Public Projects"): 0.20,
    ("Kenya", "Business & Markets"): 0.10,
    ("Sustainability", "Global Regulations"): 0.10,
    ("Sustainability", "Energy Transition"): 0.10,
    ("Biotechnologie", "Regulatory & Safety"): 0.10,
    ("Biotechnologie", "Biotech Breakthroughs"): 0.10,
    ("Cannabis", "Legalization Tracker"): 0.10,
}

_NOISE_PENALTY_WEIGHTS: dict[str, float] = {
    "breaking": -0.6,
    "latest": -0.4,
    "update": -0.4,
    "ceo": -0.7,
    "earnings": -0.9,
    "stock": -0.7,
    "share price": -0.7,
    "celebrity": -1.2,
    "gala": -0.9,
    "festival": -0.9,
    "concert": -0.9,
    "top 10": -0.8,
    "roundup": -0.8,
    "round-up": -0.8,
}


def _contains_term(text: str, term: str) -> bool:
    token = term.lower().strip()
    if not token:
        return False
    if len(token) <= 3:
        return re.search(r"\b" + re.escape(token) + r"\b", text) is not None
    if " " in token:
        return token in text
    return re.search(r"\b" + re.escape(token) + r"\b", text) is not None


def _term_hits(text: str, terms: tuple[str, ...]) -> int:
    return sum(1 for term in terms if _contains_term(text, term))


def _norm_text(title: str, summary: str) -> str:
    return f"{title} {summary}".lower()


def _weighted_hits(text: str, weighted_terms: dict[str, float]) -> tuple[float, list[tuple[str, float]]]:
    score = 0.0
    matches: list[tuple[str, float]] = []
    for term, weight in weighted_terms.items():
        if _contains_term(text, term):
            score += weight
            matches.append((term, weight))
    matches.sort(key=lambda item: abs(item[1]), reverse=True)
    return score, matches


@lru_cache(maxsize=64)
def _sector_weighted_terms(sector: str) -> dict[str, float]:
    base = {term: 1.0 for term in _SECTOR_KEYWORDS_BASE.get(sector, ())}

    if sector == "AI":
        for low in ("ceo", "hiring", "launch", "model"):
            if low in base:
                base[low] = 0.35
        for high in ("ai act", "regulation", "datacenter", "gpu", "open source", "benchmark", "inference"):
            if high in base:
                base[high] = 1.2

    if sector == "Crypto":
        for low in ("treasury", "institutional"):
            if low in base:
                base[low] = 0.7
        for high in ("liquidation", "crash", "hack", "exploit", "stablecoin", "etf"):
            if high in base:
                base[high] = 1.3

    if sector in {"Biotechnologie", "Sustainability", "Hamburg"}:
        for term in base:
            base[term] = max(base[term], 1.1)

    return base


def _sector_keyword_boost(sector: str, title: str, summary: str) -> tuple[float, list[tuple[str, float]]]:
    text = _norm_text(title, summary)
    weighted_terms = _sector_weighted_terms(sector)
    raw, matches = _weighted_hits(text, weighted_terms)
    return max(0.0, min(raw / 8.0, 1.2)), matches


def _constructive_lens_boost(
    title: str, summary: str
) -> tuple[float, list[tuple[str, float]], list[tuple[str, float]], float]:
    text = _norm_text(title, summary)
    lens_raw, lens_hits = _weighted_hits(text, _CONSTRUCTIVE_LENS_WEIGHTS)
    noise_raw, noise_hits = _weighted_hits(text, _NOISE_PENALTY_WEIGHTS)
    strategic_raw, _ = _weighted_hits(text, _STRATEGIC_RELEVANCE_WEIGHTS)
    raw = lens_raw + noise_raw
    relevance_signal = lens_raw + strategic_raw
    return max(-0.6, min(raw * 0.22, 0.8)), lens_hits, noise_hits, relevance_signal


def _editorial_adjustment(story: RawStory) -> float:
    adjustment = _SECTOR_BASELINE_BOOST.get(story.sector, 0.0)
    text = _norm_text(story.title, story.summary)

    if story.sector == "Politics":
        high_priority_hits = _term_hits(text, _POLITICS_HIGH_PRIORITY_TERMS)
        if high_priority_hits > 0:
            adjustment += min(0.4, high_priority_hits * 0.08)

        india_marker = "india" in text or "india" in story.source_name.lower()
        low_signal_hits = _term_hits(text, _LOW_SIGNAL_INDIA_POLICY_TERMS)
        if india_marker and low_signal_hits > 0:
            adjustment -= min(0.6, 0.25 + low_signal_hits * 0.08)

    return adjustment


def _impact_score(story: RawStory, relevance_signal: float) -> float:
    text = _norm_text(story.title, story.summary)
    hits = _term_hits(text, _HIGH_IMPACT_TERMS)
    base = min(hits * 0.12, 0.6)
    if relevance_signal <= 0.0:
        return min(base, 0.12)
    return base


def _subtopic_boost(sector: str, subtopic: str) -> float:
    return _SUBTOPIC_BOOSTS.get((sector, subtopic), 0.0)


def _semantic_tokens(story: RawStory) -> set[str]:
    text = _norm_text(story.title, story.summary)
    tokens = re.findall(r"[a-zA-Z0-9]{3,}", text)
    return {token for token in tokens if token not in _SEMANTIC_STOPWORDS and not token.isdigit()}


def _jaccard_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def _percentile(sorted_values: list[float], value: float) -> float:
    if not sorted_values:
        return 0.5
    lower = 0
    upper = len(sorted_values)
    while lower < upper:
        mid = (lower + upper) // 2
        if sorted_values[mid] <= value:
            lower = mid + 1
        else:
            upper = mid
    return max(0.0, min(lower / len(sorted_values), 1.0))


def _recency_score(published_at: datetime, now: datetime) -> float:
    age_hours = max((now - published_at).total_seconds() / 3600.0, 0.0)
    return 6.0 * math.exp(-age_hours / 14.0)


def _scale_score_to_1_10(raw_score: float) -> float:
    # Calibrated for current raw distribution (~0-3.5): keep ordering while
    # mapping dashboard relevance to an intuitive 1-10 scale.
    return max(1.0, min(raw_score * 3.0, 10.0))


def _log_score_explainer(candidates: list[dict[str, Any]], *, limit: int) -> None:
    if limit <= 0:
        return
    for entry in sorted(candidates, key=lambda item: item["score"], reverse=True)[:limit]:
        story = entry["story"]
        parts = [
            f"score={entry['score']:.3f}",
            f"base={entry['base_score']:.3f}",
            f"cmp={entry['comparative_score']:.3f}",
            f"coh={entry['coherence_score']:.3f}",
            f"kw={entry['keyword_weight']:.3f}",
            f"edit={entry['editorial_weight']:.3f}",
            f"impact={entry['impact_weight']:.3f}",
            f"subtopic={entry['subtopic_weight']:.3f}",
            f"sector_hits={[term for term, _ in entry['sector_hits'][:4]]}",
            f"lens_hits={[term for term, _ in entry['lens_hits'][:4]]}",
            f"noise_hits={[term for term, _ in entry['noise_hits'][:4]]}",
        ]
        logger.warning("Score explain [%s/%s]: %s :: %s", story.sector, story.subtopic, story.title[:120], " | ".join(parts))


def score_stories(raw_stories: list[RawStory], trusted_domains: dict[str, float]) -> list[ScoredStory]:
    settings = get_settings()
    now = datetime.now(timezone.utc)

    grouped: dict[tuple[str, str], list[RawStory]] = defaultdict(list)
    fallback_grouped: dict[tuple[str, str], list[RawStory]] = defaultdict(list)
    dropped_by_freshness: dict[str, int] = defaultdict(int)
    for story in raw_stories:
        max_age_hours = _SECTOR_MAX_AGE_HOURS.get(story.sector, settings.max_story_age_hours)
        freshness_cutoff = now - timedelta(hours=max_age_hours)
        fp = fingerprint_title(story.title)
        if story.published_at >= freshness_cutoff:
            grouped[(story.sector, fp)].append(story)
            continue

        dropped_by_freshness[story.sector] += 1
        fallback_max_age = _SECTOR_FALLBACK_MAX_AGE_HOURS.get(story.sector)
        if fallback_max_age is None:
            continue
        fallback_cutoff = now - timedelta(hours=fallback_max_age)
        if story.published_at >= fallback_cutoff:
            fallback_grouped[(story.sector, fp)].append(story)

    present_sectors = {sector for sector, _ in grouped.keys()}
    present_counts: dict[str, int] = defaultdict(int)
    for sector, _ in grouped.keys():
        present_counts[sector] += 1
    fallback_used: dict[str, int] = defaultdict(int)
    for sector in _SECTOR_FALLBACK_MAX_AGE_HOURS:
        if sector in present_sectors:
            continue
        for (entry_sector, fp), entries in fallback_grouped.items():
            if entry_sector != sector:
                continue
            grouped[(entry_sector, fp)].extend(entries)
            fallback_used[entry_sector] += len(entries)

    # If a sector has too few fresh stories, top it up with older fallback candidates
    # so downstream per-sector insertion has enough material to work with.
    for sector, minimum in _SECTOR_MIN_SCORABLE_ITEMS.items():
        current = present_counts.get(sector, 0)
        if current >= minimum:
            continue
        needed = minimum - current
        fallback_candidates: list[tuple[tuple[str, str], list[RawStory]]] = []
        for key, entries in fallback_grouped.items():
            entry_sector, _ = key
            if entry_sector != sector:
                continue
            # Skip keys already present in fresh grouping.
            if key in grouped:
                continue
            fallback_candidates.append((key, entries))
        fallback_candidates.sort(
            key=lambda item: max(st.published_at for st in item[1]),
            reverse=True,
        )
        for key, entries in fallback_candidates:
            grouped[key].extend(entries)
            fallback_used[sector] += len(entries)
            needed -= 1
            if needed <= 0:
                break

    if dropped_by_freshness:
        logger.warning("Scoring freshness drops by sector: %s", dict(sorted(dropped_by_freshness.items())))
    if fallback_used:
        logger.warning("Scoring freshness fallback used: %s", dict(sorted(fallback_used.items())))

    candidates: list[dict[str, Any]] = []
    for (sector, fp), mentions in grouped.items():
        best = sorted(mentions, key=lambda item: item.published_at, reverse=True)[0]
        mention_count = len({item.source_domain for item in mentions})

        recency = _recency_score(best.published_at, now)
        domain_weight = trusted_domains.get(best.source_domain, 1.0)
        mention_weight = min(math.log2(mention_count + 1) * 1.8, 4.0)
        sector_kw, sector_hits = _sector_keyword_boost(sector, best.title, best.summary)
        lens_kw, lens_hits, noise_hits, relevance_signal = _constructive_lens_boost(best.title, best.summary)
        keyword_weight = sector_kw + lens_kw
        editorial_weight = _editorial_adjustment(best)
        impact_weight = _impact_score(best, relevance_signal)
        subtopic_weight = _subtopic_boost(best.sector, best.subtopic)

        heat_score = mention_weight + recency
        base_score = (
            (recency * 0.45)
            + (domain_weight * 0.2)
            + (mention_weight * 0.18)
            + (keyword_weight * 0.22)
            + editorial_weight
            + impact_weight
            + subtopic_weight
        )
        base_score = max(base_score, 0.0)

        candidates.append(
            {
                "story": best,
                "sector": best.sector,
                "fingerprint": fp,
                "mentions": mention_count,
                "heat_score": heat_score,
                "base_score": base_score,
                "semantic_tokens": _semantic_tokens(best),
                "keyword_weight": keyword_weight,
                "editorial_weight": editorial_weight,
                "impact_weight": impact_weight,
                "subtopic_weight": subtopic_weight,
                "sector_hits": sector_hits,
                "lens_hits": lens_hits,
                "noise_hits": noise_hits,
            }
        )

    if not candidates:
        return []

    global_sorted = sorted(candidate["base_score"] for candidate in candidates)
    sector_scores: dict[str, list[float]] = defaultdict(list)
    for candidate in candidates:
        sector_scores[candidate["sector"]].append(candidate["base_score"])
    for scores in sector_scores.values():
        scores.sort()

    sector_to_indices: dict[str, list[int]] = defaultdict(list)
    for idx, candidate in enumerate(candidates):
        sector_to_indices[candidate["sector"]].append(idx)

    sector_peer_order: dict[str, list[int]] = {}
    for sector, indices in sector_to_indices.items():
        sector_peer_order[sector] = sorted(indices, key=lambda i: candidates[i]["base_score"], reverse=True)

    scored: list[ScoredStory] = []
    for idx, candidate in enumerate(candidates):
        base_score = candidate["base_score"]
        sector = candidate["sector"]
        story = candidate["story"]

        global_percentile = _percentile(global_sorted, base_score)
        sector_percentile = _percentile(sector_scores[sector], base_score)
        comparative_score = (global_percentile * 0.4) + (sector_percentile * 0.6)

        tokens = candidate["semantic_tokens"]
        peer_indices = [i for i in sector_peer_order[sector] if i != idx][:20]
        best_similarity = 0.0
        for peer_idx in peer_indices:
            similarity = _jaccard_similarity(tokens, candidates[peer_idx]["semantic_tokens"])
            if similarity > best_similarity:
                best_similarity = similarity
        coherence_score = 0.35 if not peer_indices else min(1.0, best_similarity * 2.2)

        final_score = (
            base_score * _FINAL_SCORE_WEIGHTS["base"]
            + comparative_score * _FINAL_SCORE_WEIGHTS["comparative"]
            + coherence_score * _FINAL_SCORE_WEIGHTS["coherence"]
        )
        final_score = max(final_score, 0.0)
        scaled_score = _scale_score_to_1_10(final_score)

        candidate["comparative_score"] = comparative_score
        candidate["coherence_score"] = coherence_score
        candidate["score_raw"] = final_score
        candidate["score"] = scaled_score

        scored.append(
            ScoredStory(
                sector=story.sector,
                subtopic=story.subtopic,
                title=story.title,
                url=story.url,
                source_name=story.source_name,
                source_domain=story.source_domain,
                summary=story.summary,
                published_at=story.published_at,
                score=round(scaled_score, 4),
                heat_score=round(candidate["heat_score"], 4),
                fingerprint=candidate["fingerprint"],
                mentions=candidate["mentions"],
            )
        )

    _log_score_explainer(candidates, limit=settings.scoring_explain_log_limit)
    return sorted(scored, key=lambda item: item.score, reverse=True)
