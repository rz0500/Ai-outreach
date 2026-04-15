# CLAUDE.md

This file gives Claude Code the current working context for this repository. It should match the real codebase and stay aligned with `agent.md` and `memory.md`.

## Project Overview

`leadgen` is a Python-based AI lead generation and outreach system. Current working capabilities include:

- prospect storage and orchestration in SQLite
- evidence-first outbound email generation
- website research and enrichment via Anthropic API
- Google Maps -> research -> email -> PDF -> send workflow
- multi-channel sequence foundations
- inbox reply monitoring with AI classification
- background scheduler for inbox polling and daily sequence dispatch
- settings UI for live `.env` editing
- prospect CRUD, analytics, and CSV import in the dashboard

The system is a usable internal prototype, not a fully hardened production product.

## Priority Context Files

Read these first before making major changes:

- `agent.md`
- `memory.md`

If a meaningful repo-level change is made, update all three files.

## Module Reference

### Core Data
- **`database.py`** - SQLite persistence for prospects, outreach, suppression, communication events, sequence enrollments, prospect research, and reply drafts

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

### Web
- **`web_app.py`** - Flask dashboard and API surface. Important endpoints include:
  - `GET /`
  - `GET/POST /settings`
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

## Planned Next Tasks

1. Test suite coverage for the new endpoints and email validation
2. Find-and-fire progress streaming
3. Production scheduler split / startup hardening
