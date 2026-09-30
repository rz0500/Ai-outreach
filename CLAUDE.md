# CLAUDE.md

This file gives the current working context for this repository. It should match the real codebase and stay aligned with `agent.md` and `memory.md`.

## Project Overview

`leadgen` / **GradReach** (formerly "OutreachEmpower") is a Python-based AI outreach platform. It was originally built as a multi-tenant B2B cold-outbound SaaS for local businesses, and has been repurposed (as of 2026-09-08) into a personal graduate-job-hunting outreach tool for Ritish (BSc FinTech & Data Analytics, University of Westminster). The underlying multi-tenant architecture, scheduler, deliverability stack, and Mailivery/SendGrid integrations are unchanged — only the AI prompts, email copy, PDF generator, and candidate-facing fields were repointed at pitching Ritish to hiring managers instead of pitching an agency to prospects. The house account (`client_id=1`) is now seeded with Ritish's profile instead of a generic "House Account". Current working capabilities include:

- **multi-tenant** prospect storage with `client_id` on every data table; house account = 1
- public landing page at `/`
- **lead capture** at `/onboard` (rate-limited 5/IP/hour) - saves to `leads` table, notifies operator via `OPERATOR_EMAIL`, no auto-provisioning
- **manual provisioning** in `/ops` - pending leads section with Provision button; creates workspace + starts Mailivery + sends magic link
- client-facing dashboard at `/client` with magic-link login
- client settings at `/client/settings` with sender email verification flow
- client prospects flow at `/client/prospects` with detail pages, CSV export, and bulk actions
- **client prospect status updates** - mark prospects booked or rejected from the detail page
- operator dashboard at `/ops` with workspace filtering - **Basic Auth protected**
- ops quick-action buttons: pause/resume campaign, toggle review mode, resend welcome email per workspace
- SMTP-first deliverability hardening
- SendGrid routing plus signed webhook verification support
- Mailivery warmup integration with authenticated webhook handling
- **find-and-fire scraper** - Google Maps -> research -> AI email -> PDF -> scheduled send in one button click
- **timezone-aware sending** - emails scheduled at 08:00 prospect local time via Google Maps Geocoding + timezonefinder; `_send_scheduled_outreach()` dispatches every scheduler cycle
- **sent emails tab** at `/client/emails` - expandable rows showing full email body + PDF download link
- inbox monitoring, reply classification, and **warm client notifications** on interested/booked replies
- **outreach approval queue** - per-client `outreach_review_mode` toggle; holds sequence emails for review before sending
- **daily reports at 17:00 UTC** sent to both client and `OPERATOR_EMAIL` - today's contacts, replies, warm/booked highlights, weekly totals, Mailivery health score
- one-click unsubscribe with HMAC tokens and RFC List-Unsubscribe headers
- campaign pause/resume per client
- standalone scheduler support via `python scheduler.py`
- **startup crash guards** - `SECRET_KEY` placeholder/empty and `SETTINGS_PASSWORD` `change-me`/empty raise `RuntimeError` at boot; non-fatal warnings for `APP_BASE_URL`, `DB_PATH`, and missing `SENDGRID_WEBHOOK_PUBLIC_KEY`

The system is production-ready for first clients, and is currently being run in candidate mode for Ritish's own graduate job search.

## Priority Context Files

Read these first before making major changes:

- `agent.md`
- `memory.md`

If a meaningful repo-level change is made, update all three files.

## Module Reference

### Core Data
- **`database.py`** - SQLite persistence. `DB_PATH` reads from `DB_PATH` env var (default: `prospects.db`). Set to a persistent volume path in production.
  - `add_client(name, email, niche, icp, calendar_link, location, sender_name, sender_email, degree_title, university, target_roles, skills, portfolio_url, cv_url, work_eligibility)`
  - `update_client(client_id, ..., degree_title, university, target_roles, skills, portfolio_url, cv_url, work_eligibility, campaign_paused, outreach_review_mode)`
  - `get_client`, `get_all_clients`, `get_active_clients`, `get_client_by_email`
  - `get_prospect_by_id(prospect_id)`
  - `get_pending_outreach_for_review(client_id)` - returns outreach with status `pending_review`
  - `set_sender_verify_token`, `get_client_by_sender_verify_token`, `confirm_sender_email_verified`
  - `add_lead`, `get_all_leads`, `get_lead`, `get_lead_by_email`, `mark_lead_provisioned`
  - `get_pending_sends()` - outreach rows with `send_after <= now` and `sent_at IS NULL`

### Delivery
- **`bounce_handler.py`** - detects delivery-failure notices and, on a hard bounce, suppresses the prospect, pauses the sequence and cancels queued drafts (called from `inbox_monitor`)
- **`mailer.py`** - SMTP delivery with sender override and optional `html_body` parameter
- **`sendgrid_mailer.py`** - SendGrid delivery with `html_body` support (used as `html_content`)
- **`deliverability.py`** - shared outbound suppression checks, failure classification, event logging, per-client sender identity, unsubscribe token generation/verification
- **`_route_send_email()` in `web_app.py`** - the only approved outbound send path inside the web app; accepts `html_body`

### Lead discovery

- **`contact_finder.py`** - crawls a company site (homepage + contact/about/team/careers pages), decodes obfuscated emails, filters junk/third-party addresses, and ranks careers@/jobs@ > named person > generic inbox; `find_site_intel()` also returns hiring roles found on careers pages / job boards. Used by Find-and-Fire via `web_app._extract_email_from_website`; only returns addresses that appear on the company's own site
- **`ats_jobs.py`** - reads public Greenhouse/Lever/Ashby/Workable/SmartRecruiters job-board JSON linked from a company's pages and returns analyst/analytics/graduate titles (used by `contact_finder.find_site_intel`; stored as `prospects.hiring_signal`, and companies with one are sent first)
- **`hunter_client.py`** - optional Hunter.io Domain Search lookup (`HUNTER_API_KEY`): returns the best named recruiter/HR contact (then executive/management) with title and verification status; never raises, returns `{}` without a key. Find-and-Fire tries it first, then falls back to `contact_finder`
- **`lead_discovery.py`** - daily autopilot discovery: rotates (query x city) Google Maps searches, up to 3 pages each, returns only companies new by name and website domain (state in `data/discovery_state.json`); used by `web_app._run_daily_autopilot`
- **`google_maps_finder.py`** - Google Maps discovery (first results page only, max 5 per Find-and-Fire run)

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
  - `POST /api/ops/leads/<id>/provision` - **Basic Auth required** - creates client, starts Mailivery, sends welcome email
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
- `/onboard` POST saves to `leads` table only - NO client workspace created; operator provisions manually via `/ops`
- `_send_scheduled_outreach()` runs every scheduler cycle and dispatches outreach rows where `send_after <= now`
- Timezone inference uses Google Maps Geocoding API + `timezonefinder`; falls back to UTC
- `OPERATOR_EMAIL` env var required for lead notifications and daily reports
- Daily reports fire at 17:00 UTC (not weekly); sent to both client and operator
- `get_all_prospects(db_path=db_path)` must use keyword arg - positional passes as `client_id`
- `research_prospect(id, db_path=database.DB_PATH)` must pass `db_path` as keyword arg
- Email extraction from websites uses `_valid()` check - rejects addresses with nav/path text appended
- `get_prospect_by_id()` must be used to reload a prospect after research
- SendGrid signed webhook verification is optional and controlled by `SENDGRID_WEBHOOK_PUBLIC_KEY`
- Mailivery webhook verification is required via `MAILIVERY_WEBHOOK_SECRET`
- Per-client sender identity is stored and used during outbound sends; only used when `sender_email_verified=1`
- `outreach_review_mode=1` on a client makes the sequencer hold emails as `pending_review` instead of sending
- `_route_send_email` and all DB-writing routes must pass `db_path=_db` explicitly - default arg values are frozen at import time
- `DB_PATH` env var controls database location - set to a persistent volume path in production
- `clients` table carries candidate-profile columns (`degree_title`, `university`, `target_roles`, `skills`, `portfolio_url`, `cv_url`, `work_eligibility`) used by AI prompts, `outreach.py` email templates, and `pdf_generator.py`; these are additive migrations via `ALTER TABLE ... ADD COLUMN` guarded by `try/except sqlite3.OperationalError`
- `pdf_generator.generate_proposal()` now builds a candidate portfolio/pitch PDF (`candidate_pitch_<company>.pdf`) instead of a prospect growth-breakdown deck; only `company` is a required field (no enrichment-data gate)
- Outbound copy is a coffee-chat ask for analyst roles (not a job application): no CV link/attachment on first contact, sign-off uses `CANDIDATE_LINKEDIN` from `.env`; do not reintroduce agency wording (pipeline/outbound/demand) in subjects or templates
- Hard bounces (`bounce_handler`) and SMTP-refused addresses suppress the prospect; never leave a refused address in the retry loop
- `inbox_monitor` scans INBOX **and the provider's spam folder** (Yahoo files replies to cold outreach under "Bulk") and rescues genuine prospect replies to INBOX; replies match by exact address, else by company domain when exactly one active prospect is there. `conftest.py` blocks real SMTP in all tests
- Follow-ups use the email-only `candidate_email` sequence (day 0 / 5 / 12, `SEQUENCE_NAME` env). Every scheduled email must be tagged (`outreach.sequence_name/sequence_step`) and logged with `sequence_dispatcher.record_email_step_sent` after sending, otherwise follow-ups never become due. Tests must mock `sequence_dispatcher.deliver_prospect_email` (the dispatcher has an immediate-send fallback that bypasses the daily cap)
- Outreach is sent **weekdays only** (`_next_8am_utc` skips Sat/Sun, `_send_scheduled_outreach` rests at the weekend, `SEND_WEEKENDS=true` overrides). `pytz` and `timezonefinder` must be installed (`pip install -r requirements.txt`) or send times silently fall back to UTC; startup prints a warning if they are missing
- `start_gradreach.bat` runs the app + scheduler with auto-restart; the send ramp is `warmup_engine._RAMP` (5/10/15/20 per day from `WARMUP_START_DATE`), and the house account's `daily_send_limit` must be 0 for the ramp to apply
- Tests must never launch external apps or call paid/live APIs (the deck test used to open PowerPoint through `deck_generator._convert_deck_to_pdf_windows` and call Claude); stub `deck_generator._convert_deck_to_pdf` and clear `ANTHROPIC_API_KEY` as `test_deck_generator.py` does

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
| GradReach candidate-outreach pivot (prompts, PDF, DB fields, UI copy) | Done |

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

## Live State (as of 2026-09-29)

**Status: built and tested, NOT started.** Ritish asked to get everything sorted before launching; nothing has been sent by the autopilot and `start_gradreach.bat` has never been run. The only real emails sent since the pivot were manual test emails and the 2026-09-30 rehearsal (two emails to Ritish's own Gmail).

- **Product**: GradReach is a single-user tool that emails hiring managers and analytics leads asking for a coffee chat (analyst-type roles), not a job application. Ritish works from `/ops`; the `/client` flow and public landing page are unused but left in place.
- **Sender**: personal Yahoo mailbox over plain SMTP (`smtp.mail.yahoo.com:465`, IMAP `imap.mail.yahoo.com:993`, app-password auth), `USE_SENDGRID=false`. House account (`client_id=1`) `sender_email` is that address, `sender_email_verified=1` (Yahoo rejects a From that differs from the login). SendGrid is unused (account not yet cancelled). Credentials live only in the gitignored `.env`; the repo is public.
- **Autopilot loop** (scheduler thread in `web_app.py`): `lead_discovery` (rotating Maps searches, only new companies) -> `_run_pipeline_for_db_prospect(require_email=True, make_pdf=False)` (contact via `hunter_client` if `HUNTER_API_KEY` set, else `contact_finder` website crawl; AI email with quality-gate retries) -> send scheduled 08:00 recipient-local -> `_send_scheduled_outreach` within the daily cap -> `record_email_step_sent` -> `candidate_email` follow-ups at day 5 and 12 -> replies polled over IMAP and alerted to Ritish's real inbox (`clients.email` / `OPERATOR_EMAIL`) plus a 17:00 UTC daily report.
- **Send ramp**: `warmup_engine._RAMP` 5/day (days 1-7), 10, 15, then 20/day cap, counted from `WARMUP_START_DATE` (calendar days; weekdays-only sending); house `daily_send_limit` must stay 0 for the ramp to apply.
- **Copy**: coffee-chat ask with one CV proof point per email (5% -> 20% conversion, 80% less manual work, 2% -> 12% reply rate), never mentions the current employer, no CV link or attachment (the Claude artifact CV page is private), sign-off shows LinkedIn from `CANDIDATE_LINKEDIN` in `.env`. Greeting is "Hi there," for placeholder names. Subjects are plain ("<Co> analytics team", "Coffee chat about <Co>?"). No unsubscribe footer/header or "reply no thanks" line (personal 1:1 tone); suppression still triggers on `opt_out` replies.
- **Mailivery**: subscription expired, API key returns 401; `MAILIVERY_ENABLED=false`. Free plan (10 warmups/day) or skipping it are the options.
- **Data**: `data/prospects.db` locally (needs a persistent volume if ever hosted). 48 pre-pivot agency drafts were marked `rejected_draft`; old agency-era prospects remain in the DB (deduped, never re-emailed). One qualified real lead (London Data Consulting) has no contact email.
- **Tests**: 256 passing. Development lesson: tests must mock `sequence_dispatcher.deliver_prospect_email`; one real email ("Re: Acme Data" to a fictional address) was sent by an early lifecycle test.
- Infrastructure unchanged from the SaaS era: multi-tenant DB, deliverability layer, ops dashboard, SendGrid/Mailivery integrations (dormant), Stripe fully removed, `cloudscraper` research crawler, daily reports at 17:00 UTC.

## Important Rules (additions)

- `SECRET_KEY` placeholder or empty -> `RuntimeError` at boot (crashes app)
- `SETTINGS_PASSWORD` = `change-me` or empty -> `RuntimeError` at boot (crashes app)
- LinkedIn/Instagram in `sequence_dispatcher.py`: skipped entirely (no browser) when `LINKEDIN_DRY_RUN=true`
- SMS in `sequence_dispatcher.py`: skipped unless `TWILIO_ACCOUNT_SID` is set
- SendGrid webhook returns 403 (not 400) on invalid/missing signature
- `warmup_engine.get_combined_warmup_status()` derives live health score from mailbox API call - never shows "Score loading..." when campaign is active

## Planned Next Tasks (pre-launch checklist)

1. ~~Safe end-to-end rehearsal~~ **Done 2026-09-30** on a copy of the DB with Ritish's own inbox as the only recipient: send, step logging, follow-up, reply detection and alert all verified.
2. **Ritish approves the email wording** (sample coffee-chat email + follow-ups) and the **target list** (`lead_discovery.QUERIES` x `CITIES`, currently 12 company types x 17 UK/IE/NL cities).
3. **Decide where it runs**: PC only sends while on and awake (`start_gradreach.bat`); a cloud host (~GBP 7/month) is the only truly hands-off option. Add a Windows "at log on" task if staying on the PC.
4. **Decide oversight for the first days**: watch the `/ops` queue daily, or add a review mode for the first batch.
5. **Yahoo mailbox warm-up**: check the account's age; if new, use it normally (real mail to and from friends) for about a week before launch.
6. **Reset `WARMUP_START_DATE` in `.env` to the real launch day** (it currently holds the day it was configured, 2026-09-29) so the 5/10/15/20 per day ramp starts at launch.
7. Optional: free **Adzuna + Reed** API keys -> build the job-board lead source (companies with live analyst openings); **Hunter** API key -> named recruiters (`hunter_client.py` is built but untested against the live API); Mailivery is expired (skip or use its free plan).
8. Housekeeping: cancel SendGrid once a test send is confirmed; check whether the old `info@outreachempower.com` mailbox is a paid Google Workspace plan; revoke the unused `STRIPE_SECRET_KEY` in `.env`.
