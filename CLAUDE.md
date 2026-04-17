# CLAUDE.md

This file gives the current working context for this repository. It should match the real codebase and stay aligned with `agent.md` and `memory.md`.

## Project Overview

`leadgen` / **Antigravity** is a Python-based AI lead generation and outreach SaaS. Current working capabilities include:

- **multi-tenant** prospect storage with `client_id` on every data table; house account = 1
- public landing page at `/`
- pricing / pilot checkout page at `/checkout`
- self-serve onboarding at `/onboard`
- client-facing dashboard at `/client` with magic-link login
- client settings at `/client/settings`
- client prospects flow at `/client/prospects` with detail pages, CSV export, and bulk actions
- **client prospect status updates** — mark prospects booked or rejected from the detail page
- operator dashboard at `/ops` with workspace filtering
- SMTP-first deliverability hardening
- SendGrid routing plus signed webhook verification support
- Google Maps -> research -> email -> PDF -> send workflow
- inbox monitoring, reply classification, and **warm client notifications** on interested/booked replies
- **outreach approval queue** — per-client `outreach_review_mode` toggle; holds sequence emails for review before sending
- weekly client reports with **HTML email template** (stat blocks, funnel bars, score bands, top prospects)
- one-click unsubscribe with HMAC tokens and RFC List-Unsubscribe headers
- campaign pause/resume per client
- standalone scheduler support via `python scheduler.py`

The system is a usable internal SaaS prototype, not a fully hardened production product.

## Priority Context Files

Read these first before making major changes:

- `agent.md`
- `memory.md`

If a meaningful repo-level change is made, update all three files.

## Module Reference

### Core Data
- **`database.py`** - SQLite persistence for clients, prospects, outreach, suppression, communication events, sequence enrollments, prospect research, reply drafts, and client sessions.
  - `add_client(name, email, niche, icp, calendar_link, location, sender_name, sender_email)`
  - `update_client(client_id, ..., campaign_paused, outreach_review_mode)`
  - `get_client`, `get_all_clients`, `get_active_clients`, `get_client_by_email`
  - `get_prospect_by_id(prospect_id)`
  - `get_pending_outreach_for_review(client_id)` — returns outreach with status `pending_review`

### Delivery
- **`mailer.py`** - SMTP delivery with sender override and optional `html_body` parameter
- **`sendgrid_mailer.py`** - SendGrid delivery with `html_body` support (used as `html_content`)
- **`deliverability.py`** - shared outbound suppression checks, failure classification, event logging, per-client sender identity, unsubscribe token generation/verification
- **`_route_send_email()` in `web_app.py`** - the only approved outbound send path inside the web app; accepts `html_body`

### Web
- **`web_app.py`** - Flask dashboard and API surface. Important endpoints:
  - `GET /`
  - `GET /checkout`
  - `GET/POST /onboard`
  - `GET /ops`
  - `GET /client/login`
  - `GET /client/verify`
  - `GET /client`
  - `GET/POST /client/settings`
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
  - `POST /api/find-and-fire`
  - `GET /api/find-and-fire/<job_id>`
  - `POST /webhook/sendgrid`
  - `POST /webhook/stripe`
  - `GET /unsubscribe`
  - `GET /health`

## Important Rules

- All outbound sends in `web_app.py` must go through `_route_send_email()`
- `LINKEDIN_DRY_RUN=true` by default
- Scheduler can be disabled with `--no-scheduler` or `SCHEDULER_ENABLED=false`
- `/settings` is Basic Auth protected
- `/` is public marketing and `/ops` is internal operator UI
- `/client` requires `session["client_id"]`
- House account is always `client_id=1`
- Find-and-Fire uses job-id polling, not SSE
- `get_prospect_by_id()` must be used to reload a prospect after research
- SendGrid signed webhook verification is optional and controlled by `SENDGRID_WEBHOOK_PUBLIC_KEY`
- Per-client sender identity is stored and used during outbound sends; only used when `sender_email_verified=1`
- `outreach_review_mode=1` on a client makes the sequencer hold emails as `pending_review` instead of sending
- `_route_send_email` and all DB-writing routes must pass `db_path=_db` explicitly — default arg values are frozen at import time

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
http://127.0.0.1:5000/checkout
http://127.0.0.1:5000/onboard
http://127.0.0.1:5000/client
http://127.0.0.1:5000/ops
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
| Deliverability hardening | Done |
| SendGrid webhook handling | Done |
| Per-client sender identity | Done |
| One-click unsubscribe | Done |
| Campaign pause/resume | Done |
| Warm reply notifications | Done |
| Client prospect status updates | Done |
| Outreach approval queue | Done |
| HTML weekly report | Done |

## Planned Next Tasks

1. Sender verification visibility improvement (show verified status more prominently)
2. Onboarding sanity pass (test the full new-client flow end-to-end)
3. Production deploy hardening and env cleanup
4. More `/ops` polish and deeper workspace drilldowns
