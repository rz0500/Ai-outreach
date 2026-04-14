# CLAUDE.md

This file gives Claude Code the current working context for this repository. It should match the real codebase, not the original module-by-module plan. Keep this file aligned with `agent.md` and `memory.md`.

## Project Overview

`leadgen` is a Python-based AI lead generation and outreach system. It is no longer just a database/scoring prototype. The repo now includes:

- prospect storage and orchestration in SQLite
- evidence-first outbound email generation
- enrichment and website analysis
- multi-channel sequence foundations
- inbox/reply handling foundations
- a Flask testing dashboard
- PDF-first sales deck generation from website/company inputs

The system is still in build mode. It is modular, testable, and expanding toward the larger original automation vision, but it is not “finished”.

## Priority Context Files

Read these first before making major changes:

- `agent.md` for the immediate working objective
- `memory.md` for the latest architecture and project memory

If a meaningful change is made, update:

- `agent.md`
- `memory.md`
- `CLAUDE.md` when the repo-level workflow or architecture meaningfully changes

## Current Important Modules

- `database.py`
  SQLite persistence for prospects plus compliance/orchestration tables such as `suppression_list`, `communication_events`, and `sequence_enrollments`.

- `outreach.py`
  Main outbound writer. Uses a mandatory internal `COMPANY ANALYSIS`, chooses one primary angle, applies controlled inference, and generates operator-style emails.

- `email_validator.py`
  Quality gate for outbound email copy. Rejects banned phrases, generic openers, overlong drafts, and weak/passive AI language.

- `ai_engine.py`
  Anthropic-backed prompt engine for:
  - hyper-personalized email generation
  - AI prospect scoring
  - website analysis
  - reply classification

- `research_agent.py`
  Website/data enrichment support.

- `sequencer.py`
  Legacy email sequence runner still used in the main path.

- `sequence_engine.py`
  Channel-aware future sequence model for scheduled touchpoints.

- `sequence_dispatcher.py`
  Dispatcher foundation for email, LinkedIn, Instagram, and SMS touchpoints.

- `sendgrid_mailer.py`
  SendGrid delivery and sending-domain groundwork.

- `inbox_monitor.py`
  Reply monitoring and classification support.

- `web_app.py`
  Flask dashboard and testing interface.
  Current UI supports:
  - email generation from a website URL
  - sample PDF generation
  - sample deck PDF generation
  - URL-to-deck PDF generation

- `deck_generator.py`
  Bespoke pitch deck generator. Stores a prompt template for per-company deck generation, renders a PPTX internally, then exports PDF as the primary output. On Windows it can fall back to PowerPoint COM for PDF export.

- `pdf_generator.py`
  Older ReportLab-based PDF proposal path. Still present, but the newer deck path is the stronger “sales deck” system.

## Current Output Style Rules

### Email system

The email engine should feel like a sharp operator, not a polite AI assistant.

Important rules:

- evidence first
- one primary angle per email
- no fake specificity
- controlled inference is allowed when grounded
- no passive phrasing like:
  - `might be`
  - `could be`
  - `if there is`
  - `I only have a limited read`
- fast rhythm
- short lines
- calm, confident CTA

### Deck system

The deck generator currently targets a bespoke dark deck style with:

- dark background throughout
- card-based layout
- named competitor references when available
- market-specific tension lines
- PDF as the final deliverable

The deck flow should feel like:

- specific
- commercially sharp
- tailored to the prospect’s market

Not:

- generic agency deck
- consultant fluff
- soft “AI nice” copy

## Running

Common commands:

```bash
pip install -r requirements.txt
python -m unittest discover
python web_app.py
```

Useful direct checks:

```bash
python -m compileall .
python -c "import web_app, deck_generator, outreach; print('imports ok')"
```

## Notes For Future Sessions

- `main.py` has not been fully switched to the newer multi-channel dispatcher path yet.
- `agent.md` and `memory.md` are more current than old assumptions from earlier sessions.
- Prefer improving existing modular systems rather than creating parallel duplicate paths.
- For deck work, prefer `deck_generator.py` over `pdf_generator.py` unless the user explicitly wants the older proposal format.
