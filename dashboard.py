"""
dashboard.py - CLI Dashboard
==============================
Module 4 of the AI Lead Generation & Outreach System.

Interactive command-line interface that ties Modules 1-3 together.
Browse prospects, filter by score or status, update pipeline stages,
import CSVs, trigger scoring, and view pipeline stats.

Run with:
    python dashboard.py
"""

import os

from tabulate import tabulate

from database import (
    DB_PATH,
    VALID_STATUSES,
    get_all_prospects,
    get_prospects_by_min_score,
    initialize_database,
    search_by_company,
    update_status,
)
from importer import import_csv
from scorer import score_all_new
from outreach import approve_draft, generate_batch, mark_sent
from reporter import export_prospects_csv, print_report, save_report

# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

# Columns shown in prospect tables throughout the dashboard
LIST_COLS    = ["id", "name", "company", "lead_score", "status", "email"]
# Ordered status list for the filter menu
STATUS_LIST  = ["new", "qualified", "contacted", "replied", "booked", "rejected"]

SEP  = "=" * 66
DASH = "-" * 66


def clear() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def pause() -> None:
    input("\n  Press Enter to continue...")


def header(title: str) -> None:
    """Print the dashboard header with a section title."""
    clear()
    print(f"\n{SEP}")
    print(f"  LEAD GEN DASHBOARD  |  {title}")
    print(SEP)


def show_table(prospects: list, title: str = "") -> None:
    """Print prospects as a formatted table."""
    count = len(prospects)
    label = f"{count} record{'s' if count != 1 else ''}"
    if title:
        print(f"\n  {title}  ({label})")
    else:
        print(f"\n  {label}")
    if not prospects:
        print("  (nothing to show)")
        return
    rows = [
        [str(p.get(col) or "")[:38] for col in LIST_COLS]
        for p in prospects
    ]
    print(tabulate(rows, headers=LIST_COLS, tablefmt="simple"))


def get_int(prompt: str) -> int | None:
    """Ask for an integer. Returns None if the input is not a valid number."""
    raw = input(prompt).strip()
    try:
        return int(raw)
    except ValueError:
        print(f"  '{raw}' is not a valid number.")
        return None


# ---------------------------------------------------------------------------
# Menu actions
# ---------------------------------------------------------------------------

def action_view_all(db_path: str) -> None:
    header("All Prospects")
    prospects = get_all_prospects(db_path)
    show_table(prospects, "All prospects, sorted by score")
    pause()


def action_filter_score(db_path: str) -> None:
    header("Filter by Minimum Score")
    min_score = get_int("  Minimum score (1-100): ")
    if min_score is None:
        pause()
        return
    prospects = get_prospects_by_min_score(min_score, db_path)
    show_table(prospects, f"Prospects with score >= {min_score}")
    pause()


def action_filter_status(db_path: str) -> None:
    header("Filter by Status")
    print()
    for i, s in enumerate(STATUS_LIST, start=1):
        print(f"  [{i}] {s}")
    choice = get_int("\n  Choose a status: ")
    if choice is None or not (1 <= choice <= len(STATUS_LIST)):
        print("  Invalid choice.")
        pause()
        return
    chosen = STATUS_LIST[choice - 1]
    all_p = get_all_prospects(db_path)
    filtered = [p for p in all_p if p["status"] == chosen]
    show_table(filtered, f"Prospects with status '{chosen}'")
    pause()


def action_search_company(db_path: str) -> None:
    header("Search by Company")
    term = input("  Company name (partial OK): ").strip()
    if not term:
        print("  No search term entered.")
        pause()
        return
    results = search_by_company(term, db_path)
    show_table(results, f"Results for '{term}'")
    pause()


def action_update_status(db_path: str) -> None:
    header("Update Prospect Status")

    # Show current prospects so the user can pick an ID
    show_table(get_all_prospects(db_path), "Current prospects")

    prospect_id = get_int("\n  Enter prospect ID to update: ")
    if prospect_id is None:
        pause()
        return

    # Confirm the prospect exists
    all_p = get_all_prospects(db_path)
    prospect = next((p for p in all_p if p["id"] == prospect_id), None)
    if prospect is None:
        print(f"  No prospect found with id={prospect_id}.")
        pause()
        return

    print(f"\n  Prospect: {prospect['name']} at {prospect['company']}")
    print(f"  Current status: {prospect['status']}")
    print()
    for i, s in enumerate(STATUS_LIST, start=1):
        print(f"  [{i}] {s}")

    choice = get_int("\n  New status: ")
    if choice is None or not (1 <= choice <= len(STATUS_LIST)):
        print("  Invalid choice.")
        pause()
        return

    new_status = STATUS_LIST[choice - 1]
    if new_status == prospect["status"]:
        print(f"  Status is already '{new_status}' - no change made.")
        pause()
        return

    ok = update_status(prospect_id, new_status, db_path)
    if ok:
        print(f"\n  Updated: {prospect['name']}  {prospect['status']} -> {new_status}")
    else:
        print("  Update failed.")
    pause()


def action_import_csv(db_path: str) -> None:
    header("Import from CSV")
    filepath = input("  Path to CSV file: ").strip().strip('"')
    if not filepath:
        print("  No path entered.")
        pause()
        return
    if not os.path.exists(filepath):
        print(f"  File not found: {filepath}")
        pause()
        return

    print()
    try:
        summary = import_csv(filepath, db_path, auto_score=True)
    except Exception as exc:
        print(f"  Import failed: {exc}")
        pause()
        return

    print(f"\n  Imported : {summary['imported']}")
    print(f"  Skipped  : {summary['skipped']}  (duplicate emails)")
    print(f"  Failed   : {summary['failed']}")

    if summary["duplicates"]:
        print("\n  Skipped rows:")
        for d in summary["duplicates"]:
            print(f"    row {d['row']}: {d['name']} ({d['email']}) already exists")

    if summary["errors"]:
        print("\n  Failed rows:")
        for e in summary["errors"]:
            print(f"    row {e['row']}: {e['reason']}")

    if summary["imported"] > 0:
        print(f"\n  New prospects added and scored. Use 'View all' to see them.")

    pause()


def action_score_new(db_path: str) -> None:
    header("Score All 'New' Prospects")
    new_count = sum(
        1 for p in get_all_prospects(db_path) if p["status"] == "new"
    )
    if new_count == 0:
        print("\n  No prospects with status 'new' found.")
        pause()
        return

    print(f"\n  {new_count} prospect(s) will be scored.")
    confirm = input("  Proceed? (y/n): ").strip().lower()
    if confirm != "y":
        print("  Cancelled.")
        pause()
        return

    print()
    results = score_all_new(db_path)
    print(f"\n  Done. {len(results)} prospect(s) scored.")
    pause()


def action_stats(db_path: str) -> None:
    header("Pipeline Report")

    if not get_all_prospects(db_path):
        print("\n  No prospects in the database yet.")
        pause()
        return

    print_report(db_path)

    print(f"\n{DASH}")
    print("  Export options:")
    print("  [1] Save report to .txt file")
    print("  [2] Export prospects to .csv file")
    print("  [0] Back")
    choice = input("\n  Choice: ").strip()

    if choice == "1":
        filename = input("  Filename (e.g. report.txt): ").strip() or "report.txt"
        save_report(filename, db_path)
        print(f"  Saved: {filename}")
    elif choice == "2":
        filename = input("  Filename (e.g. prospects.csv): ").strip() or "prospects.csv"
        export_prospects_csv(filename, db_path)
        print(f"  Saved: {filename}")

    pause()


# ---------------------------------------------------------------------------
# Outreach submenu
# ---------------------------------------------------------------------------

def action_outreach(db_path: str) -> None:
    """Outreach submenu: generate drafts, review, and track send status."""
    from database import get_all_outreach

    OUTREACH_MENU = """\

  [1] Generate email drafts (by minimum score)
  [2] Review drafts - approve or mark as sent
  [3] View all outreach
  [0] Back
"""
    while True:
        header("Outreach")
        all_out = get_all_outreach(db_path)
        counts = {s: sum(1 for r in all_out if r["status"] == s)
                  for s in ("draft", "approved", "sent")}
        print(f"\n  Drafts: {counts['draft']}  |  "
              f"Approved: {counts['approved']}  |  Sent: {counts['sent']}")
        print(OUTREACH_MENU)

        choice = input("  Choice: ").strip()

        if choice == "0":
            break

        elif choice == "1":
            header("Generate Email Drafts")
            min_score = get_int("  Minimum lead score to target (e.g. 60): ")
            if min_score is None:
                pause()
                continue
            print()
            results = generate_batch(min_score=min_score, db_path=db_path)
            new_count = sum(1 for r in results if not r["skipped"])
            skip_count = sum(1 for r in results if r["skipped"])
            print(f"\n  Generated: {new_count}  |  Already had draft: {skip_count}")
            pause()

        elif choice == "2":
            header("Review Drafts")
            drafts = [r for r in get_all_outreach(db_path) if r["status"] == "draft"]
            if not drafts:
                print("\n  No drafts to review.")
                pause()
                continue

            for draft in drafts:
                clear()
                print(f"\n{SEP}")
                print(f"  REVIEW DRAFT  |  id={draft['id']}")
                print(SEP)
                print(f"\n  Prospect : {draft['prospect_name']} "
                      f"at {draft['prospect_company']}  "
                      f"(score {draft['lead_score']})")
                print(f"\n  Subject  : {draft['subject']}\n")
                print(f"  Body:\n")
                for line in draft["body"].splitlines():
                    print(f"    {line}")
                print(f"\n{DASH}")
                print("  [a] Approve   [s] Mark sent   [n] Skip   [q] Quit review")
                action_key = input("\n  Action: ").strip().lower()
                if action_key == "a":
                    approve_draft(draft["id"], db_path)
                    print(f"  Approved.")
                elif action_key == "s":
                    mark_sent(draft["id"], db_path)
                    print(f"  Marked as sent.")
                elif action_key == "q":
                    break
                else:
                    print("  Skipped.")

            pause()

        elif choice == "3":
            header("All Outreach")
            all_out = get_all_outreach(db_path)
            if not all_out:
                print("\n  No outreach records yet.")
            else:
                cols = ["id", "prospect_name", "prospect_company",
                        "lead_score", "subject", "status"]
                rows = [[str(r.get(c) or "")[:32] for c in cols] for r in all_out]
                print()
                print(tabulate(rows, headers=cols, tablefmt="simple"))
            pause()

        else:
            print(f"  '{choice}' is not a valid option.")
            pause()


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

MENU = """\

  [1] View all prospects
  [2] Filter by minimum score
  [3] Filter by status
  [4] Search by company
  [5] Update prospect status
  [6] Import from CSV
  [7] Score all 'new' prospects
  [8] Pipeline stats
  [9] Outreach
  [0] Exit
"""


def run(db_path: str = DB_PATH) -> None:
    """Start the interactive dashboard."""
    initialize_database(db_path)

    actions = {
        "1": action_view_all,
        "2": action_filter_score,
        "3": action_filter_status,
        "4": action_search_company,
        "5": action_update_status,
        "6": action_import_csv,
        "7": action_score_new,
        "8": action_stats,
        "9": action_outreach,
    }

    while True:
        clear()
        total = len(get_all_prospects(db_path))
        print(f"\n{SEP}")
        print(f"  LEAD GEN DASHBOARD  |  {total} prospect(s) in database")
        print(SEP)
        print(MENU)

        choice = input("  Choice: ").strip()

        if choice == "0":
            clear()
            print("\n  Goodbye.\n")
            break

        action = actions.get(choice)
        if action:
            action(db_path)
        else:
            print(f"  '{choice}' is not a valid option.")
            pause()


if __name__ == "__main__":
    run()
