import hashlib
import html
import re
from urllib.parse import parse_qsl, quote_plus, urlencode, urlparse, urlunparse


def google_news_rss_url(query: str, *, lang: str = "en", region: str = "US") -> str:
    encoded = quote_plus(query)
    return (
        "https://news.google.com/rss/search"
        f"?q={encoded}&hl={lang}&gl={region}&ceid={region}:{lang}"
    )


def extract_domain(url: str) -> str:
    domain = urlparse(url).netloc.lower()
    return domain.removeprefix("www.")


def strip_html(text: str) -> str:
    if not text:
        return ""
    clean = text
    # Decode escaped HTML first (some feeds deliver entities like &lt;a ...&gt;).
    for _ in range(2):
        clean = html.unescape(clean)
    # Remove script/style payloads if present.
    clean = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", clean, flags=re.IGNORECASE | re.DOTALL)
    # Remove tags.
    clean = re.sub(r"<[^>]+>", " ", clean)
    # Decode any remaining entities and normalize whitespace.
    clean = html.unescape(clean)
    return re.sub(r"\s+", " ", clean).strip()


def build_summary(raw_text: str, max_len: int = 220) -> str:
    text = strip_html(raw_text)
    if len(text) <= max_len:
        return text
    cutoff = text[:max_len].rsplit(" ", 1)[0]
    return f"{cutoff}..."


def fingerprint_title(title: str) -> str:
    normalized = re.sub(r"[^a-z0-9 ]", "", title.lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def fingerprint_title_loose(title: str) -> str:
    normalized = title.lower()
    normalized = re.sub(r"\b(live|updates?|breaking|latest|watch|video|photos?)\b", " ", normalized)
    normalized = re.sub(r"\b\d{1,2}(:\d{2})?\b", " ", normalized)
    normalized = re.sub(r"[^a-z0-9 ]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def canonicalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    path = re.sub(r"/+", "/", parsed.path).rstrip("/")
    query_pairs = [
        (k, v)
        for (k, v) in parse_qsl(parsed.query, keep_blank_values=False)
        if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid", "igshid"}
    ]
    normalized = parsed._replace(
        scheme=(parsed.scheme or "https").lower(),
        netloc=parsed.netloc.lower().removeprefix("www."),
        path=path,
        params="",
        query=urlencode(sorted(query_pairs)),
        fragment="",
    )
    return urlunparse(normalized)
