"""
importer.py - CSV Import Module
=================================
Module 3 of the AI Lead Generation & Outreach System.

Reads a CSV file of prospects, maps columns flexibly (handles varied
header names from LinkedIn exports, Apollo, spreadsheets, etc.),
skips duplicate emails gracefully, and auto-scores every new import.

Recognised column name variations (case-insensitive):
    name        : name, full name, full_name, contact, contact name
    company     : company, company name, organization, organisation, employer, org
    email       : email, email address, e-mail, mail
    linkedin_url: linkedin, linkedin_url, linkedin url, linkedin profile
    website     : website, website url, company website, url, web
    phone       : phone, phone number, telephone, mobile, tel
    notes       : notes, note, comments, comment, description

Only 'name' and 'company' are required. All other columns are optional.

Usage:
    from importer import import_csv

    summary = import_csv("prospects.csv")
    print(f"Imported: {summary['imported']}, Skipped: {summary['skipped']}")
"""

import csv
import sqlite3

from database import DB_PATH, initialize_database, add_prospect
from scorer import score_and_update

# ---------------------------------------------------------------------------
# Column alias table
# Maps any recognised CSV header (lowercased) -> internal field name
# ---------------------------------------------------------------------------

COLUMN_ALIASES = {
    # name
    "name":             "name",
    "full name":        "name",
    "full_name":        "name",
    "contact":          "name",
    "contact name":     "name",
    # company
    "company":          "company",
    "company name":     "company",
    "organization":     "company",
    "organisation":     "company",
    "employer":         "company",
    "org":              "company",
    # email
    "email":            "email",
    "email address":    "email",
    "e-mail":           "email",
    "mail":             "email",
    # linkedin
    "linkedin":         "linkedin_url",
    "linkedin_url":     "linkedin_url",
    "linkedin url":     "linkedin_url",
    "linkedin profile": "linkedin_url",
    # website
    "website":          "website",
    "website url":      "website",
    "company website":  "website",
    "url":              "website",
    "web":              "website",
    # phone
    "phone":            "phone",
    "phone number":     "phone",
    "telephone":        "phone",
    "mobile":           "phone",
    "tel":              "phone",
    # notes
    "notes":            "notes",
    "note":             "notes",
    "comments":         "notes",
    "comment":          "notes",
    "description":      "notes",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _map_headers(raw_headers: list) -> dict:
    """
    Return a dict of {column_index: field_name} for every header that
    matches a known alias. Unrecognised columns are ignored.
    First match wins if a field appears under multiple headers.
    """
    mapping = {}
    seen_fields = set()
    for i, header in enumerate(raw_headers):
        alias = header.strip().lower()
        field = COLUMN_ALIASES.get(alias)
        if field and field not in seen_fields:
            mapping[i] = field
            seen_fields.add(field)
    return mapping


def _row_to_kwargs(row: list, col_map: dict) -> dict:
    """Convert a CSV row into a kwargs dict ready for add_prospect()."""
    kwargs = {}
    for col_idx, field_name in col_map.items():
        if col_idx < len(row):
            value = row[col_idx].strip() or None  # treat empty strings as None
            kwargs[field_name] = value
    return kwargs


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def import_csv(
    filepath: str,
    db_path: str = DB_PATH,
    auto_score: bool = True,
) -> dict:
    """
    Import prospects from a CSV file into the database.

    Args:
        filepath:   Path to the CSV file to import.
        db_path:    Path to the SQLite database file.
        auto_score: If True (default), run the scorer on every new import.

    Returns:
        A summary dict:
            "imported"    - number of prospects successfully added
            "skipped"     - number of rows skipped due to duplicate email
            "failed"      - number of rows that could not be imported
            "imported_ids"- list of new prospect IDs
            "duplicates"  - list of {row, name, email} for skipped rows
            "errors"      - list of {row, reason} for failed rows

    Raises:
        FileNotFoundError: If the CSV file does not exist.
        ValueError: If the CSV has no 'name' or 'company' column.
    """
    initialize_database(db_path)  # safe no-op if DB already exists

    imported_ids = []
    duplicates = []
    errors = []

    with open(filepath, newline="", encoding="utf-8-sig") as f:
        # utf-8-sig strips the BOM that Excel adds to CSV exports
        reader = csv.reader(f)

        try:
            raw_headers = next(reader)
        except StopIteration:
            raise ValueError("CSV file is empty.")

        col_map = _map_headers(raw_headers)

        mapped_fields = set(col_map.values())
        if "name" not in mapped_fields:
            raise ValueError(
                "CSV must have a 'name' column (or variant: 'full name', 'contact')."
            )
        if "company" not in mapped_fields:
            raise ValueError(
                "CSV must have a 'company' column (or variant: 'organization', 'employer')."
            )

        for row_num, row in enumerate(reader, start=2):  # row 1 = headers
            # Skip blank lines
            if not any(cell.strip() for cell in row):
                continue

            kwargs = _row_to_kwargs(row, col_map)

            # Rows missing name or company can't be saved
            if not kwargs.get("name") or not kwargs.get("company"):
                errors.append({
                    "row": row_num,
                    "reason": "missing required field (name or company)",
                })
                continue

            try:
                prospect_id = add_prospect(**kwargs, db_path=db_path)
                if auto_score:
                    score_and_update(prospect_id, db_path)
                imported_ids.append(prospect_id)

            except sqlite3.IntegrityError:
                # Unique constraint on email - this prospect already exists
                duplicates.append({
                    "row": row_num,
                    "name": kwargs.get("name"),
                    "email": kwargs.get("email"),
                })

            except Exception as exc:
                errors.append({"row": row_num, "reason": str(exc)})

    return {
        "imported":     len(imported_ids),
        "skipped":      len(duplicates),
        "failed":       len(errors),
        "imported_ids": imported_ids,
        "duplicates":   duplicates,
        "errors":       errors,
    }
