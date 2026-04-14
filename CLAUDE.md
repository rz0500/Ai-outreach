# CLAUDE.md

This file gives Claude Code the current working context for this repository. It should match the real codebase. Keep it aligned with `agent.md` and `memory.md`.

## Project Overview

`leadgen` is a Python-based AI lead generation and outreach system. It includes:

- Prospect storage and orchestration in SQLite
- Evidence-first outbound email generation (conversational style)
- Company research and website enrichment
- Full pipeline: URL → research → email → PDF in one click
- Multi-channel sequence foundations (email, LinkedIn, Instagram, SMS)
- Inbox/reply monitoring with classification and review queue
- Flask web dashboard with URL-based testing
- Dark deck-style PDF proposals
- Bespoke PPTX pitch deck generation

The system is in active build mode — modular, testable, and expanding.

## Priority Context Files

Read these first before making major changes:

- `agent.md` — immediate working objective and what was just completed
- `memory.md` — architecture decisions, module list, DB schema

If a meaningful change is made, update all three files.

## Module Reference

### Core Data
- **`database.py`** — SQLite persistence. Tables: `prospects`, `outreach`, `suppression_list`, `communication_events`, `sequence_enrollments`, `prospect_research`, `reply_drafts`.

### Outreach
- **`outreach.py`** — Main email writer. Runs `COMPANY ANALYSIS`, picks one angle, generates conversational email using the new 5-part structure. Template path (no API key needed).
- **`email_validator.py`** — Quality gate. Bans phrases, checks generic openers, enforces company name in body. Word limit: 140 max (90–130 target).
- **`ai_engine.py`** — Claude-backed prompt engine. Functions: `generate_hyper_personalized_email`, `analyze_prospect_score`, `analyze_website`, `classify_reply`. Model: `claude-haiku-4-5` (configurable).

### Research
- **`research_agent.py`** — Website enrichment. Checks `prospect_research` table first to skip re-research. Writes structured results back to DB.

### Sequencing
- **`sequencer.py`** — Legacy single-channel email sequencer (still used internally).
- **`sequence_engine.py`** — Channel-aware multi-day sequence model.
- **`sequence_dispatcher.py`** — Routes due touchpoints to email/LinkedIn/Instagram/SMS handlers.
- **`main.py`** — Entry point. Wired to `run_multichannel_sequence()`.

### Delivery
- **`mailer.py`** — SMTP delivery.
- **`sendgrid_mailer.py`** — SendGrid delivery with sending-domain support.

### Inbox
- **`inbox_monitor.py`** — IMAP reply monitor. Classifies replies with Claude. Saves interested replies to `reply_drafts` table.

### Web
- **`web_app.py`** — Flask dashboard. Key endpoints:
  - `GET /` — main dashboard
  - `POST /api/full-pipeline` — URL → research + email + PDF in one call
  - `POST /api/generate-from-url` — email only from URL
  - `POST /api/generate-deck-from-url` — deck PDF from URL
  - `POST /api/sample-pdf` — demo PDF proposal
  - `POST /api/sample-deck` — demo deck PDF
  - `GET /api/reply-drafts` — pending reply drafts
  - `POST /api/reply-drafts/<id>/action` — approve or dismiss a draft
  - `POST /api/seed-demo-reply` — inject test reply for UI testing

### Documents
- **`pdf_generator.py`** — Dark deck-style 5-page PDF proposal (ReportLab). Used by the full-pipeline and web tester. Pages: Cover / THE PROBLEM / MARKET REALITY / THE SYSTEM / PILOT + CTA. Full dark background, coloured section bars, card-based content.
- **`deck_generator.py`** — Bespoke 6-slide pitch deck (python-pptx → PDF). Windows fallback: PowerPoint COM. Used for richer per-company decks.
- **`pdf_generator.py`** vs **`deck_generator.py`**: Use `pdf_generator` for the automated pipeline proposal. Use `deck_generator` for a full bespoke sales deck.

### Discovery
- **`google_maps_finder.py`** — Local business discovery via Google Maps API.

### Other channels
- **`social_agent.py`** — LinkedIn/Instagram outreach foundations.
- **`sms_agent.py`** — SMS outreach foundations.

## Email Voice Rules (current)

The email engine uses a conversational human structure — not blunt-operator style.

**5-part structure:**
1. **Market truth opener** — describes how their type of business grows (industry-specific, empathetic, not critical)
2. **Tension line** — short, isolated, one sentence ("It works — until it doesn't.")
3. **What we do + mechanism** — names the company, "That means researching real prospects..."
4. **Risk reversal + personal selection** — "5 slots free to prove it works. [Company]'s one I had in mind."
5. **CTA as soft question** — "Worth a 15-minute call?" then calendar link on its own line, then `— [Name]`

**Hard rules:**
- No opt-out line ("If not relevant, reply no thanks")
- No "companies like yours", "in your space", "AI-powered"
- No exclamation marks
- Company name must appear in the body
- 90–130 words target, 140 max

## PDF Proposal Style Rules (current)

Dark deck aesthetic throughout:
- Background: `#0f172a` on every page
- Per-section coloured top bar (indigo / orange / green / purple / red)
- Card-based content blocks
- Large coloured metric numbers
- Content validation: tension markers required, banned phrases blocked
- 5 pages always (cover + 4 sections)

## Running

```bash
pip install -r requirements.txt
python -m unittest discover
python web_app.py
```

Quick checks:
```bash
python -c "import web_app, deck_generator, outreach, pdf_generator; print('imports ok')"
python pdf_generator.py   # generates proposals/breakdown_apex_digital.pdf
```

## Notes For Future Sessions

- `main.py` is wired to `run_multichannel_sequence()`. The old `sequencer.run_sequence()` still exists but is the legacy path.
- `_operator_market_label()` in `outreach.py` maps niche/ICP text to a short market noun used in emails. Extend it when encountering new niches that fall through to the generic fallback.
- Calendar link is currently hardcoded as `calendly.com/leadgenai/30min` in `outreach.py` (`CALENDAR_LINK`) and `pdf_generator.py` (`CTA_LINK`). Move to `.env` when going live.
- `pdf_generator.py` and `deck_generator.py` serve different purposes — do not conflate them.
- The full-pipeline endpoint does not yet persist results to the DB. That is the next task.
