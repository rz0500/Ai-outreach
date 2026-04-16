# Agent Instructions

Read this at the start of every session. Update after meaningful changes.

---

## Recently Completed

### Session 2 (hardening pass)
All 10 build tasks: background scheduler, booking detection, settings UI, prospect CRUD, email validation, analytics panel, bulk CSV import, SendGrid routing, LinkedIn dry-run wiring, settings.py expansion.

### Session 3 (operator UX)
- `delete_prospect()` cascades to `prospect_research`
- `_smtp_send_email` rename so all sends go through `_route_send_email()`
- `POST /api/prospects` manual Add Lead endpoint
- Add Lead inline form in dashboard
- Reply draft editable textarea before approve-and-send
- `POST /api/prospects/<id>/enrol` sequence enrolment endpoint
- Enrol button per prospect in pipeline table
- Basic Auth on `/settings` using `SETTINGS_USER` / `SETTINGS_PASSWORD`
- Scheduler crash resilience with `consecutive_errors`, `paused`, and `/api/monitor-status`

### Session 4 (scheduler control)
- `POST /api/monitor-reset` clears `paused=False`, `consecutive_errors=0`, and `last_inbox_error=None`
- Dashboard header now shows `Resume Inbox Polling` only while the monitor is paused
- Pipeline table now shows a `Sequence` column with `Day N` or `Not enrolled` based on `sequence_enrollments.enrolled_at`

### Session 5 (test cleanup)
- Restored shared `OPT_OUT_LINE` compatibility in `outreach.py` so compliance and legacy sequence paths agree again
- Updated reply workflow tests for `_route_send_email()` and thread-header behavior
- Realigned email reasoning and inbox monitor tests with the current operator-style email flow
- Full `python -m unittest discover` suite is passing again

### Session 6 (live inbox hardening)
- Fixed IMAP search query in `inbox_monitor.py` from `UNREAD` to `UNSEEN` for Gmail compatibility
- Added tolerant MIME decoding for `unknown-8bit` / unknown charsets
- Added `IMAP_MAX_MESSAGES_PER_POLL` cap (default `25`) so one large unread backlog does not stall a poll cycle

### Session 7 (SaaS layer — Antigravity)

**Task 1 — Multi-tenancy (complete)**
- `clients` table added to `initialize_database()` with house account seed (id=1)
- `client_id INTEGER NOT NULL DEFAULT 1` migrated onto: `prospects`, `outreach`, `suppression_list`, `communication_events`, `sequence_enrollments`, `prospect_research`, `reply_drafts`
- New client functions: `add_client`, `get_client`, `get_all_clients`, `get_active_clients`, `get_client_by_email`, `update_client`, `get_client_analytics`
- All query functions updated: `get_all_prospects`, `get_prospects_by_min_score`, `search_by_company`, `get_prospects_in_sequence`, `get_active_sequence_enrollments`, `get_all_outreach`, `save_outreach`, `get_sent_outreach`, `save_reply_draft`, `get_pending_reply_drafts`, `get_sent_reply_drafts`, `log_communication_event`, `add_prospect` — all default `client_id=1`
- `reporter.generate_summary()` and `export_prospects_csv()` accept `client_id=1`
- `google_maps_finder.search_local_businesses()` and `find_and_add_prospects()` accept `client_id=1`
- All existing web_app.py calls work unchanged (house account default)
- All `test_sequence_engine` tests pass; pre-existing missing-module errors are unchanged

**Task 2 — Self-booking onboarding (complete)**
- `GET /onboard` and `POST /onboard` in `web_app.py`
- `templates/onboard.html` — public form (name, niche, ICP, website, calendar link, email)
- `templates/onboard_confirm.html` — confirmation page
- On submit: creates client via `add_client()`, queues `client_id` in `_pending_client_research` set
- Scheduler picks up pending clients each cycle, runs research + enrols starter prospect

**Task 3 — Autonomous self-prospecting (complete)**
- New `.env` / `settings.py` keys: `SELF_PROSPECT_NICHE`, `SELF_PROSPECT_LOCATION`, `SELF_PROSPECT_DAILY_LIMIT`, `SELF_PROSPECT_RUN_HOUR`
- Background scheduler runs daily self-prospect cycle for house account (client_id=1)
- `find_and_add_prospects()` + research + sequence enrolment under client_id=1

**Task 4 — Client-facing dashboard (complete)**
- `client_sessions` table: `id, client_id, token, created_at, expires_at, used`
- `GET /client/login`, `POST /client/login` (sends magic link via `_route_send_email()`)
- `GET /client/verify?token=xxx` — validates, sets `session["client_id"]`, redirects
- `GET /client` — session-gated, shows only their workspace data
- `POST /client/logout`
- `templates/client_login.html` and `templates/client_dashboard.html`

**Task 5 — Weekly client reports (complete)**
- Background scheduler: Monday 8am UTC, iterates `get_active_clients()`, sends weekly summary
- `reporter.generate_summary(client_id=N)` used per client
- Subject: `"Your Antigravity pipeline — week of {date}"`

---

## Next Session - Planned Tasks

1. Test suite coverage for new SaaS endpoints (onboard, client auth, weekly reports)
2. Find-and-fire progress streaming (SSE or job ID + poll)
3. Gunicorn startup script with separate scheduler worker
4. SendGrid attachment + thread-header parity
5. `.env.example` full audit including all new SaaS keys

---

## Active Constraints

- `LINKEDIN_DRY_RUN=true` by default
- `USE_SENDGRID=true` routes through SendGrid and still lacks attachment/thread-header support
- Scheduler only starts from `python web_app.py`
- All sends in `web_app.py` must go through `_route_send_email()`
- `/settings` is Basic Auth protected
- `/client` requires `session["client_id"]` (magic-link set)
- House account is always `client_id=1`; all existing data defaults to it
