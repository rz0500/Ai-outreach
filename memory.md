# Project Memory

This file is the long-term memory for the repo. Update it when significant architecture, integrations, or workflows change. Keep it aligned with `agent.md` and `CLAUDE.md`.

## Current State

**Completed modules:**
`database.py`, `scorer.py`, `importer.py`, `dashboard.py`, `outreach.py`, `reporter.py`, `mailer.py`, `sequencer.py`, `ai_engine.py`, `inbox_monitor.py`, `google_maps_finder.py`, `main.py`, `web_app.py`, `research_agent.py`, `pdf_generator.py`, `social_agent.py`, `sms_agent.py`, `sendgrid_mailer.py`, `sequence_engine.py`, `sequence_dispatcher.py`, `email_validator.py`, `deck_generator.py`, `settings.py`

**Current product shape:**
- **Multi-tenant SaaS** — `clients` table + `client_id` on every data table; house account = id 1
- Self-booking onboarding at `/onboard` — prospect fills form, client workspace is auto-created
- Autonomous self-prospecting — scheduler finds new leads via Google Maps daily (house account)
- Client-facing dashboard at `/client` — magic-link login, workspace-isolated view
- Weekly pipeline reports emailed to each active client every Monday 8am UTC
- Full automated pipeline: Google Maps -> research -> email -> PDF -> send
- Background scheduler for inbox polling, daily sequence dispatch, self-prospecting, weekly reports
- Reply classification includes `booked`
- Settings UI at `/settings` (Basic Auth protected)
- Prospect add/edit/delete from the operator dashboard
- Analytics panel and bulk CSV import
- SendGrid routing and LinkedIn dry-run config
- Reply approval can send real email with thread headers

**What's missing next:**
1. Test suite coverage for new SaaS endpoints
2. Find-and-fire progress streaming
3. Gunicorn/production scheduler split
4. SendGrid attachment + thread-header parity

---

## Architectural Decisions

**Database:** SQLite `prospects.db` without ORM. `sqlite3.Row` for dict-like rows. Core tables: `clients`, `prospects`, `outreach`, `suppression_list`, `communication_events`, `sequence_enrollments`, `prospect_research`, `reply_drafts`, `client_sessions`. Every data table has `client_id INTEGER NOT NULL DEFAULT 1`. House account (id=1) is seeded in `initialize_database()`. All query functions accept `client_id=1` as default kwarg — no callers needed updating.

**Multi-tenancy isolation:** Enforced at the query layer. No prospect, outreach, event, draft, or enrollment is readable across `client_id` boundaries. The operator dashboard uses `client_id=1` implicitly. Client dashboard enforces `session["client_id"]`.

**Client session auth:** Magic-link only. `client_sessions` table stores UUID token with 24h TTL. `POST /client/login` generates token and emails link. `GET /client/verify` validates, marks used, sets Flask session. No passwords.

**Status pipeline:** `new -> qualified -> contacted -> in_sequence -> replied -> booked / rejected`.

**Reply classification:** valid categories include `interested`, `booked`, `not_interested`, `opt_out`, `out_of_office`, and `auto_reply`.

**Background scheduler:** daemon thread in `web_app.py`. Per cycle: polls inbox (`INBOX_POLL_INTERVAL`), runs sequence dispatch once daily at `SEQUENCE_RUN_HOUR`, runs self-prospecting once daily at `SELF_PROSPECT_RUN_HOUR` (house account only), drains `_pending_client_research` set (from `/onboard`), sends weekly client reports every Monday 08:00 UTC. `GET /api/monitor-status` exposes state. `POST /api/monitor-reset` clears paused state.

**Inbox polling hardening:** `inbox_monitor.py` now uses `UNSEEN` for IMAP search, normalizes odd MIME charsets like `unknown-8bit`, and limits each run to `IMAP_MAX_MESSAGES_PER_POLL` messages by default.

**Outbound email routing:** `_route_send_email()` in `web_app.py` is the single send router. SMTP supports attachments and thread headers. SendGrid currently does not.

**Compliance copy:** `outreach.py` again exposes `OPT_OUT_LINE` so both the modern generator and the legacy sequencer/compliance paths share the same opt-out language.

**Settings:** `settings.py` owns shared runtime config helpers: calendar link, scheduler interval, scheduler hour, SendGrid flag, sender name, LinkedIn dry-run mode, self-prospecting niche/location/limit/hour, and Flask secret key.

**Prospect CRUD:** `update_prospect()` supports partial updates. `delete_prospect()` hard-deletes and cascades to outreach, communication events, sequence enrollments, reply drafts, and prospect research.

**Email validation:** `_validate_email_address()` in `web_app.py` uses regex syntax plus DNS resolution before outbound sends.

**Anthropic parsing:** `ai_engine._extract_json()` strips Markdown fences before parsing JSON.

---

## APIs And Integrations

- **Anthropic API:** configured and working locally
- **SMTP:** configured and working locally
- **Google Maps API:** configured and working locally
- **SendGrid:** wired behind `USE_SENDGRID`, not fully feature-parity with SMTP
- **IMAP:** used by the background scheduler, live monitoring path present
- **Calendly / booking link:** `CALENDAR_LINK` in `.env`

---

## Key DB Tables

| Table | Purpose |
|---|---|
| `clients` | One row per workspace; id=1 is the house account |
| `prospects` | Core lead records (partitioned by `client_id`) |
| `outreach` | Email drafts and send log (partitioned by `client_id`) |
| `suppression_list` | Compliance exclusions (partitioned by `client_id`) |
| `communication_events` | Audit trail of touchpoints (partitioned by `client_id`) |
| `sequence_enrollments` | Multi-channel sequence state (partitioned by `client_id`) |
| `prospect_research` | Structured AI research results (partitioned by `client_id`) |
| `reply_drafts` | Classified inbound replies and review queue (partitioned by `client_id`) |
| `client_sessions` | Magic-link auth tokens for client dashboard login |
