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
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Path to the SQLite database file. Change this to use a different location.
DB_PATH = "prospects.db"

# All allowed values for the 'status' column.
VALID_STATUSES = {"new", "qualified", "contacted", "replied", "booked", "rejected"}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    """
    Open a connection to the SQLite database.

    row_factory=sqlite3.Row means each returned row behaves like a dict,
    so you can access columns by name: row["email"] instead of row[2].
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS prospects (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                name         TEXT    NOT NULL,
                company      TEXT    NOT NULL,
                email        TEXT    UNIQUE,
                linkedin_url TEXT,
                website      TEXT,
                phone        TEXT,
                lead_score   INTEGER DEFAULT 50
                                     CHECK (lead_score BETWEEN 1 AND 100),
                status       TEXT    DEFAULT 'new',
                notes        TEXT,
                date_added   TEXT    DEFAULT (datetime('now'))
            )
        """)
        conn.commit()
    print(f"[DB] Database ready: {db_path}")


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
                 phone, lead_score, status, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (name, company, email, linkedin_url, website,
             phone, lead_score, status, notes),
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


def get_all_prospects(db_path: str = DB_PATH) -> list:
    """
    Retrieve every prospect in the database.

    Returns:
        A list of dicts, sorted by lead_score descending (highest first).
        Each dict has keys matching the table columns.
    """
    with _get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM prospects ORDER BY lead_score DESC"
        ).fetchall()
        return [dict(row) for row in rows]


def get_prospects_by_min_score(min_score: int, db_path: str = DB_PATH) -> list:
    """
    Retrieve prospects whose lead_score is at or above a threshold.

    Useful for filtering out cold leads when deciding who to contact next.

    Args:
        min_score: Only return prospects with lead_score >= this value.
        db_path:   Path to the database file.

    Returns:
        A list of dicts, sorted by lead_score descending.
    """
    with _get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM prospects WHERE lead_score >= ? ORDER BY lead_score DESC",
            (min_score,),
        ).fetchall()
        return [dict(row) for row in rows]


def search_by_company(company_name: str, db_path: str = DB_PATH) -> list:
    """
    Find prospects whose company name contains a search term.

    The search is case-insensitive and matches partial names, so
    searching "acme" will match "Acme Corp", "AcmeSaaS", etc.

    Args:
        company_name: The search term to look for inside the company field.
        db_path:      Path to the database file.

    Returns:
        A list of matching prospect dicts (may be empty).
    """
    with _get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM prospects WHERE company LIKE ? ORDER BY lead_score DESC",
            (f"%{company_name}%",),
        ).fetchall()
        return [dict(row) for row in rows]


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
        conn.commit()


def save_outreach(
    prospect_id: int,
    subject: str,
    body: str,
    db_path: str = DB_PATH,
) -> int:
    """
    Save a new email draft to the outreach table.

    Args:
        prospect_id: ID of the prospect this email is for.
        subject:     Email subject line.
        body:        Email body text.
        db_path:     Path to the database file.

    Returns:
        The ID of the newly created outreach record.
    """
    with _get_connection(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO outreach (prospect_id, subject, body) VALUES (?, ?, ?)",
            (prospect_id, subject, body),
        )
        conn.commit()
        return cursor.lastrowid


def get_all_outreach(db_path: str = DB_PATH) -> list:
    """
    Return all outreach records joined with their prospect's name and company.

    Returns:
        A list of dicts with outreach fields plus 'prospect_name' and
        'prospect_company', sorted by date_created descending.
    """
    with _get_connection(db_path) as conn:
        rows = conn.execute("""
            SELECT
                o.id, o.prospect_id, o.subject, o.body,
                o.status, o.date_created,
                p.name  AS prospect_name,
                p.company AS prospect_company,
                p.lead_score
            FROM outreach o
            JOIN prospects p ON p.id = o.prospect_id
            ORDER BY o.date_created DESC
        """).fetchall()
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
        cursor = conn.execute(
            "UPDATE outreach SET status = ? WHERE id = ?",
            (new_status, outreach_id),
        )
        conn.commit()
        return cursor.rowcount > 0
