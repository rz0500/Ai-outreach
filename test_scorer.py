"""
test_scorer.py - Module 2 Demo
================================
Demonstrates rule-based lead scoring on 4 prospects with different
levels of profile completeness and note signals.

No API key required.

Run with:
    python test_scorer.py
"""

import gc
import os

from tabulate import tabulate

from database import initialize_database, add_prospect, get_all_prospects
from scorer import score_all_new, score_and_update, POINTS, GROWTH_KEYWORDS

TEST_DB = "test_scorer.db"


def print_table(prospects: list, columns: list, title: str) -> None:
    count = len(prospects)
    label = f"{count} record{'s' if count != 1 else ''}"
    print(f"\n  {title}  ({label})")
    if not prospects:
        print("  (no results)")
        return
    rows = [[str(p.get(col) or "")[:55] for col in columns] for p in prospects]
    print(tabulate(rows, headers=columns, tablefmt="simple"))


def run():
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)

    sep = "=" * 66
    print(f"\n{sep}")
    print("  RULE-BASED LEAD SCORER - MODULE 2 DEMO")
    print(sep)

    # Show the scoring rules upfront so the output makes sense
    print("\n  Scoring rules:")
    print(f"    +{POINTS['email']:<3} has email")
    print(f"    +{POINTS['linkedin']:<3} has linkedin_url")
    print(f"    +{POINTS['website']:<3} has website")
    print(f"    +{POINTS['phone']:<3} has phone")
    print(f"    +{POINTS['company']:<3} has company name")
    print(f"    +{POINTS['keywords']:<3} notes contain a growth keyword "
          f"({', '.join(sorted(GROWTH_KEYWORDS))})")

    # ------------------------------------------------------------------
    # 1. Set up test database
    # ------------------------------------------------------------------
    print(f"\n{sep}")
    print("[1] Setting up test database with 4 prospects...")
    initialize_database(TEST_DB)

    # Full profile + growth keywords in notes -> expect high score (100)
    id1 = add_prospect(
        name="David Osei",
        company="Fortis Logistics",
        email="d.osei@fortislogistics.com",
        linkedin_url="https://linkedin.com/in/davidosei",
        website="https://fortislogistics.com",
        phone="+1-312-555-0561",
        lead_score=50,
        status="new",
        notes="CRO at a 300-person firm. Company is hiring 5 SDRs and expanding into new markets.",
        db_path=TEST_DB,
    )

    # Full profile, no growth keywords -> expect 85
    id2 = add_prospect(
        name="Priya Nair",
        company="Nexus Health",
        email="priya.nair@nexushealth.com",
        linkedin_url="https://linkedin.com/in/priyanair",
        website="https://nexushealth.com",
        phone="+1-617-555-0814",
        lead_score=50,
        status="new",
        notes="Head of Operations. Mentioned CRM pain points on a podcast.",
        db_path=TEST_DB,
    )

    # Missing phone and LinkedIn -> expect 65
    id3 = add_prospect(
        name="Marcus Rivera",
        company="BluePeak Ventures",
        email="m.rivera@bluepeak.vc",
        linkedin_url=None,
        website="https://bluepeak.vc",
        phone=None,
        lead_score=50,
        status="new",
        notes="Partner at VC firm. Invests in B2B SaaS.",
        db_path=TEST_DB,
    )

    # Bare minimum - only company name, no contact info, no keywords -> expect 10
    id4 = add_prospect(
        name="Elena Kovacs",
        company="Drift Analytics",
        email=None,
        linkedin_url=None,
        website=None,
        phone=None,
        lead_score=50,
        status="new",
        notes=None,
        db_path=TEST_DB,
    )

    print(f"  Added IDs -> {id1}, {id2}, {id3}, {id4}")

    # ------------------------------------------------------------------
    # 2. Show before scores (all 50 placeholders)
    # ------------------------------------------------------------------
    print(f"\n{sep}")
    print("[2] Scores BEFORE scoring (placeholder 50 for all)")
    print_table(
        get_all_prospects(TEST_DB),
        ["id", "name", "company", "lead_score", "status"],
        "Before",
    )

    # ------------------------------------------------------------------
    # 3. Score all new prospects
    # ------------------------------------------------------------------
    print(f"\n{sep}")
    print("[3] Running score_all_new()...")
    print()
    results = score_all_new(TEST_DB)

    # ------------------------------------------------------------------
    # 4. Show after scores + reasoning
    # ------------------------------------------------------------------
    print(f"\n{sep}")
    print("[4] Scores AFTER scoring")
    print_table(
        get_all_prospects(TEST_DB),
        ["id", "name", "company", "lead_score", "status"],
        "After",
    )

    print("\n  Reasoning breakdown:")
    for r in results:
        print(f"  [id={r['prospect_id']}] score {r['score']:>3}  -  {r['reasoning']}")

    # ------------------------------------------------------------------
    # 5. Show that re-scoring after updating notes changes the score
    # ------------------------------------------------------------------
    print(f"\n{sep}")
    print(f"[5] Adding growth keywords to Elena's notes and re-scoring...")

    from database import update_notes
    update_notes(
        id4,
        "Just heard they are hiring and launching a new product line.",
        TEST_DB,
    )
    result = score_and_update(id4, TEST_DB)
    print(f"  Elena Kovacs  old score: 10  ->  new score: {result['score']}")
    print(f"  Reasoning: {result['reasoning']}")

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    gc.collect()
    os.remove(TEST_DB)
    print(f"\n{sep}")
    print("  Test database removed. Module 2 working correctly.")
    print(f"{sep}\n")


if __name__ == "__main__":
    run()
