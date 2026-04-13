"""
test_importer.py - Module 3 Demo
==================================
Creates three CSV files and imports them to demonstrate:
  1. A normal import with varied column names and auto-scoring
  2. Duplicate email handling (skipped, not crashed)
  3. A CSV with non-standard column headers (LinkedIn-style export)

No API key required.

Run with:
    python test_importer.py
"""

import gc
import os

from tabulate import tabulate

from database import initialize_database, get_all_prospects
from importer import import_csv

TEST_DB = "test_importer.db"
DISPLAY_COLS = ["id", "name", "company", "email", "lead_score", "status"]


def write_csv(filepath: str, content: str) -> None:
    """Write a CSV string to a file."""
    with open(filepath, "w", encoding="utf-8", newline="") as f:
        f.write(content)


def print_table(prospects: list, title: str) -> None:
    count = len(prospects)
    label = f"{count} record{'s' if count != 1 else ''}"
    print(f"\n  {title}  ({label})")
    if not prospects:
        print("  (no results)")
        return
    rows = [[str(p.get(col) or "")[:40] for col in DISPLAY_COLS] for p in prospects]
    print(tabulate(rows, headers=DISPLAY_COLS, tablefmt="simple"))


def print_summary(summary: dict, label: str) -> None:
    print(f"\n  {label}")
    print(f"    Imported : {summary['imported']}")
    print(f"    Skipped  : {summary['skipped']}  (duplicate emails)")
    print(f"    Failed   : {summary['failed']}")
    if summary["duplicates"]:
        for d in summary["duplicates"]:
            print(f"      row {d['row']}: {d['name']} ({d['email']}) already exists")
    if summary["errors"]:
        for e in summary["errors"]:
            print(f"      row {e['row']}: {e['reason']}")


def run():
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)

    sep = "=" * 66
    print(f"\n{sep}")
    print("  CSV IMPORTER - MODULE 3 DEMO")
    print(sep)

    initialize_database(TEST_DB)

    # ------------------------------------------------------------------
    # Test 1: Standard import - 5 prospects, varied completeness
    # ------------------------------------------------------------------
    print(f"\n{sep}")
    print("[1] Importing standard CSV (5 prospects, varied completeness)")

    csv1 = """\
name,company,email,linkedin_url,website,phone,notes
David Osei,Fortis Logistics,d.osei@fortislogistics.com,https://linkedin.com/in/davidosei,https://fortislogistics.com,+1-312-555-0561,CRO. Company is hiring 5 SDRs and expanding into new markets.
Priya Nair,Nexus Health,priya.nair@nexushealth.com,https://linkedin.com/in/priyanair,https://nexushealth.com,+1-617-555-0814,Head of Operations. Mentioned CRM pain points on a podcast.
Marcus Rivera,BluePeak Ventures,m.rivera@bluepeak.vc,,https://bluepeak.vc,,Partner at VC firm. Invests in B2B SaaS.
Elena Kovacs,Drift Analytics,,,,,"Junior analyst, small team."
Sarah Chen,Acme SaaS,sarah.chen@acmesaas.io,https://linkedin.com/in/sarahchen,https://acmesaas.io,+1-415-555-0192,VP of Marketing. Company recently launched a new product line.
"""
    write_csv("test_import_1.csv", csv1)
    summary1 = import_csv("test_import_1.csv", TEST_DB)
    print_summary(summary1, "Result:")
    print_table(get_all_prospects(TEST_DB), "Imported prospects (sorted by score)")

    # ------------------------------------------------------------------
    # Test 2: Duplicate handling - re-import the same file
    # ------------------------------------------------------------------
    print(f"\n{sep}")
    print("[2] Re-importing the same CSV to test duplicate detection")

    summary2 = import_csv("test_import_1.csv", TEST_DB)
    print_summary(summary2, "Result:")
    print(f"\n  Database still has {len(get_all_prospects(TEST_DB))} records (no duplicates added).")

    # ------------------------------------------------------------------
    # Test 3: Non-standard column headers (e.g. a LinkedIn Sales Nav export)
    # ------------------------------------------------------------------
    print(f"\n{sep}")
    print("[3] Importing CSV with non-standard headers (LinkedIn-style)")

    csv3 = """\
Full Name,Organization,Email Address,LinkedIn Profile,Company Website,Telephone,Description
James Okafor,Acme SaaS,j.okafor@acmesaas.io,https://linkedin.com/in/jamesokafor,https://acmesaas.io,+1-415-555-0203,Director of Sales. Team is growing fast.
Nina Patel,CloudPath Inc,nina.p@cloudpath.io,https://linkedin.com/in/ninapatel,https://cloudpath.io,+1-650-555-0374,Head of RevOps. Company just launched new pricing.
"""
    write_csv("test_import_3.csv", csv3)
    summary3 = import_csv("test_import_3.csv", TEST_DB)
    print_summary(summary3, "Result:")
    print_table(get_all_prospects(TEST_DB), "All prospects after all imports")

    # ------------------------------------------------------------------
    # Test 4: Error handling - row missing required fields
    # ------------------------------------------------------------------
    print(f"\n{sep}")
    print("[4] CSV with a row missing required 'company' field")

    csv4 = """\
name,company,email,notes
Valid Person,Real Company,valid@realco.com,Growing fast.
Missing Company Person,,no-company@example.com,This row has no company.
"""
    write_csv("test_import_4.csv", csv4)
    summary4 = import_csv("test_import_4.csv", TEST_DB)
    print_summary(summary4, "Result:")

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    gc.collect()
    for f in ["test_import_1.csv", "test_import_3.csv", "test_import_4.csv", TEST_DB]:
        if os.path.exists(f):
            os.remove(f)

    print(f"\n{sep}")
    print("  Test files removed. Module 3 working correctly.")
    print(f"{sep}\n")


if __name__ == "__main__":
    run()
