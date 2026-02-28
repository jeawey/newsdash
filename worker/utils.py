import hashlib
import html
import re
from urllib.parse import quote_plus, urlparse


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
    clean = re.sub(r"<[^>]+>", " ", text)
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
