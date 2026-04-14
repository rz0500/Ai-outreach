# Agent Instructions

This file tracks the current task and active context for Codex/Claude. Read this file at the start of any new session or when switching contexts. When a meaningful task is completed, update both `agent.md` and `memory.md` so the next session has accurate continuity.

## Current Task
**Objective**: Build the outbound pipeline around evidence-backed reasoning and expose it through a practical web-based testing interface.

**Instructions**:
- Run the mandatory internal `COMPANY ANALYSIS` step before drafting outreach.
- Pick one primary angle per email and keep every sentence traceable to source data or a clear logical inference.
- Use controlled inference confidently instead of timid disclaimers when enrichment is thin.
- Reject passive language such as "might be", "could be", "if there is", and "I only have a limited read".
- Keep outbound copy in an operator voice: short lines, sharp opener, blunt market truth, plain service explanation, risk reversal, and CTA with calendar link.
- Keep `outreach.py`, `ai_engine.py`, and `email_validator.py` aligned whenever email rules change.
- Keep the deck system aligned with the stored bespoke 6-slide prompt template and run QA checks after render.

## Active Constraints
- The system is not finished yet; do not treat the original blueprint as complete.
- Keep `agent.md` and `memory.md` updated after meaningful architecture or workflow changes.
- Prioritize high-fidelity data extraction over persuasive but unsupported copy.
- The current outbound target voice is punchy, commercially sharp, and slightly blunt rather than safe or polished.
- The deck generator now targets a 6-slide bespoke deck but returns PDF as the primary output. PPTX remains an internal render step for export.
- The web UI now surfaces the deck generator directly, and on this Windows setup PDF export works via PowerPoint COM when LibreOffice is unavailable.
- The dashboard now supports URL-driven deck PDF generation, not just the fixed sample deck.
- `main.py` still uses the legacy `sequencer.run_sequence()` path; the new dispatcher exists but is not yet the main execution path.

## Next Up
- Wire `main.py` over to the new multi-channel dispatcher.
- Add structured research persistence and richer reply handling.
- Extend the web tester so URL-based runs can be saved or pushed into the draft/research workflow.
