"""
research_agent.py - Deep Research Web Crawler
===============================================
Module 12 of the AI Lead Gen System.

Visits a prospect's website, scrapes the visible text, and uses Claude to
extract structured enrichment intelligence. The following fields are written
directly to the database:

    niche            — what the company specifically does
    icp              — their ideal customer profile
    website_headline — verbatim hero/H1 copy from the homepage
    product_feature  — their most distinctive feature or angle
    competitors      — named competitors found on-site (comma-separated)

A research hook (pain point + growth signal + opener) is also appended to
the prospect's notes field so ai_engine.py can use it when generating emails.

Prospects are skipped if they have already been researched (notes contain
the [Research Hook] marker).
"""

import logging
import requests
from bs4 import BeautifulSoup

from database import DB_PATH, get_all_prospects, update_enrichment_fields, update_notes
from ai_engine import analyze_website

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------

def scrape_website_text(url: str) -> str:
    """Safely scrape the visible text of a given URL."""
    if not url.startswith("http"):
        url = "http://" + url
    try:
        resp = requests.get(
            url,
            timeout=10,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/91.0.4472.124 Safari/537.36"
                )
            },
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        # Strip noise
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        return soup.get_text(separator=" ", strip=True)
    except Exception as e:
        return f"[Scrape Error: {e}]"


# ---------------------------------------------------------------------------
# Single prospect research
# ---------------------------------------------------------------------------

def research_prospect(prospect_id: int, db_path: str = DB_PATH) -> dict:
    """
    Scrape and research a single prospect by their ID.

    Writes enrichment fields to the DB and appends a [Research Hook] block
    to their notes. Returns the raw analysis dict from Claude, or a dict
    containing an 'error' key on failure.
    """
    all_p = get_all_prospects(db_path)
    prospect = next((p for p in all_p if p["id"] == prospect_id), None)
    if not prospect:
        raise ValueError(f"No prospect found with id={prospect_id}")

    url = prospect.get("website")
    if not url:
        return {"error": "No website URL"}

    # Skip if already researched
    existing_notes = prospect.get("notes") or ""
    if "[Research Hook]" in existing_notes:
        return {"error": "Already researched — skipping."}

    logger.info(f"    Crawling {url}...")
    website_text = scrape_website_text(url)

    if "[Scrape Error" in website_text or len(website_text) < 50:
        return {"error": "Could not scrape sufficient text or hit a firewall."}

    logger.info("    Analyzing with Claude...")
    analysis = analyze_website(prospect.get("company", "the company"), website_text)

    # --- Persist enrichment fields directly to the DB ---
    enrichment_fields = {
        "niche":            analysis.get("niche", ""),
        "icp":              analysis.get("icp", ""),
        "website_headline": analysis.get("website_headline", ""),
        "product_feature":  analysis.get("product_feature", ""),
        "competitors":      analysis.get("competitors", ""),
    }
    update_enrichment_fields(prospect_id, enrichment_fields, db_path)

    # --- Append the research hook to notes for email generation ---
    hook_note = (
        f"[Research Hook]\n"
        f"Pain Point: {analysis['pain_point']}\n"
        f"Growth Signal: {analysis['growth_signal']}\n"
        f"Opener: {analysis['hook']}"
    )
    combined = f"{existing_notes}\n\n{hook_note}".strip()
    update_notes(prospect_id, combined, db_path)

    return analysis


# ---------------------------------------------------------------------------
# Batch runner
# ---------------------------------------------------------------------------

def run_research_batch(db_path: str = DB_PATH) -> int:
    """
    Run research on all 'qualified' prospects that haven't been researched yet.

    Returns:
        Number of prospects successfully researched.
    """
    prospects = [
        p for p in get_all_prospects(db_path)
        if p["status"] == "qualified"
        and "[Research Hook]" not in (p.get("notes") or "")
    ]

    if not prospects:
        return 0

    print(f"  Found {len(prospects)} qualified prospect(s) requiring deep research.")
    success_count = 0

    for p in prospects:
        print(f"  -> Researching: {p['name']} from {p['company']}")
        try:
            result = research_prospect(p["id"], db_path)
            if "error" in result:
                print(f"    Skipped: {result['error']}")
            else:
                filled = [
                    k for k in ("niche", "icp", "website_headline", "product_feature")
                    if result.get(k)
                ]
                print(f"    Success. Fields filled: {', '.join(filled) or 'hook only'}.")
                success_count += 1
        except Exception as e:
            if "AuthenticationError" in str(e):
                print("    Failed: Missing Anthropic API Key. Stopping batch.")
                break
            print(f"    Failed: {e}")

    return success_count
