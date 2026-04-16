# CLAUDE.md

This file gives Claude Code the current working context for this repository. It should match the real codebase and stay aligned with `agent.md` and `memory.md`.

## Project Overview

`leadgen` / **Antigravity** is a Python-based AI lead generation and outreach SaaS. Current working capabilities include:

- **multi-tenant** prospect storage — every table carries `client_id`, house account = 1
- self-booking onboarding at `/onboard` — creates client workspace automatically
- autonomous self-prospecting via Google Maps on a daily schedule
- client-facing dashboard at `/client` with magic-link login
- automated weekly pipeline reports emailed to each active client
- evidence-first outbound email generation
- website research and enrichment via Anthropic API
- Google Maps -> research -> email -> PDF -> send workflow
- multi-channel sequence foundations
- inbox reply monitoring with AI classification
- background scheduler for inbox polling, daily sequence dispatch, self-prospecting, and weekly reports
- settings UI for live `.env` editing
- prospect CRUD, analytics, and CSV import in the operator dashboard

The system is a usable internal SaaS prototype, not a fully hardened production product.

## Priority Context Files

Read these first before making major changes:

- `agent.md`
- `memory.md`

If a meaningful repo-level change is made, update all three files.

## Module Reference

### Core Data
- **`database.py`** - SQLite persistence for clients, prospects, outreach, suppression, communication events, sequence enrollments, prospect research, reply drafts, and client sessions. All data tables carry `client_id` (DEFAULT 1 = house account). New client functions: `add_client`, `get_client`, `get_all_clients`, `get_active_clients`, `get_client_by_email`, `update_client`, `get_client_analytics`. All query functions accept and filter by `client_id=1`.

### Outreach
- **`outreach.py`** - Main email writer, evidence-first and angle-based
- **`email_validator.py`** - Email quality gate
- **`ai_engine.py`** - Anthropic-backed prompt engine and reply classifier

### Research
- **`research_agent.py`** - Website enrichment and structured research support

### Sequencing
- **`sequencer.py`** - Legacy single-channel sequencer
- **`sequence_engine.py`** - Channel-aware sequence model
- **`sequence_dispatcher.py`** - Dispatches email, LinkedIn, Instagram, and SMS touchpoints
- **`main.py`** - Entry point wired to the dispatcher path

### Delivery
- **`mailer.py`** - SMTP delivery
- **`sendgrid_mailer.py`** - SendGrid delivery
- **`_route_send_email()` in `web_app.py`** - the only approved outbound send path inside the web app

### Inbox
- **`inbox_monitor.py`** - IMAP reply monitor and reply classification flow
  - Gmail/live inbox path now uses `UNSEEN`
  - tolerates `unknown-8bit` style MIME charset labels
  - limits each poll with `IMAP_MAX_MESSAGES_PER_POLL` (default 25)

### Web
- **`web_app.py`** - Flask dashboard and API surface. Important endpoints include:
  - `GET /` — operator dashboard (house account, all prospects)
  - `GET/POST /settings` — Basic Auth protected
  - `GET /onboard` / `POST /onboard` — public client onboarding form
  - `GET /onboard/confirm` — post-signup confirmation page
  - `GET /client/login` / `POST /client/login` — magic link request
  - `GET /client/verify` — magic link token validation, sets session
  - `GET /client` — client-facing dashboard (session-gated)
  - `POST /client/logout`
  - `POST /api/full-pipeline`
  - `POST /api/generate-from-url`
  - `POST /api/generate-deck-from-url`
  - `POST /api/find-and-fire`
  - `POST /api/send-outreach/<id>`
  - `GET /api/outreach-tracker`
  - `GET /api/sent-replies`
  - `GET /api/reply-drafts`
  - `POST /api/reply-drafts/<id>/action`
  - `POST /api/seed-demo-reply`
  - `POST /api/prospects`
  - `PATCH /api/prospects/<id>`
  - `DELETE /api/prospects/<id>`
  - `POST /api/prospects/<id>/enrol`
  - `POST /api/import-csv`
  - `GET /api/analytics`
  - `GET /api/monitor-status`
  - `POST /api/monitor-reset`

### Documents
- **`pdf_generator.py`** - automated proposal PDF
- **`deck_generator.py`** - richer bespoke deck PDF path

### Discovery
- **`google_maps_finder.py`** - Google Maps lead discovery

### Shared Settings
- **`settings.py`** - runtime config helpers used across the app

## Important Rules

- All outbound sends in `web_app.py` must go through `_route_send_email()`
- `LINKEDIN_DRY_RUN=true` by default
- `USE_SENDGRID=true` currently drops attachment and thread-header support
- Scheduler only starts from `python web_app.py`
- `delete_prospect()` cascades through all related tables including `prospect_research`

## Running

```bash
pip install -r requirements.txt
python web_app.py
```

Focused checks:

```bash
python -m unittest test_ai_engine.py
python -m unittest test_reply_workflow.py test_subject_variety.py
python -m unittest discover
python -m compileall c:\Users\ritis\Projects\leadgen
```

## SaaS Layer Status

| Task | Status |
|---|---|
| 1. Per-client multi-tenancy | ✅ Done |
| 2. Self-booking onboarding at `/onboard` | ✅ Done |
| 3. Autonomous self-prospecting | ✅ Done |
| 4. Client-facing dashboard (`/client`) | ✅ Done |
| 5. Automated weekly client reports | ✅ Done |

## Planned Next Tasks

1. Test suite coverage for new SaaS endpoints
2. Find-and-fire progress streaming
3. Production scheduler split / startup hardening
4. SendGrid feature parity (attachments, thread headers)
5. Bounce / unsubscribe webhook handling
