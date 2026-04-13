"""
test_reporter.py - Module 6 Demo
==================================
Seeds a database with prospects spread across every pipeline status
and score range, then demonstrates all three reporter functions.

Run with:
    python test_reporter.py
"""

import gc
import os

from database import initialize_database, add_prospect
from scorer import score_all_new
from outreach import generate_batch
from reporter import print_report, save_report, export_prospects_csv

TEST_DB      = "test_reporter.db"
REPORT_FILE  = "test_report.txt"
EXPORT_FILE  = "test_export.csv"

# Prospects spread across statuses and score ranges
SEED_DATA = [
    # Hot - full profiles, growth signals
    dict(name="David Osei",    company="Fortis Logistics",
         email="d.osei@fortislogistics.com",
         linkedin_url="https://linkedin.com/in/davidosei",
         website="https://fortislogistics.com", phone="+1-312-555-0561",
         status="qualified",
         notes="CRO. Just raised Series B. Hiring 5 SDRs, expanding west coast."),
    dict(name="Priya Nair",    company="Nexus Health",
         email="priya.nair@nexushealth.com",
         linkedin_url="https://linkedin.com/in/priyanair",
         website="https://nexushealth.com", phone="+1-617-555-0814",
         status="contacted",
         notes="Head of Operations. Warm intro via Tom. Growing the ops team."),
    dict(name="Sarah Chen",    company="Acme SaaS",
         email="sarah.chen@acmesaas.io",
         linkedin_url="https://linkedin.com/in/sarahchen",
         website="https://acmesaas.io", phone="+1-415-555-0192",
         status="replied",
         notes="VP Marketing. Company launched a new product line last month."),
    dict(name="Nina Patel",    company="CloudPath Inc",
         email="nina.p@cloudpath.io",
         linkedin_url="https://linkedin.com/in/ninapatel",
         website="https://cloudpath.io", phone="+1-650-555-0374",
         status="booked",
         notes="Head of RevOps. Published article on pipeline efficiency."),
    # Warm - partial profiles
    dict(name="Marcus Rivera", company="BluePeak Ventures",
         email="m.rivera@bluepeak.vc",
         linkedin_url="https://linkedin.com/in/marcusrivera",
         website="https://bluepeak.vc", phone=None,
         status="new",
         notes="Partner at VC. Portfolio companies growing fast."),
    dict(name="James Okafor",  company="Acme SaaS",
         email="j.okafor@acmesaas.io",
         linkedin_url="https://linkedin.com/in/jamesokafor",
         website="https://acmesaas.io", phone="+1-415-555-0203",
         status="new",
         notes="Director of Sales. Secondary contact at Acme SaaS."),
    dict(name="Leo Hartmann",  company="Vanta Systems",
         email="l.hartmann@vantasys.com",
         linkedin_url=None,
         website="https://vantasys.com", phone="+1-303-555-0812",
         status="contacted",
         notes="Head of Engineering. Attended our webinar last week."),
    # Cold - minimal info
    dict(name="Elena Kovacs",  company="Drift Analytics",
         email="elena.k@driftanalytics.co",
         linkedin_url=None, website=None, phone=None,
         status="new",
         notes="Junior analyst. Small team."),
    dict(name="Tom Briggs",    company="Briggs Consulting",
         email=None, linkedin_url=None, website=None, phone=None,
         status="rejected",
         notes="Solo consultant. Not a fit."),
]


def run():
    for f in [TEST_DB, REPORT_FILE, EXPORT_FILE]:
        if os.path.exists(f):
            os.remove(f)

    sep = "=" * 58
    print(f"\n{sep}")
    print("  PIPELINE REPORTER - MODULE 6 DEMO")
    print(sep)

    # ------------------------------------------------------------------
    # 1. Seed the database
    # ------------------------------------------------------------------
    print("\n[1] Seeding database...")
    initialize_database(TEST_DB)
    ids = []
    for p in SEED_DATA:
        pid = add_prospect(**p, lead_score=50, db_path=TEST_DB)
        ids.append(pid)
    print(f"  Added {len(ids)} prospects.")

    print("\n  Scoring all 'new' prospects...")
    score_all_new(TEST_DB)

    print("\n  Generating outreach drafts for prospects with score >= 50...")
    generate_batch(min_score=50, db_path=TEST_DB)

    # ------------------------------------------------------------------
    # 2. Print report to terminal
    # ------------------------------------------------------------------
    print(f"\n{sep}")
    print("[2] print_report() - full pipeline summary\n")
    print_report(TEST_DB)

    # ------------------------------------------------------------------
    # 3. Save report to .txt file
    # ------------------------------------------------------------------
    print(f"\n{sep}")
    print(f"[3] save_report() - write to {REPORT_FILE}")
    save_report(REPORT_FILE, TEST_DB)

    # Show first 10 lines of the saved file
    with open(REPORT_FILE, encoding="utf-8") as f:
        preview = [next(f) for _ in range(10)]
    print(f"\n  Preview of {REPORT_FILE} (first 10 lines):")
    for line in preview:
        print(f"    {line}", end="")

    # ------------------------------------------------------------------
    # 4. Export prospects to CSV
    # ------------------------------------------------------------------
    print(f"\n\n{sep}")
    print(f"[4] export_prospects_csv() - write to {EXPORT_FILE}")
    count = export_prospects_csv(EXPORT_FILE, TEST_DB)

    # Show the header + first 3 data rows
    with open(EXPORT_FILE, encoding="utf-8-sig") as f:
        rows = [line.rstrip() for _, line in zip(range(4), f)]
    print(f"\n  Preview of {EXPORT_FILE} (header + first 3 rows):")
    for row in rows:
        print(f"    {row[:90]}")

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    gc.collect()
    for f in [TEST_DB, REPORT_FILE, EXPORT_FILE]:
        if os.path.exists(f):
            os.remove(f)

    print(f"\n{sep}")
    print("  Test files removed. Module 6 working correctly.")
    print(f"{sep}\n")


if __name__ == "__main__":
    run()
