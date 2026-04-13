# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI-powered lead generation and outreach system built in Python. Being developed module-by-module.

- **Module 1** — Prospect database (`database.py`) — SQLite-backed CRUD layer for prospect records.
- **Module 2** — Lead scorer (`scorer.py`) — rule-based scoring 1-100 by profile completeness and growth keywords. AI upgrade path noted in TODOs.
- **Module 3** — CSV importer (`importer.py`) — bulk import with flexible header mapping, duplicate skipping, auto-scoring.
- **Module 4** — CLI dashboard (`dashboard.py`) — interactive menu tying all modules together.
- Future modules will add email outreach and enrichment.

## Setup

```bash
pip install -r requirements.txt
```

SQLite is built into Python — no database server needed. The `.db` file is created automatically on first run.

## Running

```bash
# Module 1 - database demo (no API key needed)
python test_database.py

# Module 2 - scorer demo
python test_scorer.py

# Module 3 - CSV importer demo
python test_importer.py

# Module 4 - interactive dashboard (seeds prospects.db if empty)
python test_dashboard.py

# Launch dashboard directly against existing prospects.db
python dashboard.py
```

## Architecture

### database.py

Single-file SQLite module with no ORM. All functions accept an optional `db_path` parameter (defaults to `prospects.db`) so tests can use an isolated file without touching production data.

Key design decisions:
- `sqlite3.Row` as `row_factory` — rows are returned as dicts, not tuples.
- All public functions validate inputs (status enum, score range) before touching the DB.
- `initialize_database()` uses `CREATE TABLE IF NOT EXISTS` — safe to call on every startup.
- Duplicate emails raise `sqlite3.IntegrityError` (UNIQUE constraint on `email`).

### Prospect pipeline statuses

```
new → qualified → contacted → replied → booked
                                       → rejected
```

### scorer.py

Wraps the Anthropic SDK. Three public functions:
- `score_prospect(prospect)` — API call only, no DB writes. Returns `{score, reasoning}`.
- `score_and_update(prospect_id)` — scores and writes score + appends `[AI] <reasoning>` to notes.
- `score_all_new()` — bulk scores all prospects with `status="new"`.

Uses `claude-haiku-4-5-20251001` by default (cheap for bulk runs). Change `MODEL` at the top of the file for higher quality. The system prompt is cache-controlled so repeated bulk calls don't re-send it.

### Lead score convention

1-40 = cold, 41-70 = warm, 71-100 = hot. Scores are set by the AI scorer or overridden manually.
