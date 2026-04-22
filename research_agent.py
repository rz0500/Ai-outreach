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
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from database import (
    DB_PATH, get_all_prospects, update_enrichment_fields, update_notes,
    save_research_result, get_latest_research,
)
from ai_engine import analyze_website

logger = logging.getLogger(__name__)

# Extra pages to try when homepage text is thin
_EXTRA_PATHS = ["/about", "/about-us", "/services", "/what-we-do", "/team"]
_MIN_TEXT_LEN = 200


def _get_session():
    """Return a cloudscraper session (bypasses Cloudflare JS challenges)."""
    try:
        import cloudscraper
        return cloudscraper.create_scraper(browser={"browser": "chrome", "platform": "windows"})
    except Exception:
        import requests
        s = requests.Session()
        s.headers["User-Agent"] = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
        return s


def _parse_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    return soup.get_text(separator=" ", strip=True)


# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------

def scrape_website_text(url: str) -> str:
    """
    Scrape visible text from a URL using cloudscraper (Cloudflare bypass).
    If the homepage returns thin content, also tries /about and /services pages
    and concatenates results.
    """
    if not url.startswith("http"):
        url = "https://" + url
    session = _get_session()
    texts = []
    try:
        resp = session.get(url, timeout=12)
        resp.raise_for_status()
        text = _parse_text(resp.text)
        if text:
            texts.append(text)
    except Exception as e:
        return f"[Scrape Error: {e}]"

    # If homepage text is thin, try extra pages
    if len(" ".join(texts)) < _MIN_TEXT_LEN:
        for path in _EXTRA_PATHS:
            try:
                r = session.get(urljoin(url, path), timeout=8)
                if r.status_code == 200:
                    t = _parse_text(r.text)
                    if t:
                        texts.append(t)
                if len(" ".join(texts)) >= _MIN_TEXT_LEN:
                    break
            except Exception:
                continue

    combined = " ".join(texts)[:8000]
    return combined if combined else "[Scrape Error: no text extracted]"


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
    all_p = get_all_prospects(db_path=db_path)
    prospect = next((p for p in all_p if p["id"] == prospect_id), None)
    if not prospect:
        raise ValueError(f"No prospect found with id={prospect_id}")

    url = prospect.get("website")
    if not url:
        return {"error": "No website URL"}

    # Skip if already researched (prefer structured table; fall back to notes marker)
    if get_latest_research(prospect_id, db_path):
        return {"error": "Already researched — skipping."}
    existing_notes = prospect.get("notes") or ""
    if "[Research Hook]" in existing_notes:
        return {"error": "Already researched (legacy notes marker) — skipping."}

    logger.info(f"    Crawling {url}...")
    website_text = scrape_website_text(url)

    if "[Scrape Error" in website_text or len(website_text) < 50:
        return {"error": "Could not scrape sufficient text or hit a firewall."}

    logger.info("    Analyzing with Claude...")
    analysis = analyze_website(prospect.get("company", "the company"), website_text)

    # --- Persist structured research record (queryable, timestamped) ---
    save_research_result(prospect_id, analysis, url=url, db_path=db_path)

    # --- Persist enrichment fields directly to the prospects table ---
    enrichment_fields = {
        "niche":            analysis.get("niche", ""),
        "icp":              analysis.get("icp", ""),
        "website_headline": analysis.get("website_headline", ""),
        "product_feature":  analysis.get("product_feature", ""),
        "competitors":      analysis.get("competitors", ""),
    }
    update_enrichment_fields(prospect_id, enrichment_fields, db_path)

    # --- Append research hook to notes (backward-compat for email engine) ---
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
        p for p in get_all_prospects(db_path=db_path)
        if p["status"] == "qualified"
        and not get_latest_research(p["id"], db_path)
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
