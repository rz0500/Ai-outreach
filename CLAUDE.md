# CLAUDE.md

This file gives the current working context for this repository. It should match the real codebase and stay aligned with `agent.md` and `memory.md`.

## Project Overview

`leadgen` / **OutreachEmpower** is a Python-based AI lead generation and outreach SaaS. Current working capabilities include:

- **multi-tenant** prospect storage with `client_id` on every data table; house account = 1
- public landing page at `/`
- **lead capture** at `/onboard` (rate-limited 5/IP/hour) — saves to `leads` table, notifies operator via `OPERATOR_EMAIL`, no auto-provisioning
- **manual provisioning** in `/ops` — pending leads section with Provision button; creates workspace + starts Mailivery + sends magic link
- client-facing dashboard at `/client` with magic-link login
- client settings at `/client/settings` with sender email verification flow
- client prospects flow at `/client/prospects` with detail pages, CSV export, and bulk actions
- **client prospect status updates** - mark prospects booked or rejected from the detail page
- operator dashboard at `/ops` with workspace filtering - **Basic Auth protected**
- ops quick-action buttons: pause/resume campaign, toggle review mode, resend welcome email per workspace
- SMTP-first deliverability hardening
- SendGrid routing plus signed webhook verification support
- Mailivery warmup integration with authenticated webhook handling
- **find-and-fire scraper** - Google Maps → research → AI email → PDF → scheduled send in one button click
- **timezone-aware sending** - emails scheduled at 08:00 prospect local time via Google Maps Geocoding + timezonefinder; `_send_scheduled_outreach()` dispatches every scheduler cycle
- **sent emails tab** at `/client/emails` - expandable rows showing full email body + PDF download link
- inbox monitoring, reply classification, and **warm client notifications** on interested/booked replies
- **outreach approval queue** - per-client `outreach_review_mode` toggle; holds sequence emails for review before sending
- **daily reports at 17:00 UTC** sent to both client and `OPERATOR_EMAIL` — today's contacts, replies, warm/booked highlights, weekly totals, Mailivery health score
- one-click unsubscribe with HMAC tokens and RFC List-Unsubscribe headers
- campaign pause/resume per client
- standalone scheduler support via `python scheduler.py`
- **startup crash guards** — `SECRET_KEY` placeholder/empty and `SETTINGS_PASSWORD` `change-me`/empty raise `RuntimeError` at boot; non-fatal warnings for `APP_BASE_URL`, `DB_PATH`, and missing `SENDGRID_WEBHOOK_PUBLIC_KEY`

The system is production-ready for first clients.

## Priority Context Files

Read these first before making major changes:

- `agent.md`
- `memory.md`

If a meaningful repo-level change is made, update all three files.

## Module Reference

### Core Data
- **`database.py`** - SQLite persistence. `DB_PATH` reads from `DB_PATH` env var (default: `prospects.db`). Set to a persistent volume path in production.
  - `add_client(name, email, niche, icp, calendar_link, location, sender_name, sender_email)`
  - `update_client(client_id, ..., campaign_paused, outreach_review_mode)`
  - `get_client`, `get_all_clients`, `get_active_clients`, `get_client_by_email`
  - `get_prospect_by_id(prospect_id)`
  - `get_pending_outreach_for_review(client_id)` - returns outreach with status `pending_review`
  - `set_sender_verify_token`, `get_client_by_sender_verify_token`, `confirm_sender_email_verified`
  - `add_lead`, `get_all_leads`, `get_lead`, `get_lead_by_email`, `mark_lead_provisioned`
  - `get_pending_sends()` - outreach rows with `send_after <= now` and `sent_at IS NULL`

### Delivery
- **`mailer.py`** - SMTP delivery with sender override and optional `html_body` parameter
- **`sendgrid_mailer.py`** - SendGrid delivery with `html_body` support (used as `html_content`)
- **`deliverability.py`** - shared outbound suppression checks, failure classification, event logging, per-client sender identity, unsubscribe token generation/verification
- **`_route_send_email()` in `web_app.py`** - the only approved outbound send path inside the web app; accepts `html_body`

### Web
- **`web_app.py`** - Flask dashboard and API surface. Important endpoints:
  - `GET /`
  - `GET/POST /onboard` - rate limited 5/IP/hour; POST saves lead, notifies OPERATOR_EMAIL
  - `GET /ops` - **Basic Auth required** (SETTINGS_USER / SETTINGS_PASSWORD)
  - `GET /client/login`
  - `GET /client/verify`
  - `GET /client`
  - `GET/POST /client/settings`
  - `POST /client/settings/verify-sender`
  - `GET /client/verify-sender`
  - `GET /client/prospects`
  - `GET /client/prospects/export`
  - `GET /client/prospects/<id>`
  - `POST /client/prospects/<id>/update-status`
  - `POST /client/prospects/bulk-action`
  - `POST /client/reply-drafts/<id>/action`
  - `GET /client/outreach-queue`
  - `POST /client/outreach-queue/<id>/action`
  - `POST /client/campaign/pause`
  - `POST /client/campaign/resume`
  - `POST /client/campaign/review-mode/enable`
  - `POST /client/campaign/review-mode/disable`
  - `POST /client/logout`
  - `POST /api/ops/client/<id>/pause` - **Basic Auth required**
  - `POST /api/ops/client/<id>/resume` - **Basic Auth required**
  - `POST /api/ops/client/<id>/toggle-review-mode` - **Basic Auth required**
  - `POST /api/ops/client/<id>/resend-welcome` - **Basic Auth required**
  - `POST /api/ops/client/<id>/mailivery/connect` - **Basic Auth required**
  - `POST /api/ops/client/<id>/mailivery/start` - **Basic Auth required**
  - `POST /api/ops/client/<id>/mailivery/pause` - **Basic Auth required**
  - `POST /api/ops/client/<id>/mailivery/resume` - **Basic Auth required**
  - `GET /api/ops/client/<id>/mailivery/status` - **Basic Auth required**
  - `GET /client/emails` - sent email log with expand/PDF
  - `POST /api/find-and-fire`
  - `GET /api/find-and-fire/<job_id>`
  - `POST /client/prospecting/settings` - save niche/location/ICP for scraper
  - `GET /api/warmup-status` - live Mailivery + ramp status
  - `GET /api/warmup-advice` - Claude Haiku AI deliverability recommendation
  - `POST /api/ops/leads/<id>/provision` - **Basic Auth required** — creates client, starts Mailivery, sends welcome email
  - `POST /webhook/sendgrid`
  - `POST /webhook/mailivery`
  - `GET /unsubscribe`
  - `GET /health`

## Important Rules

- All outbound sends in `web_app.py` must go through `_route_send_email()`
- `LINKEDIN_DRY_RUN=true` by default
- Scheduler can be disabled with `--no-scheduler` or `SCHEDULER_ENABLED=false`
- `/settings` and `/ops` are Basic Auth protected (same credentials: `SETTINGS_USER` / `SETTINGS_PASSWORD`)
- `/` is public marketing and `/ops` is internal operator UI
- `/client` requires `session["client_id"]`
- House account is always `client_id=1`
- Find-and-Fire uses job-id polling, not SSE; pipeline schedules send at 08:00 prospect local time (not immediate)
- Find-and-Fire skips prospects with `status='contacted'` to prevent duplicate sends
- `/onboard` POST saves to `leads` table only — NO client workspace created; operator provisions manually via `/ops`
- `_send_scheduled_outreach()` runs every scheduler cycle and dispatches outreach rows where `send_after <= now`
- Timezone inference uses Google Maps Geocoding API + `timezonefinder`; falls back to UTC
- `OPERATOR_EMAIL` env var required for lead notifications and daily reports
- Daily reports fire at 17:00 UTC (not weekly); sent to both client and operator
- `get_all_prospects(db_path=db_path)` must use keyword arg — positional passes as `client_id`
- `research_prospect(id, db_path=database.DB_PATH)` must pass `db_path` as keyword arg
- Email extraction from websites uses `_valid()` check — rejects addresses with nav/path text appended
- `get_prospect_by_id()` must be used to reload a prospect after research
- SendGrid signed webhook verification is optional and controlled by `SENDGRID_WEBHOOK_PUBLIC_KEY`
- Mailivery webhook verification is required via `MAILIVERY_WEBHOOK_SECRET`
- Per-client sender identity is stored and used during outbound sends; only used when `sender_email_verified=1`
- `outreach_review_mode=1` on a client makes the sequencer hold emails as `pending_review` instead of sending
- `_route_send_email` and all DB-writing routes must pass `db_path=_db` explicitly - default arg values are frozen at import time
- `DB_PATH` env var controls database location - set to a persistent volume path in production

## Running

```bash
pip install -r requirements.txt

python web_app.py
python web_app.py --no-scheduler
python scheduler.py
```

Primary local routes:

```bash
http://127.0.0.1:5000/
http://127.0.0.1:5000/onboard
http://127.0.0.1:5000/client
http://127.0.0.1:5000/ops       # Basic Auth: admin / admin (dev default)
```

## Production Deploy Checklist

Set these env vars before going live (startup warnings will remind you):

```
SECRET_KEY=<secrets.token_hex(32)>
APP_BASE_URL=https://yourdomain.com
SETTINGS_PASSWORD=<strong password>
DB_PATH=/var/data/prospects.db    # persistent volume path
MAILIVERY_WEBHOOK_SECRET=<strong shared secret if Mailivery webhooks are enabled>
OPERATOR_EMAIL=you@yourdomain.com  # receives lead alerts + daily reports
```

If Mailivery is enabled, also set `MAILIVERY_ENABLED=true`, `MAILIVERY_API_KEY`, and configure Mailivery to send `X-Mailivery-Webhook-Secret` with the same shared secret to `https://yourdomain.com/webhook/mailivery`.

Procfile defines two processes (both needed):
```
web:       gunicorn web_app:app --workers 2 --bind 0.0.0.0:$PORT
scheduler: python scheduler.py
```

## SaaS Layer Status

| Task | Status |
|---|---|
| Multi-tenancy | Done |
| Public launch path | Done |
| Client dashboard | Done |
| Client settings | Done |
| Client prospects flow | Done |
| Operator workspace filtering | Done |
| Ops quick actions (pause/resume/review/resend) | Done |
| Ops Basic Auth | Done |
| Deliverability hardening | Done |
| SendGrid webhook handling | Done |
| Mailivery warmup integration | Done |
| Mailivery webhook authentication | Done |
| Per-client sender identity | Done |
| Sender email verification flow | Done |
| One-click unsubscribe | Done |
| Campaign pause/resume | Done |
| Warm reply notifications | Done |
| Client prospect status updates | Done |
| Outreach approval queue | Done |
| Lead capture at /onboard (no auto-provision) | Done |
| Manual provisioning via /ops Provision button | Done |
| Daily reports at 17:00 UTC to client + operator | Done |
| Timezone-aware sending (08:00 local time) | Done |
| Stripe removed | Done |
| Onboarding welcome email + magic link (on provision) | Done |
| Onboarding rate limiting | Done |
| Startup safety warnings | Done |
| Persistent DB via DB_PATH env var | Done |
| 81 passing tests (saas_routes suite) | Done |
| Pre-launch crash guards (SECRET_KEY, SETTINGS_PASSWORD) | Done |
| SMS/LinkedIn/Instagram channel gating | Done |
| Live Mailivery health score (no batch delay) | Done |

## Mailivery Integration

External email warmup via Mailivery API (`mailivery_client.py`).

| Component | Detail |
|---|---|
| `mailivery_client.py` | Thin REST client. `MailiveryClient` class + `get_client()` factory. Returns `{"ok": False}` on failure, never raises. |
| DB columns | `clients.mailivery_campaign_id TEXT`, `clients.mailivery_health_score INTEGER` (nullable, added via migration). |
| Settings | `get_mailivery_api_key()`, `get_mailivery_enabled()` - gated by `MAILIVERY_ENABLED` env var. |
| `warmup_engine.get_combined_warmup_status()` | Merges built-in warmup dict with live Mailivery fields (connected, status, health_score, emails_today). |
| Onboarding hook | `_mailivery_auto_connect()` - called during operator-triggered provisioning (`POST /api/ops/leads/<id>/provision`), NOT on /onboard submission. |
| Ops endpoints | `POST /api/ops/client/<id>/mailivery/connect|start|pause|resume`, `GET /api/ops/client/<id>/mailivery/status` - all Basic Auth protected. |
| Webhook | `POST /webhook/mailivery` - requires `MAILIVERY_WEBHOOK_SECRET`; handles `campaign.disconnected`, `campaign.error`, `health_score.updated`. Disconnects clear cached campaign state. |
| Scheduler | `_refresh_mailivery_health_scores()` runs every 4 hours; warns to stdout if score < 50. |
| Client dashboard | Warmup health card shown when `warmup_status.mailivery_connected` is true. |
| Tests | `test_mailivery_client.py` - all HTTP calls mocked, 21 tests. |
| Env vars | `MAILIVERY_ENABLED=false`, `MAILIVERY_API_KEY=`, `MAILIVERY_WEBHOOK_SECRET=`, `MAILIVERY_OWNER_EMAIL=` |

## Live State (as of 2026-04-22)

- Mailivery campaign 137474 active for `info@outreachempower.com`, 10 emails/day
- SendGrid enabled (`USE_SENDGRID=true`), outbound emails routing through it
- House account (client_id=1) has `sender_email=info@outreachempower.com`, `sender_email_verified=1`
- DB at `c:\Users\ritis\Projects\leadgen\data\prospects.db` locally; needs persistent volume for production
- .env had UTF-8 BOM removed — was silently breaking dotenv parsing of first key
- Code is on GitHub at `rz0500/Ai-outreach` (master) — ready to deploy to Render
- `cloudscraper` replaces raw `requests` in `research_agent.py` — bypasses Cloudflare JS challenges, tries /about /services pages when homepage text is thin
- Stripe fully removed (no routes, no dependency)
- `/onboard` is now lead capture only; `/ops` has manual Provision button
- Emails scheduled at 08:00 prospect local time via `timezonefinder` + Google Maps Geocoding
- Daily reports at 17:00 UTC replace Monday weekly reports; go to client + `OPERATOR_EMAIL`

## Important Rules (additions)

- `SECRET_KEY` placeholder or empty → `RuntimeError` at boot (crashes app)
- `SETTINGS_PASSWORD` = `change-me` or empty → `RuntimeError` at boot (crashes app)
- LinkedIn/Instagram in `sequence_dispatcher.py`: skipped entirely (no browser) when `LINKEDIN_DRY_RUN=true`
- SMS in `sequence_dispatcher.py`: skipped unless `TWILIO_ACCOUNT_SID` is set
- SendGrid webhook returns 403 (not 400) on invalid/missing signature
- `warmup_engine.get_combined_warmup_status()` derives live health score from mailbox API call — never shows "Score loading…" when campaign is active

## Planned Next Tasks

1. **Deploy to Render** — set `DB_PATH=/var/data/prospects.db`, `APP_BASE_URL`, `OPERATOR_EMAIL`, `SECRET_KEY`, `SETTINGS_PASSWORD` (strong), and all keys from `.env`
2. Configure Mailivery webhook to `https://your-app.onrender.com/webhook/mailivery` once deployed
3. Set `OPERATOR_EMAIL` in production so lead alerts and daily reports arrive
