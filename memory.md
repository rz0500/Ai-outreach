# Project Memory

This file serves as the long-term memory for Claude to prevent context loss. Please update this file when significant architectural decisions are made, new modules are completed, or important bugs are resolved.
Also keep `agent.md` updated alongside this file when the project state materially changes.

## Current State
- **Completed Modules**: `database.py`, `scorer.py`, `importer.py`, `dashboard.py`, `outreach.py`, `reporter.py`, `mailer.py`, `sequencer.py`, `ai_engine.py`, `inbox_monitor.py`, `google_maps_finder.py`, `main.py`, `web_app.py`, `research_agent.py`, `pdf_generator.py`, `social_agent.py`, `sms_agent.py`, `sendgrid_mailer.py`, `sequence_engine.py`, `sequence_dispatcher.py`, `email_validator.py`.
- **Next Immediate Goals**:
  1. Wire `main.py` from the legacy email sequencer to the new multi-channel dispatcher.
  2. Add structured research persistence and richer reply handling.
- **End Goal**: Fully automated AI lead generation and outreach system. (In progress)

## Architectural Decisions
- **Database**: SQLite `prospects.db` without ORM. `sqlite3.Row` is used to return dict-like rows. Compliance and orchestration tables include `suppression_list`, `communication_events`, and `sequence_enrollments`.
- **Scoring Scale**: 1-100 (1-40 cold, 41-70 warm, 71-100 hot).
- **Status Pipeline**: `new` -> `qualified` -> `contacted` -> `replied` -> `booked` / `rejected`.
- **Evidence-First Emailing**: `outreach.py` now runs a mandatory internal `COMPANY ANALYSIS` step, chooses one primary angle, enforces weak-data mode, and scores drafts on `specificity`, `credibility`, and `generic_risk` before returning them.
- **Controlled Inference**: The outbound system now allows grounded inferences from real data, such as clear positioning implying a defined buyer or no outbound signals implying a missed outbound opportunity. Weak/passive phrasing is explicitly rejected.
- **Operator Voice**: The outbound writer now targets a sharper founder/operator voice with fast line-by-line rhythm, stronger market truths, a 5-line body structure, and a short CTA using a calendar link placeholder.
- **Website Test Bench**: `web_app.py` now accepts a company URL and returns not just the generated email, but also extracted enrichment, internal company analysis, chosen angle, and internal quality scores so the reasoning can be tested in-browser.
- **Outbound Strictness**: `email_validator.py` blocks banned phrases, generic openers, missing company references, and computes internal quality scoring for rewrite decisions.
- **Deck Prompt System**: `deck_generator.py` now stores a filled system-prompt template for bespoke 6-slide decks, uses that prompt in AI mode, validates slide-level rules, and returns PDF as the main output after export QA.
- **Deck Export UI**: `web_app.py`, `templates/index.html`, and `static/css/index.css` now expose sample deck PDF generation in the dashboard. On Windows, `deck_generator.py` can fall back to PowerPoint COM for PPTX->PDF export when LibreOffice is not installed.
- **URL-to-Deck Flow**: `web_app.py` now has a `/api/generate-deck-from-url` path backed by shared site enrichment, and the dashboard includes a URL input that generates a PDF deck directly from a company website.
- **AI Prompt Engine**: `ai_engine.py` now instructs Claude to analyze first, choose one angle, enforce traceability, and obey weak-data mode before outputting subject/body.
- **Compliance Foundation**: `suppression_list` and `communication_events` ensure outbound activity can be audited and opted-out contacts can be excluded from future sends.
- **Sequence Foundation**: `sequence_enrollments` and `sequence_engine.py` model a future multi-channel sequence without breaking the current email sequencer.
- **Dispatcher Foundation**: `sequence_dispatcher.py` routes due touchpoints through email, LinkedIn, Instagram, and SMS handlers behind one runner. The dispatcher is implemented and tested, but `main.py` is not yet switched over to it.
- **Debugability**: `debug_email_reasoning()` exposes the internal company analysis, chosen angle, validation result, and quality score for inspection.

## APIs & Integrations (Roadmap)
- **Anthropic API**: Implemented in `ai_engine.py`.
- **SMTP**: Implemented in `mailer.py`.
- **SendGrid**: Implemented in `sendgrid_mailer.py`.
- **IMAP**: Requires App Passwords for reading emails (pending setup).
- **Google Maps API**: For business discovery (pending setup).
- **Calendly**: For booking calls (pending setup).
