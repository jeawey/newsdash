# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Internal sector news dashboard that ingests, scores, and displays ranked news stories. Uses FastAPI web app with APScheduler worker for hourly breaking updates and daily morning snapshots.

## Common Commands

### Development
```bash
# Install dependencies
python3 -m venv .venv && source .venv/bin/activate
pip install -U pip && pip install .

# Start web app
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Start scheduler worker
python scripts/start_scheduler.py

# Run single ingestion (morning or hourly based on current hour)
python scripts/run_ingestion_once.py
```

### Docker
```bash
# Build and run
docker compose up --build

# Check worker status
docker compose ps
docker compose logs -f worker

# API health check
curl http://localhost:8000/health
curl http://localhost:8000/api/job-runs
```

### Utilities
```bash
# Validate direct feeds config
python scripts/validate_direct_feeds.py

# Build static site for GitHub Pages
python scripts/build_static_site.py --output-dir site --asset-prefix ./assets

# Backfill German translations for existing stories
python scripts/backfill_translate_stories.py
```

## Architecture

### Directory Structure
- `app/`: FastAPI web app, database models, schemas, presentation layer
- `worker/`: Source config, feed fetching, scoring, persistence, scheduler, Telegram alerts
- `config/`: YAML configuration for sources, sectors, trusted/excluded domains
- `scripts/`: Scheduler startup, one-shot ingestion, validation, static site builder

### Data Flow Pipeline

1. **Fetch Phase** (`worker/fetcher.py`)
   - Pulls from Google News RSS queries and direct publisher feeds
   - Concurrent fetching with configurable timeouts and worker pool
   - `RawStory` objects created with sector/subtopic metadata

2. **Score Phase** (`worker/scoring.py`)
   - Deduplicates by title fingerprint, keeps best per sector/day
   - Scores using weighted factors: recency, domain trust, mention count, keyword relevance
   - Returns `ScoredStory` objects sorted by score (1-10 scale)

3. **Store Phase** (`worker/store.py`)
   - Per-sector insertion with diversity constraints:
     - URL + fingerprint deduplication
     - Domain caps (default 3, expanded to 7 for most sectors)
     - Content clustering via Jaccard similarity (sector-specific thresholds)
   - Replaces lowest-scoring existing stories when sector cap reached
   - Translates titles/summaries to German via `worker/translate.py`

4. **Serve Phase** (`app/main.py`)
   - API endpoint `/api/stories` returns JSON for current snapshot_date
   - Dashboard HTML rendered via Jinja2 templates
   - Hot badge shown for scores >= `hot_badge_threshold` (default 8.0)

### Scheduled Jobs (`worker/jobs.py`)

- `morning_snapshot`: Daily at 08:00 configured timezone
- `hourly_breaking`: Every hour at minute 02 (or 05 in README, code uses 02)
- `fast_breaking`: Every N minutes (default 5) if `FAST_LANE_ENABLED=true`

Fast lane uses reduced query/feed counts and higher runtime limits for near-realtime updates.

### Configuration

- **Settings**: `app/settings.py` - Pydantic settings with env var overrides
- **Sources**: `config/sources.yml` - Sector taxonomy, query map, direct feeds, trusted/excluded domains
- **Key settings**:
  - `DATABASE_URL`: SQLite path (default `sqlite:///./news_dashboard.sqlite3`)
  - `TIMEZONE`: For scheduled jobs (default `Europe/Madrid`)
  - `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`: For digest alerts
  - `FAST_LANE_ENABLED`: Enable fast-lane breaking updates
  - `HARD_RELEVANCE_GATE_ENABLED`: Hard lexical filtering (Politics, Hamburg only)
  - `RUN_INGESTION_ON_STARTUP`: Run ingestion once on worker startup

### Data Models (`app/models.py`)

- `Story`: Ranked news article with sector, subtopic, score, heat_score, fingerprint
- `JobRun`: Scheduler execution tracking with status and timing

### Scoring System

Scores combine multiple weighted factors:
- **Base score** (72%): recency (45%), domain trust (20%), mentions (18%), keywords (22%), editorial boost, impact, subtopic boost
- **Comparative score** (18%): global + sector percentile ranks
- **Coherence score** (10%): semantic diversity via Jaccard similarity

Sector-specific adjustments:
- `Biotechnologie`, `Sustainability`, `Hamburg` receive baseline boosts
- `Hamburg`, `Mallorca` enforce minimum items per subtopic
- Social domains (x.com, reddit.com, linkedin.com, substack.com) require higher scores/mentions

### Deduplication Strategy

- **URL dedup**: `canonicalize_url()` - removes query params/tracking
- **Title fingerprint**: `fingerprint_title()` - strict hash of title
- **Loose fingerprint**: `fingerprint_title_loose()` - normalized, stopwords removed
- **Content clustering**: Jaccard similarity on token sets (threshold varies by sector, 0.34-0.52)
- **Sector-specific**: Politics uses aggressive dedup (1 story per cluster), relaxed for Biotechnologie/Frequenzen/Cannabis

## Documentation Policy

Follow the workflow in `docs/DOCUMENTATION_WORKFLOW.md`:
- `docs/CHANGELOG.md`: Technical changes to code/config
- `docs/WORKLOG.md`: Operational steps (deploy, restart, manual runs, recovery)

Quick entry via script:
```bash
bash scripts/log_entry.sh worklog "Title" "Details"
bash scripts/log_entry.sh changelog "Title" "What changed and why"
```