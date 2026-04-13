"""
test_dashboard.py - Module 4 Launcher
=======================================
Seeds the database with sample prospects (if fewer than 3 exist),
scores any unscored ones, then launches the interactive dashboard.

Run with:
    python test_dashboard.py

The data is saved to prospects.db so it persists between sessions.
Delete prospects.db to start fresh.
"""

from database import DB_PATH, initialize_database, get_all_prospects, add_prospect
from scorer import score_all_new
from dashboard import run

SAMPLE_PROSPECTS = [
    dict(
        name="David Osei",
        company="Fortis Logistics",
        email="d.osei@fortislogistics.com",
        linkedin_url="https://linkedin.com/in/davidosei",
        website="https://fortislogistics.com",
        phone="+1-312-555-0561",
        lead_score=50,
        status="new",
        notes="CRO. Company is hiring 5 SDRs and expanding into new markets.",
    ),
    dict(
        name="Priya Nair",
        company="Nexus Health",
        email="priya.nair@nexushealth.com",
        linkedin_url="https://linkedin.com/in/priyanair",
        website="https://nexushealth.com",
        phone="+1-617-555-0814",
        lead_score=50,
        status="qualified",
        notes="Head of Operations. Mentioned CRM pain points on a podcast.",
    ),
    dict(
        name="Marcus Rivera",
        company="BluePeak Ventures",
        email="m.rivera@bluepeak.vc",
        linkedin_url="https://linkedin.com/in/marcusrivera",
        website="https://bluepeak.vc",
        phone="+1-212-555-0347",
        lead_score=50,
        status="new",
        notes="Partner at VC firm. Portfolio companies are growing fast.",
    ),
    dict(
        name="Sarah Chen",
        company="Acme SaaS",
        email="sarah.chen@acmesaas.io",
        linkedin_url="https://linkedin.com/in/sarahchen",
        website="https://acmesaas.io",
        phone="+1-415-555-0192",
        lead_score=50,
        status="contacted",
        notes="VP of Marketing. Company recently launched a new product line.",
    ),
    dict(
        name="Elena Kovacs",
        company="Drift Analytics",
        email="elena.k@driftanalytics.co",
        linkedin_url=None,
        website="https://driftanalytics.co",
        phone=None,
        lead_score=50,
        status="new",
        notes="Data lead. Small team.",
    ),
    dict(
        name="James Okafor",
        company="Acme SaaS",
        email="j.okafor@acmesaas.io",
        linkedin_url="https://linkedin.com/in/jamesokafor",
        website="https://acmesaas.io",
        phone="+1-415-555-0203",
        lead_score=50,
        status="replied",
        notes="Director of Sales. Replied to our first email - wants a demo.",
    ),
]


def seed_database() -> None:
    """Add sample prospects if the database has fewer than 3 records."""
    initialize_database(DB_PATH)
    existing = get_all_prospects(DB_PATH)

    if len(existing) >= 3:
        print(f"[Setup] Database already has {len(existing)} prospect(s) - skipping seed.")
        return

    print("[Setup] Seeding database with sample prospects...")
    added = 0
    for p in SAMPLE_PROSPECTS:
        try:
            add_prospect(**p, db_path=DB_PATH)
            added += 1
        except Exception:
            pass  # skip duplicates if partially seeded
    print(f"[Setup] Added {added} prospect(s).")

    print("[Setup] Scoring all 'new' prospects...")
    score_all_new(DB_PATH)
    print("[Setup] Done.\n")


if __name__ == "__main__":
    seed_database()
    run(DB_PATH)
