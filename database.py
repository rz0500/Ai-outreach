"""
database.py — Prospect Database Module
=======================================
Module 1 of the AI Lead Generation & Outreach System.

Manages a local SQLite database of sales prospects, including
functions to add, update, query, and search prospect records.

Usage:
    from database import initialize_database, add_prospect, ...
    initialize_database()
    prospect_id = add_prospect(name="Jane Doe", company="Acme Corp", ...)
"""

import sqlite3
from contextlib import contextmanager
from typing import Iterator, Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Path to the SQLite database file. Change this to use a different location.
DB_PATH = "prospects.db"

# All allowed values for the 'status' column.
VALID_STATUSES = {"new", "qualified", "contacted", "replied", "booked", "rejected", "in_sequence"}
VALID_CHANNELS = {"email", "linkedin", "instagram", "x", "sms", "call", "system"}
VALID_DIRECTIONS = {"outbound", "inbound", "internal"}
VALID_SEQUENCE_ENROLLMENT_STATUSES = {"active", "paused", "completed", "cancelled"}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

@contextmanager
def _get_connection(db_path: str = DB_PATH) -> Iterator[sqlite3.Connection]:
    """
    Open a connection to the SQLite database and always close it.

    row_factory=sqlite3.Row means each returned row behaves like a dict,
    so you can access columns by name: row["email"] instead of row[2].
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def initialize_database(db_path: str = DB_PATH) -> None:
    """
    Create the prospects table if it does not already exist.

    Safe to call every time your program starts — it won't overwrite
    existing data (CREATE TABLE IF NOT EXISTS).

    Args:
        db_path: Path to the .db file (created automatically if missing).
    """
    with _get_connection(db_path) as conn:
        # Clients table — one row per workspace (house account = id 1)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS clients (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT    NOT NULL,
                email         TEXT    NOT NULL DEFAULT '',
                status        TEXT    NOT NULL DEFAULT 'active',
                niche         TEXT,
                icp           TEXT,
                calendar_link TEXT,
                created_at    TEXT    DEFAULT (datetime('now'))
            )
        """)
        # Seed the house account so client_id=1 always exists
        conn.execute("""
            INSERT OR IGNORE INTO clients (id, name, email, status)
            VALUES (1, 'House Account', '', 'active')
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS prospects (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                name                 TEXT    NOT NULL,
                company              TEXT    NOT NULL,
                email                TEXT    UNIQUE,
                linkedin_url         TEXT,
                website              TEXT,
                phone                TEXT,
                lead_score           INTEGER DEFAULT 50
                                             CHECK (lead_score BETWEEN 1 AND 100),
                status               TEXT    DEFAULT 'new',
                notes                TEXT,
                date_added           TEXT    DEFAULT (datetime('now')),
                sequence_step        INTEGER DEFAULT 0,
                last_contacted_date  TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS suppression_list (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                email         TEXT    NOT NULL UNIQUE,
                reason        TEXT    NOT NULL,
                source        TEXT    DEFAULT 'manual',
                date_added    TEXT    DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS communication_events (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                prospect_id       INTEGER REFERENCES prospects(id),
                channel          TEXT    NOT NULL,
                direction        TEXT    NOT NULL,
                event_type       TEXT    NOT NULL,
                status           TEXT    NOT NULL,
                content_excerpt  TEXT,
                metadata         TEXT,
                created_at       TEXT    DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sequence_enrollments (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                prospect_id      INTEGER NOT NULL UNIQUE REFERENCES prospects(id),
                sequence_name   TEXT    NOT NULL,
                status          TEXT    DEFAULT 'active',
                enrolled_at     TEXT    DEFAULT (date('now')),
                paused_reason   TEXT,
                updated_at      TEXT    DEFAULT (datetime('now'))
            )
        """)
        # Structured research results — one row per research run
        conn.execute("""
            CREATE TABLE IF NOT EXISTS prospect_research (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                prospect_id      INTEGER NOT NULL REFERENCES prospects(id),
                researched_at    TEXT    DEFAULT (datetime('now')),
                url              TEXT,
                niche            TEXT,
                icp              TEXT,
                website_headline TEXT,
                product_feature  TEXT,
                competitors      TEXT,
                pain_point       TEXT,
                growth_signal    TEXT,
                hook             TEXT,
                raw_analysis     TEXT
            )
        """)
        # Reply drafts — one row per classified inbound reply
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reply_drafts (
                id                       INTEGER PRIMARY KEY AUTOINCREMENT,
                prospect_id              INTEGER NOT NULL REFERENCES prospects(id),
                created_at               TEXT    DEFAULT (datetime('now')),
                inbound_from             TEXT,
                inbound_body             TEXT,
                classification           TEXT,
                classification_reasoning TEXT,
                drafted_reply            TEXT,
                status                   TEXT    DEFAULT 'pending_review'
            )
        """)
        # Migrate existing databases — add any missing columns safely
        enrichment_columns = [
            ("sequence_step",       "INTEGER DEFAULT 0"),
            ("last_contacted_date", "TEXT"),
            # Enrichment fields for hyper-personalized email generation
            ("niche",               "TEXT"),   # What they actually do, specifically
            ("icp",                 "TEXT"),   # Their ideal customer profile
            ("website_headline",    "TEXT"),   # Hero copy / H1 from their homepage
            ("competitors",         "TEXT"),   # Real named competitors (comma-separated)
            ("hiring_signal",       "TEXT"),   # e.g. "Hiring SDR on LinkedIn Apr 2024"
            ("linkedin_activity",   "TEXT"),   # Summary of their most recent post
            ("ad_status",           "TEXT"),   # "running_ads" | "no_ads" | "unknown"
            ("outbound_status",     "TEXT"),   # "active_outbound" | "no_outbound" | "unknown"
            ("notable_result",      "TEXT"),   # Case study / result we can reference in outreach
            ("product_feature",     "TEXT"),   # Specific feature or product angle
        ]
        for col, definition in enrichment_columns:
            try:
                conn.execute(f"ALTER TABLE prospects ADD COLUMN {col} {definition}")
            except sqlite3.OperationalError:
                pass  # column already exists

        # Migrate reply_drafts — add thread-header and sent_at columns
        reply_draft_columns = [
            ("inbound_message_id", "TEXT"),   # Value of the inbound email's Message-ID header
            ("inbound_subject",    "TEXT"),   # Original subject line from the inbound email
            ("sent_at",            "TEXT"),   # Timestamp when the approved reply was sent
        ]
        for col, definition in reply_draft_columns:
            try:
                conn.execute(f"ALTER TABLE reply_drafts ADD COLUMN {col} {definition}")
            except sqlite3.OperationalError:
                pass  # column already exists

        # Multi-tenancy: add client_id to every data table (DEFAULT 1 = house account)
        _client_id_tables = [
            "prospects",
            "suppression_list",
            "communication_events",
            "sequence_enrollments",
            "prospect_research",
            "reply_drafts",
        ]
        for tbl in _client_id_tables:
            try:
                conn.execute(
                    f"ALTER TABLE {tbl} ADD COLUMN client_id INTEGER NOT NULL DEFAULT 1"
                )
            except sqlite3.OperationalError:
                pass  # column already exists

        conn.commit()
        # Client sessions — magic-link auth tokens for client dashboard
        conn.execute("""
            CREATE TABLE IF NOT EXISTS client_sessions (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id  INTEGER NOT NULL REFERENCES clients(id),
                token      TEXT    NOT NULL UNIQUE,
                created_at TEXT    DEFAULT (datetime('now')),
                expires_at TEXT    NOT NULL,
                used       INTEGER NOT NULL DEFAULT 0
            )
        """)

        conn.commit()
    print(f"[DB] Database ready: {db_path}")


# ---------------------------------------------------------------------------
# Client management
# ---------------------------------------------------------------------------

def add_client(
    name: str,
    email: str,
    niche: Optional[str] = None,
    icp: Optional[str] = None,
    calendar_link: Optional[str] = None,
    db_path: str = DB_PATH,
) -> int:
    """
    Create a new client workspace.

    Returns:
        The integer ID of the newly created client record.
    """
    with _get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO clients (name, email, niche, icp, calendar_link, status)
            VALUES (?, ?, ?, ?, ?, 'active')
            """,
            (name.strip(), email.strip().lower(), niche, icp, calendar_link),
        )
        conn.commit()
        return cursor.lastrowid


def get_client(client_id: int, db_path: str = DB_PATH) -> Optional[dict]:
    """Return a client record by ID, or None if not found."""
    with _get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM clients WHERE id = ?", (client_id,)
        ).fetchone()
        return dict(row) if row else None


def get_all_clients(db_path: str = DB_PATH) -> list:
    """Return all client records, newest first."""
    with _get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM clients ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_active_clients(db_path: str = DB_PATH) -> list:
    """Return all clients with status='active'."""
    with _get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM clients WHERE status = 'active' ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_client_by_email(email: str, db_path: str = DB_PATH) -> Optional[dict]:
    """Return a client record by email address, or None if not found."""
    normalized = (email or "").strip().lower()
    with _get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM clients WHERE lower(email) = ?", (normalized,)
        ).fetchone()
        return dict(row) if row else None


def update_client(
    client_id: int,
    name: Optional[str] = None,
    email: Optional[str] = None,
    status: Optional[str] = None,
    niche: Optional[str] = None,
    icp: Optional[str] = None,
    calendar_link: Optional[str] = None,
    db_path: str = DB_PATH,
) -> bool:
    """Update any subset of fields on a client record. Returns True if found."""
    fields: list[tuple] = []
    if name          is not None: fields.append(("name", name.strip()))
    if email         is not None: fields.append(("email", email.strip().lower()))
    if status        is not None: fields.append(("status", status))
    if niche         is not None: fields.append(("niche", niche))
    if icp           is not None: fields.append(("icp", icp))
    if calendar_link is not None: fields.append(("calendar_link", calendar_link))
    if not fields:
        return False
    set_clause = ", ".join(f"{col} = ?" for col, _ in fields)
    values = [v for _, v in fields] + [client_id]
    with _get_connection(db_path) as conn:
        cursor = conn.execute(
            f"UPDATE clients SET {set_clause} WHERE id = ?", values
        )
        conn.commit()
        return cursor.rowcount > 0


def get_client_analytics(client_id: int, db_path: str = DB_PATH) -> dict:
    """
    Return pipeline analytics for a single client workspace.

    Keys: total_prospects, emails_sent, replies, booked, recent_events.
    """
    with _get_connection(db_path) as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM prospects WHERE client_id = ?", (client_id,)
        ).fetchone()[0]
        emails_sent = conn.execute(
            "SELECT COUNT(*) FROM outreach WHERE client_id = ? AND status = 'sent'",
            (client_id,),
        ).fetchone()[0]
        replies = conn.execute(
            "SELECT COUNT(*) FROM prospects WHERE client_id = ? AND status = 'replied'",
            (client_id,),
        ).fetchone()[0]
        booked = conn.execute(
            "SELECT COUNT(*) FROM prospects WHERE client_id = ? AND status = 'booked'",
            (client_id,),
        ).fetchone()[0]
        events = conn.execute(
            """
            SELECT ce.event_type, ce.channel, ce.status, ce.created_at,
                   p.name AS prospect_name, p.company AS prospect_company
            FROM communication_events ce
            JOIN prospects p ON p.id = ce.prospect_id
            WHERE ce.client_id = ?
            ORDER BY ce.created_at DESC, ce.id DESC
            LIMIT 20
            """,
            (client_id,),
        ).fetchall()
    return {
        "total_prospects": total,
        "emails_sent": emails_sent,
        "replies": replies,
        "booked": booked,
        "recent_events": [dict(r) for r in events],
    }


def add_prospect(
    name: str,
    company: str,
    email: Optional[str] = None,
    linkedin_url: Optional[str] = None,
    website: Optional[str] = None,
    phone: Optional[str] = None,
    lead_score: int = 50,
    status: str = "new",
    notes: Optional[str] = None,
    client_id: int = 1,
    db_path: str = DB_PATH,
) -> int:
    """
    Insert a new prospect into the database.

    Args:
        name:         Full name of the prospect (required).
        company:      Company they work at (required).
        email:        Business email address.
        linkedin_url: Full LinkedIn profile URL.
        website:      Company website URL.
        phone:        Phone number as a string (e.g. "+1-415-555-0100").
        lead_score:   Quality score from 1 (cold) to 100 (very hot). Default 50.
        status:       One of: new, qualified, contacted, replied, booked, rejected.
        notes:        Free-text notes about the prospect.
        client_id:    Workspace owner. Defaults to 1 (house account).
        db_path:      Path to the database file.

    Returns:
        The integer ID of the newly created record.

    Raises:
        ValueError: If status or lead_score are out of range.
        sqlite3.IntegrityError: If the email address already exists.
    """
    if status not in VALID_STATUSES:
        raise ValueError(
            f"Invalid status '{status}'. Choose from: {sorted(VALID_STATUSES)}"
        )
    if not (1 <= lead_score <= 100):
        raise ValueError(f"lead_score must be 1–100, got {lead_score}.")

    with _get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO prospects
                (name, company, email, linkedin_url, website,
                 phone, lead_score, status, notes, client_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (name, company, email, linkedin_url, website,
             phone, lead_score, status, notes, client_id),
        )
        conn.commit()
        return cursor.lastrowid


def update_lead_score(
    prospect_id: int,
    new_score: int,
    db_path: str = DB_PATH,
) -> bool:
    """
    Change the lead score for a specific prospect.

    Args:
        prospect_id: The ID of the prospect to update.
        new_score:   New score value (1–100).
        db_path:     Path to the database file.

    Returns:
        True if the prospect was found and updated, False if not found.

    Raises:
        ValueError: If new_score is outside 1–100.
    """
    if not (1 <= new_score <= 100):
        raise ValueError(f"lead_score must be 1–100, got {new_score}.")

    with _get_connection(db_path) as conn:
        cursor = conn.execute(
            "UPDATE prospects SET lead_score = ? WHERE id = ?",
            (new_score, prospect_id),
        )
        conn.commit()
        return cursor.rowcount > 0  # rowcount == 0 means no matching ID was found


def update_status(
    prospect_id: int,
    new_status: str,
    db_path: str = DB_PATH,
) -> bool:
    """
    Change the pipeline status for a specific prospect.

    Pipeline flow (typical):
        new → qualified → contacted → replied → booked
                                              → rejected

    Args:
        prospect_id: The ID of the prospect to update.
        new_status:  One of: new, qualified, contacted, replied, booked, rejected.
        db_path:     Path to the database file.

    Returns:
        True if updated, False if the prospect ID was not found.

    Raises:
        ValueError: If new_status is not a recognised value.
    """
    if new_status not in VALID_STATUSES:
        raise ValueError(
            f"Invalid status '{new_status}'. Choose from: {sorted(VALID_STATUSES)}"
        )

    with _get_connection(db_path) as conn:
        cursor = conn.execute(
            "UPDATE prospects SET status = ? WHERE id = ?",
            (new_status, prospect_id),
        )
        conn.commit()
        return cursor.rowcount > 0


def update_enrichment_fields(
    prospect_id: int,
    fields: dict,
    db_path: str = DB_PATH,
) -> bool:
    """
    Update any subset of the enrichment columns for a prospect.

    Only non-empty string values are written. Fields not in the allowed set
    are silently ignored so callers can pass a raw AI result dict safely.

    Allowed keys: niche, icp, website_headline, competitors, hiring_signal,
                  linkedin_activity, ad_status, outbound_status,
                  notable_result, product_feature.

    Returns:
        True if the prospect was found and at least one column updated.
    """
    ALLOWED = {
        "niche", "icp", "website_headline", "competitors", "hiring_signal",
        "linkedin_activity", "ad_status", "outbound_status",
        "notable_result", "product_feature",
    }
    to_update = {k: v for k, v in fields.items() if k in ALLOWED and v}
    if not to_update:
        return False

    set_clause = ", ".join(f"{col} = ?" for col in to_update)
    values = list(to_update.values()) + [prospect_id]

    with _get_connection(db_path) as conn:
        cursor = conn.execute(
            f"UPDATE prospects SET {set_clause} WHERE id = ?",
            values,
        )
        conn.commit()
        return cursor.rowcount > 0


def update_notes(
    prospect_id: int,
    notes: str,
    db_path: str = DB_PATH,
) -> bool:
    """
    Replace the notes field for a specific prospect.

    To append rather than overwrite, read the existing notes first and
    pass the combined string here.

    Args:
        prospect_id: The ID of the prospect to update.
        notes:       The new notes string (replaces the current value).
        db_path:     Path to the database file.

    Returns:
        True if updated, False if the prospect ID was not found.
    """
    with _get_connection(db_path) as conn:
        cursor = conn.execute(
            "UPDATE prospects SET notes = ? WHERE id = ?",
            (notes, prospect_id),
        )
        conn.commit()
        return cursor.rowcount > 0


def update_prospect_email(
    prospect_id: int,
    email: str,
    db_path: str = DB_PATH,
) -> bool:
    """
    Set the email address on a prospect record. Only writes if the address
    is non-empty and the prospect does not already have one stored.

    Returns:
        True if the field was updated, False otherwise.
    """
    if not email:
        return False
    with _get_connection(db_path) as conn:
        cursor = conn.execute(
            "UPDATE prospects SET email = ? WHERE id = ? AND (email IS NULL OR email = '')",
            (email.strip().lower(), prospect_id),
        )
        conn.commit()
        return cursor.rowcount > 0


def update_prospect(
    prospect_id: int,
    name: Optional[str] = None,
    company: Optional[str] = None,
    email: Optional[str] = None,
    linkedin_url: Optional[str] = None,
    website: Optional[str] = None,
    phone: Optional[str] = None,
    lead_score: Optional[int] = None,
    status: Optional[str] = None,
    notes: Optional[str] = None,
    db_path: str = DB_PATH,
) -> bool:
    """
    Update any subset of fields on an existing prospect.
    Only non-None arguments are written. Returns True if the row was found.
    """
    fields: list[tuple] = []
    if name         is not None: fields.append(("name", name))
    if company      is not None: fields.append(("company", company))
    if email        is not None: fields.append(("email", email.strip().lower()))
    if linkedin_url is not None: fields.append(("linkedin_url", linkedin_url))
    if website      is not None: fields.append(("website", website))
    if phone        is not None: fields.append(("phone", phone))
    if notes        is not None: fields.append(("notes", notes))
    if lead_score   is not None:
        if not (1 <= lead_score <= 100):
            raise ValueError(f"lead_score must be 1-100, got {lead_score}.")
        fields.append(("lead_score", lead_score))
    if status is not None:
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid status '{status}'.")
        fields.append(("status", status))

    if not fields:
        return False

    set_clause = ", ".join(f"{col} = ?" for col, _ in fields)
    values = [v for _, v in fields] + [prospect_id]

    with _get_connection(db_path) as conn:
        cursor = conn.execute(
            f"UPDATE prospects SET {set_clause} WHERE id = ?",
            values,
        )
        conn.commit()
        return cursor.rowcount > 0


def delete_prospect(prospect_id: int, db_path: str = DB_PATH) -> bool:
    """
    Hard-delete a prospect and all related outreach records.
    Returns True if the prospect was found and removed.
    """
    with _get_connection(db_path) as conn:
        conn.execute("DELETE FROM outreach WHERE prospect_id = ?", (prospect_id,))
        conn.execute("DELETE FROM communication_events WHERE prospect_id = ?", (prospect_id,))
        conn.execute("DELETE FROM sequence_enrollments WHERE prospect_id = ?", (prospect_id,))
        conn.execute("DELETE FROM reply_drafts WHERE prospect_id = ?", (prospect_id,))
        conn.execute("DELETE FROM prospect_research WHERE prospect_id = ?", (prospect_id,))
        cursor = conn.execute("DELETE FROM prospects WHERE id = ?", (prospect_id,))
        conn.commit()
        return cursor.rowcount > 0


def get_all_prospects(client_id: int = 1, db_path: str = DB_PATH) -> list:
    """
    Retrieve every prospect for a given client workspace.

    Returns:
        A list of dicts, sorted by lead_score descending (highest first).
        Each dict has keys matching the table columns.
    """
    with _get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM prospects WHERE client_id = ? ORDER BY lead_score DESC",
            (client_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def get_prospects_by_min_score(
    min_score: int,
    client_id: int = 1,
    db_path: str = DB_PATH,
) -> list:
    """
    Retrieve prospects whose lead_score is at or above a threshold.

    Args:
        min_score: Only return prospects with lead_score >= this value.
        client_id: Filter to this workspace (default: house account).
        db_path:   Path to the database file.

    Returns:
        A list of dicts, sorted by lead_score descending.
    """
    with _get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM prospects WHERE lead_score >= ? AND client_id = ? ORDER BY lead_score DESC",
            (min_score, client_id),
        ).fetchall()
        return [dict(row) for row in rows]


def search_by_company(
    company_name: str,
    client_id: int = 1,
    db_path: str = DB_PATH,
) -> list:
    """
    Find prospects whose company name contains a search term.

    Args:
        company_name: The search term to look for inside the company field.
        client_id:    Filter to this workspace (default: house account).
        db_path:      Path to the database file.

    Returns:
        A list of matching prospect dicts (may be empty).
    """
    with _get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM prospects WHERE company LIKE ? AND client_id = ? ORDER BY lead_score DESC",
            (f"%{company_name}%", client_id),
        ).fetchall()
        return [dict(row) for row in rows]


def get_prospects_in_sequence(client_id: int = 1, db_path: str = DB_PATH) -> list:
    """
    Return all prospects currently enrolled in the follow-up sequence
    for a given client workspace.

    Returns:
        A list of prospect dicts with status='in_sequence', ordered by
        last_contacted_date ascending (longest-waiting first).
    """
    with _get_connection(db_path) as conn:
        rows = conn.execute("""
            SELECT * FROM prospects
            WHERE status = 'in_sequence'
              AND client_id = ?
              AND (email IS NULL OR lower(email) NOT IN (
                    SELECT lower(email) FROM suppression_list
              ))
            ORDER BY last_contacted_date ASC
        """, (client_id,)).fetchall()
        return [dict(row) for row in rows]


def update_sequence_progress(
    prospect_id: int,
    sequence_step: int,
    last_contacted_date: str,
    db_path: str = DB_PATH,
) -> bool:
    """
    Record that a sequence step was sent for a prospect.

    Args:
        prospect_id:         The prospect to update.
        sequence_step:       The step number just completed (1, 2, 3, …).
        last_contacted_date: ISO date string for when the step was sent (YYYY-MM-DD).
        db_path:             Path to the database file.

    Returns:
        True if the record was found and updated, False otherwise.
    """
    with _get_connection(db_path) as conn:
        cursor = conn.execute(
            """UPDATE prospects
               SET sequence_step = ?, last_contacted_date = ?
               WHERE id = ?""",
            (sequence_step, last_contacted_date, prospect_id),
        )
        conn.commit()
        return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# Outreach table
# ---------------------------------------------------------------------------

def get_prospect_by_email(email: str, db_path: str = DB_PATH) -> Optional[dict]:
    """
    Retrieve a single prospect by their exact email address.

    Args:
        email:   The email address to search for.
        db_path: Path to the database file.

    Returns:
        A dict containing the prospect's data, or None if not found.
    """
    with _get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM prospects WHERE email = ?", (email,)
        ).fetchone()
        return dict(row) if row else None


def is_suppressed(email: str, db_path: str = DB_PATH) -> bool:
    """Return True if the given email exists in the suppression list."""
    normalized = (email or "").strip().lower()
    if not normalized:
        return False

    with _get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM suppression_list WHERE lower(email) = ?",
            (normalized,),
        ).fetchone()
        return row is not None


def suppress_contact(
    email: str,
    reason: str,
    source: str = "manual",
    db_path: str = DB_PATH,
) -> bool:
    """
    Add an email address to the suppression list.

    Returns:
        True if a new suppression record was created, False if it already existed.
    """
    normalized = (email or "").strip().lower()
    if not normalized:
        raise ValueError("email is required to suppress a contact")
    if not reason.strip():
        raise ValueError("reason is required to suppress a contact")

    with _get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO suppression_list (email, reason, source)
            VALUES (?, ?, ?)
            """,
            (normalized, reason.strip(), source.strip() or "manual"),
        )
        conn.commit()
        return cursor.rowcount > 0


def suppress_prospect(
    prospect_id: int,
    reason: str,
    source: str = "manual",
    db_path: str = DB_PATH,
) -> bool:
    """
    Suppress a prospect by email and move them to rejected status.

    Returns:
        True if the prospect had an email and was newly added to the suppression list.
    """
    with _get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM prospects WHERE id = ?", (prospect_id,)
        ).fetchone()
    prospect = dict(row) if row else None
    if not prospect:
        raise ValueError(f"No prospect found with id={prospect_id}")

    email = prospect.get("email")
    if not email:
        return False

    created = suppress_contact(email, reason, source=source, db_path=db_path)
    update_status(prospect_id, "rejected", db_path)
    return created


def get_suppressed_contacts(db_path: str = DB_PATH) -> list:
    """Return all suppressed contacts, newest first."""
    with _get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM suppression_list ORDER BY date_added DESC"
        ).fetchall()
        return [dict(row) for row in rows]


def log_communication_event(
    prospect_id: Optional[int],
    channel: str,
    direction: str,
    event_type: str,
    status: str,
    content_excerpt: Optional[str] = None,
    metadata: Optional[str] = None,
    client_id: int = 1,
    db_path: str = DB_PATH,
) -> int:
    """
    Log an outbound or inbound communication event for auditing/reporting.
    """
    if channel not in VALID_CHANNELS:
        raise ValueError(f"Invalid channel '{channel}'. Choose from: {sorted(VALID_CHANNELS)}")
    if direction not in VALID_DIRECTIONS:
        raise ValueError(f"Invalid direction '{direction}'. Choose from: {sorted(VALID_DIRECTIONS)}")

    with _get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO communication_events
                (prospect_id, channel, direction, event_type, status,
                 content_excerpt, metadata, client_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (prospect_id, channel, direction, event_type, status,
             content_excerpt, metadata, client_id),
        )
        conn.commit()
        return cursor.lastrowid


def get_communication_events(
    prospect_id: Optional[int] = None,
    db_path: str = DB_PATH,
) -> list:
    """Return communication events, optionally filtered to one prospect."""
    with _get_connection(db_path) as conn:
        if prospect_id is None:
            rows = conn.execute(
                "SELECT * FROM communication_events ORDER BY created_at DESC, id DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM communication_events
                WHERE prospect_id = ?
                ORDER BY created_at DESC, id DESC
                """,
                (prospect_id,),
            ).fetchall()
        return [dict(row) for row in rows]


def ensure_sequence_enrollment(
    prospect_id: int,
    sequence_name: str = "default_multichannel",
    db_path: str = DB_PATH,
) -> int:
    """
    Ensure a prospect has a sequence enrollment record and return its ID.
    """
    with _get_connection(db_path) as conn:
        existing = conn.execute(
            "SELECT id FROM sequence_enrollments WHERE prospect_id = ?",
            (prospect_id,),
        ).fetchone()
        if existing:
            return int(existing["id"])

        cursor = conn.execute(
            """
            INSERT INTO sequence_enrollments (prospect_id, sequence_name, status)
            VALUES (?, ?, 'active')
            """,
            (prospect_id, sequence_name),
        )
        conn.commit()
        return cursor.lastrowid


def get_sequence_enrollment(
    prospect_id: int,
    db_path: str = DB_PATH,
) -> Optional[dict]:
    """Return a prospect's sequence enrollment, if one exists."""
    with _get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM sequence_enrollments WHERE prospect_id = ?",
            (prospect_id,),
        ).fetchone()
        return dict(row) if row else None


def get_active_sequence_enrollments(
    db_path: str = DB_PATH,
    sequence_name: Optional[str] = None,
    client_id: int = 1,
) -> list:
    """
    Return active sequence enrollments joined with prospect data,
    filtered to a single client workspace.
    """
    sql = """
        SELECT
            se.id AS enrollment_id,
            se.sequence_name,
            se.status AS enrollment_status,
            se.enrolled_at,
            se.paused_reason,
            se.updated_at AS enrollment_updated_at,
            p.*
        FROM sequence_enrollments se
        JOIN prospects p ON p.id = se.prospect_id
        WHERE se.status = 'active'
          AND p.client_id = ?
    """
    params: list = [client_id]
    if sequence_name:
        sql += " AND se.sequence_name = ?"
        params.append(sequence_name)
    sql += """
          AND p.status = 'in_sequence'
          AND (p.email IS NULL OR lower(p.email) NOT IN (
                SELECT lower(email) FROM suppression_list
          ))
        ORDER BY se.enrolled_at ASC, se.id ASC
    """
    with _get_connection(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]


def update_sequence_enrollment_status(
    prospect_id: int,
    new_status: str,
    paused_reason: Optional[str] = None,
    db_path: str = DB_PATH,
) -> bool:
    """
    Update the status of a sequence enrollment.
    """
    if new_status not in VALID_SEQUENCE_ENROLLMENT_STATUSES:
        raise ValueError(
            f"Invalid sequence enrollment status '{new_status}'. "
            f"Choose from: {sorted(VALID_SEQUENCE_ENROLLMENT_STATUSES)}"
        )

    with _get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            UPDATE sequence_enrollments
            SET status = ?, paused_reason = ?, updated_at = datetime('now')
            WHERE prospect_id = ?
            """,
            (new_status, paused_reason, prospect_id),
        )
        conn.commit()
        return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# Outreach table
# ---------------------------------------------------------------------------

VALID_OUTREACH_STATUSES = {"draft", "approved", "sent"}


def initialize_outreach_table(db_path: str = DB_PATH) -> None:
    """
    Create the outreach table if it does not already exist.

    Each row is one email draft tied to a prospect.
    Call this once at the start of any outreach operation.
    """
    with _get_connection(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS outreach (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                prospect_id  INTEGER NOT NULL REFERENCES prospects(id),
                subject      TEXT    NOT NULL,
                body         TEXT    NOT NULL,
                status       TEXT    DEFAULT 'draft',
                date_created TEXT    DEFAULT (datetime('now'))
            )
        """)
        # Migrate: add sent_at, pdf_path, and client_id columns
        for col in ("sent_at TEXT", "pdf_path TEXT",
                    "client_id INTEGER NOT NULL DEFAULT 1"):
            try:
                conn.execute(f"ALTER TABLE outreach ADD COLUMN {col}")
            except sqlite3.OperationalError:
                pass  # column already exists
        conn.commit()


def save_outreach(
    prospect_id: int,
    subject: str,
    body: str,
    pdf_path: str = "",
    client_id: int = 1,
    db_path: str = DB_PATH,
) -> int:
    """
    Save a new email draft to the outreach table.

    Args:
        prospect_id: ID of the prospect this email is for.
        subject:     Email subject line.
        body:        Email body text.
        pdf_path:    Optional path to a PDF proposal to attach when sending.
        client_id:   Workspace owner. Defaults to 1 (house account).
        db_path:     Path to the database file.

    Returns:
        The ID of the newly created outreach record.
    """
    with _get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO outreach (prospect_id, subject, body, pdf_path, client_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (prospect_id, subject, body, pdf_path or "", client_id),
        )
        conn.commit()
        return cursor.lastrowid


def get_all_outreach(client_id: int = 1, db_path: str = DB_PATH) -> list:
    """
    Return all outreach records for a client workspace, joined with prospect data.

    Returns:
        A list of dicts with outreach fields plus 'prospect_name' and
        'prospect_company', sorted by date_created descending.
    """
    with _get_connection(db_path) as conn:
        rows = conn.execute("""
            SELECT
                o.*,
                p.name    AS prospect_name,
                p.company AS prospect_company,
                p.lead_score
            FROM outreach o
            JOIN prospects p ON p.id = o.prospect_id
            WHERE o.client_id = ?
            ORDER BY o.date_created DESC
        """, (client_id,)).fetchall()
        return [dict(row) for row in rows]


def get_sent_outreach(client_id: int = 1, db_path: str = DB_PATH) -> list:
    """
    Return all outreach records with status='sent' for a client workspace.
    Includes the prospect's current status so the tracker can show 'replied'.
    Sorted most-recent-send first.
    """
    with _get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                o.id, o.prospect_id, o.subject, o.body,
                o.status AS outreach_status,
                o.sent_at, o.date_created,
                p.name    AS prospect_name,
                p.company AS prospect_company,
                p.email   AS prospect_email,
                p.website AS prospect_website,
                p.status  AS prospect_status
            FROM outreach o
            JOIN prospects p ON p.id = o.prospect_id
            WHERE o.status = 'sent' AND o.client_id = ?
            ORDER BY o.sent_at DESC, o.date_created DESC
            """,
            (client_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def get_outreach_by_prospect(prospect_id: int, db_path: str = DB_PATH) -> list:
    """Return all outreach records for a specific prospect."""
    with _get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM outreach WHERE prospect_id = ? ORDER BY date_created DESC",
            (prospect_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def update_outreach_status(
    outreach_id: int,
    new_status: str,
    db_path: str = DB_PATH,
) -> bool:
    """
    Update the status of an outreach record.

    Args:
        outreach_id: ID of the outreach record.
        new_status:  One of: draft, approved, sent.
        db_path:     Path to the database file.

    Returns:
        True if updated, False if the record was not found.

    Raises:
        ValueError: If new_status is not a valid value.
    """
    if new_status not in VALID_OUTREACH_STATUSES:
        raise ValueError(
            f"Invalid status '{new_status}'. "
            f"Choose from: {sorted(VALID_OUTREACH_STATUSES)}"
        )
    with _get_connection(db_path) as conn:
        if new_status == "sent":
            cursor = conn.execute(
                "UPDATE outreach SET status = ?, sent_at = datetime('now') WHERE id = ?",
                (new_status, outreach_id),
            )
        else:
            cursor = conn.execute(
                "UPDATE outreach SET status = ? WHERE id = ?",
                (new_status, outreach_id),
            )
        conn.commit()
        return cursor.rowcount > 0


def get_draft_outreach(client_id: int = 1, db_path: str = DB_PATH) -> list:
    """
    Return all outreach records with status='draft' for a client workspace,
    joined with the prospect's name, company, and email.
    Sorted oldest-first so the review queue shows leads in arrival order.
    """
    with _get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                o.id, o.prospect_id, o.subject, o.body,
                o.status, o.date_created, o.pdf_path,
                p.name    AS prospect_name,
                p.company AS prospect_company,
                p.email   AS prospect_email,
                p.website AS prospect_website
            FROM outreach o
            JOIN prospects p ON p.id = o.prospect_id
            WHERE o.status = 'draft' AND o.client_id = ?
            ORDER BY o.date_created ASC
            """,
            (client_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def delete_outreach(outreach_id: int, db_path: str = DB_PATH) -> bool:
    """Delete an outreach record by ID. Returns True if a row was deleted."""
    with _get_connection(db_path) as conn:
        cursor = conn.execute("DELETE FROM outreach WHERE id = ?", (outreach_id,))
        conn.commit()
        return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# Research persistence
# ---------------------------------------------------------------------------

def save_research_result(
    prospect_id: int,
    analysis: dict,
    url: str = "",
    db_path: str = DB_PATH,
) -> int:
    """
    Persist a structured research result for a prospect.

    Stores every field from Claude's analysis individually so they can be
    queried without parsing notes text. Also keeps the full analysis JSON
    as raw_analysis for auditing.

    Returns:
        The ID of the newly created research record.
    """
    import json as _json
    with _get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO prospect_research
                (prospect_id, url, niche, icp, website_headline,
                 product_feature, competitors, pain_point, growth_signal, hook, raw_analysis)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                prospect_id,
                url or "",
                analysis.get("niche", ""),
                analysis.get("icp", ""),
                analysis.get("website_headline", ""),
                analysis.get("product_feature", ""),
                analysis.get("competitors", ""),
                analysis.get("pain_point", ""),
                analysis.get("growth_signal", ""),
                analysis.get("hook", ""),
                _json.dumps(analysis),
            ),
        )
        conn.commit()
        return cursor.lastrowid


def get_latest_research(
    prospect_id: int,
    db_path: str = DB_PATH,
) -> Optional[dict]:
    """Return the most recent research record for a prospect, or None."""
    with _get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT * FROM prospect_research
            WHERE prospect_id = ?
            ORDER BY researched_at DESC, id DESC
            LIMIT 1
            """,
            (prospect_id,),
        ).fetchone()
        return dict(row) if row else None


def get_research_history(
    prospect_id: int,
    db_path: str = DB_PATH,
) -> list:
    """Return all research records for a prospect, newest first."""
    with _get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM prospect_research
            WHERE prospect_id = ?
            ORDER BY researched_at DESC, id DESC
            """,
            (prospect_id,),
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Reply drafts
# ---------------------------------------------------------------------------

VALID_REPLY_DRAFT_STATUSES = {"pending_review", "approved", "sent", "dismissed"}


def save_reply_draft(
    prospect_id: int,
    inbound_from: str,
    inbound_body: str,
    classification: str,
    classification_reasoning: str,
    drafted_reply: str,
    inbound_message_id: str = "",
    inbound_subject: str = "",
    client_id: int = 1,
    db_path: str = DB_PATH,
) -> int:
    """
    Persist a classified inbound reply and its AI-drafted response.

    Stores the original reply body, the classification, the reasoning, and
    the suggested reply so they can be reviewed and approved in the UI.

    Args:
        inbound_message_id: The Message-ID header from the inbound email, used to
                            set In-Reply-To / References when sending the reply.
        inbound_subject:    The Subject header from the inbound email, used to
                            build a proper Re: subject line on the outgoing reply.
        client_id:          Workspace owner. Defaults to 1 (house account).

    Returns:
        The ID of the newly created reply_draft record.
    """
    with _get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO reply_drafts
                (prospect_id, inbound_from, inbound_body,
                 classification, classification_reasoning, drafted_reply,
                 inbound_message_id, inbound_subject, client_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                prospect_id,
                inbound_from or "",
                inbound_body or "",
                classification or "",
                classification_reasoning or "",
                drafted_reply or "",
                inbound_message_id or "",
                inbound_subject or "",
                client_id,
            ),
        )
        conn.commit()
        return cursor.lastrowid


def get_pending_reply_drafts(client_id: int = 1, db_path: str = DB_PATH) -> list:
    """
    Return all reply drafts with status='pending_review' for a client workspace.

    Sorted by created_at ascending so oldest replies surface first.
    """
    with _get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                rd.*,
                p.name    AS prospect_name,
                p.company AS prospect_company,
                p.email   AS prospect_email,
                p.lead_score
            FROM reply_drafts rd
            JOIN prospects p ON p.id = rd.prospect_id
            WHERE rd.status = 'pending_review'
              AND rd.drafted_reply != ''
              AND rd.client_id = ?
            ORDER BY rd.created_at ASC
            """,
            (client_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_sent_reply_drafts(client_id: int = 1, db_path: str = DB_PATH) -> list:
    """
    Return all reply drafts with status='sent' for a client workspace.
    Sorted most-recently-sent first.
    """
    with _get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                rd.*,
                p.name    AS prospect_name,
                p.company AS prospect_company,
                p.email   AS prospect_email,
                p.status  AS prospect_status
            FROM reply_drafts rd
            JOIN prospects p ON p.id = rd.prospect_id
            WHERE rd.status = 'sent'
              AND rd.client_id = ?
            ORDER BY rd.sent_at DESC, rd.created_at DESC
            """,
            (client_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_reply_drafts_for_prospect(
    prospect_id: int,
    db_path: str = DB_PATH,
) -> list:
    """Return all reply drafts for a specific prospect, newest first."""
    with _get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM reply_drafts
            WHERE prospect_id = ?
            ORDER BY created_at DESC
            """,
            (prospect_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_reply_draft_by_id(
    draft_id: int,
    db_path: str = DB_PATH,
) -> Optional[dict]:
    """Return one reply draft joined with prospect data, or None if missing."""
    with _get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT
                rd.*,
                p.name    AS prospect_name,
                p.company AS prospect_company,
                p.email   AS prospect_email,
                p.status  AS prospect_status,
                p.lead_score
            FROM reply_drafts rd
            JOIN prospects p ON p.id = rd.prospect_id
            WHERE rd.id = ?
            LIMIT 1
            """,
            (draft_id,),
        ).fetchone()
        return dict(row) if row else None


# ---------------------------------------------------------------------------
# Client session management (magic-link auth)
# ---------------------------------------------------------------------------

def create_client_session(
    client_id: int,
    token: str,
    expires_at: str,
    db_path: str = DB_PATH,
) -> int:
    """
    Persist a new magic-link session token.

    Args:
        client_id:  The client this token grants access to.
        token:      A UUID string generated by the caller.
        expires_at: ISO datetime string (UTC) when the token expires.

    Returns:
        The ID of the new session record.
    """
    with _get_connection(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO client_sessions (client_id, token, expires_at) VALUES (?, ?, ?)",
            (client_id, token, expires_at),
        )
        conn.commit()
        return cursor.lastrowid


def get_client_session(token: str, db_path: str = DB_PATH) -> Optional[dict]:
    """Return a session record by token, or None if not found."""
    with _get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM client_sessions WHERE token = ?", (token,)
        ).fetchone()
        return dict(row) if row else None


def mark_session_used(token: str, db_path: str = DB_PATH) -> None:
    """Mark a session token as used so it cannot be replayed."""
    with _get_connection(db_path) as conn:
        conn.execute(
            "UPDATE client_sessions SET used = 1 WHERE token = ?", (token,)
        )
        conn.commit()


def update_reply_draft_status(
    draft_id: int,
    new_status: str,
    db_path: str = DB_PATH,
) -> bool:
    """
    Update the review status of a reply draft.

    Valid statuses: pending_review → approved → sent  (or dismissed at any point).
    """
    if new_status not in VALID_REPLY_DRAFT_STATUSES:
        raise ValueError(
            f"Invalid reply draft status '{new_status}'. "
            f"Choose from: {sorted(VALID_REPLY_DRAFT_STATUSES)}"
        )
    with _get_connection(db_path) as conn:
        if new_status == "sent":
            cursor = conn.execute(
                "UPDATE reply_drafts SET status = ?, sent_at = datetime('now') WHERE id = ?",
                (new_status, draft_id),
            )
        else:
            cursor = conn.execute(
                "UPDATE reply_drafts SET status = ? WHERE id = ?",
                (new_status, draft_id),
            )
        conn.commit()
        return cursor.rowcount > 0
