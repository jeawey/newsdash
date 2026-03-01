from __future__ import annotations

from functools import lru_cache
import json
import re
from urllib.parse import quote
from urllib.request import Request, urlopen


_TRANSLATE_TIMEOUT_SECONDS = 4
_MAX_TEXT_LENGTH = 2200

# Quick heuristic to avoid unnecessary translation calls for already-German text.
_GERMAN_HINT_RE = re.compile(
    r"\b(der|die|das|und|ist|nicht|mit|für|von|im|am|ein|eine|nach|auf|als|auch|bei)\b|[äöüÄÖÜß]",
    re.IGNORECASE,
)


def _looks_german(text: str) -> bool:
    return bool(_GERMAN_HINT_RE.search(text))


@lru_cache(maxsize=8192)
def translate_to_german(text: str) -> str:
    if not text:
        return text

    trimmed = text.strip()
    if not trimmed:
        return text

    if _looks_german(trimmed):
        return text

    payload = trimmed[:_MAX_TEXT_LENGTH]
    url = (
        "https://translate.googleapis.com/translate_a/single"
        f"?client=gtx&sl=auto&tl=de&dt=t&q={quote(payload)}"
    )

    try:
        req = Request(url, headers={"User-Agent": "newsdash-worker/1.0"})
        with urlopen(req, timeout=_TRANSLATE_TIMEOUT_SECONDS) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
        data = json.loads(raw)
        parts = data[0] if isinstance(data, list) and data else []
        translated = "".join((p[0] or "") for p in parts if isinstance(p, list) and p)
        return translated.strip() or text
    except Exception:
        return text

