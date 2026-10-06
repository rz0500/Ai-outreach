# Agent Instructions

Read this at the start of every session. Update after meaningful changes.

---

## Current Status (2026-09-29)

Built and tested (256 tests), **not started**. Ritish wants everything sorted before launch: do not run `start_gradreach.bat`, `python web_app.py` with the scheduler, or otherwise start the autopilot unless they ask. Any experiment must use a COPY of the database (set `DB_PATH` to the copy before importing `web_app`) and must never send real mail. Remaining work is the pre-launch checklist under "Next Session - Planned Tasks" below.

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

### Cutting Maps cost for free (2026-10-06)
Live test of the funnel (55 real companies, copy DB): about 20% sendable under contact + 20-250 filters (Adzuna 12%, Maps 27%), est. ~$0.20 per sendable company, mostly Google Maps lookups. Ritish asked for a free way to cut it. Added (1) `company_size.screen_names` name-only batch screen of Adzuna employers (dropped 38 of 86 before any lookup) and (2) `job_leads.guess_website` free domain guessing (18 of 30 found free; Maps fallback for the rest), cutting Adzuna Maps lookups ~70%. Maps discovery for the Maps source itself still needs Place Details for each website. 372 tests pass.

### Volume goal 600-800 in 60 days (2026-10-06)
Goal fixed at 600-800 first emails over 60 days (ramp gives ~730, weekdays only, no follow-ups). Because the contact and 20-250 size filters pass only a minority of discovered companies, `_run_daily_autopilot` now loops in batches of 15 until the queue holds ~2 days of emails, capped at `AUTOPILOT_MAX_CANDIDATES` (150) candidates per run to bound Maps/AI spend. Pass rate and cost per sendable company are still unmeasured. 368 tests pass.

### Company size filter 20-250 (2026-10-06)
Ritish wants only companies with 20-250 employees. No source we use gives headcount, so `company_size.py` reads the company's about/team/careers pages: explicit statements (verbatim quote verified) are used first; otherwise Claude gives an estimated range (decided on its midpoint, low confidence = unknown). On a 20-company test of known UK fintech/data firms: 3 stated a headcount on their site, ~16 got a verdict with estimates, all 'out' calls were right, one 'in' was wrong (Faculty) because estimates are rough at the edge. Unknown is skipped by default. Effects: fewer eligible leads (large corporates and sub-20 firms drop out); the in-band rate on live discovery was not measured (Ritish declined the ~$2 live test). 365 tests pass.

### Warmer emails with real recent facts (2026-10-06)
Ritish asked for a more open-ended, warmer coffee-chat email that says he likes the company and mentions a couple of recent things they did. `company_news.find_recent_facts` reads the company's news/blog/press pages, asks Claude Haiku for up to two facts each with a verbatim quote, and keeps only facts whose quote is found in the fetched text (anti-hallucination). Stored in `prospects.recent_facts`, shown to the email writer; with no facts the email makes no recent claim. Live check: GoCardless (Recurring Pay by Bank launch) and Monzo (FCA AI Live Testing) got real facts; Peak AI got none and fell back to a general warm note. About 5-9s and ~1p per company. 352 tests pass.

### No follow-ups (2026-10-06)
Ritish does not want follow-up emails. `sequence_engine.get_sequence_definition` returns only step 1 of `candidate_email` unless `FOLLOWUPS_ENABLED=true` (`settings.get_followups_enabled`). The daily cap now goes entirely to new companies: ~730 first emails in 60 days (weekdays, 5/10/15/20 ramp), needing ~12 new contactable companies/day, still inside measured lead supply (~1,600 contactable in the Maps pool plus Adzuna). 340 tests pass.

### Adzuna job-board leads (2026-09-30)
Ritish registered a free Adzuna API key (kept only in the gitignored `.env` as `ADZUNA_APP_ID` / `ADZUNA_APP_KEY`; plan shows "Trial Access"; free tier is roughly 250 calls/day). Built `job_leads.py`, the best lead source so far: companies advertising a relevant analyst role RIGHT NOW.
- **Supply (UK, last 30 days, measured live)**: ~1,063 "data analyst", ~1,657 "business analyst", ~1,142 entry-level analyst titles (`title_only=analyst` + `what_or=graduate junior entry associate trainee apprentice`). Note Adzuna's `what` is AND-matching (a "graduate data analyst" query returns 0), so searches use `title_only`/`what_or`.
- **How it works**: `discover_job_leads(target)` rotates 11 searches (`job_leads.SEARCHES`, per-search page pointer in `<db>_job_state.json`, 3 pages x 50 jobs per run), keeps relevant analyst titles (`is_relevant_title`: analyst/analytics + a fitting domain word, excluding cyber/support/test/engineer/claims/payroll etc.), drops recruitment agencies/job boards (`is_agency` name list plus Google's `employment_agency` place type), keeps one role per employer (early-career preferred), finds the employer's website via Google Maps (`find_website`, name-similarity check, rejects job-board/social URLs), dedupes by name and website domain, and inserts prospects with `hiring_signal = "Advertising: <role>"` and the role/URL in `notes`.
- **Wiring**: `web_app._run_daily_autopilot` calls `discover_job_leads` first and tops up with Maps `discover_new_leads`. `database.get_pending_sends` now sends early-career openings first (`graduate/junior/trainee/apprentice/entry/intern/associate` in the signal), then other hiring signals, then the rest. The AI prompt may name an advertised role once as the reason for writing, but only when it is early-career; for senior roles it only says the team looks to be growing. Verified live: "I saw Coveris is hiring a Trainee Commercial Analyst..." while a Senior Data Analyst opening was not named.
- **Live test (copy of the DB, nothing sent)**: 30 new companies in 24s; 31 of 42 employer lookups matched a real website (74%); 13 of 30 (43%) had a usable contact (6 personal, 2 careers, 5 generic), e.g. recruitment@ at Motability, earlycareers@ at Janus Henderson. Large banks/corporates often show no contact email on their site (Hunter would help). Cost about USD 2 of Maps lookups for that run (~USD 0.15 per usable contact).
- 22 tests in `test_job_leads.py` (all HTTP mocked).

### Can we source enough leads? Supply test (2026-09-30)
16 consecutive rotation searches (12 London company types, then Manchester) on a DB COPY with real Maps + crawls, nothing emailed:
- 250 genuinely new companies, ~15.6 per search (each search returns up to 60 places but many are duplicates, irrelevant types or have no website). No saturation yet: first 6 searches averaged 14 new, last 6 averaged 16.
- 51% (129/250) had a usable contact email; 19 (~8%) showed any hiring signal. Crawling 250 sites took ~4.5 minutes; Maps cost was a few dollars.
- Pool estimate: 204 (query x city) combinations x ~15 new = roughly 3,000 discoverable companies, ~1,600 with a contact, with the current query list. Needs: ~350 companies for 1,000 total messages (about 45 searches, trivial); 1,000 companies would consume ~60% of the pool (feasible, with dilution in smaller cities) unless more queries/cities/sources (Adzuna, Reed) are added.
- Conclusion: supply is not the bottleneck; daily send capacity on one Yahoo inbox is. `_run_daily_autopilot` can discover ~90 new companies/day (max 6 searches).

### Weekdays-only sending + missing timezone packages (2026-09-30)
- Ritish chose weekdays-only sending. `web_app._next_8am_utc(tz, now=None)` now returns the next 08:00 local that is Mon-Fri (built with `tz.localize`, so clock changes are right), and `_send_scheduled_outreach` returns immediately at the weekend (`_is_weekend()`, UK time), so anything already due but held back by the cap waits for Monday. `SEND_WEEKENDS=true` (`settings.get_send_weekends`) switches it off. Follow-ups inherit this because the dispatcher schedules through `_next_8am_utc`. The ramp still counts calendar days (each 5/10/15/20 tier is one calendar week = five send days), so planning figures for 1,000 total messages on this one inbox: about 63 days with a health-based cap up to ~35/day, about 80 days with the flat 20/day cap; about 710 messages in 60 days.
- **Environment bug found while testing**: `pytz` and `timezonefinder` are in `requirements.txt` but were NOT installed on this machine, so `_infer_timezone` returned UTC and `_next_8am_utc` fell back to 08:00 UTC for every prospect, silently. Installed both (`pytz 2026.4`, `timezonefinder 9.0.0`); verified London -> 07:00 UTC (08:00 BST), Amsterdam -> 06:00 UTC. Windows has no system tz database and `tzdata` is not installed, so `zoneinfo` cannot be used as a fallback. `web_app` now prints a startup warning when either package is missing, and the SendGrid webhook-key warning only appears when `USE_SENDGRID` is on.
- Yahoo's published limits (for reference): ~500 messages/day and ~100/hour hard, so 20-40/day is a self-imposed reputation limit for a new freemail account, not a platform limit.
- Not built yet (offered): spread each day's sends over ~08:00-11:00 with random offsets instead of one 08:00 burst, and a health-based cap (+5/day each week while bounces stay under ~2% and nothing is flagged, ceiling ~40).
- 12 tests in `test_weekday_sending.py` (weekday rollover, clock change, other timezones, weekend guard).

### Lead supply: measurement, pagination bug, hiring signals (2026-09-30)
Focus of the day was getting leads. Measured on a COPY of the DB (real Maps + real crawls, nothing emailed): `lead_discovery.discover_new_leads(target=40, pages=3, max_searches=3)` produced 40 brand-new London fintech/data/software companies in ~58s, and crawling them took ~45s.
- **Critical bug found and fixed**: fetching Maps result page 2+ failed with `INVALID_REQUEST` (a fresh `next_page_token` is rejected for a few seconds), and because it raised inside the generator the whole search was discarded, so every autopilot discovery run would have returned 0 leads (unit tests only used single pages). `_next_page` now waits and retries (2s, 3.5s, 5s, 6.5s) and a permanent page-2 failure keeps the page-1 results. Rotation state is now per database (`<db>_discovery_state.json`) so tests/copies cannot move the live rotation.
- **Contact yield (40 companies)**: 50% had a usable contact; best-contact kinds: careers/jobs 6, personal 3, generic 11.
- **Hiring signals**: `contact_finder.find_site_intel(url)` now returns contacts + `hiring_roles` + `graduate_friendly` in one crawl (`describe_hiring()` -> text stored in `prospects.hiring_signal` via `update_enrichment_fields` and fed to the AI prompt). New `ats_jobs.py` reads public job-board JSON (Greenhouse, Lever, Ashby, Workable, SmartRecruiters; no keys) for boards linked from a company's pages and keeps analyst/analytics/graduate titles. Real-world yield was low: 4 of 40 (10%) had any signal, 1 (2%) had a named analyst role (Credit Analyst), because most small firms' careers pages load jobs with JavaScript or use no public ATS. `database.get_pending_sends` now sends companies with a hiring signal first when the daily cap binds.
- **Conclusion**: Maps + crawl supplies plenty of companies for the 20/day cap (about 40 new companies/day -> ~20 contacts), but relevance (who is actually hiring analysts) needs a job-board source. Adzuna/Reed free keys (Ritish has not registered them yet) are the next lead-quality step; Hunter gives named recruiters.
- Tests: `test_site_intel.py`, `test_ats_jobs.py`, extra cases in `test_lead_discovery.py`.

### Bounce handling (2026-09-30)
- New `bounce_handler.py`: `is_bounce` (RFC 3464 `multipart/report` with `report-type=delivery-status`, or a MAILER-DAEMON/postmaster sender with a bounce-style subject), `parse_bounce` (recipient from `Final-Recipient`/`Original-Recipient`, else emails in the text; hard = `Status: 5.x.x` or clear "no such user / 550" text; `Action: delayed/delivered`, 4.x.x and mailbox-full are soft), `process_bounce` (hard bounce -> `suppress_prospect(reason='hard_bounce')`, sequence enrollment paused, queued drafts cancelled via `database.skip_pending_outreach`, `bounce` event logged; skips replied/booked/rejected prospects so a repeat notice is idempotent). Verified against the real Yahoo "Failure Notice" left in the mailbox by the accidental test send (550 No Such User Here for sam@acmedata.com).
- `inbox_monitor._scan_folder` runs it before reply matching for INBOX and the spam folder; bounce notices are marked read but never moved or treated as replies.
- `web_app._send_scheduled_outreach`: when the SMTP server refuses an address outright (`classify_delivery_failure == 'invalid_recipient'`) the prospect is suppressed, the sequence paused and the row skipped, instead of being retried every scheduler cycle. Other transient failures are still retried each cycle (no attempt limit yet).
- 17 tests in `test_bounce_handler.py` (detection, hard/soft, DB effects, idempotence, monitor integration).

### Rehearsal passed + reply-monitor fixes (2026-09-30)
Ran the end-to-end rehearsal on a COPY of the DB (`data/rehearsal.db`, gitignored) with every recipient set to Ritish's own Gmail, over the real Yahoo mailbox:
- Pipeline (real research + Claude, quality 100) -> real `_send_scheduled_outreach` send -> step 1 logged -> simulated day 5 -> follow-up 1 scheduled by the dispatcher and sent -> step 2 logged. Worked first time.
- Ritish replied from Gmail. **Yahoo filed the reply in its spam folder ("Bulk")** and the monitor only read INBOX, so a real reply would have been missed. Fixed: `inbox_monitor` now scans the provider's spam folder (`_find_junk_folder`, RFC 6154 `\\Junk` flag) via `_scan_folder`; genuine prospect replies found there are processed and moved to INBOX (which also tells the provider the sender is not spam), while ordinary spam is left untouched. After the fix the reply was classified `interested`, the prospect became `replied`, the enrollment paused (`interested_reply_awaiting_response`), a draft response was saved (`pending_review`), an alert was emailed to Ritish, and the already-queued follow-up 2 was skipped, not sent.
- Replies from a colleague at the same company (e.g. `sarah@` answering an `info@` email) were also missed because matching was by exact address. `_prospect_for_sender` now falls back to `database.get_prospects_by_email_domain` when exactly one active prospect is at the sender's company domain; freemail, system senders (mailer-daemon/postmaster/noreply) and ambiguous domains never match.
- Test hygiene: a new `conftest.py` blocks real SMTP for every test. The `/onboard` tests had been sending two real "New lead" emails from the live mailbox to the operator address on every full run (found in the Yahoo Sent folder).
- Known gap: `mark_as_read=True` marks every unread inbox message read, so the Yahoo account must stay dedicated to this tool. (Bounce notices were a gap here; fixed, see the bounce entry above.)

### PowerPoint popping up on every test run (2026-09-30)
- Cause: `test_deck_generator.py::test_generate_deck_creates_pptx` called the real `generate_deck()`. `run_deck_qa` always converts the deck to PDF, and with no LibreOffice (`soffice`) installed `deck_generator._convert_deck_to_pdf_windows` launches PowerPoint via PowerShell COM. Every full test run opened PowerPoint, and the same test also made a live Claude call (`ANTHROPIC_API_KEY` set -> AI deck copy) and took ~30s.
- Fix: the test now stubs `_convert_deck_to_pdf` / `_rasterize_pdf` and blanks `ANTHROPIC_API_KEY` (template copy); it runs in ~0.1s with no app launch, no API cost and no leftover `deck_test_*` folder. The autopilot never calls `generate_deck`; only the old `/api/...deck` routes in `web_app.py` do.
- Rule: tests must never launch external apps or hit paid APIs.

### Hands-free autopilot (2026-09-29)
Goal: one Yahoo mailbox, no domain, a process that runs itself and gets replies. Audit of the existing scheduler found several things that would have broken that; all fixed:
- **Lead discovery** used the house account's `niche` ("Graduate Analyst & Operations Outreach") as the Google Maps query, and `find_and_add_prospects` returns already-known companies again (re-researched daily). New `lead_discovery.py`: rotates (query x city) pairs (12 analyst-friendly company types x 17 UK/IE/NL cities), reads up to 3 Maps pages per search, skips irrelevant place types/closed/no-website, dedupes by name AND website domain, returns only NEW prospects; rotation index saved in `data/discovery_state.json`.
- **Autopilot** (`web_app._run_daily_autopilot`, called from the scheduler once a day at `SELF_PROSPECT_RUN_HOUR`): keeps ~2 days of first emails queued (`cap * 2`, cap = client `daily_send_limit` or the warmup ramp or 20), discovers leads, runs the pipeline with `require_email=True, make_pdf=False` (no contact found -> dropped before any Claude cost; no unused PDF).
- **Follow-ups never worked**: (1) the default sequence stalled at step 2 (LinkedIn, dry-run, logged "failed"); (2) scheduled emails never logged a `sequence_step` "sent" event; (3) sent prospects became `contacted` and dropped out of `get_active_sequence_enrollments` (`p.status = 'in_sequence'`); (4) `_send_scheduled_outreach` skipped every `contacted` prospect, i.e. all follow-ups. Also the dispatcher's `email_initial` step created a duplicate first email next to the pipeline's AI draft. Fix: new email-only sequence `candidate_email` (`sequence_engine`: day 0 initial, day 5 follow-up 1, day 12 follow-up 2; `SEQUENCE_NAME` env / `settings.get_active_sequence_name`), `outreach.sequence_name/sequence_step` columns + `database.tag_outreach_sequence_step` / `has_outreach_for_step` (no duplicate rows), `sequence_dispatcher.record_email_step_sent` called after a real send, skipped (dry-run/no profile) non-email steps count as done, active enrollments include `contacted`, scheduled sends skip prospects who replied/booked/rejected and pause with the campaign, and stop for the day when the cap is hit. Pipeline enrols each prospect and tags its AI draft as step 1. Lifecycle covered by `test_followup_lifecycle.py` (never sends: it mocks `deliver_prospect_email` and uses example.com).
- **Ramp**: `warmup_engine._RAMP` now 5/day (days 1-7), 10, 15, then 20/day cap (was 10/20/40/70/120/200); `WARMUP_START_DATE` set in `.env`; house `daily_send_limit` set to 0 so the ramp (not a fixed 10) applies; status page uses a 21-day ramp.
- **Copy**: greeting is "Hi there," for placeholder names ("Owner/Manager"); templates/subjects use the clean brand name (`outreach._display_company` via `_company_core_name`) instead of Maps noise ("FintechOS HQ - London, UK"); `email_validator._company_mentioned` accepts a distinctive shortened brand ("Traction") but not generic words ("fintech"); `ai_engine.generate_hyper_personalized_email` retries up to 3x telling Claude exactly what the quality gate rejected (length, company name) before falling back to the template.
- **Config done in `.env`/DB (not in repo)**: `MAILIVERY_ENABLED=false` (plan expired, key 401), `OPERATOR_EMAIL` and house `clients.email` set to Ritish's real inbox so reply alerts and the 17:00 UTC daily report reach him, `SEQUENCE_NAME=candidate_email`, `WARMUP_START_DATE` = today. 48 stale April agency-pitch drafts marked `rejected_draft` (none had a send time).
- `start_gradreach.bat` keeps `python web_app.py` (web app + scheduler) running and restarts it after a crash; log goes to `gradreach.log` (gitignored). The PC must be on and awake for anything to send; Windows Task Scheduler "at log on" or a cloud host is needed for true hands-off.
- Verified on a COPY of the live DB with real Maps + Claude (nothing sent): 6 discovered, 3 with a contact queued and enrolled as step 1, 3 dropped.
- Mistake worth remembering: an early version of `test_followup_lifecycle.py` used a temp DB missing the `send_after` column, so the dispatcher's "scheduling failed -> send immediately" fallback ran and sent one real email ("Re: Acme Data") to sam@acmedata.com. The fallback (`_dispatch_single_touchpoint`) still exists because older tests rely on it; it bypasses the daily cap, so tests must always mock `sequence_dispatcher.deliver_prospect_email`.

### Coffee-chat framing (2026-09-29)
- Ritish wants analyst-type roles, pitched as a low-pressure coffee chat / short call to hear how the team uses data, NOT a job application. All outbound copy now follows that: `ai_engine._EMAIL_SYSTEM_PROMPT` (goal, structure, ONE relevant proof point from the CV: 5%->20% conversion, 80% less manual work, 2%->12% reply rate; never say "applying", never mention the current employer, never attach/link a CV; also lists the phrases the quality gate bans), `outreach._weak_data_email` / `_build_data_driven_email` (shared `_COFFEE_CHAT_ASK` and `_signature()`), and all follow-ups in `sequence_engine.py` (new `_signoff()`).
- Subjects: `_build_angle_subject` no longer uses agency words (pipeline/outbound/demand/buyers); `_coffee_chat_subject()` picks a plain subject per company ("<Co> analytics team", "Question about <Co>'s data work", "Coffee chat about <Co>?", "Early-career analytics at <Co>"). `test_subject_variety.py` rewritten to match.
- The CV link is gone from emails: the Claude artifact behind it is private, so recipients most likely could not open it (unauthenticated fetch returns a generic shell). Sign-off now shows the candidate's LinkedIn from `CANDIDATE_LINKEDIN` in `.env` (`settings.get_candidate_linkedin`; kept out of the public repo). The CV PDF is offered on request only.
- The generated candidate pitch PDF is still created for reference but is no longer stored on `outreach.pdf_path`, so nothing is attached to sends (a cold attachment reads as a mass application and hurts a fresh mailbox).
- Verified live: `generate_hyper_personalized_email` for London Data Consulting produced a coffee-chat email at quality 97/100.

### Hunter.io recruiter lookup (2026-09-29)
- New `hunter_client.find_hiring_contact(url)` calls Hunter's Domain Search (`department=hr`, then `executive`, then `management`; personal addresses only; confidence >= 70; invalid-verification rejected) and picks the best person, scoring recruiter/talent titles above generic HR and penalising assistant/intern titles. Enabled only when `HUNTER_API_KEY` is set (`settings.get_hunter_api_key`, documented in `.env.example`); returns `{}` on any failure so the pipeline falls back to `contact_finder`.
- `_run_pipeline_for_db_prospect` order is now Hunter -> website crawl. A named contact renames "Owner/Manager" prospects and adds a `Contact role: <name>, <title>` line to the prospect's notes so the AI email can speak to their role.
- Hunter pricing (checked 2026-09-29): free = 50 credits/month, max 10 results per call; Starter $34/month = 2,000 credits. About one credit per company, so 50-100 new companies/day needs a paid plan. NOT yet verified against the live API - no key was available; covered by mocked tests only.
- Ritish considered Apollo.io (bigger free tier, 75 credits/month) but its API access on the free plan is unconfirmed; Hunter was built first.

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

1. ~~Safe end-to-end rehearsal~~ **Done 2026-09-30** (send, step logging, follow-up, reply detection, alert all verified; see entry above). Remaining rehearsal idea: a bounce test.
2. **Ritish approves the email wording** (sample coffee-chat email + follow-ups) and the **target list** (`lead_discovery.QUERIES` x `CITIES`, currently 12 company types x 17 UK/IE/NL cities).
3. **Decide where it runs**: PC only sends while on and awake (`start_gradreach.bat`); a cloud host (~GBP 7/month) is the only truly hands-off option. Add a Windows "at log on" task if staying on the PC.
4. **Decide oversight for the first days**: watch the `/ops` queue daily, or add a review mode for the first batch.
5. **Yahoo mailbox warm-up**: check the account's age; if new, use it normally (real mail to and from friends) for about a week before launch.
6. **Reset `WARMUP_START_DATE` in `.env` to the real launch day** (it currently holds the day it was configured, 2026-09-29) so the 5/10/15/20 per day ramp starts at launch.
7. Adzuna job-board lead source **built 2026-09-30** (Reed key optional, not needed); **Hunter** API key -> named recruiters (`hunter_client.py` is built but untested against the live API); Mailivery is expired (skip or use its free plan).
8. Housekeeping: cancel SendGrid once a test send is confirmed; check whether the old `info@outreachempower.com` mailbox is a paid Google Workspace plan; revoke the unused `STRIPE_SECRET_KEY` in `.env`.
