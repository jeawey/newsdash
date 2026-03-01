# Internal Sector News Dashboard

An internal dashboard that ingests sector news, ranks it by relevance + heat, and updates:
- Daily snapshot at **08:00 Europe/Madrid**
- Breaking updates **every hour at minute 05**

Sectors covered:
- Biotechnology
- AI
- Crypto
- Sustainability
- Cannabis
- Kenya

## What is implemented

- FastAPI dashboard (`/`) with:
  - Top stories across all sectors
  - Sector-specific ranked cards
- API endpoint (`/api/stories`) for raw dashboard JSON
- Scheduler worker (APScheduler) with:
  - Morning job at 08:00
  - Hourly breaking-news job
- Ingestion pipeline:
  - Pulls from query-based RSS feeds
  - Deduplicates by normalized title fingerprint
  - Scores each story by recency, source trust weight, and momentum
- Telegram integration for digests
- Configurable sector/subtopic query map in `config/sources.yml`

## Architecture

- `app/`: dashboard web app + DB models + API
- `worker/`: source config, feed fetching, scoring, persistence, scheduler, Telegram alerts
- `config/sources.yml`: sector taxonomy and trusted/excluded domain policies
- `scripts/`: start scheduler and manual one-shot ingestion

## Local run

1. Create env file:
   - `cp .env.example .env`
2. Optional: set Telegram credentials in `.env`
3. Install dependencies:
   - `python3 -m venv .venv`
   - `source .venv/bin/activate`
   - `pip install -U pip`
   - `pip install .`
4. Start web app:
   - `uvicorn app.main:app --host 0.0.0.0 --port 8000`
5. Start scheduler (new terminal):
   - `python scripts/start_scheduler.py`

## Docker run

1. `cp .env.example .env`
2. `docker compose up --build`
3. Dashboard: `http://localhost:8000`

### Verify scheduler/ingestion on VPS

- Check worker is running:
  - `docker compose ps`
- Tail worker logs:
  - `docker compose logs -f worker`
- Confirm ingestion runs from API:
  - `curl http://<your-host>/api/job-runs`

Notes:
- The hourly scheduled run is at minute `05` in your configured timezone.
- On worker startup, one ingestion run is executed immediately by default (`RUN_INGESTION_ON_STARTUP=true`).
- Duplicate suppression uses canonical URL + strict and loose title fingerprints per sector/day.
- Source diversity is enforced with `MAX_ITEMS_PER_DOMAIN_PER_SECTOR` (default `2`).
- Local quota for `Hamburg` and `Mallorca` enforces at least `MIN_ITEMS_PER_LOCAL_SUBTOPIC` items per category (default `4`) when available.

## GitHub Pages deployment (public, free)

This repo now includes:
- Static builder: `scripts/build_static_site.py`
- Auto-deploy workflow: `.github/workflows/pages.yml`

What the workflow does:
- Runs every hour (`cron: 7 * * * *`)
- Fetches and ranks stories
- Builds a static site into `site/`
- Deploys to GitHub Pages

### Enable Pages

1. Push this repo to GitHub (default branch `main`).
2. In GitHub repository settings:
   - Open **Pages**
   - Set **Source** to **GitHub Actions**
3. Trigger the workflow once manually:
   - **Actions** -> **Build and Deploy Pages** -> **Run workflow**

### Optional custom domain

1. Add repository variable `PAGES_CUSTOM_DOMAIN` with your domain (example `news.example.com`).
2. Point your DNS:
   - `CNAME` from `news.example.com` to `<your-user>.github.io`
3. The workflow writes a `CNAME` file automatically during build.

### Local static build preview

```bash
python scripts/build_static_site.py --output-dir site --asset-prefix ./assets
```

Then open `site/index.html` in your browser.

## Telegram setup

- Create a bot with `@BotFather` and copy token to `TELEGRAM_BOT_TOKEN`
- Add bot to your target chat/channel
- Set `TELEGRAM_CHAT_ID`

## Source policy notes

Current setup is free-source friendly and avoids paid APIs.
You should still validate terms of use for each source and for your intended internal redistribution behavior.

## Security / internal access

For an internal team dashboard, put the app behind one of:
- SSO reverse proxy (recommended): enforce Google/Microsoft/Okta login before app access
- Network-only access (VPN/private network)
- Basic auth (temporary only)

## Remaining decisions (from you)

1. Which SSO identity provider do you want (Google Workspace, Microsoft Entra, Okta)?
2. Do you want English-only news, or EN + ES feeds?
3. Do you want an operator panel to manually pin/remove headlines?
