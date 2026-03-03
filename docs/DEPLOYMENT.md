# Deployment Guide - Earthquake/Volcano Map

## Quick Deploy Commands (VPS)

### 1. Pull & Deploy

```bash
# SSH auf VPS
ssh user@your-vps-ip

# Zum Projektverzeichnis
cd /path/to/newsdash

# Aktuelle Änderungen pullen
git pull origin main

# Dependencies installieren
pip install -e .
pip install slowapi
```

### 2. Environment Variables setzen

```bash
# .env Datei bearbeiten
nano .env

# MAPBOX_TOKEN prüfen (muss gesetzt sein):
MAPBOX_TOKEN=<your-mapbox-token-here>
```

### 3. Service Neustarten

#### Option A: Mit systemd (empfohlen)

```bash
sudo systemctl restart newsdash-web
sudo systemctl status newsdash-web
```

#### Option B: Mit Docker Compose

```bash
docker compose up -d --build
docker compose logs -f web
```

#### Option C: Manuell

```bash
pkill -f "uvicorn app.main:app" || true
nohup python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > /var/log/newsdash-web.log 2>&1 &
```

### 4. Health Check

```bash
curl http://localhost:8000/health
curl http://localhost:8000/api/astrophysics/map
curl http://localhost:8000/api/mapbox/config
```

---

## Deployment Script

Erstelle `scripts/deploy.sh`:

```bash
#!/bin/bash
set -e

echo "🚀 Starting deployment..."

git pull origin main
pip install -e .
pip install slowapi

if [ ! -f .env ]; then
    cp .env.example .env
    echo "⚠️ Please edit .env and set MAPBOX_TOKEN"
    exit 1
fi

if ! grep -q "MAPBOX_TOKEN=" .env; then
    echo "⚠️ MAPBOX_TOKEN not set in .env!"
    exit 1
fi

if [ -f docker-compose.yml ]; then
    docker compose up -d --build
    sleep 10
    docker compose logs -f --tail=20
else
    if systemctl is-active --quiet newsdash-web; then
        sudo systemctl restart newsdash-web
    else
        pkill -f "uvicorn app.main:app" || true
        nohup python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > /var/log/newsdash-web.log 2>&1 &
    fi
fi

sleep 5
if curl -s http://localhost:8000/health | grep -q "ok"; then
    echo "✅ Deployment successful!"
    QUAKE_COUNT=$(curl -s http://localhost:8000/api/astrophysics/map | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('earthquakes', [])))")
    echo "🗺️ Earthquakes loaded: $QUAKE_COUNT"
else
    echo "❌ Health check failed!"
    exit 1
fi
```

Usage:
```bash
chmod +x scripts/deploy.sh
./scripts/deploy.sh
```

---

## Systemd Service Configuration

### `/etc/systemd/system/newsdash-web.service`

```ini
[Unit]
Description=Constructive News Web App
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/var/www/newsdash
Environment="PATH=/var/www/newsdash/.venv/bin"
ExecStart=/var/www/newsdash/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Activate:

```bash
sudo systemctl daemon-reload
sudo systemctl enable newsdash-web
sudo systemctl start newsdash-web
sudo systemctl status newsdash-web
```

---

## Docker Compose

```yaml
services:
  web:
    build: .
    ports:
      - "8000:8000"
    environment:
      - MAPBOX_TOKEN=${MAPBOX_TOKEN}
      - DATABASE_URL=sqlite:///./news_dashboard.sqlite3
    volumes:
      - ./data:/app/data
    restart: unless-stopped

  worker:
    build: .
    command: python scripts/start_scheduler.py
    environment:
      - MAPBOX_TOKEN=${MAPBOX_TOKEN}
      - DATABASE_URL=sqlite:///./news_dashboard.sqlite3
    volumes:
      - ./data:/app/data
    depends_on:
      - web
    restart: unless-stopped
```

Deploy:
```bash
docker compose up -d --build
```

---

## Troubleshooting

### Map zeigt "Token nicht konfiguriert"
```bash
grep MAPBOX_TOKEN .env
sudo systemctl restart newsdash-web
sudo journalctl -u newsdash-web -f
```

### Rate Limiting funktioniert nicht
```bash
pip show slowapi
pip install slowapi
sudo systemctl restart newsdash-web
```

### API liefert keine Daten
```bash
curl -v http://localhost:8000/api/astrophysics/map
python3 -c "from worker.astrophysics import AstrophysicsData; print(AstrophysicsData().get_earthquakes_map_data())"
```

---

## One-Liner für VPS

```bash
ssh user@vps "cd newsdash && git pull && pip install -e . && sudo systemctl restart newsdash-web && curl http://localhost:8000/health"
```

---

## Original Deployment Recommendation

## Recommended option: single VM + Docker Compose + Cloudflare Access

Why this is best for your current constraints:
- No paid news APIs required
- Predictable operations, no vendor-specific rewrites
- Easy to run both web app and scheduler worker continuously
- Internal access control via SSO + MFA at the edge

How:
1. Provision one Linux VM (2 vCPU / 4 GB RAM is enough to start)
2. Install Docker + Docker Compose
3. Deploy this repo and run `docker compose up -d --build`
4. Put the app behind Cloudflare Access and enforce your IdP login
5. Configure Telegram bot token + chat ID in `.env`

## Managed option: Cloud Run + Cloud Scheduler

Why:
- Less server maintenance
- Native scheduled jobs + retries
- Good if your team prefers managed infrastructure

Tradeoff:
- Slightly more cloud setup complexity than a single VM
- You still need an auth layer for internal-only access

How:
1. Deploy web container to Cloud Run
2. Deploy worker endpoint or job target
3. Configure two Cloud Scheduler jobs:
   - `0 8 * * *` (Europe/Madrid) for morning run
   - `5 * * * *` (Europe/Madrid) for hourly breaking run
4. Protect web access with identity-aware controls

## Access/Auth terminology

- `SSO` = Single Sign-On. Team members log in with your existing company identity provider (Google Workspace, Microsoft Entra ID, or Okta) instead of separate dashboard passwords.
