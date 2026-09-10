# Project Memory

This file is the long-term memory for the repo. Update it when significant architecture, integrations, or workflows change. Keep it aligned with `agent.md` and `CLAUDE.md`.

## Current State

**Session additions (2026-09-08 - GradReach pivot):**
- Platform repurposed from B2B cold-outbound SaaS ("OutreachEmpower") into personal graduate-job-hunting outreach tool ("GradReach") for Ritish (BSc FinTech & Data Analytics, University of Westminster)
- `clients` table gained `degree_title`, `university`, `target_roles`, `skills`, `portfolio_url`, `cv_url`, `work_eligibility` columns (additive migration); house account (id=1) reseeded with Ritish's profile
- `ai_engine.py` system prompts (email/score/website-research/reply-classify) rewritten to pitch Ritish to hiring managers
- `outreach.py` email builders hardcode Ritish's bio/skills/Harmony Booths pitch, dropped calendar-link CTA and old tension-line structure
- `pdf_generator.py` `generate_proposal()` rewritten to produce a candidate portfolio/pitch PDF; removed ~250 lines of now-unreachable pitch-deck generation code and its unused helpers/content-validation gate that were left dangling after an early `return`
- `settings.py` gained candidate getters (`get_candidate_degree/university/target_roles/skills/portfolio`)
- Templates/landing copy rebranded to GradReach; "Prospects" -> "Employers", "Booked calls" -> "Interviews/Chats"
- `test_subject_variety.py` updated for the new fallback subject format; full suite green (215 tests)
- No architecture change: multi-tenancy, scheduler, deliverability, SendGrid/Mailivery integrations, and `/ops` dashboard are untouched

**Completed modules:**
`database.py`, `scorer.py`, `importer.py`, `dashboard.py`, `outreach.py`, `reporter.py`, `mailer.py`, `sequencer.py`, `ai_engine.py`, `inbox_monitor.py`, `google_maps_finder.py`, `main.py`, `web_app.py`, `research_agent.py`, `pdf_generator.py`, `social_agent.py`, `sms_agent.py`, `sendgrid_mailer.py`, `sequence_engine.py`, `sequence_dispatcher.py`, `email_validator.py`, `deck_generator.py`, `settings.py`, `mailivery_client.py`

**Current product shape:**
- **Multi-tenant SaaS** - `clients` table + `client_id` on every data table; house account = id 1
- Public OutreachEmpower landing page at `/` for the client-facing entry point
- Public lead capture at `/onboard` - saves to `leads` table and notifies `OPERATOR_EMAIL`
- Autonomous self-prospecting - scheduler finds new leads via Google Maps daily (house account)
- Client-facing dashboard at `/client` - magic-link login, workspace-isolated view
- Client-facing prospects experience is live: `/client/prospects`, `/client/prospects/<id>`, filtered CSV export, bulk actions, and in-page reply handling from prospect detail
- Client settings now store sender identity (`sender_name`, `sender_email`) in addition to niche, ICP, location, and booking link
- Client sender verification flow is live: requested sender emails get a tokenized verification email and only verified sender addresses are used for outbound identity
- Daily reports emailed at 17:00 UTC to each active client and `OPERATOR_EMAIL`
- Full automated pipeline: Google Maps -> research -> email -> PDF -> send
- Background scheduler for inbox polling, daily sequence dispatch, self-prospecting, scheduled-send dispatch, and daily reports
- Operator dashboard moved off `/` and now lives at `/ops` with `/dashboard` as an alias
- Reply classification includes `booked`
- Settings UI at `/settings` (Basic Auth protected)
- Prospect add/edit/delete from the operator dashboard
- Analytics panel and bulk CSV import
- SendGrid routing and LinkedIn dry-run config
- Reply approval can send real email with thread headers
- SMTP-first deliverability hardening is live: suppression enforcement, failure classification, and operator-visible deliverability summary
- SendGrid webhook handling is live for bounce, dropped, unsubscribe, group_unsubscribe, and spamreport events
- SendGrid webhook signature verification is supported via `SENDGRID_WEBHOOK_PUBLIC_KEY`
- Mailivery webhook handling is live at `/webhook/mailivery`, requires `MAILIVERY_WEBHOOK_SECRET`, and clears cached campaign state on disconnect
- Mailivery ops endpoints can connect/start/pause/resume/status-check client warmup campaigns
- Find-and-Fire now has additive backend job state for stage, message, current company, current index, item-level statuses, and partial results
- Find-and-Fire operator UI now polls and renders incremental results with per-lead stage badges
- Operator dashboard now supports per-client workspace filtering on `/ops` and client-scoped analytics refreshes
- Entire platform rebranded to **OutreachEmpower** with a premium dark-mode aesthetic, dynamic gradients, glassmorphism UI, and Inter typography across all views.

**Session additions (2026-04-23):**
- Stripe fully removed: no `/checkout`, no `/webhook/stripe`, no `stripe` package
- `/onboard` is now lead capture only - saves to `leads` table, emails `OPERATOR_EMAIL`, no auto-provisioning
- `/ops` Pending Leads section + `POST /api/ops/leads/<id>/provision` for manual client creation
- `database.leads` table added; `add_lead`, `get_all_leads`, `get_lead_by_email`, `mark_lead_provisioned`, `get_pending_sends` added
- `settings.get_operator_email()` added; `OPERATOR_EMAIL` added to `.env.example`
- Weekly report replaced with daily report at 17:00 UTC; sent to both client and `OPERATOR_EMAIL`; includes today's stats + weekly totals + Mailivery health
- Timezone-aware sending: `_infer_timezone(location)` via Google Maps + `timezonefinder`; `_next_8am_utc(tz_name)` calculates UTC send time; `outreach.send_after` column stores scheduled UTC time; `_send_scheduled_outreach()` dispatches every scheduler cycle
- `sequence_dispatcher.py` updated: follow-up emails use same timezone scheduling
- `timezonefinder>=6.5.0` and `pytz>=2024.1` added to `requirements.txt`
- `prospects.prospect_timezone` column added for tz reuse on follow-ups
- 102 tests passing

**Session additions (2026-04-23 - pre-launch hardening):**
- `SECRET_KEY` placeholder/empty now raises `RuntimeError` at boot (hard crash instead of warning)
- `SETTINGS_PASSWORD` = `change-me` or empty now raises `RuntimeError` at boot
- Non-fatal startup warnings added for: weak `SETTINGS_PASSWORD`, missing `APP_BASE_URL`, unset `DB_PATH`, unset `SENDGRID_WEBHOOK_PUBLIC_KEY`
- SendGrid webhook returns 403 on invalid signature (was 400)
- LinkedIn/Instagram in `sequence_dispatcher.py`: skips entirely when `LINKEDIN_DRY_RUN=true` (no browser launch)
- SMS in `sequence_dispatcher.py`: skips when `TWILIO_ACCOUNT_SID` not configured
- `warmup_engine.get_combined_warmup_status()` derives live Mailivery health score from mailbox API response; dashboard no longer shows "Score loading..." when campaign is active
- `.env.example` updated: `DB_PATH` uncommented, critical vars annotated with crash consequence
- `Procfile` updated with memory/multi-process deployment note
- 81 tests passing (saas_routes suite)

**Session additions (2026-04-22):**
- `research_agent.py` now uses `cloudscraper` for Cloudflare bypass; scrapes /about /services pages when homepage is thin; capped at 8000 chars
- Find-and-fire pipeline now includes Step 4 Send: `_run_pipeline_for_db_prospect` calls `_route_send_email`, marks prospect `contacted`, stores full body as JSON `metadata` in `communication_events`
- Duplicate send guard: `already_sent` check in pipeline; `GROUP BY prospect_id` in emails query
- `_valid()` email address validator rejects addresses with nav/path text appended
- `GET /client/emails` - sent email log with expandable body, filter buttons, PDF download; backfills metadata from `outreach` table
- `templates/client_emails.html` - new template for sent emails tab
- Mailivery API fixed: `X-Request-ID` UUID header on every request; `get_health_score` / `get_metrics` use `GET /campaigns/{id}` not non-existent sub-endpoints; nested `{"data": {...}}` response parsed correctly
- Code pushed to GitHub at `rz0500/Ai-outreach` - ready to deploy to Render
- `.gitignore` updated to exclude pip packages accidentally installed to repo root

**Deferred / next later:**
1. **Deploy to Render** - Web Service + Background Worker + Persistent Disk; set `DB_PATH`, `APP_BASE_URL`, `OPERATOR_EMAIL`, and all env vars
2. Mailivery dashboard setup: configure webhook URL to `https://your-app.onrender.com/webhook/mailivery`
3. More `/ops` polish and deeper workspace drilldowns
---

## Architectural Decisions

**Database:** SQLite `prospects.db` without ORM. `sqlite3.Row` for dict-like rows. Core tables: `clients`, `prospects`, `outreach`, `suppression_list`, `communication_events`, `sequence_enrollments`, `prospect_research`, `reply_drafts`, `client_sessions`. The `clients` table now also stores `location`, `sender_name`, `sender_email`, and (as of the GradReach pivot) candidate-profile fields `degree_title`, `university`, `target_roles`, `skills`, `portfolio_url`, `cv_url`, `work_eligibility`. Every data table has `client_id INTEGER NOT NULL DEFAULT 1`. House account (id=1) is seeded in `initialize_database()`. All query functions accept `client_id=1` as default kwarg - no callers needed updating.

**Multi-tenancy isolation:** Enforced at the query layer. No prospect, outreach, event, draft, or enrollment is readable across `client_id` boundaries. The operator dashboard uses `client_id=1` implicitly. Client dashboard enforces `session["client_id"]`.

**Launch routing:** `/` is the public OutreachEmpower landing page, `/onboard` captures leads for manual operator provisioning, and `/ops` is the internal operator dashboard. This keeps the public product path separate from the internal workspace.

**Client session auth:** Magic-link only. `client_sessions` stores UUID login tokens with expiry and single-use semantics. `POST /client/login` creates the token and emails the link. `GET /client/verify` validates it, marks it used, and sets the Flask session.

**Status pipeline:** `new -> qualified -> contacted -> in_sequence -> replied -> booked / rejected`.

**Reply classification:** valid categories include `interested`, `booked`, `not_interested`, `opt_out`, `out_of_office`, and `auto_reply`.

**Background scheduler:** daemon thread in `web_app.py`. Per cycle: polls inbox (`INBOX_POLL_INTERVAL`), runs sequence dispatch once daily at `SEQUENCE_RUN_HOUR`, runs self-prospecting once daily at `SELF_PROSPECT_RUN_HOUR` (house account only), dispatches due scheduled outreach, and sends daily client/operator reports at 17:00 UTC. `GET /api/monitor-status` exposes state. `POST /api/monitor-reset` clears paused state.

**Outbound email routing:** `_route_send_email()` in `web_app.py` is the single send router. SMTP supports attachments and thread headers. SendGrid currently does not.

**Deliverability layer:** `deliverability.py` centralizes outbound suppression checks, SMTP-first outcome mapping (`sent`, `invalid_recipient`, `auth_or_config_error`, `transient_send_error`, `suppressed_skip`), hard-failure auto-suppression, and communication event logging. Operator dashboard context now includes a deliverability summary.

**Find-and-Fire job model:** `_find_fire_jobs` in `web_app.py` now stores richer polling state: `status`, `stage`, `progress`, `total`, `results`, `items`, `message`, `current_company`, `current_index`, and `error`. The backend worker reports explicit `finding -> research -> email -> pdf -> done/error` transitions, appends partial results as each lead completes, and the `/ops` frontend now renders incremental cards with stage badges.

**Client prospect workflow:** `/client/prospects` supports search, filtering, sorting, pagination, CSV export, and bulk actions. `/client/prospects/<id>` shows research, outreach history, reply history, and lets the client approve or dismiss pending reply drafts in place.

**Per-client sender identity:** `client.sender_name` and `client.sender_email` are persisted. Sender email changes create a verification token; `deliverability.py` only uses the custom sender address after `sender_email_verified=1`, otherwise it falls back to the system SMTP identity.

**SendGrid webhook security:** `/webhook/sendgrid` can verify signed webhook requests using `SENDGRID_WEBHOOK_PUBLIC_KEY`. If the key is unset, the route remains permissive for local/dev use.

**Mailivery webhook security:** `/webhook/mailivery` requires a shared secret (`MAILIVERY_WEBHOOK_SECRET`) sent as `X-Mailivery-Webhook-Secret` or `Authorization: Bearer ...`. Disconnect events clear `clients.mailivery_campaign_id` and cached health score.

**Mailivery warmup integration:** `mailivery_client.py` wraps the external API. Operator provisioning can auto-connect SMTP/IMAP mailboxes when `MAILIVERY_ENABLED=true` and credentials are present. The scheduler refreshes health scores every 4 hours, and the client dashboard shows Mailivery health once connected.

**Operator workspace filtering:** `/ops` accepts `client_id` and keeps the selected workspace across analytics refreshes, outreach actions, reply queue actions, and Find-and-Fire polling so operators can work inside one client workspace at a time.

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
- **SendGrid signed webhooks:** optional verification via `SENDGRID_WEBHOOK_PUBLIC_KEY`
- **Mailivery:** optional warmup integration via `MAILIVERY_ENABLED`, `MAILIVERY_API_KEY`, and `MAILIVERY_WEBHOOK_SECRET`
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
| `leads` | Inbound onboarding leads awaiting manual operator provisioning |
