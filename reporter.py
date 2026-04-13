"""
reporter.py - Pipeline Reporter
=================================
Module 6 of the AI Lead Generation & Outreach System.

Generates a plain-text pipeline summary and exports prospect data
to CSV. Useful for weekly reviews and sharing progress with a team.

Report sections:
    - Overview       : totals, data completeness
    - Status funnel  : counts, percentages, booked conversion rate
    - Score bands    : hot / warm / cold breakdown
    - Top prospects  : top 10 by lead score
    - Top companies  : companies with the most prospects
    - Outreach       : draft / approved / sent counts

Usage:
    from reporter import print_report, export_prospects_csv, save_report

    print_report()                          # print to terminal
    export_prospects_csv("export.csv")      # CSV of all prospects
    save_report("weekly_report.txt")        # save text report to file
"""

import csv
from datetime import date

from database import DB_PATH, get_all_prospects, get_all_outreach

# Pipeline statuses in funnel order
FUNNEL_ORDER = ["new", "qualified", "contacted", "replied", "booked", "rejected"]


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------

def generate_summary(db_path: str = DB_PATH) -> dict:
    """
    Collect all pipeline statistics into a single dict.

    Returns a dict with keys: date, prospects, outreach, funnel,
    score_bands, top_prospects, top_companies.
    """
    prospects = get_all_prospects(db_path)
    total = len(prospects)

    # --- Completeness ---
    with_email    = sum(1 for p in prospects if p.get("email"))
    with_linkedin = sum(1 for p in prospects if p.get("linkedin_url"))
    with_phone    = sum(1 for p in prospects if p.get("phone"))
    scored        = sum(1 for p in prospects if p.get("lead_score", 50) != 50)

    # --- Status funnel ---
    status_counts = {s: 0 for s in FUNNEL_ORDER}
    for p in prospects:
        status = p.get("status", "new")
        if status in status_counts:
            status_counts[status] += 1

    booked   = status_counts["booked"]
    rejected = status_counts["rejected"]
    active   = total - rejected
    conversion_rate = round(booked / total * 100, 1) if total else 0.0

    # --- Score bands ---
    hot  = sum(1 for p in prospects if p["lead_score"] >= 71)
    warm = sum(1 for p in prospects if 41 <= p["lead_score"] <= 70)
    cold = sum(1 for p in prospects if p["lead_score"] <= 40)

    # --- Top 10 prospects (already sorted by score desc) ---
    top_prospects = prospects[:10]

    # --- Top companies by prospect count ---
    company_counts: dict = {}
    for p in prospects:
        co = (p.get("company") or "Unknown").strip()
        company_counts[co] = company_counts.get(co, 0) + 1
    top_companies = sorted(company_counts.items(), key=lambda x: x[1], reverse=True)[:7]

    # --- Outreach ---
    outreach = get_all_outreach(db_path)
    outreach_counts = {"draft": 0, "approved": 0, "sent": 0}
    for r in outreach:
        s = r.get("status", "draft")
        if s in outreach_counts:
            outreach_counts[s] += 1

    return {
        "date":        str(date.today()),
        "prospects": {
            "total":        total,
            "scored":       scored,
            "with_email":   with_email,
            "with_linkedin": with_linkedin,
            "with_phone":   with_phone,
        },
        "funnel": {
            "counts":          status_counts,
            "active":          active,
            "conversion_rate": conversion_rate,
        },
        "score_bands": {"hot": hot, "warm": warm, "cold": cold},
        "top_prospects": top_prospects,
        "top_companies": top_companies,
        "outreach":      outreach_counts,
    }


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def _pct(part: int, total: int) -> str:
    """Return 'X%' string, or '0%' if total is zero."""
    if total == 0:
        return "0%"
    return f"{round(part / total * 100)}%"


def _bar(count: int, max_count: int, width: int = 20) -> str:
    """Return a simple ASCII bar scaled to max_count."""
    if max_count == 0:
        return ""
    filled = round(count / max_count * width)
    return "#" * filled


def format_report(summary: dict) -> str:
    """
    Render a summary dict as a plain-text report string.

    Args:
        summary: Dict returned by generate_summary().

    Returns:
        A multi-line string ready to print or write to a file.
    """
    SEP  = "=" * 58
    DASH = "-" * 58
    lines = []

    def add(text: str = "") -> None:
        lines.append(text)

    p   = summary["prospects"]
    f   = summary["funnel"]
    sb  = summary["score_bands"]
    out = summary["outreach"]
    total = p["total"]

    add(SEP)
    add("  LEAD GENERATION PIPELINE REPORT")
    add(f"  Generated: {summary['date']}")
    add(SEP)

    # --- Overview ---
    add()
    add("  OVERVIEW")
    add(DASH)
    add(f"  Total prospects  : {total}")
    add(f"  With email       : {p['with_email']:<4}  ({_pct(p['with_email'],   total)})")
    add(f"  With LinkedIn    : {p['with_linkedin']:<4}  ({_pct(p['with_linkedin'], total)})")
    add(f"  With phone       : {p['with_phone']:<4}  ({_pct(p['with_phone'],   total)})")

    # --- Funnel ---
    add()
    add("  STATUS FUNNEL")
    add(DASH)
    max_count = max(f["counts"].values()) if f["counts"] else 1
    for status in FUNNEL_ORDER:
        count = f["counts"][status]
        bar   = _bar(count, max_count)
        add(f"  {status:<12} {count:>4}  ({_pct(count, total):>4})  {bar}")
    add()
    add(f"  Overall conversion (new -> booked): {f['conversion_rate']}%")

    # --- Score bands ---
    add()
    add("  SCORE DISTRIBUTION")
    add(DASH)
    max_band = max(sb["hot"], sb["warm"], sb["cold"], 1)
    add(f"  Hot  (71-100)  {sb['hot']:>4}  ({_pct(sb['hot'],  total):>4})  "
        f"{_bar(sb['hot'],  max_band)}")
    add(f"  Warm (41-70)   {sb['warm']:>4}  ({_pct(sb['warm'], total):>4})  "
        f"{_bar(sb['warm'], max_band)}")
    add(f"  Cold  (1-40)   {sb['cold']:>4}  ({_pct(sb['cold'], total):>4})  "
        f"{_bar(sb['cold'], max_band)}")

    # --- Top prospects ---
    add()
    add("  TOP PROSPECTS  (by lead score)")
    add(DASH)
    add(f"  {'#':<4} {'Name':<22} {'Company':<22} {'Score':>5}  Status")
    add(f"  {'-'*4} {'-'*22} {'-'*22} {'-'*5}  {'-'*10}")
    for i, p_ in enumerate(summary["top_prospects"], start=1):
        add(
            f"  {i:<4} {(p_['name'] or '')[:22]:<22} "
            f"{(p_['company'] or '')[:22]:<22} "
            f"{p_['lead_score']:>5}  {p_['status']}"
        )

    # --- Top companies ---
    add()
    add("  TOP COMPANIES  (by prospect count)")
    add(DASH)
    max_co = summary["top_companies"][0][1] if summary["top_companies"] else 1
    for company, count in summary["top_companies"]:
        bar = _bar(count, max_co, width=15)
        add(f"  {company[:30]:<30}  {count:>3}  {bar}")

    # --- Outreach ---
    add()
    add("  OUTREACH")
    add(DASH)
    add(f"  Drafts           : {out['draft']}")
    add(f"  Approved         : {out['approved']}")
    add(f"  Sent             : {out['sent']}")
    total_out = sum(out.values())
    add(f"  Total            : {total_out}")

    add()
    add(SEP)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def print_report(db_path: str = DB_PATH) -> None:
    """Generate and print the pipeline report to the terminal."""
    summary = generate_summary(db_path)
    print(format_report(summary))


def save_report(filepath: str, db_path: str = DB_PATH) -> None:
    """
    Generate the pipeline report and save it to a plain-text file.

    Args:
        filepath: Path to write the .txt file (created or overwritten).
        db_path:  Path to the database file.
    """
    summary = generate_summary(db_path)
    report  = format_report(summary)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"[Reporter] Report saved to: {filepath}")


def export_prospects_csv(filepath: str, db_path: str = DB_PATH) -> int:
    """
    Export all prospects to a CSV file.

    Columns match the database schema so the file can be re-imported
    or opened in Excel / Google Sheets.

    Args:
        filepath: Path to write the .csv file (created or overwritten).
        db_path:  Path to the database file.

    Returns:
        The number of rows written (excluding the header).
    """
    prospects = get_all_prospects(db_path)
    if not prospects:
        print("[Reporter] No prospects to export.")
        return 0

    fieldnames = [
        "id", "name", "company", "email", "linkedin_url",
        "website", "phone", "lead_score", "status", "notes", "date_added",
    ]

    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        # utf-8-sig adds a BOM so Excel opens it correctly
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(prospects)

    print(f"[Reporter] {len(prospects)} prospect(s) exported to: {filepath}")
    return len(prospects)
