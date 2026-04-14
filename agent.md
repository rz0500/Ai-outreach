# Agent Instructions

This file tracks the current task and active context for Claude. Read this file at the start of any new session or when switching contexts. When a meaningful task is completed, update both `agent.md` and `memory.md` so the next session has accurate continuity.

---

## Current Task

**Objective:** Extend and polish the outbound system — the core pipeline (research → email → PDF) is working end-to-end in the web UI. Focus is now on persistence, refinement, and closing remaining gaps.

---

## What Was Just Completed (this session)

1. **Full Pipeline endpoint** (`POST /api/full-pipeline`)
   - Takes a URL, runs research, generates email, generates PDF proposal — all in one call
   - Returns all outputs in a single JSON response
   - Exposed in the dashboard as "Full Outreach Pipeline" (prominent card at top of page)

2. **PDF proposal redesign** (`pdf_generator.py`)
   - Completely rewritten to dark-background deck style matching the reference design
   - 5-page structure: Cover → THE PROBLEM → MARKET REALITY → THE SYSTEM → PILOT + CTA
   - Per-section coloured top bars, card-based content, large metric numbers
   - Content logic (validation, tension markers, section generators) unchanged

3. **Email voice overhaul** (`outreach.py` + `ai_engine.py`)
   - New conversational structure: market truth opener → tension line → offer + mechanism → risk reversal → CTA question
   - Removed blunt operator structure and opt-out line
   - Added `_market_truth_opener()`, `_tension_line()`, `_mechanism_line()`
   - AI system prompt updated to match new structure with explicit paragraph-by-paragraph instructions
   - Validator word cap updated from 90 → 140 to fit new format

4. **Reply Review UI** (`web_app.py`, `templates/index.html`, `static/css/index.css`)
   - Cards per pending reply draft with Approve/Dismiss buttons
   - Seed demo reply button for testing without live IMAP
   - CSS classes added for reply-draft-card, btn-approve, btn-dismiss, etc.

---

## Active Constraints

- System is not finished. Do not treat it as complete.
- Keep `agent.md`, `memory.md`, and `CLAUDE.md` updated after meaningful changes.
- `main.py` uses the multi-channel dispatcher (`run_multichannel_sequence`) — the legacy `sequencer.run_sequence()` path still exists but is not the main path.
- For proposals, `pdf_generator.py` is the dark-deck style used in the web pipeline. `deck_generator.py` is the bespoke PPTX-based system for richer full decks.
- Email word limit is now 90–130 words (validator cap: 140).
- The `_operator_market_label()` function drives the market noun in emails. Extend it when new niches are encountered.

---

## Next Up

1. **Persist full pipeline results** — when `/api/full-pipeline` runs, save research into `prospect_research` table and email draft into `outreach` table so they appear in the dashboard pipeline.
2. **Make CTA calendar link configurable** — currently hardcoded as `[Calendar link]` / `calendly.com/leadgenai/30min`. Should come from `.env` or settings.
3. **Subject line variety** — currently most emails default to `"outbound for {Company}"`. Add more angle-specific subject patterns.
4. **Reply approve → send** — when a reply draft is approved in the UI, wire it to the mailer so it can actually be sent.
