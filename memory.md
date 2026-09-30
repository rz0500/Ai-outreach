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

**Session additions (2026-09-10 - CV link + settings gap fix):**
- Ritish's real CV (previously only a PDF file) published as a hosted Artifact page so the platform has a URL to link: `https://claude.ai/code/artifact/8f6f7dd6-3254-4298-97c6-07837a94eb37`
- `settings.get_candidate_cv_url()` added (`CANDIDATE_CV_URL` env var, defaults to that link); `outreach.py` email sign-offs and `pdf_generator.py`'s CTA line now point to it instead of `harmonybooths.com` (Harmony Booths stays in the body copy as commercial-experience proof, just isn't the clickable link anymore)
- `ai_engine._EMAIL_SYSTEM_PROMPT` sign-off updated via a `{{CV_LINK}}` placeholder + `.replace()` (not `.format()` — the prompt's trailing JSON example has literal braces)
- Fixed a real UI gap: `cv_url` was already read/written by `database.py`/`web_app.py` but had no input field in `templates/client_settings.html` — added one
- Backfilled the live `data/prospects.db` client_id=1 row by hand — the code-level reseed only fires via `INSERT OR IGNORE` on brand-new databases, so the existing DB still had `name='House Account'` and stale `niche='solar panel'` from before the pivot until updated with `database.update_client(1, ...)`
- Removed leftover dead code: unused `get_calendar_link` import in `ai_engine.py`, unused `outreach._calendar_link()` helper
- Fixed awkward AI-fallback phrasing in `outreach._build_data_driven_email` ("building in the {headline} space" -> "positioned around {headline}") since `company_positioning` can be a full sentence, not a short phrase

**Session additions (2026-09-10 - end-to-end Find-and-Fire smoke test):**
- Ran the real pipeline (`POST /api/find-and-fire`) against two real companies with the server started `--no-scheduler`, so nothing could auto-send (Find-and-Fire only ever schedules `send_after`; dispatch is a separate scheduler-cycle step) — found two real bugs from real output
- **Niche-bleed bug**: `web_app._run_pipeline_for_db_prospect` fell back to injecting `client.niche` onto a prospect when research failed. In the old B2B model that was a reasonable proxy (client's own niche ≈ what kind of prospect they target); in candidate mode `client.niche` describes Ritish's own campaign, not any target's industry, so it was leaking into email copy ("positioned around Graduate Analyst & Operations Outreach"). Fixed by dropping that fallback field (kept the location-into-notes fallback) — thin-data prospects now correctly use the weak-data template instead of a wrong "data-driven" one
- **Quality-gate false-rejection bug**: `email_validator.validate_email`'s company-name check required the *exact raw* Google-Maps business name (e.g. `"FintechOS HQ - London, UK"`) verbatim in the body. Claude naturally writes the clean brand name, so this check was failing on essentially every AI-generated email and silently falling back to the generic template — the "hyper-personalized AI email" feature was effectively never firing. Added `email_validator._company_core_name()` to strip parenthetical abbreviations / location suffixes / corporate qualifiers before the check; verified the AI draft then passes (97/100) instead of being discarded
- `pdf_generator`'s CTA box can overflow to a near-empty second page on long contact lines — noted, not fixed (cosmetic/low priority)
- 215/215 tests still passing after both fixes; kept the real "London Data Consulting (LDC)" lead discovered during the test in the live DB (user's call)

**Session additions (2026-09-11 - de-automate outbound copy):**
- Removed the auto-appended `To unsubscribe: <url>` footer and `list_unsubscribe` header from `deliverability.deliver_prospect_email()` — that header makes Gmail/Outlook show a native "Unsubscribe" chip, an instant giveaway that mail came from a bulk-send tool. Suppression still works via `inbox_monitor.py`'s `opt_out` reply classification, just isn't advertised in every email anymore. Dropped `OPT_OUT_LINE` boilerplate from `outreach.py`'s templates for the same reason.
- Found `sequence_engine.py`'s follow-up templates were never updated during the GradReach pivot — still pitched the old B2B agency copy ("we help service businesses build predictable outbound pipelines"). Rewrote all of them (email follow-ups 1-3, breakup, LinkedIn connect/DM, Instagram DM, SMS follow-up) in Ritish's voice with the CV link. `sequencer.py` has similar old copy but is dead code (not called anywhere live) so left as-is.
- `USE_SENDGRID=true` is a separate de-automation issue: SendGrid sends can show "via sendgridmail.com" in Gmail/Outlook. Recommended switching to a real personal mailbox (Zoho free or Microsoft Exchange Online Plan 1 ~£3/mo on `harmonybooths.com`) and setting `USE_SENDGRID=false` — SMTP path already fully supported, IMAP-based reply monitoring unaffected by sender provider.
- `test_compliance.py` updated: asserts absence of automated opt-out language instead of its presence
- 215/215 tests passing

**Session additions (2026-09-29 - Yahoo mailbox switch):**
- `.env` now sends via personal Yahoo SMTP (`smtp.mail.yahoo.com:465`) with `USE_SENDGRID=false`; IMAP reply monitoring uses `imap.mail.yahoo.com:993`; both use a Yahoo app password. House-account `sender_email` updated and verified in the DB. Test send via the real `route_outbound_email` path succeeded.
- Mailivery API key returns 401 on all calls, so warmup could not be moved to the new mailbox; needs a key/plan fix in the Mailivery dashboard.

**Session additions (2026-09-29 - contact finder):**
- `contact_finder.py` crawls contact/about/team/careers pages, decodes obfuscated emails, filters junk, and ranks careers@ > named person > generic > last resort. Replaces the old homepage-only scrape; Find-and-Fire also renames "Owner/Manager" prospects to a person found in the address. Yield on a 48-site London sample: 24 emails (50%) vs 16 (34%) before; realistic Maps-only yield is still ~10-20 relevant leads/day.
- Sending goal is 50-100/day, which is unrealistic from a fresh free Yahoo account; plan is a gradual ramp and a custom-domain mailbox before passing ~20-30/day. Not yet built: multi-page Maps, more sources, per-company dedupe by domain.

**Session additions (2026-09-29 - Hunter recruiter lookup):**
- `hunter_client.py` finds a named recruiter/HR/executive contact per company domain via Hunter.io (needs `HUNTER_API_KEY`; free 50 credits/month, Starter $34 = 2,000). Pipeline tries Hunter, then `contact_finder`. Built and unit-tested with mocked HTTP only - not yet run against the live API because no key exists yet.

**Session additions (2026-09-29 - coffee-chat framing):**
- Outreach is now framed as a coffee-chat ask for analyst-type roles (not a job application): AI prompt, fallback templates, subjects and follow-up sequence all rewritten; one CV proof point per email; no CV link or attachment (the Claude artifact CV page is private so recipients probably can't open it); sign-off shows LinkedIn from `CANDIDATE_LINKEDIN` (.env only, repo is public).
- Pitch PDF still generated but no longer attached (`pdf_path` not stored on outreach rows).

**Session additions (2026-09-29 - hands-free autopilot):**
- Daily loop is now: `lead_discovery` (rotating searches, only new companies) -> pipeline (contact via Hunter/site crawl, AI coffee-chat email, `require_email=True`) -> scheduled send at 08:00 local within the ramp cap (5/10/15/20 per day) -> replies polled over IMAP and alerted to Ritish's real inbox -> email-only follow-ups at day 5 and 12 (`candidate_email` sequence). Follow-ups previously never worked (sequence stalled on LinkedIn step, steps never logged as sent, contacted prospects dropped out of the sequence); fixed and covered by `test_followup_lifecycle.py`.
- Run with `start_gradreach.bat` (PC must stay on). Mailivery is off (expired). Nothing is attached to emails; sign-off has LinkedIn only.
- Test-safety lesson: never let a test reach the dispatcher's immediate-send fallback (one real email went to sam@acmedata.com during development); mock `sequence_dispatcher.deliver_prospect_email`.

**Session additions (2026-09-30 - rehearsal):**
- End-to-end rehearsal on a DB copy with only Ritish's Gmail as recipient passed: send -> step logging -> follow-up -> reply -> classification -> alert -> follow-up 2 skipped. It exposed that Yahoo files replies in its spam folder ("Bulk"); `inbox_monitor` now scans the junk folder and rescues genuine prospect replies to INBOX, and matches colleague replies by company domain. `conftest.py` blocks real SMTP in tests (the `/onboard` tests had been emailing the operator on every run).
- Bounces are now handled (`bounce_handler.py`: hard bounce -> suppress, pause sequence, cancel queue; SMTP-refused addresses are no longer retried every cycle). Still open: the remaining pre-launch checklist items.

**Session additions (2026-09-30 - lead supply):**
- Measured real lead yield (40 new companies from 3 rotating Maps searches): 50% have a usable contact (careers 6 / personal 3 / generic 11 of 20), only ~10% show any hiring signal, 2% a named analyst role. Found and fixed a critical bug where Maps page-2 fetches failed with INVALID_REQUEST (token not ready) and discarded the whole search, which would have made every autopilot discovery return 0 leads. Added `ats_jobs.py` (public ATS job-board JSON) and hiring-signal-first send ordering. Real "who is hiring analysts" supply needs Adzuna/Reed keys (not yet registered).

**Session additions (2026-09-30 - weekdays only):**
- Sending is weekdays-only (next 08:00 local Mon-Fri; send loop idle at weekends; `SEND_WEEKENDS` override). Found that `pytz`/`timezonefinder` were not installed here, so all send times had silently been 08:00 UTC; installed them and added a startup warning. Planning figure for 1,000 total messages from the one Yahoo inbox: ~2 months (about 9 weeks with a health-based cap, ~11-12 weeks flat 20/day). Pacing jitter and a health-based cap are offered but not built.

**Session additions (2026-09-30 - supply test):**
- Real supply test: 16 rotation searches gave 250 new companies (~15.6/search, no saturation), 51% with a usable contact, ~8% with a hiring signal; estimated pool ~3,000 companies (~1,600 contactable) with the current 12 queries x 17 cities. Enough for 1,000 total messages (~350 companies) easily; 1,000 companies would use ~60% of the pool. Sending capacity, not leads, is the limit.

**Session additions (2026-09-30 - Adzuna):**
- Adzuna key added (in `.env` only). `job_leads.py` finds companies advertising analyst roles (UK: ~1,100 entry-level analyst openings a month), resolves their websites via Maps, and feeds the autopilot ahead of plain Maps discovery; early-career openings are emailed first and named once in the email; senior roles are not named. Live test: 30 companies in 24s, 74% website match, 43% usable contact.

**Completed modules:**
(added since the pivot: `contact_finder.py`, `hunter_client.py`, `lead_discovery.py`, `ats_jobs.py`, `job_leads.py`, `bounce_handler.py`, `start_gradreach.bat`)
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

**Deferred / next later (pre-launch checklist):**
1. **Safe end-to-end rehearsal** on a copy of the DB with every recipient set to Ritish's own inbox: real scheduled send -> step logged -> day-5 follow-up scheduled -> Ritish replies -> `inbox_monitor` classifies it -> alert email arrives. Not yet done; the scheduler send loop has never run for real.
2. **Ritish approves the email wording** (sample coffee-chat email + follow-ups) and the **target list** (`lead_discovery.QUERIES` x `CITIES`, currently 12 company types x 17 UK/IE/NL cities).
3. **Decide where it runs**: PC only sends while on and awake (`start_gradreach.bat`); a cloud host (~GBP 7/month) is the only truly hands-off option. Add a Windows "at log on" task if staying on the PC.
4. **Decide oversight for the first days**: watch the `/ops` queue daily, or add a review mode for the first batch.
5. **Yahoo mailbox warm-up**: check the account's age; if new, use it normally (real mail to and from friends) for about a week before launch.
6. **Reset `WARMUP_START_DATE` in `.env` to the real launch day** (it currently holds the day it was configured, 2026-09-29) so the 5/10/15/20 per day ramp starts at launch.
7. Adzuna job-board lead source **built 2026-09-30** (Reed key optional, not needed); **Hunter** API key -> named recruiters (`hunter_client.py` is built but untested against the live API); Mailivery is expired (skip or use its free plan).
8. Housekeeping: cancel SendGrid once a test send is confirmed; check whether the old `info@outreachempower.com` mailbox is a paid Google Workspace plan; revoke the unused `STRIPE_SECRET_KEY` in `.env`.

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
| `outreach` | Email drafts and send log (partitioned by `client_id`); `send_after` schedules the send, `sequence_name`/`sequence_step` tag which follow-up step a row is |
| `suppression_list` | Compliance exclusions (partitioned by `client_id`) |
| `communication_events` | Audit trail of touchpoints (partitioned by `client_id`) |
| `sequence_enrollments` | Multi-channel sequence state (partitioned by `client_id`) |
| `prospect_research` | Structured AI research results (partitioned by `client_id`) |
| `reply_drafts` | Classified inbound replies and review queue (partitioned by `client_id`) |
| `client_sessions` | Magic-link auth tokens for client dashboard login |
| `leads` | Inbound onboarding leads awaiting manual operator provisioning |
