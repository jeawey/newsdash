# Deployment Recommendation

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
