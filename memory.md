# Project Memory

This file is the long-term memory for the repo. Update it when significant architecture, integrations, or workflows change. Keep it aligned with `agent.md` and `CLAUDE.md`.

## Current State

**Completed modules:**
`database.py`, `scorer.py`, `importer.py`, `dashboard.py`, `outreach.py`, `reporter.py`, `mailer.py`, `sequencer.py`, `ai_engine.py`, `inbox_monitor.py`, `google_maps_finder.py`, `main.py`, `web_app.py`, `research_agent.py`, `pdf_generator.py`, `social_agent.py`, `sms_agent.py`, `sendgrid_mailer.py`, `sequence_engine.py`, `sequence_dispatcher.py`, `email_validator.py`, `deck_generator.py`, `settings.py`

**Current product shape:**
- Full automated pipeline: Google Maps -> research -> email -> PDF -> send
- Background scheduler for inbox polling and daily sequence dispatch
- Reply classification includes `booked`
- Settings UI at `/settings`
- Prospect add/edit/delete from the dashboard
- Analytics panel and bulk CSV import
- SendGrid routing and LinkedIn dry-run config
- Reply approval can send real email
- Monitor can now be resumed without restarting the app
- Pipeline table now shows sequence day progress from enrollment date
- Full unittest discovery is green again after compatibility and expectation cleanup

**What's missing next:**
1. Test suite coverage for the new API surface
2. Find-and-fire progress streaming
3. Gunicorn/production scheduler split

---

## Architectural Decisions

**Database:** SQLite `prospects.db` without ORM. `sqlite3.Row` for dict-like rows. Core related tables: `suppression_list`, `communication_events`, `sequence_enrollments`, `prospect_research`, `reply_drafts`.

**Status pipeline:** `new -> qualified -> contacted -> in_sequence -> replied -> booked / rejected`.

**Reply classification:** valid categories include `interested`, `booked`, `not_interested`, `opt_out`, `out_of_office`, and `auto_reply`.

**Background scheduler:** daemon thread in `web_app.py`. Polls `check_for_replies()` every `INBOX_POLL_INTERVAL` seconds and runs `run_multichannel_sequence()` once daily at `SEQUENCE_RUN_HOUR`. `GET /api/monitor-status` exposes state. `POST /api/monitor-reset` clears the paused state and consecutive inbox errors.

**Outbound email routing:** `_route_send_email()` in `web_app.py` is the single send router. SMTP supports attachments and thread headers. SendGrid currently does not.

**Compliance copy:** `outreach.py` again exposes `OPT_OUT_LINE` so both the modern generator and the legacy sequencer/compliance paths share the same opt-out language.

**Settings:** `settings.py` owns shared runtime config helpers such as calendar link, scheduler interval, scheduler hour, SendGrid flag, sender name, and LinkedIn dry-run mode.

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
| `prospects` | Core lead records |
| `outreach` | Email drafts and send log |
| `suppression_list` | Compliance exclusions |
| `communication_events` | Audit trail of touchpoints |
| `sequence_enrollments` | Multi-channel sequence state |
| `prospect_research` | Structured AI research results |
| `reply_drafts` | Classified inbound replies and review queue |
