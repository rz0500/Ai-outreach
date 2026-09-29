# Agent Instructions

Read this at the start of every session. Update after meaningful changes.

---

## Recently Completed

### GradReach pivot (2026-09-08)
The platform was repurposed from a B2B cold-outbound SaaS ("OutreachEmpower") into a personal graduate-job-hunting outreach tool ("GradReach") for Ritish (BSc FinTech & Data Analytics, University of Westminster). Scope of the change:
- `ai_engine.py` prompts (email writer, scorer, website researcher, reply classifier) rewritten around Ritish's candidate profile and target roles (Graduate Data/Business/RevOps/Commercial/FinTech Analyst) instead of B2B sales copy
- `database.py` `clients` table gained candidate columns: `degree_title`, `university`, `target_roles`, `skills`, `portfolio_url`, `cv_url`, `work_eligibility` (additive `ALTER TABLE`, guarded); house account reseeded as Ritish's profile
- `outreach.py` fallback/data-driven email builders hardcode Ritish's bio, skills, and Harmony Booths pitch; dropped the old market-truth/tension/mechanism structure and calendar-link CTA
- `pdf_generator.py` `generate_proposal()` now builds a candidate portfolio/pitch PDF (`candidate_pitch_<company>.pdf`) instead of a prospect growth-breakdown deck; the old 5-page pitch-deck content generators, banned-phrase/tension validation gate, and unused layout helpers (`_metrics_row`, `_comp_cards`, `_numbered_step`, `_step_colors`, `_cta_button`) were removed as dead code (the function had an early `return` that made ~130 lines unreachable)
- `settings.py` gained `get_candidate_degree/university/target_roles/skills/portfolio()` getters
- `web_app.py` `/client/settings` POST reads/saves the new candidate fields
- Templates rebranded: "OutreachEmpower" -> "GradReach", "Prospects" -> "Employers", "Booked calls" -> "Interviews/Chats", landing page pitch rewritten for job search
- Tests updated to match (calendar-link assertions dropped, SendGrid webhook 403 expectation, LinkedIn dry-run patch); full suite passing (215 tests)
- The underlying multi-tenant DB, scheduler, deliverability stack, SendGrid/Mailivery integrations, and ops dashboard are all unchanged — this was a content/prompt/schema-field pivot, not an architecture change

### CV link + settings gap fix (2026-09-10)
- Published Ritish's actual CV as a hosted HTML page (Artifact) since the platform needs a URL, not a file, for email/PDF links: `https://claude.ai/code/artifact/8f6f7dd6-3254-4298-97c6-07837a94eb37`
- Added `settings.get_candidate_cv_url()` (env var `CANDIDATE_CV_URL`, defaults to that link) and pointed `outreach.py`'s two hardcoded email sign-offs and `pdf_generator.py`'s CTA contact line at it, replacing the `harmonybooths.com` link that was there before; Harmony Booths itself is still cited in the body as commercial-experience proof
- Rewrote `ai_engine._EMAIL_SYSTEM_PROMPT`'s sign-off line via a `{{CV_LINK}}` placeholder + `.replace()` post-processing (not `.format()`, since the prompt's trailing JSON example contains literal braces that would need escaping)
- Removed dead code found along the way: unused `get_calendar_link` import in `ai_engine.py`, and `outreach._calendar_link()` (defined, never called, left over from dropping the calendar-link CTA)
- Found and fixed a real gap: `database.py`/`web_app.py` already read/wrote a `cv_url` client field, but `templates/client_settings.html` never had an input for it — added a "CV / Resume link" field
- Backfilled the **live** `data/prospects.db` house-account row (id=1): the code-level reseed only applies to brand-new databases (`INSERT OR IGNORE`), so the existing DB still had `name='House Account'`, `niche='solar panel'`, and all candidate columns `NULL` until manually updated via `database.update_client(1, ...)`
- Fixed an awkward phrasing bug in `outreach._build_data_driven_email`: `company_positioning` could be a full website headline sentence, producing "building in the {headline} space"; reworded to "positioned around {headline}"

### End-to-end Find-and-Fire smoke test (2026-09-10)
Ran the actual pipeline against two real target companies via `POST /api/find-and-fire` (server started with `--no-scheduler` so nothing could auto-send during testing — the pipeline only ever *schedules* a send via `send_after`, actual dispatch is a separate scheduler-cycle step). Found and fixed two real bugs surfaced by real output:
- **`web_app._run_pipeline_for_db_prospect` niche-bleed bug**: when research failed, the code injected `client.niche` (the *client's own* niche field) onto the prospect as a stand-in for the target company's industry. That made sense in the old B2B-agency model (client's niche ≈ the kind of prospect they specialize in) but is wrong in candidate mode, where `client.niche` describes Ritish's own campaign ("Graduate Analyst & Operations Outreach") — it was leaking into email copy as "Noticed how [Company] is positioned around Graduate Analyst & Operations Outreach." Fixed by dropping the niche injection (location injection into notes is kept); thin-data prospects now correctly fall through to the safer weak-data email template instead of a fabricated, wrong "data-driven" one.
- **`email_validator.validate_email` company-name quality-gate bug**: the check required the prospect's *exact, raw* Google-Maps-scraped business name (e.g. `"London Data Consulting (LDC)"`, `"FintechOS HQ - London, UK"`) to appear verbatim in the email body. Claude naturally writes the clean brand name ("London Data Consulting"), so the check failed on effectively every AI-generated email, silently discarding it and falling back to the generic deterministic template — meaning the "hyper-personalized AI email" feature was not actually being used in practice. Added `_company_core_name()` to strip parenthetical abbreviations, trailing " - location" suffixes, and generic corporate qualifiers (hq/ltd/llc/inc/group/plc/co) before the substring check. Re-tested against the same real company after the fix: the AI draft now passes at 97/100 instead of being rejected.
- Also confirmed: `pdf_generator`'s CTA box can overflow onto its own near-empty second page when the contact line is long (cosmetic, not fixed — low priority)
- Full suite still 215/215 after both fixes; live DB kept the real "London Data Consulting (LDC)" lead discovered during testing (user's call, not a throwaway)

### Contact finder (2026-09-29)
- New `contact_finder.py` replaces the old homepage-only email scrape (`web_app._extract_email_from_website` now delegates to it). It crawls the homepage plus contact/about/team/careers pages (links found on the homepage and fixed paths, max 8 extra pages), decodes Cloudflare-protected and "name [at] domain [dot] com" addresses, drops junk (press@, marketing@, editor@, noreply@, legal/privacy, billing) and third-party/file-name lookalikes, and ranks: careers/jobs/recruitment > named person > generic inbox (hello/info/contact) > sales/support and freemail as last resort. Only addresses that appear on the company's own site are returned; nothing is guessed.
- Find-and-Fire pipeline (`_run_pipeline_for_db_prospect`) now uses `find_best_contact` and, when the address is a named person (e.g. `first.last@`), renames the prospect from "Owner/Manager" to that name so the greeting is personal.
- Measured on 48 London fintech/data/SaaS company sites from Google Maps: emails found on 24 (50%) vs 16 of 47 (34%) with the old scraper; 6 were careers/jobs inboxes (0 before). Realistic yield from Maps alone is still ~10-20 relevant leads/day, so 50-100/day needs more sources (multi-page Maps, more query/city combos, company-registry seeds) - not built yet.
- Ritish does not want the Tsenta connector; don't suggest it.
- 16 new tests in `test_contact_finder.py`.

### Yahoo sending mailbox switch (2026-09-29)
- Moved outbound off SendGrid and off the `info@outreachempower.com` (Gmail/Workspace) mailbox onto a personal Yahoo mailbox using an app password: `.env` now has `SMTP_HOST=smtp.mail.yahoo.com`, `SMTP_PORT=465`, `IMAP_HOST=imap.mail.yahoo.com`, `IMAP_PORT=993`, `USE_SENDGRID=false` (old lines kept commented out in `.env` for rollback). Free Outlook.com was ruled out (needs OAuth2 for SMTP) and the secondary Gmail was blocked (no App Passwords option on the account).
- House account `sender_email` set to the Yahoo address and marked verified; SMTP and IMAP logins both verified, and a test email sent through `deliverability.route_outbound_email` (provider=smtp) delivered.
- **Mailivery is broken**: every API call (including reads on old campaign 137474) returns 401 Unauthenticated, so the key is invalid/expired. A new campaign for the Yahoo mailbox could not be created. Ritish needs to check the Mailivery dashboard (regenerate key or reactivate the plan), or decide to skip warmup and send at very low volume.
- Not done: SendGrid account itself not yet cancelled (Ritish's call after confirming the test email arrived).

### De-automate outbound copy (2026-09-11)
Ritish wants outreach to read as a genuine 1:1 email, not something a hiring manager can tell was sent by a mass-mail tool. Fixed the concrete things that give it away:
- `deliverability.deliver_prospect_email()` no longer appends a `\n\n---\nTo unsubscribe: <url>` footer or passes `list_unsubscribe` to the sender — that header makes Gmail/Outlook show a native "Unsubscribe" chip next to the sender name, an instant mass-mailer tell. Suppression enforcement is unchanged and still triggers independently when a reply is classified `opt_out` (`inbox_monitor.py`), so recipients who ask to stop are still protected — it's just not advertised in every email.
- Dropped the `OPT_OUT_LINE` boilerplate ("If this isn't relevant, reply no thanks and I'll stop.") from `outreach.py`'s two email templates — same reasoning, reads as automated compliance copy rather than something a person writes.
- **Bigger find while investigating**: `sequence_engine.py`'s follow-up templates (`email_followup_1/2/3`, `email_breakup`, `linkedin_connect`, `linkedin_dm`, `instagram_dm`, `sms_followup`) were never touched during the GradReach pivot — they still pitched "we help service businesses build predictable outbound pipelines," i.e. the old agency copy, which would have gone out days after a correct, personalized initial email to the same hiring manager. Rewrote all of them in Ritish's voice/CV-link sign-off, consistent with `outreach.py`.
- `test_compliance.py`'s `test_generate_email_includes_opt_out_line` (asserted the boilerplate line's presence) replaced with `test_generate_email_has_no_automated_optout_language` (asserts its absence) — the old assertion protected a compliance behavior we deliberately removed.
- `sequencer.py` still has its own old-copy templates + opt-out line, but it's dead code (not called from `web_app.py` or `scheduler.py` — superseded by `sequence_dispatcher.py`/`sequence_engine.py`), so left untouched.
- Separately: `USE_SENDGRID=true` in `.env` is itself a de-automation issue independent of any of the above — Gmail/Outlook can show "via sendgridmail.com" next to the sender name when the DKIM-signing domain doesn't match the From address. Recommended Ritish move off SendGrid entirely onto a real personal mailbox (Zoho free or Microsoft Exchange Online Plan 1, ~£3/mo, on `harmonybooths.com`) and set `USE_SENDGRID=false`, since SMTP-based sending is already fully supported (`mailer.py`) and reply monitoring is IMAP-based regardless of which provider sent the original message.
- 215/215 tests still passing after all of the above

### Foundation through current SaaS state
Full pipeline is now in place across the repo: multi-tenant DB, background scheduler, operator dashboard, email validation, analytics, CSV import, SendGrid routing, reply classification, deliverability hardening, Find-and-Fire polling/UI, client prospects flow, SendGrid webhook security, Mailivery warmup integration, and per-client sender identity.

### Rebranding & UI Overhaul
The application has been successfully rebranded to **OutreachEmpower**. The UI has been heavily refined with a deeper dark mode, glassmorphism, dynamic gradients, micro-animations, and updated typography (Inter font) across all templates.

### Current shipped client/product layer

**Public/product flow:**
- `/` = landing page
- `/onboard` = public lead capture form
- `/client/login` -> `/client/verify` -> `/client` = magic-link client dashboard
- `/ops` = internal operator dashboard

**Client-facing features:**
- `GET/POST /client/settings` - clients can update niche, ICP, location, booking link, sender name, and sender email
- `GET /client/prospects` - client-scoped prospects list with search/filter/sort/pagination
- `GET /client/prospects/export` - filtered CSV export
- `GET /client/prospects/<id>` - client prospect detail page
- `POST /client/prospects/bulk-action` - bulk enrol and bulk status updates for client-owned prospects
- `POST /client/reply-drafts/<id>/action` - client-gated approve/dismiss
- `GET /client/emails` - sent email log with expand/body/PDF download
- prospect detail page supports in-place reply draft approve/dismiss for pending drafts

**Operator/internal features:**
- `/ops` accepts `client_id` and scopes dashboard data to a selected workspace
- operator AJAX refreshes keep the selected `client_id`
- operator actions respect selected workspace across outreach queue, reply queue, send-outreach, enrol, patch, and delete actions
- Find-and-Fire `/ops` UI now uses enriched polling state and renders incremental result cards with stage badges
- `/ops` includes pending-lead review and manual provisioning via `POST /api/ops/leads/<id>/provision`

**Deliverability / email features:**
- `deliverability.py` is the shared outbound decision layer
- SMTP-first outcome mapping is live
- SendGrid bounce/drop/unsubscribe webhook handling is live at `/webhook/sendgrid`
- SendGrid signed event verification is supported via `SENDGRID_WEBHOOK_PUBLIC_KEY`
- Mailivery warmup webhooks are live at `/webhook/mailivery` and require `MAILIVERY_WEBHOOK_SECRET`
- per-client sender identity is persisted, verified through the sender-email flow, and used during outbound sends only after verification

**Research quality improvements:**
- `research_agent.py` now uses `cloudscraper` (Cloudflare bypass) instead of raw `requests`
- Homepage text < 200 chars triggers fallback scraping of /about, /about-us, /services, /what-we-do, /team
- Capped at 8000 chars total to keep AI prompt within limits
- Pipeline falls back to niche/location context when research fails (no crash on scrape errors)

**Find-and-Fire pipeline (full end-to-end):**
- Stage 1: Google Maps scraping
- Stage 2: Website research (cloudscraper)
- Stage 3: AI email generation
- Stage 4: PDF proposal generation
- **Stage 5: Schedule send** - email is scheduled at 08:00 prospect local time via `_infer_timezone()` + `_next_8am_utc()`; `send_after` stored on outreach record
- `_send_scheduled_outreach()` runs every scheduler cycle; dispatches due sends, marks prospect `contacted`, logs to `communication_events`
- Duplicate send prevention: `already_sent` check skips prospects with `status='contacted'`
- Email address validation: `_valid()` rejects addresses with nav/path text appended

**Timezone-aware sending:**
- `_infer_timezone(location)` -> Google Maps Geocoding API + `timezonefinder` -> IANA tz name (e.g. `Europe/London`)
- `_next_8am_utc(tz_name)` -> next 08:00 local as UTC datetime
- Timezone stored on `prospects.prospect_timezone` after first lookup (reused for follow-ups)
- Falls back to UTC if lookup fails or `GOOGLE_MAPS_API_KEY` missing
- Same scheduling applied in `sequence_dispatcher.py` for follow-up emails

**Emails tab:**
- `GET /client/emails` shows all sent emails per workspace grouped by prospect (GROUP BY prospect_id)
- Expandable rows show subject + full body (from `metadata` JSON)
- PDF download link when `pdf_url` is present
- Filter buttons: All / Sent / Opened / Clicked / Bounced
- Backfills metadata from `outreach` table for emails sent before metadata was stored

---

**Lead capture + provisioning flow:**
- `/onboard` POST saves to `leads` table, emails `OPERATOR_EMAIL`, redirects to confirm - NO client creation
- `/ops` shows "Pending Leads" section; Provision button calls `POST /api/ops/leads/<id>/provision`
- Provision endpoint: creates client, calls `_mailivery_auto_connect()`, sends `_send_onboard_welcome()`
- `database.leads` table: `id, name, email, niche, location, booking_link, provisioned, provisioned_at, created_at`

**Daily reports (replaced weekly):**
- Fire at 17:00 UTC every day (not Monday-only)
- Sent to each active client AND `OPERATOR_EMAIL`
- Content: today's contacts, today's replies by classification, warm/booked highlights, weekly totals, Mailivery health score

**Session additions (2026-04-23 - pre-launch hardening):**
- `SECRET_KEY` placeholder/empty -> `RuntimeError` at boot (hard crash, not warning)
- `SETTINGS_PASSWORD` = `change-me` or empty -> `RuntimeError` at boot
- Startup non-fatal warnings: weak `SETTINGS_PASSWORD`, missing `APP_BASE_URL`, unset `DB_PATH`, unset `SENDGRID_WEBHOOK_PUBLIC_KEY`
- SendGrid webhook handler returns 403 (was 400) on failed signature verification
- `sequence_dispatcher.py` LinkedIn/Instagram: skips entirely when `LINKEDIN_DRY_RUN=true` (no browser launch)
- `sequence_dispatcher.py` SMS: skips when `TWILIO_ACCOUNT_SID` not set; `os` import added
- `warmup_engine.get_combined_warmup_status()` derives live Mailivery health score from mailbox API response - no longer waits for 4-hour batch job
- `.env.example`: `DB_PATH` uncommented with Render note, `SECRET_KEY`/`SETTINGS_PASSWORD` annotated with crash consequence
- `Procfile`: memory/multi-process note added

## Active Constraints

- **User works from `/ops` (Basic Auth via `SETTINGS_USER`/`SETTINGS_PASSWORD`, already set in `.env`), not `/client`.** The client-facing magic-link login, `/client` dashboard/settings/prospects flow, public landing page, and `/onboard` lead capture were all built for the original multi-tenant B2B SaaS product and are unused now that the platform runs candidate-mode for Ritish alone (house account, `client_id=1`). Per explicit instruction (2026-09-10), this code is being left in place as-is, not removed — just don't assume the client-facing flow is the active workflow when reasoning about how things get used day to day. `/api/find-and-fire`, `/ops` outreach queue, and `/client/settings`'s candidate-profile fields (called directly or via `database.update_client`) are the paths actually exercised.
- `LINKEDIN_DRY_RUN=true` by default
- All sends in `web_app.py` must go through `_route_send_email()`
- Client reply draft actions check `draft.client_id == session.client_id` and return 404 on mismatch
- Scheduler can be disabled with `--no-scheduler` or `SCHEDULER_ENABLED=false`
- `/settings` is Basic Auth protected
- `/` is public marketing and `/ops` is internal operator UI
- `/client` requires `session["client_id"]`
- House account is always `client_id=1`
- Find-and-Fire uses job-id polling, not SSE; pipeline schedules send at 08:00 local time (NOT immediate)
- Find-and-Fire skips prospects with `status='contacted'` to prevent duplicate sends
- `/onboard` POST never creates a client workspace - operator provisions manually via `/ops`
- `OPERATOR_EMAIL` must be set for lead alerts and daily reports
- Stripe is fully removed - no `/checkout`, no `/webhook/stripe`, no `stripe` package
- `SECRET_KEY` placeholder or empty crashes app at boot with RuntimeError
- `SETTINGS_PASSWORD` = `change-me` or empty crashes app at boot with RuntimeError
- LinkedIn/Instagram sequence steps are no-ops when `LINKEDIN_DRY_RUN=true` (skips browser entirely)
- SMS sequence steps are no-ops when `TWILIO_ACCOUNT_SID` is unset
- `get_all_prospects(db_path=db_path)` must use keyword arg - positional passes as `client_id`
- `research_prospect(id, db_path=database.DB_PATH)` must pass `db_path` as keyword arg
- `get_prospect_by_id()` must be used to reload a prospect after research
- SendGrid now supports attachments and thread headers
- SendGrid signed webhook verification is optional and only enforced when `SENDGRID_WEBHOOK_PUBLIC_KEY` is set
- Client sender identity is stored per workspace and used during outbound sends only when `sender_email_verified=1`
- Mailivery webhook verification is mandatory when `/webhook/mailivery` is used

---

## Next Session - Planned Tasks

1. **Deploy to Render** - Web Service + Background Worker + Persistent Disk; set `DB_PATH=/var/data/prospects.db`, `APP_BASE_URL`, `OPERATOR_EMAIL`, `SECRET_KEY` (strong random), `SETTINGS_PASSWORD` (strong), and all keys; see deployment plan `snoopy-pondering-hickey.md`
2. Configure Mailivery webhook URL/header in Mailivery dashboard to `https://your-app.onrender.com/webhook/mailivery`
3. Set `OPERATOR_EMAIL` in production env vars
4. More `/ops` polish and deeper workspace drilldowns
