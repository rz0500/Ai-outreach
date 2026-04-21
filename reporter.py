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

def generate_summary(client_id: int = 1, db_path: str = DB_PATH) -> dict:
    """
    Collect all pipeline statistics for a client workspace into a single dict.

    Args:
        client_id: Filter to this workspace (default: house account = 1).
        db_path:   Path to the database file.

    Returns a dict with keys: date, prospects, outreach, funnel,
    score_bands, top_prospects, top_companies.
    """
    prospects = get_all_prospects(client_id=client_id, db_path=db_path)
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
    outreach = get_all_outreach(client_id=client_id, db_path=db_path)
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
# HTML report for weekly email
# ---------------------------------------------------------------------------

def generate_weekly_report_html(
    summary: dict,
    client_name: str = "",
    week_label: str = "",
    dashboard_url: str = "",
) -> str:
    """
    Render a summary dict as a branded HTML email body.

    Args:
        summary:       Dict returned by generate_summary().
        client_name:   Client's name for the greeting line.
        week_label:    Human-readable week string, e.g. "14 Apr 2026".
        dashboard_url: Full URL to the client dashboard (for the CTA button).

    Returns:
        HTML string safe to pass to mailer.send_email(html_body=...).
    """
    p   = summary["prospects"]
    f   = summary["funnel"]
    sb  = summary["score_bands"]
    out = summary["outreach"]
    total = p["total"]

    def stat_block(label: str, value) -> str:
        return (
            f'<td style="text-align:center;padding:12px 16px;">'
            f'<div style="font-size:28px;font-weight:700;color:#a78bfa;">{value}</div>'
            f'<div style="font-size:11px;color:#64748b;text-transform:uppercase;'
            f'letter-spacing:0.08em;margin-top:4px;">{label}</div>'
            f'</td>'
        )

    def funnel_row(label: str, count: int, colour: str) -> str:
        pct = round(count / total * 100) if total else 0
        bar_w = max(4, pct)
        return (
            f'<tr>'
            f'<td style="padding:5px 0;font-size:13px;color:#94a3b8;width:90px;">{label}</td>'
            f'<td style="padding:5px 8px;font-size:13px;font-weight:600;color:#e2e8f0;'
            f'width:36px;text-align:right;">{count}</td>'
            f'<td style="padding:5px 0;">'
            f'<div style="height:8px;border-radius:4px;background:{colour};'
            f'width:{bar_w}%;max-width:100%;"></div></td>'
            f'</tr>'
        )

    # Top prospects rows
    top_rows = ""
    for p_ in summary["top_prospects"][:5]:
        score = p_.get("lead_score", 0)
        score_colour = "#6ee7b7" if score >= 71 else ("#fbbf24" if score >= 41 else "#94a3b8")
        top_rows += (
            f'<tr style="border-bottom:1px solid rgba(255,255,255,0.04);">'
            f'<td style="padding:8px 0;font-size:13px;color:#e2e8f0;">'
            f'{(p_.get("name") or "")[:28]}</td>'
            f'<td style="padding:8px 8px;font-size:12px;color:#94a3b8;">'
            f'{(p_.get("company") or "")[:24]}</td>'
            f'<td style="padding:8px 0;font-size:13px;font-weight:700;'
            f'color:{score_colour};text-align:right;">{score}</td>'
            f'<td style="padding:8px 0 8px 8px;font-size:11px;color:#64748b;'
            f'text-transform:uppercase;">{p_.get("status","")}</td>'
            f'</tr>'
        )

    cta = (
        f'<tr><td colspan="2" style="padding-top:28px;text-align:center;">'
        f'<a href="{dashboard_url}" style="display:inline-block;background:'
        f'linear-gradient(135deg,#7c3aed,#4f46e5);color:#fff;text-decoration:none;'
        f'font-weight:700;font-size:14px;padding:12px 28px;border-radius:10px;">'
        f'View your dashboard</a>'
        f'</td></tr>'
    ) if dashboard_url else ""

    greeting = f"Hi {client_name}," if client_name else "Hi,"
    week_str  = week_label or str(date.today())

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#080c14;font-family:'Helvetica Neue',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#080c14;padding:32px 16px;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">

  <!-- Header -->
  <tr><td style="padding-bottom:24px;">
    <div style="font-size:13px;font-weight:700;color:#a78bfa;letter-spacing:0.1em;
                text-transform:uppercase;">OutreachEmpower</div>
    <h1 style="margin:8px 0 4px;font-size:22px;font-weight:700;color:#f8fafc;">
      Your pipeline — week of {week_str}</h1>
    <p style="margin:0;font-size:14px;color:#64748b;">{greeting}</p>
  </td></tr>

  <!-- Stats row -->
  <tr><td style="padding-bottom:24px;">
    <table width="100%" cellpadding="0" cellspacing="0"
           style="background:#0d1117;border:1px solid rgba(255,255,255,0.07);
                  border-radius:14px;">
      <tr>
        {stat_block("Prospects", total)}
        {stat_block("Sent", out.get("sent", 0))}
        {stat_block("Replies", f["counts"].get("replied", 0))}
        {stat_block("Booked", f["counts"].get("booked", 0))}
      </tr>
    </table>
  </td></tr>

  <!-- Funnel + Score bands -->
  <tr><td style="padding-bottom:24px;">
    <table width="100%" cellpadding="0" cellspacing="0" style="border-spacing:0;">
      <tr valign="top">
        <td width="52%" style="padding-right:12px;">
          <div style="background:#0d1117;border:1px solid rgba(255,255,255,0.07);
                      border-radius:14px;padding:16px 18px;">
            <div style="font-size:11px;color:#64748b;text-transform:uppercase;
                        letter-spacing:0.08em;margin-bottom:10px;">Status funnel</div>
            <table cellpadding="0" cellspacing="0" width="100%">
              {funnel_row("New", f["counts"].get("new",0), "#6366f1")}
              {funnel_row("Contacted", f["counts"].get("contacted",0), "#8b5cf6")}
              {funnel_row("Replied", f["counts"].get("replied",0), "#a78bfa")}
              {funnel_row("Booked", f["counts"].get("booked",0), "#6ee7b7")}
              {funnel_row("Rejected", f["counts"].get("rejected",0), "#475569")}
            </table>
            <div style="margin-top:10px;font-size:11px;color:#64748b;">
              Conversion rate: <strong style="color:#a78bfa;">{f["conversion_rate"]}%</strong>
            </div>
          </div>
        </td>
        <td width="48%">
          <div style="background:#0d1117;border:1px solid rgba(255,255,255,0.07);
                      border-radius:14px;padding:16px 18px;">
            <div style="font-size:11px;color:#64748b;text-transform:uppercase;
                        letter-spacing:0.08em;margin-bottom:10px;">Lead scores</div>
            <div style="margin-bottom:10px;">
              <div style="font-size:12px;color:#6ee7b7;font-weight:600;">
                Hot (71–100) &nbsp;<span style="color:#e2e8f0;">{sb["hot"]}</span></div>
              <div style="height:6px;border-radius:3px;background:#6ee7b7;
                          width:{round(sb["hot"]/max(total,1)*100)}%;margin:4px 0 8px;"></div>
              <div style="font-size:12px;color:#fbbf24;font-weight:600;">
                Warm (41–70) &nbsp;<span style="color:#e2e8f0;">{sb["warm"]}</span></div>
              <div style="height:6px;border-radius:3px;background:#fbbf24;
                          width:{round(sb["warm"]/max(total,1)*100)}%;margin:4px 0 8px;"></div>
              <div style="font-size:12px;color:#94a3b8;font-weight:600;">
                Cold (1–40) &nbsp;<span style="color:#e2e8f0;">{sb["cold"]}</span></div>
              <div style="height:6px;border-radius:3px;background:#475569;
                          width:{round(sb["cold"]/max(total,1)*100)}%;margin:4px 0;"></div>
            </div>
          </div>
        </td>
      </tr>
    </table>
  </td></tr>

  <!-- Top prospects -->
  {'<tr><td style="padding-bottom:24px;"><div style="background:#0d1117;border:1px solid rgba(255,255,255,0.07);border-radius:14px;padding:16px 18px;"><div style="font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:10px;">Top prospects</div><table width="100%" cellpadding="0" cellspacing="0">' + top_rows + '</table></div></td></tr>' if top_rows else ""}

  <!-- CTA -->
  <tr><td>
    <table width="100%" cellpadding="0" cellspacing="0">
      {cta}
      <tr><td style="padding-top:24px;border-top:1px solid rgba(255,255,255,0.06);">
        <p style="margin:0;font-size:12px;color:#475569;text-align:center;">
          — The OutreachEmpower Team
        </p>
      </td></tr>
    </table>
  </td></tr>

</table>
</td></tr>
</table>
</body></html>"""


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


def export_prospects_csv(filepath: str, client_id: int = 1, db_path: str = DB_PATH) -> int:
    """
    Export prospects for a client workspace to a CSV file.

    Columns match the database schema so the file can be re-imported
    or opened in Excel / Google Sheets.

    Args:
        filepath:  Path to write the .csv file (created or overwritten).
        client_id: Filter to this workspace (default: house account = 1).
        db_path:   Path to the database file.

    Returns:
        The number of rows written (excluding the header).
    """
    prospects = get_all_prospects(client_id=client_id, db_path=db_path)
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
