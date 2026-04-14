import os
from flask import Flask, render_template, send_from_directory, jsonify, request
from urllib.parse import urlparse
from dotenv import load_dotenv

# Load .env before any module that creates an Anthropic client at import time
load_dotenv()

import database
import reporter
from outreach import debug_email_reasoning, generate_email

app = Flask(__name__)

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
    prospects = database.get_all_prospects()
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
    new_status = "approved" if action == "approve" else "dismissed"
    ok = database.update_reply_draft_status(draft_id, new_status)
    if not ok:
        return jsonify({"error": "Draft not found"}), 404
    return jsonify({"ok": True, "status": new_status})


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
            "If easier, grab a slot directly: calendly.com/leadgenai/30min\n\n"
            "Talk soon."
        ),
    )
    return jsonify({"ok": True, "draft_id": draft_id, "prospect": p.get("name")})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
