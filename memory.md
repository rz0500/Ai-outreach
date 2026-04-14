# Project Memory

This file serves as the long-term memory for Claude to prevent context loss. Update it when significant architectural decisions are made, new modules are completed, or important bugs are resolved.
Also keep `agent.md` and `CLAUDE.md` updated alongside this file when the project state materially changes.

## Current State

**Completed Modules:**
`database.py`, `scorer.py`, `importer.py`, `dashboard.py`, `outreach.py`, `reporter.py`, `mailer.py`, `sequencer.py`, `ai_engine.py`, `inbox_monitor.py`, `google_maps_finder.py`, `main.py`, `web_app.py`, `research_agent.py`, `pdf_generator.py`, `social_agent.py`, `sms_agent.py`, `sendgrid_mailer.py`, `sequence_engine.py`, `sequence_dispatcher.py`, `email_validator.py`, `deck_generator.py`

**Next Immediate Goals:**
1. Extend URL-based runs to save into the draft/research workflow (persist to DB)
2. Wire the full pipeline endpoint to also save research into `prospect_research` table

**End Goal:** Fully automated AI lead generation and outreach system. (In progress)

---

## Architectural Decisions

**Database:** SQLite `prospects.db` without ORM. `sqlite3.Row` for dict-like rows. Compliance and orchestration tables: `suppression_list`, `communication_events`, `sequence_enrollments`, `prospect_research`, `reply_drafts`.

**Scoring Scale:** 1–100 (1–40 cold, 41–70 warm, 71–100 hot).

**Status Pipeline:** `new` → `qualified` → `contacted` → `replied` → `booked` / `rejected`.

**Email Voice (updated):** Conversational, human, empathetic — not blunt-operator. New structure:
1. Market truth opener — describes how their type of business typically grows (industry-specific)
2. Tension line — short, isolated, one sentence ("It works — until it doesn't.")
3. What we do + mechanism — names the company + "That means researching real prospects..."
4. Risk reversal + personal selection — "5 slots for free to prove it works. [Company]'s one of the ones I had in mind."
5. CTA as soft question — "Worth a 15-minute call?"
6. Calendar link on its own line
7. Sign-off: `— [Name]` (no opt-out line)

**Email Body Length:** 90–130 words. Validator cap updated to 140 words (was 90).

**Evidence-First Emailing:** `outreach.py` runs a mandatory internal `COMPANY ANALYSIS` step, chooses one primary angle, enforces weak-data mode, and scores drafts before returning.

**Controlled Inference:** Grounded inferences from real data are allowed and expected. Passive/hesitant phrasing is explicitly rejected.

**Website Test Bench:** `web_app.py` accepts a company URL and returns enrichment, company analysis, chosen angle, email draft, and quality scores for in-browser testing.

**Full Pipeline Endpoint:** `POST /api/full-pipeline` — takes a URL and runs research + email + PDF proposal in one shot. Returns all outputs in a single JSON response. UI section "Full Outreach Pipeline" is the primary dashboard feature.

**Outbound Strictness:** `email_validator.py` blocks banned phrases, generic openers, missing company references, and computes internal quality scoring for rewrite decisions.

**PDF Proposal Style (updated):** `pdf_generator.py` now produces a fully dark-background 5-page deck-style PDF:
- Page 1: Cover — company name, niche, 3 metric cards (purple/orange/cyan)
- Page 2: THE PROBLEM (orange bar) — 2×2 card grid of pain points + tension kicker
- Page 3: MARKET REALITY (green bar) — competitor cards + red takeaway box
- Page 4: THE SYSTEM (purple bar) — 4 numbered step cards with coloured accent bars
- Page 5: PILOT + CTA (red bar) — metric cards + CTA booking block
- Dark background (`#0f172a`) on every page via canvas callback
- Per-section coloured top bar driven by `_PAGE_BAR` list

**Deck Generator:** `deck_generator.py` is a separate bespoke pitch deck system (PPTX → PDF). The PDF proposal (`pdf_generator.py`) is used for the full-pipeline and web tester flows.

**Reply Review UI:** `reply_drafts` table stores classified inbound replies with `pending_review` / `approved` / `sent` / `dismissed` status. Dashboard shows cards with Approve/Dismiss buttons. `/api/seed-demo-reply` injects test data.

**Structured Research Persistence:** `prospect_research` table stores every Claude analysis run with timestamp, URL, all enrichment fields, and full JSON. `research_agent.py` checks this table first to skip already-researched prospects.

**Sequence Foundation:** `sequence_enrollments` + `sequence_engine.py` model future multi-channel sequences. `sequence_dispatcher.py` routes touchpoints through email, LinkedIn, Instagram, and SMS.

**Compliance Foundation:** `suppression_list` and `communication_events` enable audit trails and opt-out exclusions.

---

## APIs & Integrations

- **Anthropic API:** Implemented in `ai_engine.py`. Model: `claude-haiku-4-5` (swap to `claude-sonnet-4-6` for higher quality).
- **SMTP:** Implemented in `mailer.py`.
- **SendGrid:** Implemented in `sendgrid_mailer.py`.
- **IMAP:** Implemented in `inbox_monitor.py`. Requires App Passwords.
- **Google Maps API:** Implemented in `google_maps_finder.py` (pending live key setup).
- **Calendly:** Placeholder `calendly.com/leadgenai/30min` used throughout (pending real setup).

---

## Key DB Tables

| Table | Purpose |
|---|---|
| `prospects` | Core lead records |
| `outreach` | Email drafts/sent log |
| `suppression_list` | Opt-outs + compliance exclusions |
| `communication_events` | Full audit trail of all touchpoints |
| `sequence_enrollments` | Multi-channel sequence state per prospect |
| `prospect_research` | Structured AI research results with timestamp |
| `reply_drafts` | Classified inbound replies with review queue |
