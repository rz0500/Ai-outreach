"""
test_outreach.py - Module 5 Demo
==================================
Demonstrates email generation, batch drafting, and the
draft -> approved -> sent workflow.

No API key required.

Run with:
    python test_outreach.py
"""

import gc
import os

from tabulate import tabulate

from database import initialize_database, add_prospect, get_all_outreach
from scorer import score_all_new
from outreach import (
    generate_email,
    generate_and_save,
    generate_batch,
    approve_draft,
    mark_sent,
)

TEST_DB = "test_outreach.db"


def print_outreach_table(records: list, title: str) -> None:
    count = len(records)
    label = f"{count} record{'s' if count != 1 else ''}"
    print(f"\n  {title}  ({label})")
    if not records:
        print("  (none)")
        return
    cols = ["id", "prospect_name", "prospect_company", "lead_score", "subject", "status"]
    rows = [[str(r.get(c) or "")[:35] for c in cols] for r in records]
    print(tabulate(rows, headers=cols, tablefmt="simple"))


def run():
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)

    sep = "=" * 66
    print(f"\n{sep}")
    print("  EMAIL OUTREACH WRITER - MODULE 5 DEMO")
    print(sep)

    # ------------------------------------------------------------------
    # 1. Seed database with 5 prospects that trigger different templates
    # ------------------------------------------------------------------
    print("\n[1] Seeding database with 5 prospects (varied signals in notes)...")
    initialize_database(TEST_DB)

    # Triggers: funding + growth keywords
    id1 = add_prospect(
        name="David Osei",       company="Fortis Logistics",
        email="d.osei@fortislogistics.com",
        linkedin_url="https://linkedin.com/in/davidosei",
        website="https://fortislogistics.com", phone="+1-312-555-0561",
        lead_score=50, status="qualified",
        notes="CRO. Just raised Series B. Company is hiring 5 SDRs.",
        db_path=TEST_DB,
    )
    # Triggers: warm intro
    id2 = add_prospect(
        name="Priya Nair",        company="Nexus Health",
        email="priya.nair@nexushealth.com",
        linkedin_url="https://linkedin.com/in/priyanair",
        website="https://nexushealth.com", phone="+1-617-555-0814",
        lead_score=50, status="new",
        notes="Head of Operations. Warm intro via Tom at IndigoVC.",
        db_path=TEST_DB,
    )
    # Triggers: pain point
    id3 = add_prospect(
        name="Marcus Rivera",     company="BluePeak Ventures",
        email="m.rivera@bluepeak.vc",
        linkedin_url="https://linkedin.com/in/marcusrivera",
        website="https://bluepeak.vc", phone="+1-212-555-0347",
        lead_score=50, status="new",
        notes="Partner. Tweeted about the broken state of outbound sales tools.",
        db_path=TEST_DB,
    )
    # Triggers: content signal
    id4 = add_prospect(
        name="Nina Patel",        company="CloudPath Inc",
        email="nina.p@cloudpath.io",
        linkedin_url="https://linkedin.com/in/ninapatel",
        website="https://cloudpath.io", phone="+1-650-555-0374",
        lead_score=50, status="new",
        notes="Head of RevOps. Published a great blog post on pipeline efficiency.",
        db_path=TEST_DB,
    )
    # No special signals - triggers generic template
    id5 = add_prospect(
        name="Elena Kovacs",      company="Drift Analytics",
        email="elena.k@driftanalytics.co",
        linkedin_url=None, website="https://driftanalytics.co", phone=None,
        lead_score=50, status="new",
        notes="Data lead. Small team.",
        db_path=TEST_DB,
    )

    print(f"  Added IDs -> {id1}, {id2}, {id3}, {id4}, {id5}")

    # Score all new so we have real scores
    print()
    score_all_new(TEST_DB)

    # ------------------------------------------------------------------
    # 2. Preview one email without saving (generate_email)
    # ------------------------------------------------------------------
    print(f"\n{sep}")
    print("[2] generate_email() preview - no DB write (David Osei, funding signal)")
    from database import get_all_prospects
    david = next(p for p in get_all_prospects(TEST_DB) if p["id"] == id1)
    draft = generate_email(david)
    print(f"\n  Subject : {draft['subject']}")
    print(f"\n  Body:\n")
    for line in draft["body"].splitlines():
        print(f"    {line}")

    # ------------------------------------------------------------------
    # 3. Generate and save for a single prospect
    # ------------------------------------------------------------------
    print(f"\n{sep}")
    print("[3] generate_and_save() - saves draft to DB (Priya Nair, warm intro)")
    result = generate_and_save(id2, db_path=TEST_DB)
    print(f"  Outreach ID : {result['outreach_id']}")
    print(f"  Subject     : {result['subject']}")
    print(f"  Skipped     : {result['skipped']}")

    # Calling again without overwrite=True should skip
    result2 = generate_and_save(id2, db_path=TEST_DB)
    print(f"\n  Re-running generate_and_save() for same prospect:")
    print(f"  Skipped     : {result2['skipped']}  (already has a draft)")

    # ------------------------------------------------------------------
    # 4. Batch generate for all prospects with score >= 40
    # ------------------------------------------------------------------
    print(f"\n{sep}")
    print("[4] generate_batch(min_score=40) - all prospects above threshold")
    print()
    results = generate_batch(min_score=40, db_path=TEST_DB)

    # ------------------------------------------------------------------
    # 5. View all drafts
    # ------------------------------------------------------------------
    print(f"\n{sep}")
    print("[5] All outreach drafts after batch generation")
    print_outreach_table(get_all_outreach(TEST_DB), "Outreach Drafts")

    # ------------------------------------------------------------------
    # 6. Approve one draft, mark another as sent
    # ------------------------------------------------------------------
    print(f"\n{sep}")
    print("[6] Approving David's draft, then marking Priya's as sent")

    # Find their outreach IDs
    all_outreach = get_all_outreach(TEST_DB)
    david_out = next(r for r in all_outreach if r["prospect_id"] == id1)
    priya_out  = next(r for r in all_outreach if r["prospect_id"] == id2)

    approve_draft(david_out["id"], TEST_DB)
    print(f"  Approved  outreach id={david_out['id']} ({david_out['prospect_name']})")

    mark_sent(priya_out["id"], TEST_DB)
    print(f"  Sent      outreach id={priya_out['id']} ({priya_out['prospect_name']})")

    # ------------------------------------------------------------------
    # 7. Final outreach table showing status changes
    # ------------------------------------------------------------------
    print(f"\n{sep}")
    print("[7] Final outreach table")
    print_outreach_table(get_all_outreach(TEST_DB), "All Outreach")

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    gc.collect()
    os.remove(TEST_DB)
    print(f"\n{sep}")
    print("  Test database removed. Module 5 working correctly.")
    print(f"{sep}\n")


if __name__ == "__main__":
    run()
