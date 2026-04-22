# Agent Instructions

Read this at the start of every session. Update after meaningful changes.

---

## Recently Completed

### Foundation through current SaaS state
Full pipeline is now in place across the repo: multi-tenant DB, background scheduler, operator dashboard, email validation, analytics, CSV import, SendGrid routing, reply classification, deliverability hardening, Find-and-Fire polling/UI, client prospects flow, SendGrid webhook security, Mailivery warmup integration, and per-client sender identity.

### Rebranding & UI Overhaul
The application has been successfully rebranded to **OutreachEmpower**. The UI has been heavily refined with a deeper dark mode, glassmorphism, dynamic gradients, micro-animations, and updated typography (Inter font) across all templates.

### Current shipped client/product layer

**Public/product flow:**
- `/` = landing page
- `/checkout` = pricing / pilot checkout page
- `/onboard` = self-serve signup
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
- **Stage 5: Send** — email is actually sent via `_route_send_email()`; prospect marked `contacted`; full body stored as JSON in `metadata` field of `communication_events`
- Duplicate send prevention: `already_sent` check skips prospects with `status='contacted'`
- Email address validation: `_valid()` rejects addresses with nav/path text appended

**Emails tab:**
- `GET /client/emails` shows all sent emails per workspace grouped by prospect (GROUP BY prospect_id)
- Expandable rows show subject + full body (from `metadata` JSON)
- PDF download link when `pdf_url` is present
- Filter buttons: All / Sent / Opened / Clicked / Bounced
- Backfills metadata from `outreach` table for emails sent before metadata was stored

---

## Active Constraints

- `LINKEDIN_DRY_RUN=true` by default
- All sends in `web_app.py` must go through `_route_send_email()`
- Client reply draft actions check `draft.client_id == session.client_id` and return 404 on mismatch
- Scheduler can be disabled with `--no-scheduler` or `SCHEDULER_ENABLED=false`
- `/settings` is Basic Auth protected
- `/` is public marketing and `/ops` is internal operator UI
- `/client` requires `session["client_id"]`
- House account is always `client_id=1`
- Find-and-Fire uses job-id polling, not SSE; pipeline now sends immediately (research→email→PDF→send)
- Find-and-Fire skips prospects with `status='contacted'` to prevent duplicate sends
- `get_all_prospects(db_path=db_path)` must use keyword arg — positional passes as `client_id`
- `research_prospect(id, db_path=database.DB_PATH)` must pass `db_path` as keyword arg
- `get_prospect_by_id()` must be used to reload a prospect after research
- SendGrid now supports attachments and thread headers
- SendGrid signed webhook verification is optional and only enforced when `SENDGRID_WEBHOOK_PUBLIC_KEY` is set
- Client sender identity is stored per workspace and used during outbound sends only when `sender_email_verified=1`
- Mailivery webhook verification is mandatory when `/webhook/mailivery` is used

---

## Next Session - Planned Tasks

1. **Deploy to Render** — Web Service + Background Worker + Persistent Disk at `/var/data`; set `DB_PATH=/var/data/prospects.db`, `APP_BASE_URL`, `SECRET_KEY`, and all keys from local `.env`; see deployment plan `snoopy-pondering-hickey.md`
2. Configure Mailivery webhook URL/header in Mailivery dashboard to `https://your-app.onrender.com/webhook/mailivery`
3. Stripe payments — test `checkout.session.completed` webhook end-to-end when billing goes live
4. More `/ops` polish and deeper workspace drilldowns
