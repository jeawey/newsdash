#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timedelta

import pytz
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Story
from app.settings import get_settings
from worker.translate import translate_to_german


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill-translate existing stories to German")
    parser.add_argument("--hours", type=int, default=72, help="Only process stories fetched in last N hours (default: 72)")
    parser.add_argument("--limit", type=int, default=2000, help="Max stories to process per run (default: 2000)")
    args = parser.parse_args()

    settings = get_settings()
    tz = pytz.timezone(settings.timezone)
    cutoff = datetime.now(tz) - timedelta(hours=args.hours)

    db = SessionLocal()
    try:
        rows = db.execute(
            select(Story)
            .where(Story.fetched_at >= cutoff)
            .order_by(Story.fetched_at.desc())
            .limit(args.limit)
        ).scalars().all()

        processed = 0
        changed = 0
        for story in rows:
            processed += 1
            new_title = translate_to_german(story.title or "")
            new_summary = translate_to_german(story.summary or "")

            touched = False
            if new_title and new_title != story.title:
                story.title = new_title
                touched = True
            if new_summary and new_summary != story.summary:
                story.summary = new_summary
                touched = True

            if touched:
                changed += 1

        db.commit()
        print(f"processed={processed} changed={changed} hours={args.hours} limit={args.limit}")
    finally:
        db.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
