import os
import time
import datetime
from flask import Flask, render_template, send_from_directory, jsonify, request
from urllib.parse import urlparse
from dotenv import load_dotenv

# Load .env before any module that creates an Anthropic client at import time
load_dotenv()

import database
import reporter
from mailer import send_email as _smtp_send_email
from outreach import debug_email_reasoning, generate_email
from settings import (
    get_calendar_link,
    get_inbox_poll_interval,
    get_sequence_run_hour,
    get_use_sendgrid,
)

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Background scheduler state — shared across threads (GIL-safe for these ops)
# ---------------------------------------------------------------------------
_scheduler_state: dict = {
    "last_inbox_check":      None,   # datetime | None
    "last_inbox_result":     None,   # int (replies found) | None
    "last_inbox_error":      None,   # str | None
    "last_sequence_run":     None,   # datetime | None
    "last_sequence_error":   None,   # str | None
    "running":               False,
    "paused":                False,  # True after MAX_CONSECUTIVE_ERRORS inbox failures
    "consecutive_errors":    0,
}

_MAX_CONSECUTIVE_ERRORS = 5


def _background_scheduler() -> None:
    """
    Daemon thread that:
      - Polls the inbox every INBOX_POLL_INTERVAL seconds.
      - Runs the sequence dispatcher once per day at SEQUENCE_RUN_HOUR (UTC).
      - Pauses inbox polling after 5 consecutive errors (IMAP misconfigured etc.)
    Runs forever; killed automatically when the main process exits.
    """
    _scheduler_state["running"] = True
    last_sequence_date: datetime.date | None = None

    while True:
        now_utc = datetime.datetime.utcnow()

        # ── Inbox poll ────────────────────────────────────────────────────
        if not _scheduler_state["paused"]:
            try:
                from inbox_monitor import check_for_replies
                found = check_for_replies(mark_as_read=True)
                _scheduler_state["last_inbox_check"]    = now_utc
                _scheduler_state["last_inbox_result"]   = found
                _scheduler_state["last_inbox_error"]    = None
                _scheduler_state["consecutive_errors"]  = 0
            except Exception as exc:
                _scheduler_state["last_inbox_check"]  = now_utc
                _scheduler_state["last_inbox_error"]  = str(exc)
                _scheduler_state["consecutive_errors"] += 1
                if _scheduler_state["consecutive_errors"] >= _MAX_CONSECUTIVE_ERRORS:
                    _scheduler_state["paused"] = True
                    _scheduler_state["last_inbox_error"] = (
                        f"Paused after {_MAX_CONSECUTIVE_ERRORS} consecutive errors. "
                        f"Last: {exc}"
                    )

        # ── Daily sequence run ────────────────────────────────────────────
        run_hour = get_sequence_run_hour()
        today = now_utc.date()
        if now_utc.hour >= run_hour and last_sequence_date != today:
            try:
                from sequence_dispatcher import run_multichannel_sequence
                run_multichannel_sequence(dry_run=False)
                _scheduler_state["last_sequence_run"]   = now_utc
                _scheduler_state["last_sequence_error"] = None
                last_sequence_date = today
            except Exception as exc:
                _scheduler_state["last_sequence_error"] = str(exc)
                last_sequence_date = today  # don't retry same day on error

        time.sleep(get_inbox_poll_interval())

# Ensure tables exist to prevent sqlite crash if visited before running main
database.initialize_database()
database.initialize_outreach_table()

# ---------------------------------------------------------------------------
# Sample prospect data used to showcase the email engine on the dashboard
# ---------------------------------------------------------------------------
SAMPLE_PROSPECTS = [
    {
        "name": "Sarah Chen",
        "company": "Acme SaaS",
        "niche": "CRM automation for mid-market agencies",
        "website_headline": "The CRM built for fast-moving agencies",
        "competitors": "HubSpot, Pipedrive",
        "ad_status": "running_ads",
    },
    {
        "name": "Marcus Rivera",
        "company": "BluePeak Ventures",
        "niche": "B2B SaaS growth consulting",
        "hiring_signal": "hiring an SDR on LinkedIn",
    },
    {
        "name": "Elena Kovacs",
        "company": "Drift Analytics",
        "niche": "no-code analytics platform for ops teams",
        "product_feature": "native integration with Snowflake and dbt",
        "outbound_status": "no_outbound",
    },
    {
        "name": "Priya Nair",
        "company": "Nexus Health",
        "niche": "health-tech SaaS for clinic administrators",
        "linkedin_activity": "reducing admin burnout in NHS clinics",
    },
    {
        "name": "David Osei",
        "company": "Fortis Logistics",
        "outbound_status": "no_outbound",
    },
]

ANGLE_LABELS = [
    "Homepage + Competitor",
    "Hiring Signal",
    "Product Feature",
    "LinkedIn Post",
    "Thin Data Fallback",
]


def _annotate_sequence_progress(prospects: list[dict]) -> list[dict]:
    """
    Add a human-readable sequence progress label for the dashboard pipeline table.

    "Day N" is based on sequence_enrollments.enrolled_at, counting the enrollment
    date as Day 1. If no enrollment exists, the label is "Not enrolled".
    """
    today = datetime.date.today()
    annotated: list[dict] = []

    for prospect in prospects:
        row = dict(prospect)
        enrollment = database.get_sequence_enrollment(row["id"])
        row["sequence_day_label"] = "Not enrolled"

        if enrollment and enrollment.get("enrolled_at"):
            try:
                enrolled_at = datetime.date.fromisoformat(enrollment["enrolled_at"])
                row["sequence_day_label"] = f"Day {max((today - enrolled_at).days + 1, 1)}"
            except ValueError:
                row["sequence_day_label"] = "Enrolled"

        annotated.append(row)

    return annotated


def _fetch_url_enrichment(url: str, company_override: str = "") -> tuple[dict, str | None]:
    """Fetch a company website and convert it into prospect enrichment data."""
    import requests as _req
    from bs4 import BeautifulSoup

    raw_url = (url or "").strip()
    company_override = (company_override or "").strip()

    if not raw_url:
        return {}, "No URL provided."

    if not raw_url.startswith("http"):
        raw_url = "https://" + raw_url

    try:
        resp = _req.get(raw_url, timeout=12, headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        })
        resp.raise_for_status()
    except Exception as exc:
        return {}, f"Could not reach that URL: {exc}"

    soup = BeautifulSoup(resp.text, "html.parser")

    def _meta(name=None, prop=None):
        tag = soup.find("meta", attrs={"name": name} if name else {"property": prop})
        return (tag.get("content") or "").strip() if tag else ""

    page_title = (soup.title.string or "").strip() if soup.title else ""
    og_site_name = _meta(prop="og:site_name")
    meta_desc = _meta(name="description") or _meta(prop="og:description")
    h1_tag = soup.find("h1")
    h1_text = h1_tag.get_text(strip=True) if h1_tag else ""

    if company_override:
        company_name = company_override
    elif og_site_name:
        company_name = og_site_name
    elif page_title:
        company_name = page_title.split("|")[0].split("-")[0].split("â€“")[0].strip()
    else:
        domain = urlparse(raw_url).netloc.replace("www.", "")
        company_name = domain.split(".")[0].title()

    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    website_text = soup.get_text(separator=" ", strip=True)

    if len(website_text) < 50:
        return {}, "Page returned too little text. Try a different URL."

    has_api_key = bool(os.getenv("ANTHROPIC_API_KEY", "").strip())
    if has_api_key:
        from ai_engine import analyze_website

        try:
            analysis = analyze_website(company_name, website_text)
        except Exception as exc:
            return {}, f"Analysis failed: {exc}"

        prospect = {
            "name": "Founder",
            "company": company_name,
            "website": raw_url,
            "niche": analysis.get("niche", ""),
            "icp": analysis.get("icp", ""),
            "website_headline": analysis.get("website_headline", ""),
            "product_feature": analysis.get("product_feature", ""),
            "competitors": analysis.get("competitors", ""),
            "notes": (
                f"[Research Hook]\n"
                f"Pain Point: {analysis.get('pain_point', '')}\n"
                f"Growth Signal: {analysis.get('growth_signal', '')}\n"
                f"Opener: {analysis.get('hook', '')}"
            ),
        }
        prospect["enrichment"] = {
            "company": company_name,
            "niche": analysis.get("niche", ""),
            "icp": analysis.get("icp", ""),
            "headline": analysis.get("website_headline", ""),
            "product_feature": analysis.get("product_feature", ""),
            "hook": analysis.get("hook", ""),
        }
        return prospect, None

    prospect = {
        "name": "Founder",
        "company": company_name,
        "website": raw_url,
        "website_headline": h1_text or "",
        "niche": meta_desc[:120] if meta_desc else "",
        "icp": "",
        "product_feature": "",
        "competitors": "",
        "notes": "",
    }
    prospect["enrichment"] = {
        "company": company_name,
        "niche": meta_desc[:120] if meta_desc else "",
        "icp": "",
        "headline": h1_text or "",
        "product_feature": "",
        "hook": "",
    }
    return prospect, None

def _generate_sample_emails():
    """Generate sample emails from test prospects to showcase the engine."""
    samples = []
    for i, p in enumerate(SAMPLE_PROSPECTS):
        result = generate_email(p)
        samples.append({
            "prospect_name": p["name"],
            "prospect_company": p["company"],
            "angle": ANGLE_LABELS[i] if i < len(ANGLE_LABELS) else "Custom",
            "subject": result["subject"],
            "body": result["body"],
            "quality_score": result["quality_score"],
        })
    return samples


@app.route("/")
def index():
    # We query the database via our existing modules
    prospects = _annotate_sequence_progress(database.get_all_prospects())
    summary = reporter.generate_summary()
    
    # Get recent outbox drafts/sent
    try:
        outreach_data = database.get_all_outreach()
    except Exception:
        outreach_data = []
        
    # Get generated PDF proposals
    pdfs = []
    if os.path.exists("proposals"):
        pdfs = [f for f in os.listdir("proposals") if f.endswith(".pdf")]
    decks = []
    if os.path.exists("decks"):
        decks = [f for f in os.listdir("decks") if f.endswith(".pdf")]

    # Reply drafts awaiting review
    try:
        reply_drafts = database.get_pending_reply_drafts()
    except Exception:
        reply_drafts = []

    # Generate sample emails to showcase on dashboard
    sample_emails = _generate_sample_emails()

    return render_template(
        "index.html",
        summary=summary,
        prospects=prospects,
        outreach=outreach_data,
        pdfs=pdfs,
        decks=decks,
        reply_drafts=reply_drafts,
        sample_emails=sample_emails,
    )

@app.route("/api/sample-emails")
def api_sample_emails():
    """JSON endpoint returning sample generated emails for external tools."""
    return jsonify(_generate_sample_emails())

@app.route("/proposals/<path:filename>")
def serve_proposal(filename):
    """Securely serve generated PDF files so they can be viewed in browser."""
    return send_from_directory(os.path.abspath("proposals"), filename)


@app.route("/decks/<path:filename>")
def serve_deck(filename):
    """Securely serve generated deck files."""
    return send_from_directory(os.path.abspath("decks"), filename)


@app.route("/api/sample-pdf", methods=["POST"])
def api_sample_pdf():
    """
    Generate (or regenerate) the built-in Apex Digital demo PDF and return
    its serve path so the browser can open it immediately.
    """
    from pdf_generator import generate_proposal

    demo = {
        "name": "James Cole",
        "company": "Apex Digital",
        "email": "james@apexdigital.io",
        "status": "qualified",
        "niche": "B2B SaaS for construction project managers",
        "icp": "mid-sized UK construction firms managing 5+ concurrent projects",
        "website_headline": "Stop losing projects to miscommunication",
        "product_feature": "real-time site-to-office sync with automated progress reporting",
        "competitors": "Buildertrend, CoConstruct",
        "ad_status": "running_ads",
        "outbound_status": "no_outbound",
        "notes": (
            "[Research Hook]\n"
            "Pain Point: Construction PMs waste 6+ hours per week on manual status updates.\n"
            "Growth Signal: Recently rebranded site with enterprise case studies added.\n"
            "Opener: Apex Digital's positioning around miscommunication is sharp — "
            "it is a problem every PM recognises immediately."
        ),
    }

    try:
        filepath = generate_proposal(demo)
        filename = os.path.basename(filepath)
        return jsonify({"url": f"/proposals/{filename}", "filename": filename})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/sample-deck", methods=["POST"])
def api_sample_deck():
    """Generate the built-in Apex Digital sample deck PDF and return its asset."""
    from deck_generator import generate_deck

    demo = {
        "name": "James Cole",
        "company": "Apex Digital",
        "email": "james@apexdigital.io",
        "status": "qualified",
        "niche": "B2B SaaS for construction project managers",
        "icp": "mid-sized UK construction firms managing 5+ concurrent projects",
        "website_headline": "Stop losing projects to miscommunication",
        "product_feature": "real-time site-to-office sync with automated progress reporting",
        "competitors": "Buildertrend, CoConstruct",
        "ad_status": "running_ads",
        "outbound_status": "no_outbound",
        "notes": (
            "[Research Hook]\n"
            "Pain Point: miscommunication between site and office\n"
            "Growth Signal: Recently rebranded site with enterprise case studies added.\n"
            "Opener: Apex Digital's positioning around miscommunication is sharp because every PM feels it on a live project."
        ),
    }

    try:
        filepath = generate_deck(demo)
        filename = os.path.basename(filepath)
        return jsonify({"pdf_url": f"/decks/{filename}", "pdf_filename": filename})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/generate-deck-from-url", methods=["POST"])
def api_generate_deck_from_url():
    """Accept a company URL and generate a deck PDF from extracted site data."""
    from deck_generator import generate_deck

    data = request.get_json(silent=True) or {}
    prospect, error = _fetch_url_enrichment(
        url=(data.get("url") or "").strip(),
        company_override=(data.get("company") or "").strip(),
    )
    if error:
        return jsonify({"error": error}), 400

    try:
        filepath = generate_deck(prospect)
        filename = os.path.basename(filepath)
        return jsonify({
            "pdf_url": f"/decks/{filename}",
            "pdf_filename": filename,
            "company": prospect.get("company", ""),
            "enrichment": prospect.get("enrichment", {}),
        })
    except Exception as exc:
        return jsonify({
            "error": str(exc),
            "company": prospect.get("company", ""),
            "enrichment": prospect.get("enrichment", {}),
        }), 500


@app.route("/api/generate-from-url", methods=["POST"])
def api_generate_from_url():
    """
    Accepts a website URL and returns a cold email plus debugging data.

    If ANTHROPIC_API_KEY is set: full AI mode — Claude analyzes the site
    and generates a hyper-personalized email.

    If no key: template mode — extracts enrichment from HTML tags (title,
    meta description, H1, OG tags) and routes through the template engine.

    Body: { "url": "https://...", "company": "(optional override)" }
    """
    import requests as _req
    from bs4 import BeautifulSoup

    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    company_override = (data.get("company") or "").strip()

    if not url:
        return jsonify({"error": "No URL provided."}), 400

    if not url.startswith("http"):
        url = "https://" + url

    # ------------------------------------------------------------------ #
    # 1. Fetch page                                                       #
    # ------------------------------------------------------------------ #
    try:
        resp = _req.get(url, timeout=12, headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        })
        resp.raise_for_status()
    except Exception as exc:
        return jsonify({"error": f"Could not reach that URL: {exc}"}), 400

    soup = BeautifulSoup(resp.text, "html.parser")

    # ------------------------------------------------------------------ #
    # 2. Extract enrichment from raw HTML (no AI needed)                  #
    # ------------------------------------------------------------------ #
    def _meta(name=None, prop=None):
        tag = soup.find("meta", attrs={"name": name} if name else {"property": prop})
        return (tag.get("content") or "").strip() if tag else ""

    page_title   = (soup.title.string or "").strip() if soup.title else ""
    og_site_name = _meta(prop="og:site_name")
    meta_desc    = _meta(name="description") or _meta(prop="og:description")
    h1_tag       = soup.find("h1")
    h1_text      = h1_tag.get_text(strip=True) if h1_tag else ""

    # Company name: override > og:site_name > page title > domain
    if company_override:
        company_name = company_override
    elif og_site_name:
        company_name = og_site_name
    elif page_title:
        company_name = page_title.split("|")[0].split("-")[0].split("–")[0].strip()
    else:
        domain = urlparse(url).netloc.replace("www.", "")
        company_name = domain.split(".")[0].title()

    # Strip noise before pulling body text
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    website_text = soup.get_text(separator=" ", strip=True)

    if len(website_text) < 50:
        return jsonify({"error": "Page returned too little text. Try a different URL."}), 400

    # ------------------------------------------------------------------ #
    # 3. Route: AI mode vs template mode                                  #
    # ------------------------------------------------------------------ #
    has_api_key = bool(os.getenv("ANTHROPIC_API_KEY", "").strip())

    if has_api_key:
        # ---- AI MODE ----
        from ai_engine import analyze_website, generate_hyper_personalized_email

        try:
            analysis = analyze_website(company_name, website_text)
        except Exception as exc:
            return jsonify({"error": f"Analysis failed: {exc}"}), 500

        prospect = {
            "name":             "Founder",
            "company":          company_name,
            "website":          url,
            "niche":            analysis.get("niche", ""),
            "icp":              analysis.get("icp", ""),
            "website_headline": analysis.get("website_headline", ""),
            "product_feature":  analysis.get("product_feature", ""),
            "competitors":      analysis.get("competitors", ""),
            "notes": (
                f"[Research Hook]\n"
                f"Pain Point: {analysis.get('pain_point', '')}\n"
                f"Growth Signal: {analysis.get('growth_signal', '')}\n"
                f"Opener: {analysis.get('hook', '')}"
            ),
        }
        debug = debug_email_reasoning(prospect)

        try:
            email_result = generate_hyper_personalized_email(prospect)
        except ValueError as exc:
            return jsonify({
                "error": str(exc),
                "mode": "ai",
                "analysis": debug["analysis"],
                "angle": debug["angle"],
                "internal_quality": {
                    "specificity": debug["internal_quality"].specificity,
                    "credibility": debug["internal_quality"].credibility,
                    "generic_risk": debug["internal_quality"].generic_risk,
                },
                "debug_email": debug["email"],
                "enrichment": {
                    "company":         company_name,
                    "niche":           analysis.get("niche", ""),
                    "icp":             analysis.get("icp", ""),
                    "headline":        analysis.get("website_headline", ""),
                    "product_feature": analysis.get("product_feature", ""),
                    "hook":            analysis.get("hook", ""),
                },
            }), 422
        except Exception as exc:
            return jsonify({"error": f"Email generation failed: {exc}"}), 500

        return jsonify({
            "mode":          "ai",
            "subject":       email_result["subject"],
            "body":          email_result["body"],
            "quality_score": email_result["quality_score"],
            "warnings":      email_result["warnings"],
            "analysis":      debug["analysis"],
            "angle":         debug["angle"],
            "internal_quality": {
                "specificity": debug["internal_quality"].specificity,
                "credibility": debug["internal_quality"].credibility,
                "generic_risk": debug["internal_quality"].generic_risk,
            },
            "enrichment": {
                "company":         company_name,
                "niche":           analysis.get("niche", ""),
                "icp":             analysis.get("icp", ""),
                "headline":        analysis.get("website_headline", ""),
                "product_feature": analysis.get("product_feature", ""),
                "hook":            analysis.get("hook", ""),
            },
        })

    else:
        # ---- TEMPLATE MODE (no API key) ----
        # Build prospect from HTML-parsed enrichment fields
        prospect = {
            "name":             "Founder",
            "company":          company_name,
            "website":          url,
            "website_headline": h1_text or "",
            "niche":            meta_desc[:120] if meta_desc else "",
            "icp":              "",
            "product_feature":  "",
            "competitors":      "",
            "notes":            "",
        }

        debug = debug_email_reasoning(prospect)
        email_result = generate_email(prospect)

        enrichment = {
            "company":         company_name,
            "niche":           meta_desc[:120] if meta_desc else "",
            "icp":             "",
            "headline":        h1_text or "",
            "product_feature": "",
            "hook":            "",
        }

        return jsonify({
            "mode":          "template",
            "subject":       email_result["subject"],
            "body":          email_result["body"],
            "quality_score": email_result["quality_score"],
            "warnings":      ["Running in template mode. Add ANTHROPIC_API_KEY to .env for AI-generated emails."],
            "analysis":      debug["analysis"],
            "angle":         debug["angle"],
            "internal_quality": {
                "specificity": debug["internal_quality"].specificity,
                "credibility": debug["internal_quality"].credibility,
                "generic_risk": debug["internal_quality"].generic_risk,
            },
            "enrichment":    enrichment,
        })


@app.route("/api/full-pipeline", methods=["POST"])
def api_full_pipeline():
    """
    URL → Research → Email → PDF Proposal in one shot.

    Steps (all run server-side, result returned in one JSON blob):
      1. Fetch website + AI enrichment (company analysis, competitor detection,
         pain point, growth signal, ICP, hook)
      2. Generate outbound email (AI or template)
      3. Generate PDF proposal (pdf_generator)

    Body: { "url": "https://...", "company": "(optional override)" }
    """
    from pdf_generator import generate_proposal

    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    company_override = (data.get("company") or "").strip()

    if not url:
        return jsonify({"error": "No URL provided."}), 400

    # ------------------------------------------------------------------ #
    # Step 1: Research / enrichment                                        #
    # ------------------------------------------------------------------ #
    prospect, error = _fetch_url_enrichment(url, company_override)
    if error:
        return jsonify({"error": error, "step": "research"}), 400

    has_api_key = bool(os.getenv("ANTHROPIC_API_KEY", "").strip())

    # Pull structured fields out of the notes block written by _fetch_url_enrichment
    research_data = {
        "niche":           prospect.get("niche", ""),
        "icp":             prospect.get("icp", ""),
        "headline":        prospect.get("website_headline", ""),
        "product_feature": prospect.get("product_feature", ""),
        "competitors":     prospect.get("competitors", ""),
        "pain_point":      "",
        "growth_signal":   "",
        "hook":            "",
    }
    for line in (prospect.get("notes") or "").split("\n"):
        if line.startswith("Pain Point:"):
            research_data["pain_point"] = line[11:].strip()
        elif line.startswith("Growth Signal:"):
            research_data["growth_signal"] = line[14:].strip()
        elif line.startswith("Opener:"):
            research_data["hook"] = line[7:].strip()

    # ------------------------------------------------------------------ #
    # Persist prospect + research to DB                                   #
    # ------------------------------------------------------------------ #
    company_name = prospect.get("company", "")
    prospect_url = prospect.get("website", url)

    # Find or create a prospect record for this company/URL
    existing = database.search_by_company(company_name)
    matched = [p for p in existing if p.get("website") == prospect_url]
    if matched:
        prospect_id = matched[0]["id"]
    else:
        try:
            prospect_id = database.add_prospect(
                name="Founder",
                company=company_name,
                website=prospect_url,
                status="qualified",
            )
        except Exception:
            # Company may already exist with a different URL — just use first match
            if existing:
                prospect_id = existing[0]["id"]
            else:
                prospect_id = None

    if prospect_id:
        database.update_enrichment_fields(prospect_id, {
            "niche":            research_data["niche"],
            "icp":              research_data["icp"],
            "website_headline": research_data["headline"],
            "product_feature":  research_data["product_feature"],
            "competitors":      research_data["competitors"],
        })
        research_record_id = database.save_research_result(
            prospect_id=prospect_id,
            analysis={
                "niche":            research_data["niche"],
                "icp":              research_data["icp"],
                "website_headline": research_data["headline"],
                "product_feature":  research_data["product_feature"],
                "competitors":      research_data["competitors"],
                "pain_point":       research_data["pain_point"],
                "growth_signal":    research_data["growth_signal"],
                "hook":             research_data["hook"],
            },
            url=prospect_url,
        )
    else:
        research_record_id = None

    # ------------------------------------------------------------------ #
    # Step 2: Generate outbound email                                      #
    # ------------------------------------------------------------------ #
    email_result = {}
    angle = ""
    analysis_data = {}
    internal_quality = {}

    try:
        debug = debug_email_reasoning(prospect)
        angle = debug.get("angle", "")
        analysis_data = debug.get("analysis", {})
        iq = debug.get("internal_quality")
        if iq:
            internal_quality = {
                "specificity":   getattr(iq, "specificity", None),
                "credibility":   getattr(iq, "credibility", None),
                "generic_risk":  getattr(iq, "generic_risk", None),
            }
    except Exception:
        pass

    if has_api_key:
        from ai_engine import generate_hyper_personalized_email
        try:
            email_result = generate_hyper_personalized_email(prospect)
        except ValueError as exc:
            # Quality gate rejected — return the debug draft anyway
            email_result = {
                "subject":       debug.get("email", {}).get("subject", ""),
                "body":          debug.get("email", {}).get("body", ""),
                "quality_score": 0,
                "warnings":      [str(exc)],
            }
        except Exception as exc:
            email_result = {
                "subject": "", "body": "",
                "quality_score": 0, "warnings": [f"Email generation failed: {exc}"],
            }
    else:
        email_result = generate_email(prospect)

    # Save email draft to outreach table
    outreach_record_id = None
    if prospect_id and email_result.get("subject") and email_result.get("body"):
        try:
            outreach_record_id = database.save_outreach(
                prospect_id=prospect_id,
                subject=email_result["subject"],
                body=email_result["body"],
            )
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # Step 3: Generate PDF proposal                                        #
    # ------------------------------------------------------------------ #
    pdf_url      = ""
    pdf_filename = ""
    pdf_error    = ""
    try:
        filepath     = generate_proposal(prospect)
        pdf_filename = os.path.basename(filepath)
        pdf_url      = f"/proposals/{pdf_filename}"
    except Exception as exc:
        pdf_error = str(exc)

    return jsonify({
        "mode":    "ai" if has_api_key else "template",
        "company": prospect.get("company", ""),
        "url":     url,
        "prospect_id":   prospect_id,
        "research_id":   research_record_id,
        "outreach_id":   outreach_record_id,
        "research": research_data,
        "analysis": analysis_data,
        "angle":    angle,
        "internal_quality": internal_quality,
        "email": {
            "subject":       email_result.get("subject", ""),
            "body":          email_result.get("body", ""),
            "quality_score": email_result.get("quality_score", 0),
            "warnings":      email_result.get("warnings", []),
        },
        "pdf": {
            "url":      pdf_url,
            "filename": pdf_filename,
            "error":    pdf_error,
        },
    })


@app.route("/api/reply-drafts")
def api_reply_drafts():
    """Return all reply drafts with status=pending_review."""
    return jsonify(database.get_pending_reply_drafts())


@app.route("/api/sent-replies")
def api_sent_replies():
    """Return all reply drafts that have been approved and sent."""
    return jsonify(database.get_sent_reply_drafts())


@app.route("/api/reply-drafts/<int:draft_id>/action", methods=["POST"])
def api_reply_draft_action(draft_id):
    """
    Approve or dismiss a reply draft.
    Body: { "action": "approve" | "dismiss" }
    """
    data = request.get_json(silent=True) or {}
    action = (data.get("action") or "").strip()
    if action not in ("approve", "dismiss"):
        return jsonify({"error": "action must be 'approve' or 'dismiss'"}), 400

    draft = database.get_reply_draft_by_id(draft_id)
    if not draft:
        return jsonify({"error": "Draft not found"}), 404

    if action == "dismiss":
        database.update_reply_draft_status(draft_id, "dismissed")
        return jsonify({"ok": True, "status": "dismissed"})

    recipient = (draft.get("inbound_from") or draft.get("prospect_email") or "").strip()
    if not recipient:
        return jsonify({"error": "Reply draft has no recipient email."}), 400

    valid, reason = _validate_email_address(recipient)
    if not valid:
        return jsonify({"error": f"Invalid recipient: {reason}"}), 400

    # Caller may supply an edited body; fall back to the stored draft
    body = (data.get("body") or draft.get("drafted_reply") or "").strip()
    if not body:
        return jsonify({"error": "Reply draft has no body."}), 400

    # Build a proper Re: subject from the stored inbound subject when available,
    # otherwise fall back to the company name.
    raw_subject = (draft.get("inbound_subject") or "").strip()
    if not raw_subject:
        company = (draft.get("prospect_company") or "").strip()
        raw_subject = company or "follow-up"
    subject = raw_subject if raw_subject.lower().startswith("re:") else f"Re: {raw_subject}"

    # Thread headers — wire In-Reply-To / References so mail clients group the
    # reply into the original conversation thread.
    inbound_message_id = (draft.get("inbound_message_id") or "").strip()

    sent, error = _route_send_email(
        recipient, subject, body,
        in_reply_to=inbound_message_id,
        references=inbound_message_id,
    )
    if not sent:
        return jsonify({"error": f"Send failed: {error}"}), 500

    database.update_reply_draft_status(draft_id, "sent")
    database.update_status(draft["prospect_id"], "replied")
    database.log_communication_event(
        prospect_id=draft["prospect_id"],
        channel="email",
        direction="outbound",
        event_type="reply_draft_sent",
        status="sent",
        content_excerpt=body[:250],
        metadata=f"draft_id={draft_id};recipient={recipient};subject={subject}",
    )
    return jsonify({"ok": True, "status": "sent", "recipient": recipient, "subject": subject})


@app.route("/api/seed-demo-reply", methods=["POST"])
def api_seed_demo_reply():
    """
    Inject a fake interested reply into reply_drafts so the review UI
    can be tested without a live inbox connection.
    """
    prospects = database.get_all_prospects()
    if not prospects:
        return jsonify({"error": "No prospects in DB to attach demo reply to."}), 400
    p = prospects[0]
    draft_id = database.save_reply_draft(
        prospect_id=p["id"],
        inbound_from=p.get("email") or "demo@example.com",
        inbound_body=(
            "Hey, thanks for reaching out — this actually caught me at a good time. "
            "We have been thinking about outbound for a while but haven't pulled the trigger. "
            "Happy to jump on a call. What does your availability look like next week?"
        ),
        classification="interested",
        classification_reasoning="Prospect explicitly expressed interest and requested a call.",
        drafted_reply=(
            f"Hi {p.get('name', 'there').split()[0]},\n\n"
            "Great timing — really glad it landed well.\n\n"
            "I have Thursday 2pm or Friday 10am free. Either work for you? "
            f"If easier, grab a slot directly: {get_calendar_link()}\n\n"
            "Talk soon."
        ),
    )
    return jsonify({"ok": True, "draft_id": draft_id, "prospect": p.get("name")})


# ---------------------------------------------------------------------------
# Find & Fire — Google Maps → Research → Email → PDF pipeline
# ---------------------------------------------------------------------------

def _extract_email_from_website(url: str) -> str:
    """
    Scrape a company website and return the first business email address found.

    Strategy (in order):
      1. Look for mailto: links — most reliable signal.
      2. Regex-scan page text for email patterns.
      3. If nothing found on the homepage, retry on /contact.

    Filters out noreply/postmaster/bounce addresses unless nothing else
    is available.

    Returns an empty string if no address can be found.
    """
    import re as _re
    import requests as _req
    from bs4 import BeautifulSoup as _BS
    from urllib.parse import urljoin

    _SKIP = ("noreply", "no-reply", "donotreply", "bounce", "postmaster",
             "webmaster", "mailer", "daemon", "support", "help")
    _EMAIL_RE = _re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

    def _scrape(page_url: str) -> list[str]:
        try:
            resp = _req.get(page_url, timeout=8, headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            })
            resp.raise_for_status()
        except Exception:
            return []

        soup = _BS(resp.text, "html.parser")
        found: set[str] = set()

        # mailto: links are the strongest signal
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.lower().startswith("mailto:"):
                addr = href[7:].split("?")[0].strip().lower()
                if "@" in addr:
                    found.add(addr)

        # Regex scan over full page text
        for match in _EMAIL_RE.findall(soup.get_text()):
            found.add(match.lower())

        return list(found)

    def _pick(emails: list[str]) -> str:
        if not emails:
            return ""
        preferred = [e for e in emails if not any(e.startswith(s) for s in _SKIP)]
        return (preferred or emails)[0]

    if not url:
        return ""
    if not url.startswith("http"):
        url = "https://" + url

    found = _scrape(url)
    if found:
        return _pick(found)

    # Retry on /contact page
    found = _scrape(urljoin(url, "/contact"))
    return _pick(found)


def _run_pipeline_for_db_prospect(prospect: dict) -> dict:
    """
    Run research + email + PDF for a prospect that is already in the DB.
    Returns a result dict consumed by the find-and-fire endpoint.
    """
    from pdf_generator import generate_proposal
    from research_agent import research_prospect

    prospect_id = prospect["id"]
    company     = prospect.get("company", "")
    website     = prospect.get("website", "")

    result = {
        "prospect_id":    prospect_id,
        "company":        company,
        "website":        website,
        "prospect_email": prospect.get("email") or "",
        "research":  {},
        "email":     {},
        "pdf":       {},
        "outreach_id": None,
    }

    # Step 1 — Research
    if not website:
        result["research"] = {"note": "No website — research skipped"}
    else:
        try:
            analysis = research_prospect(prospect_id)
            if "error" in analysis:
                result["research"] = {"note": analysis["error"]}
            else:
                result["research"] = {
                    "niche":          analysis.get("niche", ""),
                    "icp":            analysis.get("icp", ""),
                    "headline":       analysis.get("website_headline", ""),
                    "product_feature":analysis.get("product_feature", ""),
                    "competitors":    analysis.get("competitors", ""),
                    "pain_point":     analysis.get("pain_point", ""),
                    "growth_signal":  analysis.get("growth_signal", ""),
                }
        except Exception as exc:
            result["research"] = {"note": f"Research error: {exc}"}

    # Reload prospect from DB so enrichment fields are present
    enriched = next(
        (p for p in database.get_all_prospects() if p["id"] == prospect_id),
        prospect,
    )

    # Auto-extract email if the prospect has no email on file
    if not enriched.get("email") and website:
        extracted = _extract_email_from_website(website)
        if extracted:
            database.update_prospect_email(prospect_id, extracted)
            enriched = dict(enriched)   # make mutable
            enriched["email"] = extracted
            result["prospect_email"] = extracted

    # Step 2 — Email
    has_api_key = bool(os.getenv("ANTHROPIC_API_KEY", "").strip())
    try:
        if has_api_key:
            from ai_engine import generate_hyper_personalized_email
            email_result = generate_hyper_personalized_email(enriched)
        else:
            email_result = generate_email(enriched)
    except Exception:
        try:
            email_result = generate_email(enriched)
        except Exception as exc:
            email_result = {"subject": "", "body": "", "quality_score": 0}

    result["email"] = {
        "subject":       email_result.get("subject", ""),
        "body":          email_result.get("body", ""),
        "quality_score": email_result.get("quality_score", 0),
    }

    # Save email draft to outreach table
    if result["email"]["subject"] and result["email"]["body"]:
        try:
            result["outreach_id"] = database.save_outreach(
                prospect_id=prospect_id,
                subject=result["email"]["subject"],
                body=result["email"]["body"],
            )
        except Exception:
            pass

    # Step 3 — PDF
    pdf_filepath = ""
    try:
        pdf_filepath = generate_proposal(enriched)
        filename = os.path.basename(pdf_filepath)
        result["pdf"] = {"url": f"/proposals/{filename}", "filename": filename}
    except Exception as exc:
        result["pdf"] = {"url": "", "filename": "", "error": str(exc)}

    # Persist the PDF path on the outreach draft so send can attach it
    if result["outreach_id"] and pdf_filepath and os.path.isfile(pdf_filepath):
        try:
            with database._get_connection(database.DB_PATH) as conn:
                conn.execute(
                    "UPDATE outreach SET pdf_path = ? WHERE id = ?",
                    (pdf_filepath, result["outreach_id"]),
                )
                conn.commit()
        except Exception:
            pass

    return result


@app.route("/api/find-and-fire", methods=["POST"])
def api_find_and_fire():
    """
    Google Maps → Research → Email → PDF for up to `limit` businesses.

    Body: { "query": "dentists", "location": "Manchester", "limit": 3 }

    Returns a list of per-company campaign results. Each result contains
    prospect_id, outreach_id, email draft, pdf url, and research summary.
    """
    from google_maps_finder import find_and_add_prospects

    data     = request.get_json(silent=True) or {}
    query    = (data.get("query") or "").strip()
    location = (data.get("location") or "").strip()
    limit    = max(1, min(int(data.get("limit", 3)), 5))  # cap at 5

    if not query or not location:
        return jsonify({"error": "query and location are required"}), 400

    if not os.getenv("GOOGLE_MAPS_API_KEY", "").strip():
        return jsonify({"error": "GOOGLE_MAPS_API_KEY not configured in .env"}), 400

    prospects = find_and_add_prospects(query, location, limit=limit)
    if not prospects:
        return jsonify({"error": "No businesses with websites found for that search."}), 404

    results = []
    for p in prospects:
        results.append(_run_pipeline_for_db_prospect(p))

    return jsonify({"query": query, "location": location, "count": len(results), "results": results})


@app.route("/api/send-outreach/<int:outreach_id>", methods=["POST"])
def api_send_outreach(outreach_id):
    """
    Send a specific outreach draft.

    Body: { "to_address": "person@company.com" }  (required if prospect has no email on file)
    """
    data       = request.get_json(silent=True) or {}
    to_address = (data.get("to_address") or "").strip()

    # Load the outreach record
    all_outreach = database.get_all_outreach()
    record = next((o for o in all_outreach if o["id"] == outreach_id), None)
    if not record:
        return jsonify({"error": "Outreach record not found"}), 404

    # Fall back to prospect's stored email if no address supplied
    if not to_address:
        all_prospects = database.get_all_prospects()
        p = next((x for x in all_prospects if x["id"] == record["prospect_id"]), None)
        to_address = (p.get("email") or "") if p else ""

    if not to_address:
        return jsonify({"error": "No email address. Pass to_address in the request body."}), 400

    valid, reason = _validate_email_address(to_address)
    if not valid:
        return jsonify({"error": f"Invalid recipient: {reason}"}), 400

    pdf_path = (record.get("pdf_path") or "").strip()
    sent, error = _route_send_email(
        to_address, record["subject"], record["body"],
        attachment_path=pdf_path,
    )
    if not sent:
        return jsonify({"error": f"Send failed: {error}"}), 500

    database.update_outreach_status(outreach_id, "sent")
    database.update_status(record["prospect_id"], "contacted")
    database.log_communication_event(
        prospect_id=record["prospect_id"],
        channel="email",
        direction="outbound",
        event_type="outreach_sent",
        status="sent",
        content_excerpt=record["body"][:250],
        metadata=f"outreach_id={outreach_id};recipient={to_address}",
    )
    return jsonify({"ok": True, "sent_to": to_address, "subject": record["subject"]})


@app.route("/api/outreach-tracker")
def api_outreach_tracker():
    """Return all sent outreach records for the tracker panel."""
    return jsonify(database.get_sent_outreach())


def _route_send_email(
    to_address: str,
    subject: str,
    body: str,
    attachment_path: str = "",
    in_reply_to: str = "",
    references: str = "",
) -> tuple[bool, str]:
    """
    Route outbound email through SendGrid or SMTP depending on USE_SENDGRID setting.
    SendGrid path: ignores attachment and thread headers (not yet supported there).
    SMTP path: supports PDF attachment and RFC-2822 thread headers.
    """
    if get_use_sendgrid():
        from sendgrid_mailer import send_email as sg_send
        return sg_send(to_address, subject, body)
    return _smtp_send_email(
        to_address, subject, body,
        attachment_path=attachment_path,
        in_reply_to=in_reply_to,
        references=references,
    )


def _validate_email_address(address: str) -> tuple[bool, str]:
    """
    Basic pre-send email validation.
    Returns (True, "") on pass, or (False, reason) on fail.
    Does NOT send a real verification email — just syntax + MX check.
    """
    import re
    import socket

    addr = (address or "").strip().lower()
    if not addr:
        return False, "Email address is empty."

    # Syntax check
    _EMAIL_RE = re.compile(
        r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
    )
    if not _EMAIL_RE.match(addr):
        return False, f"'{addr}' is not a valid email address."

    # Domain MX / A record check (fast, non-blocking for normal domains)
    domain = addr.split("@")[1]
    try:
        socket.getaddrinfo(domain, None)
    except socket.gaierror:
        return False, f"Domain '{domain}' does not resolve — address may not exist."

    return True, ""


@app.route("/api/prospects", methods=["POST"])
def api_add_prospect():
    """Add a single prospect manually. Body: { name, company, email?, website?, phone?, notes? }"""
    data = request.get_json(silent=True) or {}
    name    = (data.get("name") or "").strip()
    company = (data.get("company") or "").strip()
    if not name or not company:
        return jsonify({"error": "name and company are required"}), 400
    try:
        pid = database.add_prospect(
            name=name,
            company=company,
            email=(data.get("email") or "").strip() or None,
            website=(data.get("website") or "").strip() or None,
            phone=(data.get("phone") or "").strip() or None,
            notes=(data.get("notes") or "").strip() or None,
            status="new",
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400
    prospect = next((p for p in database.get_all_prospects() if p["id"] == pid), None)
    return jsonify({"ok": True, "id": pid, "prospect": dict(prospect) if prospect else {}})


@app.route("/api/prospects/<int:prospect_id>/enrol", methods=["POST"])
def api_enrol_prospect(prospect_id):
    """
    Enrol a prospect in the default multi-channel sequence.
    Idempotent — safe to call if already enrolled.
    Also sets prospect status to 'in_sequence'.
    """
    all_prospects = database.get_all_prospects()
    if not any(p["id"] == prospect_id for p in all_prospects):
        return jsonify({"error": "Prospect not found"}), 404
    enrollment_id = database.ensure_sequence_enrollment(prospect_id)
    database.update_status(prospect_id, "in_sequence")
    enrollment = database.get_sequence_enrollment(prospect_id)
    return jsonify({
        "ok": True,
        "enrollment_id": enrollment_id,
        "status": dict(enrollment) if enrollment else {},
    })


@app.route("/api/prospects/<int:prospect_id>", methods=["PATCH"])
def api_update_prospect(prospect_id):
    """
    Update a prospect's editable fields.
    Body: { "name": "...", "company": "...", "email": "...",
            "website": "...", "phone": "...", "lead_score": 75,
            "status": "qualified", "notes": "..." }
    All fields are optional.
    """
    data = request.get_json(silent=True) or {}
    allowed = ("name", "company", "email", "linkedin_url", "website",
               "phone", "lead_score", "status", "notes")
    kwargs = {k: data[k] for k in allowed if k in data}
    if not kwargs:
        return jsonify({"error": "No updatable fields provided."}), 400

    try:
        updated = database.update_prospect(prospect_id, **kwargs)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    if not updated:
        return jsonify({"error": "Prospect not found."}), 404
    return jsonify({"ok": True})


@app.route("/api/prospects/<int:prospect_id>", methods=["DELETE"])
def api_delete_prospect(prospect_id):
    """Hard-delete a prospect and all related records."""
    removed = database.delete_prospect(prospect_id)
    if not removed:
        return jsonify({"error": "Prospect not found."}), 404
    return jsonify({"ok": True})


def _check_settings_auth() -> bool:
    """Return True if the request carries valid Basic Auth for the settings page."""
    user = os.getenv("SETTINGS_USER", "admin").strip()
    pw   = os.getenv("SETTINGS_PASSWORD", "admin").strip()
    auth = request.authorization
    if not auth:
        return False
    return auth.username == user and auth.password == pw


@app.route("/settings", methods=["GET", "POST"])
def settings_page():
    """
    Settings page — view and update .env values via the dashboard.
    GET  : renders settings.html pre-filled with current values.
    POST : writes changed values back to .env using python-dotenv.
    """
    if not _check_settings_auth():
        return (
            "Unauthorised",
            401,
            {"WWW-Authenticate": 'Basic realm="LeadGen Settings"'},
        )

    from dotenv import set_key

    env_path = os.path.join(os.path.dirname(__file__), ".env")

    FIELDS = [
        # (env key, label, input type, default)
        ("SMTP_HOST",            "SMTP Host",              "text",     "smtp.gmail.com"),
        ("SMTP_PORT",            "SMTP Port",              "number",   "465"),
        ("SMTP_USER",            "SMTP User (sender email)", "email",  ""),
        ("SMTP_PASSWORD",        "SMTP Password / App password", "password", ""),
        ("IMAP_HOST",            "IMAP Host",              "text",     "imap.gmail.com"),
        ("IMAP_PORT",            "IMAP Port",              "number",   "993"),
        ("IMAP_USER",            "IMAP User",              "email",    ""),
        ("IMAP_PASSWORD",        "IMAP Password",          "password", ""),
        ("IMAP_MAX_MESSAGES_PER_POLL", "IMAP Max Messages Per Poll", "number", "25"),
        ("ANTHROPIC_API_KEY",    "Anthropic API Key",      "password", ""),
        ("GOOGLE_MAPS_API_KEY",  "Google Maps API Key",    "password", ""),
        ("CALENDAR_LINK",        "Calendar / Booking Link","url",      ""),
        ("SENDER_NAME",          "Sender First Name",      "text",     "Alex"),
        ("INBOX_POLL_INTERVAL",  "Inbox Poll Interval (s)","number",   "300"),
        ("SEQUENCE_RUN_HOUR",    "Sequence Run Hour (UTC 0-23)", "number", "9"),
        ("USE_SENDGRID",         "Use SendGrid (true/false)", "text",  "false"),
        ("SENDGRID_API_KEY",     "SendGrid API Key",       "password", ""),
        ("LINKEDIN_DRY_RUN",     "LinkedIn Dry Run (true/false)", "text", "true"),
        ("SETTINGS_USER",        "Settings Page Username",  "text",     "admin"),
        ("SETTINGS_PASSWORD",    "Settings Page Password",  "password", "admin"),
    ]

    saved = False
    errors: list[str] = []

    if request.method == "POST":
        form = request.form
        for key, _label, _type, _default in FIELDS:
            val = form.get(key, "").strip()
            # Never blank-overwrite passwords/keys that were left empty in the form
            if not val and _type == "password":
                continue
            try:
                set_key(env_path, key, val)
                os.environ[key] = val  # update in-process env immediately
            except Exception as exc:
                errors.append(f"{key}: {exc}")
        if not errors:
            # Reload settings module values
            load_dotenv(override=True)
            saved = True

    current = {key: os.getenv(key, default) for key, _label, _type, default in FIELDS}

    return render_template(
        "settings.html",
        fields=FIELDS,
        current=current,
        saved=saved,
        errors=errors,
    )


@app.route("/api/import-csv", methods=["POST"])
def api_import_csv():
    """
    Accept a multipart CSV file upload and import it into the prospect DB.
    Form field: 'file' — a .csv file.
    """
    import tempfile
    from importer import import_csv

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded. Send a multipart form with field 'file'."}), 400

    f = request.files["file"]
    if not f.filename or not f.filename.lower().endswith(".csv"):
        return jsonify({"error": "Only .csv files are accepted."}), 400

    # Write to a temp file so importer can read it normally
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="wb") as tmp:
        f.save(tmp)
        tmp_path = tmp.name

    try:
        summary = import_csv(tmp_path, auto_score=True)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": f"Import failed: {exc}"}), 500
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    return jsonify(summary)


@app.route("/api/analytics")
def api_analytics():
    """Return full pipeline analytics for the dashboard analytics panel."""
    summary = reporter.generate_summary()
    # Convert top_companies list-of-tuples to JSON-safe list-of-dicts
    summary["top_companies"] = [
        {"company": co, "count": cnt} for co, cnt in summary["top_companies"]
    ]
    # top_prospects contain sqlite3.Row objects — normalise to plain dicts
    summary["top_prospects"] = [dict(p) for p in summary["top_prospects"]]
    return jsonify(summary)


@app.route("/api/monitor-status")
def api_monitor_status():
    """Return current background scheduler state for the dashboard status bar."""
    def _fmt(dt: datetime.datetime | None) -> str:
        return dt.strftime("%H:%M:%S UTC") if dt else "never"

    return jsonify({
        "running":             _scheduler_state["running"],
        "paused":              _scheduler_state["paused"],
        "consecutive_errors":  _scheduler_state["consecutive_errors"],
        "poll_interval":       get_inbox_poll_interval(),
        "sequence_run_hour":   get_sequence_run_hour(),
        "last_inbox_check":    _fmt(_scheduler_state["last_inbox_check"]),
        "last_inbox_result":   _scheduler_state["last_inbox_result"],
        "last_inbox_error":    _scheduler_state["last_inbox_error"],
        "last_sequence_run":   _fmt(_scheduler_state["last_sequence_run"]),
        "last_sequence_error": _scheduler_state["last_sequence_error"],
    })


@app.route("/api/monitor-reset", methods=["POST"])
def api_monitor_reset():
    """
    Resume the background inbox monitor after it was auto-paused.

    Clears the paused flag and consecutive error counter so the scheduler
    can attempt inbox polling again on the next cycle.
    """
    _scheduler_state["paused"] = False
    _scheduler_state["consecutive_errors"] = 0
    _scheduler_state["last_inbox_error"] = None
    return jsonify({
        "ok": True,
        "paused": _scheduler_state["paused"],
        "consecutive_errors": _scheduler_state["consecutive_errors"],
    })


if __name__ == "__main__":
    import threading
    t = threading.Thread(target=_background_scheduler, daemon=True, name="bg-scheduler")
    t.start()
    app.run(debug=True, port=5000, use_reloader=False)
