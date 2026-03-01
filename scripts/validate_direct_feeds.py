#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen

import feedparser
import yaml

from app.settings import get_settings
from worker.fetcher import _resolve_direct_feed_url


USER_AGENT = "newsdash-feed-validator/1.0"
DEFAULT_TIMEOUT = 8.0
DEFAULT_SLOW_SECONDS = 6.0


@dataclass
class ValidationResult:
    index: int
    sector: str
    subtopic: str
    source_name: str
    original_url: str
    resolved_url: str
    ok: bool
    reason: str
    elapsed_seconds: float
    status_code: int | None
    entry_count: int
    bozo: int
    slow: bool


def _looks_html(payload: bytes, content_type: str) -> bool:
    ct = (content_type or "").lower()
    if "text/html" in ct:
        return True
    head = payload[:1024].lower()
    return b"<html" in head or b"<!doctype html" in head


def _fetch_bytes(url: str, timeout: float) -> tuple[bytes, int | None, str]:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, text/xml, */*"})
    with urlopen(req, timeout=timeout) as resp:
        status = getattr(resp, "status", None)
        content_type = resp.headers.get("Content-Type", "")
        payload = resp.read()
    return payload, status, content_type


def validate_feed(item: dict[str, Any], idx: int, timeout: float, slow_seconds: float) -> ValidationResult:
    sector = str(item.get("sector", ""))
    subtopic = str(item.get("subtopic", ""))
    source_name = str(item.get("source_name", ""))
    original_url = str(item.get("url", ""))

    resolved_url = _resolve_direct_feed_url(original_url)
    if not resolved_url:
        return ValidationResult(idx, sector, subtopic, source_name, original_url, resolved_url, False, "invalid_resolved_url", 0.0, None, 0, 0, False)

    start = time.monotonic()
    try:
        payload, status_code, content_type = _fetch_bytes(resolved_url, timeout)
    except HTTPError as e:
        elapsed = time.monotonic() - start
        return ValidationResult(idx, sector, subtopic, source_name, original_url, resolved_url, False, f"http_error_{e.code}", elapsed, e.code, 0, 0, elapsed > slow_seconds)
    except URLError:
        elapsed = time.monotonic() - start
        return ValidationResult(idx, sector, subtopic, source_name, original_url, resolved_url, False, "network_error", elapsed, None, 0, 0, elapsed > slow_seconds)
    except TimeoutError:
        elapsed = time.monotonic() - start
        return ValidationResult(idx, sector, subtopic, source_name, original_url, resolved_url, False, "timeout", elapsed, None, 0, 0, True)
    except Exception:
        elapsed = time.monotonic() - start
        return ValidationResult(idx, sector, subtopic, source_name, original_url, resolved_url, False, "fetch_exception", elapsed, None, 0, 0, elapsed > slow_seconds)

    elapsed = time.monotonic() - start
    parsed = feedparser.parse(payload)
    entry_count = len(parsed.entries)
    bozo = int(getattr(parsed, "bozo", 0) or 0)

    has_feed_meta = bool(getattr(parsed, "feed", None) and (parsed.feed.get("title") or parsed.feed.get("link") or parsed.feed.get("updated")))

    if status_code is not None and status_code >= 400:
        reason = f"http_status_{status_code}"
        ok = False
    elif _looks_html(payload, content_type) and entry_count == 0:
        reason = "html_not_feed"
        ok = False
    elif entry_count == 0 and not has_feed_meta:
        reason = "no_feed_content"
        ok = False
    else:
        reason = "ok"
        ok = True

    return ValidationResult(
        idx,
        sector,
        subtopic,
        source_name,
        original_url,
        resolved_url,
        ok,
        reason,
        elapsed,
        status_code,
        entry_count,
        bozo,
        elapsed > slow_seconds,
    )


def write_report(path: Path, results: list[ValidationResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "index",
            "sector",
            "subtopic",
            "source_name",
            "original_url",
            "resolved_url",
            "ok",
            "reason",
            "elapsed_seconds",
            "status_code",
            "entry_count",
            "bozo",
            "slow",
        ])
        for r in results:
            writer.writerow([
                r.index,
                r.sector,
                r.subtopic,
                r.source_name,
                r.original_url,
                r.resolved_url,
                r.ok,
                r.reason,
                f"{r.elapsed_seconds:.3f}",
                r.status_code or "",
                r.entry_count,
                r.bozo,
                r.slow,
            ])


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and optionally prune direct RSS feeds.")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="HTTP timeout seconds per feed (default: 8)")
    parser.add_argument("--slow-seconds", type=float, default=DEFAULT_SLOW_SECONDS, help="Mark feed as slow above this duration")
    parser.add_argument("--prune", action="store_true", help="Remove invalid feeds from sources.yml")
    parser.add_argument("--prune-slow", action="store_true", help="Also remove feeds marked slow (requires --prune)")
    parser.add_argument("--report", default="data/direct_feed_validation_report.csv", help="CSV report output path")
    args = parser.parse_args()

    settings = get_settings()
    cfg_path = settings.resolved_source_config_path()

    with cfg_path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    direct_feeds: list[dict[str, Any]] = list(raw.get("direct_feeds", []))
    results: list[ValidationResult] = []

    for i, item in enumerate(direct_feeds, start=1):
        results.append(validate_feed(item, i, timeout=args.timeout, slow_seconds=args.slow_seconds))

    ok_count = sum(1 for r in results if r.ok)
    bad_count = len(results) - ok_count
    slow_count = sum(1 for r in results if r.slow)

    report_path = Path(args.report)
    write_report(report_path, results)

    print(f"total={len(results)} ok={ok_count} invalid={bad_count} slow={slow_count}")
    print(f"report={report_path.resolve()}")

    invalid_reasons: dict[str, int] = {}
    for r in results:
        if r.ok:
            continue
        invalid_reasons[r.reason] = invalid_reasons.get(r.reason, 0) + 1
    if invalid_reasons:
        print("invalid_breakdown=")
        for k in sorted(invalid_reasons):
            print(f"  {k}: {invalid_reasons[k]}")

    if args.prune:
        bad_urls = {r.original_url for r in results if not r.ok}
        if args.prune_slow:
            bad_urls.update({r.original_url for r in results if r.slow})

        cfg_text = cfg_path.read_text(encoding="utf-8")
        start_marker = "direct_feeds:\n"
        end_marker = "\ntrusted_domains:"
        start_idx = cfg_text.find(start_marker)
        end_idx = cfg_text.find(end_marker, start_idx + len(start_marker))
        if start_idx == -1 or end_idx == -1:
            raise SystemExit("Could not locate direct_feeds block in sources.yml")

        block = cfg_text[start_idx + len(start_marker) : end_idx]
        lines = block.splitlines(keepends=True)

        kept_chunks: list[str] = []
        i = 0
        removed = 0

        while i < len(lines):
            line = lines[i]
            if line.lstrip().startswith("- sector:"):
                j = i + 1
                while j < len(lines) and not lines[j].lstrip().startswith("- sector:"):
                    j += 1
                item_chunk = "".join(lines[i:j])
                m = None
                for l in lines[i:j]:
                    if l.lstrip().startswith("url:"):
                        m = l
                        break
                url = ""
                if m:
                    mm = re.search(r'url:\s*"([^"]+)"', m)
                    if mm:
                        url = mm.group(1).strip()
                if url and url in bad_urls:
                    removed += 1
                else:
                    kept_chunks.append(item_chunk)
                i = j
                continue

            kept_chunks.append(line)
            i += 1

        new_block = "".join(kept_chunks)
        new_text = cfg_text[: start_idx + len(start_marker)] + new_block + cfg_text[end_idx:]
        cfg_path.write_text(new_text, encoding="utf-8")

        before = len(direct_feeds)
        kept = before - removed
        print(f"pruned={removed} kept={kept} file={cfg_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
