"""
test_database.py - Module 1 Demo & Test
========================================
Adds 5 realistic example prospects and demonstrates every function
in database.py.

Run with:
    python test_database.py
"""

import gc
import os
from database import (
    initialize_database,
    add_prospect,
    update_lead_score,
    update_status,
    get_all_prospects,
    get_prospects_by_min_score,
    search_by_company,
)
from tabulate import tabulate

# ---------------------------------------------------------------------------
# Use a separate test DB so we never touch the real prospects.db
# ---------------------------------------------------------------------------
TEST_DB = "test_prospects.db"

# Columns shown in the printed tables (full record has more fields)
DISPLAY_COLUMNS = ["id", "name", "company", "lead_score", "status", "email"]


def print_table(prospects: list, title: str) -> None:
    """Print a list of prospect dicts as a formatted table."""
    count = len(prospects)
    label = f"{count} record{'s' if count != 1 else ''}"
    print(f"\n  {title}  ({label})")
    if not prospects:
        print("  (no results)")
        return
    rows = [[p.get(col, "") for col in DISPLAY_COLUMNS] for p in prospects]
    print(tabulate(rows, headers=DISPLAY_COLUMNS, tablefmt="simple"))


# ---------------------------------------------------------------------------
# Main test sequence
# ---------------------------------------------------------------------------

def run():
    # Clean up any leftover file from a previous run
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)

    separator = "=" * 62
    print(f"\n{separator}")
    print("  PROSPECT DATABASE - MODULE 1 DEMO")
    print(separator)

    # ------------------------------------------------------------------
    # 1. Initialize the database
    # ------------------------------------------------------------------
    print("\n[1] Initialising database...")
    initialize_database(TEST_DB)

    # ------------------------------------------------------------------
    # 2. Add 5 example prospects
    # ------------------------------------------------------------------
    print("\n[2] Adding 5 example prospects...")

    # High-value lead - decision-maker who mentioned a pain point publicly
    id1 = add_prospect(
        name="Priya Nair",
        company="Nexus Health",
        email="priya.nair@nexushealth.com",
        linkedin_url="https://linkedin.com/in/priyanair",
        website="https://nexushealth.com",
        phone="+1-617-555-0814",
        lead_score=91,
        status="qualified",
        notes="Head of Operations. Mentioned CRM pain points on a podcast (ep. 112).",
        db_path=TEST_DB,
    )

    # Strong lead - active VC investor looking for B2B tools
    id2 = add_prospect(
        name="Marcus Rivera",
        company="BluePeak Ventures",
        email="m.rivera@bluepeak.vc",
        linkedin_url="https://linkedin.com/in/marcusrivera",
        website="https://bluepeak.vc",
        phone="+1-212-555-0347",
        lead_score=67,
        status="new",
        notes="Partner at VC firm. Actively investing in B2B SaaS. Warm intro via David.",
        db_path=TEST_DB,
    )

    # Good lead - VP at a 500-person company
    id3 = add_prospect(
        name="Sarah Chen",
        company="Acme SaaS",
        email="sarah.chen@acmesaas.io",
        linkedin_url="https://linkedin.com/in/sarahchen",
        website="https://acmesaas.io",
        phone="+1-415-555-0192",
        lead_score=82,
        status="new",
        notes="VP of Marketing. Company recently raised Series B - likely expanding tools stack.",
        db_path=TEST_DB,
    )

    # Secondary contact at same company (tests company search)
    id4 = add_prospect(
        name="James Okafor",
        company="Acme SaaS",
        email="j.okafor@acmesaas.io",
        linkedin_url="https://linkedin.com/in/jamesokafor",
        website="https://acmesaas.io",
        phone="+1-415-555-0203",
        lead_score=55,
        status="new",
        notes="Director of Sales at Acme SaaS. Secondary contact - loop in after Sarah responds.",
        db_path=TEST_DB,
    )

    # Cold lead - small company, uncertain fit
    id5 = add_prospect(
        name="Elena Kovacs",
        company="Drift Analytics",
        email="elena.k@driftanalytics.co",
        linkedin_url="https://linkedin.com/in/elenakovacs",
        website="https://driftanalytics.co",
        phone=None,                   # phone is optional - None is fine
        lead_score=38,
        status="new",
        notes="Data lead. Team of 10 - probably too small right now. Revisit in 6 months.",
        db_path=TEST_DB,
    )

    print(f"  Assigned IDs -> {id1}, {id2}, {id3}, {id4}, {id5}")

    # ------------------------------------------------------------------
    # 3. get_all_prospects
    # ------------------------------------------------------------------
    print(f"\n{separator}")
    print("[3] get_all_prospects()  -  all records, sorted by score (high -> low)")
    print_table(get_all_prospects(TEST_DB), "All Prospects")

    # ------------------------------------------------------------------
    # 4. get_prospects_by_min_score
    # ------------------------------------------------------------------
    print(f"\n{separator}")
    print("[4] get_prospects_by_min_score(70)  -  high-value leads only")
    print_table(get_prospects_by_min_score(70, TEST_DB), "Leads with score >= 70")

    # ------------------------------------------------------------------
    # 5. search_by_company
    # ------------------------------------------------------------------
    print(f"\n{separator}")
    print("[5] search_by_company('Acme')  -  partial, case-insensitive match")
    print_table(search_by_company("Acme", TEST_DB), "Prospects at 'Acme' companies")

    # ------------------------------------------------------------------
    # 6. update_lead_score
    # ------------------------------------------------------------------
    print(f"\n{separator}")
    print(f"[6] update_lead_score(id={id2}, 85)")
    print(f"    Marcus Rivera's score: 67 -> 85  (warm intro confirmed)")
    ok = update_lead_score(id2, 85, TEST_DB)
    print(f"    Success: {ok}")

    # ------------------------------------------------------------------
    # 7. update_status
    # ------------------------------------------------------------------
    print(f"\n{separator}")
    print(f"[7] update_status(id={id1}, 'contacted')")
    print(f"    Priya Nair's status: qualified -> contacted  (email sent)")
    ok = update_status(id1, "contacted", TEST_DB)
    print(f"    Success: {ok}")

    # ------------------------------------------------------------------
    # 8. Final state
    # ------------------------------------------------------------------
    print(f"\n{separator}")
    print("[8] Final database state after updates")
    print_table(get_all_prospects(TEST_DB), "All Prospects")

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    gc.collect()  # ensure SQLite connections are released before deleting on Windows
    os.remove(TEST_DB)
    print(f"\n{separator}")
    print("  Test database removed. All functions working correctly.")
    print(separator + "\n")


if __name__ == "__main__":
    run()
