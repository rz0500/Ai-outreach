import os
import time
import datetime
import uuid
import hmac
from flask import (
    Flask, render_template, send_from_directory, jsonify,
    request, session, redirect, url_for,
)
from urllib.parse import urlparse
from dotenv import load_dotenv

# Load .env before any module that creates an Anthropic client at import time
load_dotenv()

import database
from deliverability import deliver_prospect_email, route_outbound_email, verify_unsubscribe_token
import reporter
from outreach import debug_email_reasoning, generate_email
import settings
from settings import (
    get_calendar_link,
    get_inbox_poll_interval,
    get_sequence_run_hour,
    get_self_prospect_niche,
    get_self_prospect_location,
    get_self_prospect_daily_limit,
    get_self_prospect_run_hour,
    get_secret_key,
)
import warmup_engine
import mailivery_client

app = Flask(__name__)
app.secret_key = get_secret_key()

# ── Production safety checks ──────────────────────────────────────────────────
def _check_production_safety() -> None:
    """
    Warn loudly on stdout when the app starts with insecure or missing
    production configuration.  These are non-fatal so local dev still works,
    but each warning is a hard blocker before going live.
    """
    warnings: list[str] = []

    if get_secret_key() in (
        "dev-secret-change-in-production",
        "dev-secret-change-before-deploying",
        "change-this-to-a-random-secret",
        "",
    ):
        warnings.append(
            "SECRET_KEY is the dev default — sessions can be forged. "
            "Run: python -c \"import secrets; print(secrets.token_hex(32))\" "
            "and set SECRET_KEY in your environment."
        )

    app_base = os.getenv("APP_BASE_URL", "").strip()
    if not app_base or "localhost" in app_base or "127.0.0.1" in app_base:
        warnings.append(
            "APP_BASE_URL is not set or points to localhost. "
            "Magic links and unsubscribe URLs will be broken in production. "
            "Set APP_BASE_URL=https://yourdomain.com"
        )

    settings_pw = os.getenv("SETTINGS_PASSWORD", "admin").strip()
    if settings_pw in ("admin", "change-me", "password", ""):
        warnings.append(
            "SETTINGS_PASSWORD is insecure (value: '{}'). "
            "The /settings and /ops pages will be trivially accessible. "
            "Set SETTINGS_PASSWORD to a strong password.".format(settings_pw or "(empty)")
        )

    db_path = os.getenv("DB_PATH", "").strip()
    if not db_path:
        warnings.append(
            "DB_PATH is not set — SQLite will write to 'prospects.db' in the project "
            "root. On platforms with ephemeral filesystems (Render, Railway, Fly) this "
            "file is wiped on every redeploy. Set DB_PATH to a path on a persistent "
            "volume, e.g. DB_PATH=/var/data/prospects.db"
        )

    if warnings:
        bar = "=" * 68
        print(f"\n{bar}")
        print("  OUTREACHEMPOWER — PRODUCTION SAFETY WARNINGS")
        print(bar)
        for i, w in enumerate(warnings, 1):
            print(f"  [{i}] {w}")
        print(bar)
        print("  These are non-fatal in development. Fix before deploying.\n")

_check_production_safety()

# Pending client research queue — client_ids added by /onboard, drained by scheduler
_pending_client_research: set = set()

# ── Onboard rate limiting ─────────────────────────────────────────────────────
# Maps IP → list of submission timestamps (floats).  Kept in-memory; resets on
# restart which is fine — this is just spam protection, not a hard security wall.
_onboard_ip_log: dict = {}
_ONBOARD_RATE_LIMIT   = 5     # max submissions per IP
_ONBOARD_RATE_WINDOW  = 3600  # within this many seconds (1 hour)


def _onboard_rate_check(ip: str) -> bool:
    """Return True if the IP is within the rate limit, False if it should be blocked."""
    now = time.time()
    cutoff = now - _ONBOARD_RATE_WINDOW
    times = _onboard_ip_log.get(ip) or []
    times = [t for t in times if t > cutoff]   # drop expired entries
    if len(times) >= _ONBOARD_RATE_LIMIT:
        _onboard_ip_log[ip] = times
        return False
    times.append(now)
    _onboard_ip_log[ip] = times
    return True

# ---------------------------------------------------------------------------
# Background scheduler state — shared across threads (GIL-safe for these ops)
# ---------------------------------------------------------------------------
_scheduler_state: dict = {
    "last_inbox_check":           None,   # datetime | None
    "last_inbox_result":          None,   # int (replies found) | None
    "last_inbox_error":           None,   # str | None
    "last_sequence_run":          None,   # datetime | None
    "last_sequence_error":        None,   # str | None
    "last_self_prospect_count":   None,   # int | None
    "last_self_prospect_error":   None,   # str | None
    "last_weekly_report_error":   None,   # str | None
    "running":                    False,
    "paused":                     False,  # True after MAX_CONSECUTIVE_ERRORS inbox failures
    "consecutive_errors":         0,
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
    last_self_prospect_date: datetime.date | None = None
    last_weekly_report_date: datetime.date | None = None
    last_warmup_cycle_hour: int | None = None  # tracks which 4-hour slot last ran

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

        # ── Daily self-prospecting (house account) ────────────────────────
        sp_hour = get_self_prospect_run_hour()
        if now_utc.hour >= sp_hour and last_self_prospect_date != today:
            _house = database.get_client(1, db_path=database.DB_PATH)
            niche    = (_house or {}).get("niche") or get_self_prospect_niche()
            location = (_house or {}).get("location") or get_self_prospect_location()
            if niche and location:
                try:
                    from google_maps_finder import find_and_add_prospects
                    limit     = get_self_prospect_daily_limit()
                    new_leads = find_and_add_prospects(niche, location, limit=limit, client_id=1)
                    for prospect in new_leads:
                        try:
                            _run_pipeline_for_db_prospect(prospect)
                            database.ensure_sequence_enrollment(prospect["id"])
                            database.update_status(prospect["id"], "in_sequence")
                        except Exception as exc:
                            print(f"[Scheduler] self-prospect pipeline failed for '{prospect.get('company')}': {exc}")
                    _scheduler_state["last_self_prospect_count"] = len(new_leads)
                    _scheduler_state["last_self_prospect_error"] = None
                except Exception as exc:
                    _scheduler_state["last_self_prospect_error"] = str(exc)
            last_self_prospect_date = today

        # ── Drain pending client research queue (from /onboard) ───────────
        if _pending_client_research:
            to_process = set(_pending_client_research)
            for cid in to_process:
                try:
                    client_rec = database.get_client(cid)

                    # 1. Research the stub prospect (client's own website) if present
                    prospects = database.get_all_prospects(client_id=cid)
                    website_stub = next(
                        (p for p in prospects if p.get("website")),
                        None,
                    )
                    if website_stub:
                        try:
                            _run_pipeline_for_db_prospect(website_stub)
                        except Exception as exc:
                            print(f"[Scheduler] onboard website research failed for client {cid}: {exc}")

                    # 2. Discover real prospects via Google Maps using the client's niche
                    client_niche     = (client_rec or {}).get("niche") if client_rec else None
                    client_location  = (client_rec or {}).get("location") if client_rec else None
                    global_location  = get_self_prospect_location()
                    search_location  = client_location or global_location
                    if client_niche and search_location:
                        try:
                            from google_maps_finder import find_and_add_prospects
                            limit      = get_self_prospect_daily_limit()
                            new_leads  = find_and_add_prospects(
                                client_niche, search_location, limit=limit, client_id=cid
                            )
                            for lead in new_leads:
                                try:
                                    _run_pipeline_for_db_prospect(lead)
                                    database.ensure_sequence_enrollment(lead["id"])
                                    database.update_status(lead["id"], "in_sequence")
                                except Exception as exc:
                                    print(f"[Scheduler] onboard lead pipeline failed for client {cid}, "
                                          f"'{lead.get('company')}': {exc}")
                            print(f"[Scheduler] onboard: added {len(new_leads)} leads for client {cid}")
                        except Exception as exc:
                            print(f"[Scheduler] onboard Google Maps discovery failed for client {cid}: {exc}")

                    _pending_client_research.discard(cid)
                except Exception as exc:
                    print(f"[Scheduler] onboard drain error for client {cid}: {exc}")
                    _pending_client_research.discard(cid)

        # ── Weekly client reports (Monday 08:00 UTC) ──────────────────────
        this_monday = today - datetime.timedelta(days=today.weekday())
        if today.weekday() == 0 and now_utc.hour >= 8 and last_weekly_report_date != this_monday:
            try:
                _send_weekly_client_reports()
                _scheduler_state["last_weekly_report_error"] = None
            except Exception as exc:
                _scheduler_state["last_weekly_report_error"] = str(exc)
            last_weekly_report_date = this_monday

        # ── Warmup email cycle (every 4 hours) ────────────────────────────
        warmup_slot = now_utc.hour // 4  # 0-5, changes 6× per day
        if last_warmup_cycle_hour != (today, warmup_slot):
            try:
                warmup_engine.run_warmup_cycle(db_path=database.DB_PATH)
            except Exception as exc:
                print(f"[Scheduler] warmup cycle error: {exc}")

            # Refresh Mailivery health scores for all connected clients
            try:
                _refresh_mailivery_health_scores()
            except Exception as exc:
                print(f"[Scheduler] Mailivery health score refresh error: {exc}")

            last_warmup_cycle_hour = (today, warmup_slot)

        time.sleep(get_inbox_poll_interval())

# Ensure tables exist to prevent sqlite crash if visited before running main
database.initialize_database()
database.initialize_outreach_table()
database.initialize_send_counters_table()

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


def _coerce_operator_client_id(raw_value, default: int = 1) -> int:
    """Parse an operator-selected client id and fall back safely."""
    try:
        client_id = int(raw_value)
    except (TypeError, ValueError):
        return default
    if client_id < 1:
        return default
    return client_id


def _apply_client_prospect_filters(prospects: list, q: str, status_filter: str, sort_key: str, sort_dir: str) -> tuple[list, str, str]:
    """Apply shared client prospect search, status, and sorting rules."""
    filtered = prospects
    if q:
        filtered = [
            p for p in filtered
            if q in (p.get("name") or "").lower()
            or q in (p.get("company") or "").lower()
            or q in (p.get("email") or "").lower()
        ]
    if status_filter:
        filtered = [p for p in filtered if (p.get("status") or "").lower() == status_filter]

    sorters = {
        "score": lambda p: p.get("lead_score") or 0,
        "name": lambda p: (p.get("name") or "").lower(),
        "company": lambda p: (p.get("company") or "").lower(),
        "status": lambda p: (p.get("status") or "").lower(),
    }
    if sort_key not in sorters:
        sort_key = "score"
    if sort_dir not in ("asc", "desc"):
        sort_dir = "desc"

    filtered = sorted(
        filtered,
        key=sorters[sort_key],
        reverse=(sort_dir == "desc"),
    )
    return filtered, sort_key, sort_dir


def _render_operator_dashboard():
    _db = database.DB_PATH
    clients = database.get_all_clients(db_path=_db)
    selected_client_id = _coerce_operator_client_id(request.args.get("client_id"), 1)
    selected_client = database.get_client(selected_client_id, db_path=_db)
    if not selected_client:
        selected_client_id = 1
        selected_client = database.get_client(1, db_path=_db)

    # We query the database via our existing modules
    prospects = _annotate_sequence_progress(
        database.get_all_prospects(client_id=selected_client_id, db_path=_db)
    )
    summary = reporter.generate_summary(client_id=selected_client_id, db_path=_db)
    deliverability = database.get_deliverability_summary(client_id=selected_client_id, db_path=_db)
    selected_client_analytics = database.get_client_analytics(selected_client_id, db_path=_db)
    
    # Get recent outbox drafts/sent
    try:
        outreach_data = database.get_all_outreach(client_id=selected_client_id, db_path=_db)
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
        reply_drafts = database.get_pending_reply_drafts(client_id=selected_client_id, db_path=_db)
    except Exception:
        reply_drafts = []

    # Pending outreach queue count for selected workspace
    try:
        pending_outreach_count = len(
            database.get_pending_outreach_for_review(selected_client_id, db_path=_db)
        )
    except Exception:
        pending_outreach_count = 0

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
        deliverability=deliverability,
        clients=clients,
        selected_client=selected_client,
        selected_client_id=selected_client_id,
        selected_client_analytics=selected_client_analytics,
        pending_outreach_count=pending_outreach_count,
    )


# ── Ops quick-action API endpoints ────────────────────────────────────────────

@app.route("/api/ops/client/<int:client_id>/pause", methods=["POST"])
def ops_pause_client(client_id: int):
    """Ops: pause campaign for any client workspace."""
    denied = _ops_auth_required()
    if denied:
        return denied
    _db = database.DB_PATH
    if not database.get_client(client_id, db_path=_db):
        return jsonify({"error": "client not found"}), 404
    database.update_client(client_id, campaign_paused=1, db_path=_db)
    return jsonify({"ok": True, "campaign_paused": True})


@app.route("/api/ops/client/<int:client_id>/resume", methods=["POST"])
def ops_resume_client(client_id: int):
    """Ops: resume campaign for any client workspace."""
    denied = _ops_auth_required()
    if denied:
        return denied
    _db = database.DB_PATH
    if not database.get_client(client_id, db_path=_db):
        return jsonify({"error": "client not found"}), 404
    database.update_client(client_id, campaign_paused=0, db_path=_db)
    return jsonify({"ok": True, "campaign_paused": False})


@app.route("/api/ops/client/<int:client_id>/toggle-review-mode", methods=["POST"])
def ops_toggle_review_mode(client_id: int):
    """Ops: toggle outreach review mode for any client workspace."""
    denied = _ops_auth_required()
    if denied:
        return denied
    _db = database.DB_PATH
    client = database.get_client(client_id, db_path=_db)
    if not client:
        return jsonify({"error": "client not found"}), 404
    new_mode = 0 if client.get("outreach_review_mode") else 1
    database.update_client(client_id, outreach_review_mode=new_mode, db_path=_db)
    return jsonify({"ok": True, "outreach_review_mode": bool(new_mode)})


@app.route("/api/ops/client/<int:client_id>/resend-welcome", methods=["POST"])
def ops_resend_welcome(client_id: int):
    """Ops: resend magic-link welcome email to any client."""
    denied = _ops_auth_required()
    if denied:
        return denied
    _db = database.DB_PATH
    client = database.get_client(client_id, db_path=_db)
    if not client:
        return jsonify({"error": "client not found"}), 404
    if not (client.get("email") or "").strip():
        return jsonify({"error": "client has no email address"}), 400
    try:
        _send_onboard_welcome(client, _db)
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/ops/client/<int:client_id>/mailivery/connect", methods=["POST"])
def ops_mailivery_connect(client_id: int):
    """Ops: manually connect a client mailbox to Mailivery."""
    denied = _ops_auth_required()
    if denied:
        return denied
    _db = database.DB_PATH
    client = database.get_client(client_id, db_path=_db)
    if not client:
        return jsonify({"error": "client not found"}), 404
    mc = mailivery_client.get_client()
    if not mc:
        return jsonify({"error": "Mailivery not enabled"}), 400
    _mailivery_auto_connect(client_id, _db)
    updated = database.get_client(client_id, db_path=_db)
    return jsonify({"ok": True, "mailivery_campaign_id": (updated or {}).get("mailivery_campaign_id")})


@app.route("/api/ops/client/<int:client_id>/mailivery/start", methods=["POST"])
def ops_mailivery_start(client_id: int):
    """Ops: start Mailivery warmup for a client campaign."""
    denied = _ops_auth_required()
    if denied:
        return denied
    client = database.get_client(client_id, db_path=database.DB_PATH)
    if not client:
        return jsonify({"error": "client not found"}), 404
    campaign_id = (client.get("mailivery_campaign_id") or "").strip()
    if not campaign_id:
        return jsonify({"error": "no Mailivery campaign linked"}), 400
    mc = mailivery_client.get_client()
    if not mc:
        return jsonify({"error": "Mailivery not enabled"}), 400
    result = mc.start_warmup(campaign_id)
    return jsonify(result)


@app.route("/api/ops/client/<int:client_id>/mailivery/pause", methods=["POST"])
def ops_mailivery_pause(client_id: int):
    """Ops: pause Mailivery warmup for a client campaign."""
    denied = _ops_auth_required()
    if denied:
        return denied
    client = database.get_client(client_id, db_path=database.DB_PATH)
    if not client:
        return jsonify({"error": "client not found"}), 404
    campaign_id = (client.get("mailivery_campaign_id") or "").strip()
    if not campaign_id:
        return jsonify({"error": "no Mailivery campaign linked"}), 400
    mc = mailivery_client.get_client()
    if not mc:
        return jsonify({"error": "Mailivery not enabled"}), 400
    result = mc.pause_warmup(campaign_id)
    return jsonify(result)


@app.route("/api/ops/client/<int:client_id>/mailivery/resume", methods=["POST"])
def ops_mailivery_resume(client_id: int):
    """Ops: resume Mailivery warmup for a client campaign."""
    denied = _ops_auth_required()
    if denied:
        return denied
    client = database.get_client(client_id, db_path=database.DB_PATH)
    if not client:
        return jsonify({"error": "client not found"}), 404
    campaign_id = (client.get("mailivery_campaign_id") or "").strip()
    if not campaign_id:
        return jsonify({"error": "no Mailivery campaign linked"}), 400
    mc = mailivery_client.get_client()
    if not mc:
        return jsonify({"error": "Mailivery not enabled"}), 400
    result = mc.resume_warmup(campaign_id)
    return jsonify(result)


@app.route("/api/ops/client/<int:client_id>/mailivery/status")
def ops_mailivery_status(client_id: int):
    """Ops: fetch live Mailivery warmup status for a client campaign."""
    denied = _ops_auth_required()
    if denied:
        return denied
    client = database.get_client(client_id, db_path=database.DB_PATH)
    if not client:
        return jsonify({"error": "client not found"}), 404
    campaign_id = (client.get("mailivery_campaign_id") or "").strip()
    if not campaign_id:
        return jsonify({"ok": True, "connected": False})
    mc = mailivery_client.get_client()
    if not mc:
        return jsonify({"error": "Mailivery not enabled"}), 400
    mailbox = mc.get_mailbox(campaign_id)
    health  = mc.get_health_score(campaign_id)
    return jsonify({
        "ok":           True,
        "connected":    True,
        "campaign_id":  campaign_id,
        "mailbox":      mailbox,
        "health_score": health,
    })


@app.route("/")
def landing_page():
    """Public marketing page for the self-serve product launch."""
    return render_template(
        "landing.html",
        default_calendar_link=get_calendar_link(),
    )


@app.route("/checkout")
def checkout_page():
    """Pricing page — Stripe Checkout when configured, otherwise pilot flow."""
    return render_template("checkout_dummy.html")


@app.route("/api/create-checkout-session", methods=["POST"])
def create_checkout_session():
    """
    Create a Stripe Checkout session and return the hosted URL.
    Falls back to {"fallback": "/onboard"} when STRIPE_SECRET_KEY is not set.
    """
    secret_key = os.getenv("STRIPE_SECRET_KEY", "").strip()
    price_id   = os.getenv("STRIPE_PRICE_ID", "").strip()

    if not secret_key or not price_id:
        return jsonify({"fallback": "/onboard"})

    try:
        import stripe as _stripe
        _stripe.api_key = secret_key
        session = _stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=request.host_url.rstrip("/") + "/onboard?plan=paid",
            cancel_url=request.host_url.rstrip("/") + "/checkout",
        )
        return jsonify({"url": session.url})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


def _ops_auth_required():
    """Return a 401 challenge if the request lacks valid Basic Auth credentials."""
    if not _check_settings_auth():
        return (
            "Unauthorised",
            401,
            {"WWW-Authenticate": 'Basic realm="OutreachEmpower Ops"'},
        )
    return None


@app.route("/ops")
@app.route("/dashboard")
def index():
    """Internal operator dashboard — Basic Auth protected."""
    denied = _ops_auth_required()
    if denied:
        return denied
    return _render_operator_dashboard()

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
    except Exception as exc:
        print(f"[Pipeline] email reasoning failed: {exc}")

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
        except Exception as exc:
            print(f"[Pipeline] save_outreach failed for prospect {prospect_id}: {exc}")

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
    client_id = _coerce_operator_client_id(request.args.get("client_id"), 1)
    return jsonify(database.get_pending_reply_drafts(client_id=client_id, db_path=database.DB_PATH))


@app.route("/api/sent-replies")
def api_sent_replies():
    """Return all reply drafts that have been approved and sent."""
    client_id = _coerce_operator_client_id(request.args.get("client_id"), 1)
    return jsonify(database.get_sent_reply_drafts(client_id=client_id, db_path=database.DB_PATH))


@app.route("/api/reply-drafts/<int:draft_id>/action", methods=["POST"])
def api_reply_draft_action(draft_id):
    """
    Approve or dismiss a reply draft.
    Body: { "action": "approve" | "dismiss" }
    """
    data = request.get_json(silent=True) or {}
    action = (data.get("action") or "").strip()
    client_id = _coerce_operator_client_id(request.args.get("client_id"), 1)
    if action not in ("approve", "dismiss"):
        return jsonify({"error": "action must be 'approve' or 'dismiss'"}), 400

    draft = database.get_reply_draft_by_id(draft_id, db_path=database.DB_PATH)
    if not draft or draft.get("client_id", 1) != client_id:
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

    draft_client_id = draft.get("client_id", 1)
    ok, err = _route_send_email(
        to_address=recipient,
        subject=subject,
        body=body,
        in_reply_to=inbound_message_id,
        references=inbound_message_id,
        respect_suppression=True,
        client_id=draft_client_id,
        db_path=database.DB_PATH,
    )
    if not ok:
        return jsonify({"error": f"Send failed: {err}"}), 500

    database.log_communication_event(
        prospect_id=draft["prospect_id"],
        channel="email",
        direction="outbound",
        event_type="reply_draft_sent",
        status="sent",
        content_excerpt=body[:250],
        metadata=f"draft_id={draft_id};recipient={recipient};subject={subject}",
        client_id=draft_client_id,
        db_path=database.DB_PATH,
    )

    database.update_reply_draft_status(draft_id, "sent")
    database.update_status(draft["prospect_id"], "replied")
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


def _run_pipeline_for_db_prospect(prospect: dict, stage_hook=None) -> dict:
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
        "stage_statuses": {
            "research": "pending",
            "email": "pending",
            "pdf": "pending",
        },
        "stage_errors": {},
        "status": "running",
    }

    # Step 1 — Research
    if stage_hook:
        stage_hook("research", "active", {"company": company})
    if not website:
        result["stage_statuses"]["research"] = "skipped"
        result["research"] = {"note": "No website — research skipped"}
    else:
        try:
            analysis = research_prospect(prospect_id)
            if "error" in analysis:
                result["stage_statuses"]["research"] = "error"
                result["stage_errors"]["research"] = analysis["error"]
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
                result["stage_statuses"]["research"] = "done"
        except Exception as exc:
            result["stage_statuses"]["research"] = "error"
            result["stage_errors"]["research"] = str(exc)
            result["research"] = {"note": f"Research error: {exc}"}

    if stage_hook:
        stage_hook(
            "research",
            result["stage_statuses"]["research"],
            {"company": company, "error": result["stage_errors"].get("research", "")},
        )

    # Reload prospect from DB so enrichment fields are present
    enriched = database.get_prospect_by_id(prospect_id) or prospect

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
    if stage_hook:
        stage_hook("email", "active", {"company": company})
    try:
        if has_api_key:
            from ai_engine import generate_hyper_personalized_email
            email_result = generate_hyper_personalized_email(enriched)
        else:
            email_result = generate_email(enriched)
    except Exception as exc:
        result["stage_errors"]["email"] = str(exc)
        try:
            email_result = generate_email(enriched)
        except Exception as exc:
            email_result = {"subject": "", "body": "", "quality_score": 0}
            result["stage_errors"]["email"] = str(exc)

    result["email"] = {
        "subject":       email_result.get("subject", ""),
        "body":          email_result.get("body", ""),
        "quality_score": email_result.get("quality_score", 0),
    }
    if result["email"]["subject"] and result["email"]["body"]:
        result["stage_statuses"]["email"] = "done"
    else:
        result["stage_statuses"]["email"] = "error"
        result["stage_errors"]["email"] = result["stage_errors"].get("email", "Email generation returned no draft.")

    # Save email draft to outreach table
    if result["email"]["subject"] and result["email"]["body"]:
        try:
            result["outreach_id"] = database.save_outreach(
                prospect_id=prospect_id,
                subject=result["email"]["subject"],
                body=result["email"]["body"],
            )
        except Exception as exc:
            print(f"[Pipeline] save_outreach failed for '{company}': {exc}")

    # Step 3 — PDF
    if stage_hook:
        stage_hook(
            "email",
            result["stage_statuses"]["email"],
            {"company": company, "error": result["stage_errors"].get("email", "")},
        )

    pdf_filepath = ""
    if stage_hook:
        stage_hook("pdf", "active", {"company": company})
    try:
        pdf_filepath = generate_proposal(enriched)
        filename = os.path.basename(pdf_filepath)
        result["pdf"] = {"url": f"/proposals/{filename}", "filename": filename}
        result["stage_statuses"]["pdf"] = "done"
    except Exception as exc:
        result["pdf"] = {"url": "", "filename": "", "error": str(exc)}
        result["stage_statuses"]["pdf"] = "error"
        result["stage_errors"]["pdf"] = str(exc)

    # Persist the PDF path on the outreach draft so send can attach it
    if result["outreach_id"] and pdf_filepath and os.path.isfile(pdf_filepath):
        try:
            with database._get_connection(database.DB_PATH) as conn:
                conn.execute(
                    "UPDATE outreach SET pdf_path = ? WHERE id = ?",
                    (pdf_filepath, result["outreach_id"]),
                )
                conn.commit()
        except Exception as exc:
            print(f"[Pipeline] pdf_path update failed for '{company}': {exc}")

    if stage_hook:
        stage_hook(
            "pdf",
            result["stage_statuses"]["pdf"],
            {"company": company, "error": result["stage_errors"].get("pdf", "")},
        )

    if all(status in ("done", "skipped") for status in result["stage_statuses"].values()):
        result["status"] = "completed"
    elif any(status == "done" for status in result["stage_statuses"].values()):
        result["status"] = "partial_error"
    else:
        result["status"] = "failed"

    return result


# In-memory job store for find-and-fire background jobs
# { job_id: {status, stage, progress, total, results, error, ...} }
_find_fire_jobs: dict = {}


def _new_find_fire_job(limit: int) -> dict:
    """Return the initial job payload for a Find-and-Fire background run."""
    return {
        "status": "running",
        "stage": "finding",
        "progress": 0,
        "total": limit,
        "results": [],
        "items": [],
        "error": None,
        "message": "Finding businesses...",
        "current_company": "",
        "current_index": 0,
    }


def _set_find_fire_stage(job: dict, stage: str, message: str = "", *, error: str | None = None) -> None:
    """Update the top-level state for a Find-and-Fire job."""
    job["stage"] = stage
    if error:
        job["status"] = "error"
        job["error"] = error
    elif stage == "done":
        job["status"] = "done"
    else:
        job["status"] = "running"
    if message:
        job["message"] = message


def _ensure_find_fire_item(job: dict, index: int, company: str, website: str = "") -> dict:
    """Return or create a per-lead progress record for the job."""
    while len(job["items"]) <= index:
        job["items"].append({
            "index": len(job["items"]) + 1,
            "company": "",
            "website": "",
            "status": "pending",
            "current_stage": "pending",
            "stage_statuses": {"research": "pending", "email": "pending", "pdf": "pending"},
            "error": "",
        })
    item = job["items"][index]
    if company:
        item["company"] = company
    if website:
        item["website"] = website
    return item


def _run_find_fire_job(job_id: str, query: str, location: str, limit: int, finder) -> None:
    """
    Execute a Find-and-Fire job using the provided discovery callable.
    Broken out for easier testing and richer progress updates.
    """
    job = _find_fire_jobs[job_id]
    _set_find_fire_stage(job, "finding", f"Finding businesses for {query} in {location}...")

    try:
        prospects = finder(query, location, limit=limit)
    except Exception as exc:
        _set_find_fire_stage(job, "error", "Business discovery failed.", error=str(exc))
        return

    if not prospects:
        job["error"] = "No businesses with websites found for that search."
        _set_find_fire_stage(job, "done", job["error"])
        return

    job["total"] = len(prospects)
    job["items"] = []

    for i, prospect in enumerate(prospects):
        company = prospect.get("company", "?")
        website = prospect.get("website", "")
        item = _ensure_find_fire_item(job, i, company, website)
        item["status"] = "running"
        item["current_stage"] = "research"
        job["current_company"] = company
        job["current_index"] = i + 1

        def _stage_hook(stage: str, state: str, meta: dict | None = None):
            meta = meta or {}
            item["current_stage"] = stage
            item["stage_statuses"][stage] = state
            if state == "active":
                _set_find_fire_stage(job, stage, f"{stage.title()} {company} ({i + 1}/{job['total']})")
            elif state == "error":
                item["error"] = meta.get("error", "")
                item["status"] = "partial_error"
                _set_find_fire_stage(job, stage, f"{stage.title()} issue for {company}")
            elif state in ("done", "skipped") and all(
                s in ("done", "skipped") for s in item["stage_statuses"].values()
            ):
                item["status"] = "completed"

        try:
            result = _run_pipeline_for_db_prospect(prospect, stage_hook=_stage_hook)
        except Exception as exc:
            item["status"] = "failed"
            item["error"] = str(exc)
            result = {
                "prospect_id": prospect.get("id"),
                "company": company,
                "website": website,
                "prospect_email": prospect.get("email") or "",
                "research": {},
                "email": {},
                "pdf": {},
                "outreach_id": None,
                "stage_statuses": dict(item["stage_statuses"]),
                "stage_errors": {"worker": str(exc)},
                "status": "failed",
                "error": str(exc),
            }

        item["stage_statuses"] = dict(result.get("stage_statuses", item["stage_statuses"]))
        item["status"] = result.get("status", item["status"])
        item["current_stage"] = "done"
        item["error"] = result.get("error") or "; ".join(
            err for err in result.get("stage_errors", {}).values() if err
        )
        job["results"].append(result)
        job["progress"] = i + 1
        if i + 1 < job["total"]:
            _set_find_fire_stage(job, "research", f"Preparing next lead ({i + 2}/{job['total']})")

    job["current_company"] = ""
    job["current_index"] = job["total"]
    _set_find_fire_stage(job, "done", f"Processed {job['progress']} of {job['total']} businesses.")


@app.route("/api/find-and-fire", methods=["POST"])
def api_find_and_fire():
    """
    Google Maps → Research → Email → PDF for up to `limit` businesses.

    Starts a background job and returns immediately with a job_id.
    Poll GET /api/find-and-fire/<job_id> for progress and results.

    Body: { "query": "dentists", "location": "Manchester", "limit": 3 }
    """
    import threading as _threading
    from google_maps_finder import find_and_add_prospects

    data     = request.get_json(silent=True) or {}
    query    = (data.get("query") or "").strip()
    location = (data.get("location") or "").strip()
    try:
        limit = max(1, min(int(data.get("limit", 3)), 5))
    except (TypeError, ValueError):
        limit = 3

    if not query or not location:
        return jsonify({"error": "query and location are required"}), 400

    if not os.getenv("GOOGLE_MAPS_API_KEY", "").strip():
        return jsonify({"error": "GOOGLE_MAPS_API_KEY not configured in .env"}), 400

    job_id = str(uuid.uuid4())
    _find_fire_jobs[job_id] = _new_find_fire_job(limit)

    t = _threading.Thread(
        target=_run_find_fire_job,
        args=(job_id, query, location, limit, find_and_add_prospects),
        daemon=True,
    )
    t.start()

    return jsonify({
        "job_id": job_id,
        "status": "running",
        "stage": _find_fire_jobs[job_id]["stage"],
        "progress": 0,
        "total": limit,
        "current_company": "",
        "current_index": 0,
        "results": [],
        "items": [],
        "message": _find_fire_jobs[job_id]["message"],
        "error": None,
    })


@app.route("/api/find-and-fire/<job_id>", methods=["GET"])
def api_find_and_fire_status(job_id):
    """Poll the status of a find-and-fire background job."""
    job = _find_fire_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify({
        "job_id":   job_id,
        "status":   job["status"],
        "stage":    job.get("stage", ""),
        "progress": job["progress"],
        "total":    job["total"],
        "current_company": job.get("current_company", ""),
        "current_index": job.get("current_index", 0),
        "items":    job.get("items", []),
        "message":  job.get("message", ""),
        "results":  job["results"],
        "error":    job["error"],
    })


@app.route("/api/send-outreach/<int:outreach_id>", methods=["POST"])
def api_send_outreach(outreach_id):
    """
    Send a specific outreach draft.

    Body: { "to_address": "person@company.com" }  (required if prospect has no email on file)
    """
    data       = request.get_json(silent=True) or {}
    to_address = (data.get("to_address") or "").strip()
    client_id  = _coerce_operator_client_id(request.args.get("client_id"), 1)

    # Load the outreach record
    all_outreach = database.get_all_outreach(client_id=client_id, db_path=database.DB_PATH)
    record = next((o for o in all_outreach if o["id"] == outreach_id), None)
    if not record:
        return jsonify({"error": "Outreach record not found"}), 404

    # Fall back to prospect's stored email if no address supplied
    if not to_address:
        p = database.get_prospect_by_id(record["prospect_id"], db_path=database.DB_PATH)
        to_address = (p.get("email") or "") if p else ""

    if not to_address:
        return jsonify({"error": "No email address. Pass to_address in the request body."}), 400

    valid, reason = _validate_email_address(to_address)
    if not valid:
        return jsonify({"error": f"Invalid recipient: {reason}"}), 400

    pdf_path = (record.get("pdf_path") or "").strip()
    delivery = deliver_prospect_email(
        to_address=to_address,
        subject=record["subject"],
        body=record["body"],
        prospect_id=record["prospect_id"],
        event_type="outreach_sent",
        client_id=record.get("client_id", 1),
        db_path=database.DB_PATH,
        content_excerpt=record["body"][:250],
        metadata=f"outreach_id={outreach_id};recipient={to_address}",
        attachment_path=pdf_path,
    )
    if not delivery["sent"]:
        return jsonify({"error": f"Send failed: {delivery['error']}"}), 500

    database.update_outreach_status(outreach_id, "sent", db_path=database.DB_PATH)
    database.update_status(record["prospect_id"], "contacted", db_path=database.DB_PATH)
    return jsonify({"ok": True, "sent_to": to_address, "subject": record["subject"]})


@app.route("/api/outreach-tracker")
def api_outreach_tracker():
    """Return all sent outreach records for the tracker panel."""
    client_id = _coerce_operator_client_id(request.args.get("client_id"), 1)
    return jsonify(database.get_sent_outreach(client_id=client_id, db_path=database.DB_PATH))


def _route_send_email(
    to_address: str,
    subject: str,
    body: str,
    attachment_path: str = "",
    in_reply_to: str = "",
    references: str = "",
    respect_suppression: bool = True,
    client_id: int = 1,
    db_path: str = database.DB_PATH,
    skip_warmup_throttle: bool = False,
    html_body: str = "",
) -> tuple[bool, str]:
    """
    Route outbound email through SendGrid or SMTP depending on USE_SENDGRID setting.
    SendGrid path: ignores attachment and thread headers (not yet supported there).
    SMTP path: supports PDF attachment and RFC-2822 thread headers.

    skip_warmup_throttle — set True for system emails (magic links, weekly reports,
    warmup emails themselves) that should not count against the daily outreach cap.
    """
    if not skip_warmup_throttle:
        _client_rec = database.get_client(client_id, db_path=db_path) if client_id else None
        _client_limit = int((_client_rec or {}).get("daily_send_limit") or 0)
        allowed, reason = warmup_engine.can_send_today(db_path=db_path, client_limit=_client_limit)
        if not allowed:
            return False, reason

    ok, err = route_outbound_email(
        to_address=to_address,
        subject=subject,
        body=body,
        attachment_path=attachment_path,
        in_reply_to=in_reply_to,
        references=references,
        respect_suppression=respect_suppression,
        client_id=client_id,
        db_path=db_path,
        html_body=html_body,
    )
    if ok and not skip_warmup_throttle:
        warmup_engine.record_real_send(db_path=db_path)
    return ok, err


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
    client_id = _coerce_operator_client_id(data.get("client_id"), 1)
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
            client_id=client_id,
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400
    prospect = next(
        (
            p
            for p in database.get_all_prospects(client_id=client_id, db_path=database.DB_PATH)
            if p["id"] == pid
        ),
        None,
    )
    return jsonify({"ok": True, "id": pid, "prospect": dict(prospect) if prospect else {}})


@app.route("/api/prospects/<int:prospect_id>/enrol", methods=["POST"])
def api_enrol_prospect(prospect_id):
    """
    Enrol a prospect in the default multi-channel sequence.
    Idempotent — safe to call if already enrolled.
    Also sets prospect status to 'in_sequence'.
    """
    client_id = _coerce_operator_client_id(request.args.get("client_id"), 1)
    prospect = database.get_prospect_by_id(prospect_id, db_path=database.DB_PATH)
    if not prospect or prospect.get("client_id", 1) != client_id:
        return jsonify({"error": "Prospect not found"}), 404
    enrollment_id = database.ensure_sequence_enrollment(prospect_id, db_path=database.DB_PATH)
    database.update_status(prospect_id, "in_sequence", db_path=database.DB_PATH)
    enrollment = database.get_sequence_enrollment(prospect_id, db_path=database.DB_PATH)
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
    client_id = _coerce_operator_client_id(request.args.get("client_id"), 1)
    allowed = ("name", "company", "email", "linkedin_url", "website",
               "phone", "lead_score", "status", "notes")
    kwargs = {k: data[k] for k in allowed if k in data}
    if not kwargs:
        return jsonify({"error": "No updatable fields provided."}), 400

    prospect = database.get_prospect_by_id(prospect_id, db_path=database.DB_PATH)
    if not prospect or prospect.get("client_id", 1) != client_id:
        return jsonify({"error": "Prospect not found."}), 404

    try:
        updated = database.update_prospect(prospect_id, db_path=database.DB_PATH, **kwargs)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    if not updated:
        return jsonify({"error": "Prospect not found."}), 404
    return jsonify({"ok": True})


@app.route("/api/prospects/<int:prospect_id>", methods=["DELETE"])
def api_delete_prospect(prospect_id):
    """Hard-delete a prospect and all related records."""
    client_id = _coerce_operator_client_id(request.args.get("client_id"), 1)
    prospect = database.get_prospect_by_id(prospect_id, db_path=database.DB_PATH)
    if not prospect or prospect.get("client_id", 1) != client_id:
        return jsonify({"error": "Prospect not found."}), 404
    removed = database.delete_prospect(prospect_id, db_path=database.DB_PATH)
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
        ("SENDGRID_WEBHOOK_PUBLIC_KEY", "SendGrid Webhook Public Key", "password", ""),
        ("LINKEDIN_DRY_RUN",     "LinkedIn Dry Run (true/false)", "text", "true"),
        ("SETTINGS_USER",        "Settings Page Username",  "text",     "admin"),
        ("SETTINGS_PASSWORD",    "Settings Page Password",  "password", "admin"),
        ("WARMUP_START_DATE",    "Warmup Start Date (YYYY-MM-DD)", "text", ""),
        ("WARMUP_ADDRESSES",     "Warmup Partner Emails (comma-separated)", "text", ""),
        ("WARMUP_EMAILS_PER_CYCLE", "Warmup Emails Per Cycle", "number", "3"),
        ("MAX_DAILY_SENDS",      "Max Real Sends Per Day (0 = use ramp)", "number", "0"),
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
    client_id = _coerce_operator_client_id(request.args.get("client_id"), 1)
    summary = reporter.generate_summary(client_id=client_id, db_path=database.DB_PATH)
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


@app.route("/api/sample-decks", methods=["POST"])
def api_sample_decks():
    """
    Generate (or re-use cached) 4 sample pitch decks across different industries.
    Returns a list of {company, contact, industry, url, error} dicts.
    """
    from deck_generator import generate_deck

    # Each sample uses a distinct visual theme
    SAMPLE_THEMES = [
        "dark_indigo",    # Apex Digital  — deep navy, purple/orange/cyan
        "charcoal_gold",  # ClearLaw      — black bg, gold accents
        "midnight_teal",  # PulseStudio   — dark teal, cyan/emerald
        "dark_slate_red", # Helix Agency  — near-black, red/amber
    ]

    SAMPLES = [
        {
            "company":          "Apex Digital",
            "name":             "James Cole",
            "niche":            "B2B SaaS for construction project managers",
            "icp":              "mid-sized UK construction firms running 5+ concurrent projects",
            "website_headline": "Stop losing projects to miscommunication",
            "product_feature":  "real-time site-to-office sync with automated progress reporting",
            "competitors":      "Buildertrend, CoConstruct",
            "ad_status":        "running_ads",
            "outbound_status":  "no_outbound",
            "notes":            "[Research Hook]\nPain Point: construction PMs waste 6+ hours per week on manual status updates\nGrowth Signal: recently rebranded with enterprise case studies\nOpener: sharp positioning around miscommunication",
        },
        {
            "company":          "ClearLaw",
            "name":             "Sophie Hunt",
            "niche":            "legal tech SaaS for independent law firms",
            "icp":              "UK law firms with 5-30 solicitors handling high-volume caseloads",
            "website_headline": "Case management that keeps up with your caseload",
            "product_feature":  "AI-assisted document review with deadline tracking",
            "competitors":      "Clio, Leap",
            "ad_status":        "no_ads",
            "outbound_status":  "no_outbound",
            "notes":            "[Research Hook]\nPain Point: solicitors spend 40% of billable time on admin instead of client work\nGrowth Signal: recently added remote working features\nOpener: every hour on admin is an hour not billed",
        },
        {
            "company":          "PulseStudio",
            "name":             "Marcus Webb",
            "niche":            "SaaS for boutique fitness studios and gym operators",
            "icp":              "independent fitness studios with 200-800 active members",
            "website_headline": "Run your studio. Not spreadsheets.",
            "product_feature":  "automated class booking, retention alerts, and member communication",
            "competitors":      "Mindbody, Glofox",
            "ad_status":        "running_ads",
            "outbound_status":  "no_outbound",
            "notes":            "[Research Hook]\nPain Point: studio owners lose 3-5 members per month to churn they never see coming\nGrowth Signal: launched a new membership tier this quarter\nOpener: the members who leave rarely say why",
        },
        {
            "company":          "Helix Agency",
            "name":             "Priya Nair",
            "niche":            "performance marketing agency for DTC e-commerce brands",
            "icp":              "UK DTC brands doing £500k-£5m annual revenue on Meta and Google",
            "website_headline": "Performance marketing that pays for itself",
            "product_feature":  "cross-channel attribution and creative testing at scale",
            "competitors":      "Impression, Hallam",
            "ad_status":        "running_ads",
            "outbound_status":  "active_outbound",
            "notes":            "[Research Hook]\nPain Point: DTC brands cap out on paid acquisition as CPAs rise and ROAS drops\nGrowth Signal: recently expanded to TikTok ads\nOpener: paid traffic is rented pipeline — remove the budget and it stops",
        },
    ]

    results = []
    for s, theme in zip(SAMPLES, SAMPLE_THEMES):
        company_safe = "".join(c if c.isalnum() else "_" for c in s["company"]).lower()
        existing_pdf  = os.path.join("decks", f"deck_{company_safe}.pdf")
        existing_pptx = os.path.join("decks", f"deck_{company_safe}.pptx")

        # Return cached file if it already exists
        if os.path.exists(existing_pdf):
            results.append({
                "company": s["company"],
                "contact": s["name"],
                "industry": s["niche"].split(" for ")[0] if " for " in s["niche"] else s["niche"][:40],
                "url": f"/decks/deck_{company_safe}.pdf",
                "error": None,
            })
            continue
        if os.path.exists(existing_pptx):
            results.append({
                "company": s["company"],
                "contact": s["name"],
                "industry": s["niche"].split(" for ")[0] if " for " in s["niche"] else s["niche"][:40],
                "url": f"/decks/deck_{company_safe}.pptx",
                "error": None,
            })
            continue

        # Generate
        try:
            path = generate_deck(s, theme=theme)
            filename = os.path.basename(path)
            results.append({
                "company": s["company"],
                "contact": s["name"],
                "industry": s["niche"].split(" for ")[0] if " for " in s["niche"] else s["niche"][:40],
                "url": f"/decks/{filename}",
                "error": None,
            })
        except Exception as exc:
            results.append({
                "company": s["company"],
                "contact": s["name"],
                "industry": s["niche"].split(" for ")[0] if " for " in s["niche"] else s["niche"][:40],
                "url": None,
                "error": str(exc)[:120],
            })

    return jsonify({"samples": results})


@app.route("/api/warmup-advice")
def api_warmup_advice():
    """Ask Claude to analyse warmup + real delivery data and recommend a safe daily send limit."""
    client_id = session.get("client_id", 1)
    _db = database.DB_PATH
    status = warmup_engine.get_combined_warmup_status(client_id=client_id, db_path=_db)
    client = database.get_client(client_id, db_path=_db)
    status["daily_send_limit"] = int((client or {}).get("daily_send_limit") or 0)
    delivery_metrics = database.get_delivery_metrics(client_id=client_id, days=30, db_path=_db)
    try:
        from ai_engine import get_warmup_advice
        advice = get_warmup_advice(status, delivery_metrics)
        return jsonify({"ok": True, "delivery_metrics": delivery_metrics, **advice})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/warmup-status")
def api_warmup_status():
    """Return email warmup ramp progress for the dashboard widget."""
    client_id = session.get("client_id", 1)
    status = warmup_engine.get_combined_warmup_status(client_id=client_id, db_path=database.DB_PATH)
    client = database.get_client(client_id, db_path=database.DB_PATH)
    status["daily_send_limit"] = int((client or {}).get("daily_send_limit") or 0)
    return jsonify(status)


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


# ---------------------------------------------------------------------------
# Weekly client report helper
# ---------------------------------------------------------------------------

def _send_weekly_client_reports() -> None:
    """
    Send a plain-text pipeline summary to every active client.
    Called by the background scheduler every Monday at 08:00 UTC.
    """
    monday = (datetime.date.today() - datetime.timedelta(days=datetime.date.today().weekday()))
    subject = f"Your OutreachEmpower pipeline — week of {monday.strftime('%d %b %Y')}"

    clients = database.get_active_clients()
    for client in clients:
        if not client.get("email"):
            continue
        try:
            summary  = reporter.generate_summary(client_id=client["id"])
            funnel   = summary["funnel"]["counts"]
            outreach = summary["outreach"]
            prospects_total = summary["prospects"]["total"]
            # Plain-text fallback
            plain_body = (
                f"Hi {client['name']},\n\n"
                f"Here's your OutreachEmpower pipeline update for the week of {monday}:\n\n"
                f"  Prospects found : {prospects_total}\n"
                f"  Emails sent     : {outreach.get('sent', 0)}\n"
                f"  Replies         : {funnel.get('replied', 0)}\n"
                f"  Booked calls    : {funnel.get('booked', 0)}\n\n"
                f"Your pipeline is active. We'll be in touch as results come in.\n\n"
                f"— The OutreachEmpower Team\n"
            )
            base_url = settings.get_app_base_url().rstrip("/")
            html_body = reporter.generate_weekly_report_html(
                summary,
                client_name=client.get("name", ""),
                week_label=monday.strftime("%d %b %Y"),
                dashboard_url=f"{base_url}/client" if base_url else "",
            )
            _route_send_email(
                to_address=client["email"],
                subject=subject,
                body=plain_body,
                html_body=html_body,
                respect_suppression=False,
                client_id=client["id"],
                skip_warmup_throttle=True,
            )
        except Exception as exc:
            print(f"[Weekly report] Failed for client {client['id']}: {exc}")


# ---------------------------------------------------------------------------
# Onboarding — public self-serve signup
# ---------------------------------------------------------------------------

@app.route("/onboard", methods=["GET"])
def onboard_page():
    """Public onboarding form — no auth required."""
    return render_template("onboard.html")


@app.route("/onboard", methods=["POST"])
def onboard_submit():
    """
    Create a new client workspace from the onboarding form.
    Queues the client for their first research and outreach cycle.
    Sends a welcome email with a magic login link.
    """
    data = request.form
    name          = (data.get("name") or "").strip()
    niche         = (data.get("niche") or "").strip()
    icp           = (data.get("icp") or "").strip()
    website       = (data.get("website") or "").strip()
    calendar_link = (data.get("calendar_link") or "").strip()
    location      = (data.get("location") or "").strip()
    email         = (data.get("email") or "").strip().lower()
    sender_name   = (data.get("sender_name") or "").strip()
    sender_email  = (data.get("sender_email") or "").strip().lower()

    if not name or not email:
        return render_template("onboard.html", error="Business name and email are required.")

    # Rate limit: max 5 signups per IP per hour
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()
    if not _onboard_rate_check(ip):
        return render_template(
            "onboard.html",
            error="Too many submissions from your network. Please try again later.",
        ), 429

    _db = database.DB_PATH

    # Prevent duplicate signups for the same email — re-send the welcome link
    existing = database.get_client_by_email(email, db_path=_db)
    if existing:
        _send_onboard_welcome(existing, _db)
        return redirect(url_for("onboard_confirm"))

    client_id = database.add_client(
        name=name,
        email=email,
        niche=niche or None,
        icp=icp or None,
        calendar_link=calendar_link or None,
        location=location or None,
        sender_name=sender_name or None,
        sender_email=sender_email or None,
        db_path=_db,
    )

    # Add a stub prospect for website research if a website was provided
    if website:
        database.add_prospect(
            name="Owner",
            company=name,
            website=website,
            client_id=client_id,
            status="new",
            db_path=_db,
        )

    _pending_client_research.add(client_id)

    # Auto-connect Mailivery warmup if enabled and sender SMTP credentials exist
    _mailivery_auto_connect(client_id, _db)

    # Send welcome email with magic login link
    new_client = database.get_client(client_id, db_path=_db)
    if new_client:
        _send_onboard_welcome(new_client, _db)

    return redirect(url_for("onboard_confirm"))


def _send_onboard_welcome(client: dict, db_path: str) -> None:
    """
    Create a 24-hour magic link and email it to the new client.
    Called immediately after /onboard signup.
    """
    import uuid as _uuid
    token      = str(_uuid.uuid4())
    expires_at = (
        datetime.datetime.utcnow() + datetime.timedelta(hours=24)
    ).strftime("%Y-%m-%d %H:%M:%S")
    database.create_client_session(
        client_id=client["id"],
        token=token,
        expires_at=expires_at,
        db_path=db_path,
    )
    base_url   = settings.get_app_base_url().rstrip("/") or request.host_url.rstrip("/")
    verify_url = f"{base_url}{url_for('client_verify')}?token={token}"
    try:
        _route_send_email(
            to_address=client["email"],
            subject="Welcome to OutreachEmpower — access your dashboard",
            respect_suppression=False,
            client_id=client["id"],
            skip_warmup_throttle=True,
            body=(
                f"Hi {client['name']},\n\n"
                f"Your OutreachEmpower workspace is set up and we're starting research now.\n\n"
                f"Click here to access your dashboard:\n\n"
                f"{verify_url}\n\n"
                f"This link expires in 24 hours. You can always get a new one at /client/login.\n\n"
                f"What happens next:\n"
                f"  1. We research your target market (niche: {client.get('niche') or 'TBC'})\n"
                f"  2. We write personalised cold emails for each prospect\n"
                f"  3. Emails go out over the next few hours\n"
                f"  4. Warm replies will appear in your dashboard automatically\n\n"
                f"Questions? Just reply to this email.\n\n"
                f"— The OutreachEmpower Team\n"
            ),
        )
    except Exception as exc:
        print(f"[Onboard] Welcome email failed for client {client['id']}: {exc}")


def _mailivery_auto_connect(client_id: int, db_path: str) -> None:
    """
    If Mailivery is enabled and the client has SMTP credentials configured,
    auto-connect their mailbox to Mailivery warmup and start the campaign.
    Silently skips if Mailivery is disabled or credentials are missing.
    """
    mc = mailivery_client.get_client()
    if not mc:
        return
    client = database.get_client(client_id, db_path=db_path)
    if not client:
        return
    sender_email = (client.get("sender_email") or "").strip()
    if not sender_email:
        return
    smtp_host = os.getenv("SMTP_HOST", "").strip()
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USERNAME", os.getenv("SMTP_USER", "")).strip()
    smtp_pass = os.getenv("SMTP_PASSWORD", os.getenv("SMTP_PASS", "")).strip()
    if not (smtp_host and smtp_user and smtp_pass):
        return
    owner_email = os.getenv("MAILIVERY_OWNER_EMAIL", smtp_user).strip()
    first_name  = (client.get("sender_name") or client.get("name") or "").split()[0]
    last_name   = " ".join((client.get("sender_name") or client.get("name") or "").split()[1:]) or "."
    result = mc.connect_smtp_mailbox(
        first_name=first_name,
        last_name=last_name,
        email=sender_email,
        owner_email=owner_email,
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        smtp_username=smtp_user,
        smtp_password=smtp_pass,
        imap_host=os.getenv("IMAP_HOST", smtp_host),
        imap_port=int(os.getenv("IMAP_PORT", "993")),
        imap_username=smtp_user,
        imap_password=smtp_pass,
    )
    if not result.get("ok"):
        print(f"[Mailivery] Auto-connect failed for client {client_id}: {result.get('error')}")
        return
    campaign_id = result.get("id") or result.get("campaign_id")
    if campaign_id:
        database.update_client(client_id, mailivery_campaign_id=str(campaign_id), db_path=db_path)
        mc.start_warmup(str(campaign_id))
        print(f"[Mailivery] Connected and started warmup for client {client_id} (campaign {campaign_id})")


def _refresh_mailivery_health_scores() -> None:
    """
    Fetch and cache Mailivery health scores for all active clients that have
    a linked campaign. Runs every 4 hours from the background scheduler.
    Warns to stdout if any score drops below 50.
    """
    mc = mailivery_client.get_client()
    if not mc:
        return
    _db = database.DB_PATH
    for client in database.get_active_clients(db_path=_db):
        campaign_id = (client.get("mailivery_campaign_id") or "").strip()
        if not campaign_id:
            continue
        result = mc.get_health_score(campaign_id)
        if not result.get("ok"):
            continue
        score = result.get("health_score")
        if score is None:
            continue
        database.update_client(client["id"], mailivery_health_score=int(score), db_path=_db)
        if score < 50:
            print(f"[Mailivery] WARNING: health score {score}/100 for client {client['id']} "
                  f"({client.get('email')}) — campaign {campaign_id}")


@app.route("/onboard/confirm")
def onboard_confirm():
    """Post-signup confirmation page."""
    return render_template("onboard_confirm.html")


# ---------------------------------------------------------------------------
# Client dashboard — magic-link login
# ---------------------------------------------------------------------------

def _client_login_required():
    """Return the client_id from session, or None if not authenticated."""
    return session.get("client_id")


@app.route("/client/login", methods=["GET"])
def client_login_page():
    """Magic link request form."""
    return render_template("client_login.html", sent=False, error=None)


@app.route("/client/login", methods=["POST"])
def client_login_submit():
    """
    Generate a magic link token and email it to the client.
    Uses the same _route_send_email() path as all other outbound sends.
    """
    email = (request.form.get("email") or "").strip().lower()
    if not email:
        return render_template("client_login.html", sent=False, error="Email is required.")

    _db = database.DB_PATH
    client = database.get_client_by_email(email, db_path=_db)
    if not client:
        # Don't reveal whether the email exists — show the same success message
        return render_template("client_login.html", sent=True, error=None)

    token      = str(uuid.uuid4())
    expires_at = (
        datetime.datetime.utcnow() + datetime.timedelta(hours=24)
    ).strftime("%Y-%m-%d %H:%M:%S")

    database.create_client_session(
        client_id=client["id"],
        token=token,
        expires_at=expires_at,
        db_path=_db,
    )

    verify_url = request.host_url.rstrip("/") + url_for("client_verify") + f"?token={token}"

    try:
        _route_send_email(
            to_address=email,
            subject="Your OutreachEmpower login link",
            respect_suppression=False,
            client_id=client["id"],
            skip_warmup_throttle=True,
            body=(
                f"Hi {client['name']},\n\n"
                f"Click this link to access your OutreachEmpower dashboard:\n\n"
                f"{verify_url}\n\n"
                f"This link expires in 24 hours and can only be used once.\n\n"
                f"— The OutreachEmpower Team\n"
            ),
        )
    except Exception as exc:
        return render_template(
            "client_login.html", sent=False,
            error=f"Could not send login email: {exc}"
        )

    return render_template("client_login.html", sent=True, error=None)


@app.route("/client/verify")
def client_verify():
    """Validate a magic link token and log the client in."""
    token = request.args.get("token", "").strip()
    if not token:
        return redirect(url_for("client_login_page"))

    _db = database.DB_PATH
    record = database.get_client_session(token, db_path=_db)
    if not record:
        return render_template("client_login.html", sent=False, error="Invalid login link.")

    if record["used"]:
        return render_template("client_login.html", sent=False, error="This link has already been used.")

    expires_at = datetime.datetime.strptime(record["expires_at"], "%Y-%m-%d %H:%M:%S")
    if datetime.datetime.utcnow() > expires_at:
        return render_template("client_login.html", sent=False, error="This link has expired.")

    database.mark_session_used(token, db_path=_db)
    session["client_id"] = record["client_id"]
    return redirect(url_for("client_dashboard"))


@app.route("/client")
def client_dashboard():
    """
    Client-facing pipeline dashboard.
    Shows only data for the logged-in client's workspace.
    """
    client_id = _client_login_required()
    if not client_id:
        return redirect(url_for("client_login_page"))

    _db = database.DB_PATH
    client    = database.get_client(client_id, db_path=_db)
    if not client:
        session.clear()
        return redirect(url_for("client_login_page"))

    analytics             = database.get_client_analytics(client_id, db_path=_db)
    outreach_queue_count  = len(database.get_pending_outreach_for_review(client_id, db_path=_db))
    warmup_status         = warmup_engine.get_combined_warmup_status(client_id=client_id, db_path=_db)
    return render_template(
        "client_dashboard.html",
        client=client,
        analytics=analytics,
        outreach_queue_count=outreach_queue_count,
        warmup_status=warmup_status,
    )


@app.route("/client/prospects")
def client_prospects_page():
    """Client-facing prospect list scoped to the logged-in workspace."""
    client_id = _client_login_required()
    if not client_id:
        return redirect(url_for("client_login_page"))

    _db = database.DB_PATH
    client = database.get_client(client_id, db_path=_db)
    if not client:
        session.clear()
        return redirect(url_for("client_login_page"))

    all_prospects = _annotate_sequence_progress(
        database.get_all_prospects(client_id=client_id, db_path=_db)
    )
    q = (request.args.get("q") or "").strip().lower()
    status_filter = (request.args.get("status") or "").strip().lower()
    sort_key = (request.args.get("sort") or "score").strip().lower()
    sort_dir = (request.args.get("dir") or "desc").strip().lower()
    try:
        current_page = max(1, int(request.args.get("page", 1)))
    except (TypeError, ValueError):
        current_page = 1
    per_page = 10

    prospects, sort_key, sort_dir = _apply_client_prospect_filters(
        all_prospects,
        q,
        status_filter,
        sort_key,
        sort_dir,
    )

    total_filtered = len(prospects)
    total_pages = max(1, (total_filtered + per_page - 1) // per_page)
    if current_page > total_pages:
        current_page = total_pages
    start = (current_page - 1) * per_page
    end = start + per_page
    prospects = prospects[start:end]

    available_statuses = sorted({
        (p.get("status") or "").lower()
        for p in all_prospects
        if (p.get("status") or "").strip()
    })
    return render_template(
        "client_prospects.html",
        client=client,
        prospects=prospects,
        all_prospects=all_prospects,
        available_statuses=available_statuses,
        search_query=request.args.get("q", "").strip(),
        status_filter=status_filter,
        sort_key=sort_key,
        sort_dir=sort_dir,
        current_page=current_page,
        total_pages=total_pages,
        total_filtered=total_filtered,
        per_page=per_page,
    )


@app.route("/client/prospects/export")
def client_prospects_export():
    """Export the logged-in client's filtered prospects as CSV."""
    import csv
    import io
    from flask import Response

    client_id = _client_login_required()
    if not client_id:
        return redirect(url_for("client_login_page"))

    _db = database.DB_PATH
    client = database.get_client(client_id, db_path=_db)
    if not client:
        session.clear()
        return redirect(url_for("client_login_page"))

    all_prospects = _annotate_sequence_progress(
        database.get_all_prospects(client_id=client_id, db_path=_db)
    )
    q = (request.args.get("q") or "").strip().lower()
    status_filter = (request.args.get("status") or "").strip().lower()
    sort_key = (request.args.get("sort") or "score").strip().lower()
    sort_dir = (request.args.get("dir") or "desc").strip().lower()
    prospects, _, _ = _apply_client_prospect_filters(
        all_prospects,
        q,
        status_filter,
        sort_key,
        sort_dir,
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["name", "company", "email", "website", "sequence", "lead_score", "status", "notes"])
    for prospect in prospects:
        writer.writerow([
            prospect.get("name", ""),
            prospect.get("company", ""),
            prospect.get("email", ""),
            prospect.get("website", ""),
            prospect.get("sequence_day_label", ""),
            prospect.get("lead_score", ""),
            prospect.get("status", ""),
            prospect.get("notes", ""),
        ])

    safe_name = "".join(ch if ch.isalnum() else "_" for ch in (client.get("name") or "client")).strip("_") or "client"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}_prospects.csv"'
        },
    )


@app.route("/client/prospects/<int:prospect_id>")
def client_prospect_detail_page(prospect_id):
    """Client-facing detail page for a single workspace prospect."""
    client_id = _client_login_required()
    if not client_id:
        return redirect(url_for("client_login_page"))

    _db = database.DB_PATH
    client = database.get_client(client_id, db_path=_db)
    if not client:
        session.clear()
        return redirect(url_for("client_login_page"))

    prospect = database.get_prospect_by_id(prospect_id, db_path=_db)
    if not prospect or prospect.get("client_id") != client_id:
        return redirect(url_for("client_prospects_page"))

    annotated = _annotate_sequence_progress([prospect])[0]
    latest_research = database.get_latest_research(prospect_id, db_path=_db)
    outreach_history = database.get_outreach_by_prospect(prospect_id, db_path=_db)
    reply_history = database.get_reply_drafts_for_prospect(prospect_id, db_path=_db)

    return render_template(
        "client_prospect_detail.html",
        client=client,
        prospect=annotated,
        latest_research=latest_research,
        outreach_history=outreach_history,
        reply_history=reply_history,
    )


@app.route("/client/prospects/<int:prospect_id>/update-status", methods=["POST"])
def client_prospect_update_status(prospect_id):
    """Allow a client to manually mark a prospect as booked or rejected."""
    client_id = _client_login_required()
    if not client_id:
        return redirect(url_for("client_login_page"))

    _db = database.DB_PATH
    prospect = database.get_prospect_by_id(prospect_id, db_path=_db)
    if not prospect or prospect.get("client_id") != client_id:
        return redirect(url_for("client_prospects_page"))

    new_status = (request.form.get("new_status") or "").strip().lower()
    if new_status == "booked":
        database.update_status(prospect_id, "booked", db_path=_db)
        database.update_sequence_enrollment_status(
            prospect_id, "completed", paused_reason="manually_marked_booked", db_path=_db
        )
    elif new_status == "rejected":
        database.update_status(prospect_id, "rejected", db_path=_db)
        database.update_sequence_enrollment_status(
            prospect_id, "paused", paused_reason="manually_marked_rejected", db_path=_db
        )

    return redirect(url_for("client_prospect_detail_page", prospect_id=prospect_id))


@app.route("/client/prospects/bulk-action", methods=["POST"])
def client_prospects_bulk_action():
    """Client-authenticated bulk actions for prospects in the current workspace."""
    client_id = _client_login_required()
    if not client_id:
        return jsonify({"error": "Not authenticated"}), 401

    data = request.get_json(silent=True) or {}
    action = (data.get("action") or "").strip().lower()
    raw_ids = data.get("prospect_ids") or []
    if action not in ("enrol", "status"):
        return jsonify({"error": "Unsupported bulk action."}), 400
    if not isinstance(raw_ids, list) or not raw_ids:
        return jsonify({"error": "Select at least one prospect."}), 400

    prospect_ids = []
    for value in raw_ids:
        try:
            prospect_ids.append(int(value))
        except (TypeError, ValueError):
            return jsonify({"error": "Prospect IDs must be integers."}), 400

    unique_ids = sorted(set(prospect_ids))
    prospects = [
        database.get_prospect_by_id(pid, db_path=database.DB_PATH)
        for pid in unique_ids
    ]
    allowed = [p for p in prospects if p and p.get("client_id") == client_id]
    if len(allowed) != len(unique_ids):
        return jsonify({"error": "One or more prospects were not found."}), 404

    updated = 0
    if action == "enrol":
        for prospect in allowed:
            database.ensure_sequence_enrollment(prospect["id"], db_path=database.DB_PATH)
            database.update_status(prospect["id"], "in_sequence", db_path=database.DB_PATH)
            updated += 1
        return jsonify({"ok": True, "action": "enrol", "updated": updated})

    status = (data.get("status") or "").strip().lower()
    if status not in database.VALID_STATUSES:
        return jsonify({"error": "Invalid status."}), 400

    for prospect in allowed:
        database.update_prospect(prospect["id"], status=status, db_path=database.DB_PATH)
        updated += 1
    return jsonify({"ok": True, "action": "status", "status": status, "updated": updated})


@app.route("/client/reply-drafts/<int:draft_id>/action", methods=["POST"])
def client_reply_draft_action(draft_id):
    """
    Client-facing approve/dismiss for a reply draft.
    Verifies the draft belongs to the logged-in client before acting.
    """
    client_id = _client_login_required()
    if not client_id:
        return jsonify({"error": "Not authenticated"}), 401

    data   = request.get_json(silent=True) or {}
    action = (data.get("action") or "").strip()
    if action not in ("approve", "dismiss"):
        return jsonify({"error": "action must be 'approve' or 'dismiss'"}), 400

    draft = database.get_reply_draft_by_id(draft_id, db_path=database.DB_PATH)
    if not draft:
        return jsonify({"error": "Draft not found"}), 404
    if draft.get("client_id") != client_id:
        return jsonify({"error": "Not found"}), 404  # don't leak existence

    if action == "dismiss":
        database.update_reply_draft_status(draft_id, "dismissed", db_path=database.DB_PATH)
        return jsonify({"ok": True, "status": "dismissed"})

    recipient = (draft.get("inbound_from") or draft.get("prospect_email") or "").strip()
    if not recipient:
        return jsonify({"error": "Draft has no recipient email."}), 400

    valid, reason = _validate_email_address(recipient)
    if not valid:
        return jsonify({"error": f"Invalid recipient: {reason}"}), 400

    body = (data.get("body") or draft.get("drafted_reply") or "").strip()
    if not body:
        return jsonify({"error": "Draft has no body."}), 400

    raw_subject = (draft.get("inbound_subject") or "").strip()
    if not raw_subject:
        raw_subject = (draft.get("prospect_company") or "follow-up")
    subject = raw_subject if raw_subject.lower().startswith("re:") else f"Re: {raw_subject}"

    inbound_message_id = (draft.get("inbound_message_id") or "").strip()
    delivery = deliver_prospect_email(
        to_address=recipient,
        subject=subject,
        body=body,
        prospect_id=draft["prospect_id"],
        event_type="reply_draft_sent",
        client_id=client_id,
        db_path=database.DB_PATH,
        content_excerpt=body[:250],
        metadata=f"draft_id={draft_id};source=client_dashboard",
        in_reply_to=inbound_message_id,
        references=inbound_message_id,
    )
    if not delivery["sent"]:
        return jsonify({"error": f"Send failed: {delivery['error']}"}), 500

    database.update_reply_draft_status(draft_id, "sent", db_path=database.DB_PATH)
    database.update_status(draft["prospect_id"], "replied", db_path=database.DB_PATH)
    return jsonify({"ok": True, "status": "sent", "recipient": recipient})


@app.route("/client/settings", methods=["GET"])
def client_settings_page():
    """Client settings — update niche, ICP, location, calendar link."""
    client_id = _client_login_required()
    if not client_id:
        return redirect(url_for("client_login_page"))
    client = database.get_client(client_id, db_path=database.DB_PATH)
    if not client:
        session.clear()
        return redirect(url_for("client_login_page"))
    saved        = request.args.get("saved") == "1"
    verified     = request.args.get("verified") == "1"
    verify_sent  = request.args.get("verify_sent") == "1"
    verify_error = request.args.get("verify_error") or ""
    return render_template(
        "client_settings.html",
        client=client,
        saved=saved,
        verified=verified,
        verify_sent=verify_sent,
        verify_error=verify_error,
    )


@app.route("/client/settings", methods=["POST"])
def client_settings_submit():
    """Save updated client settings."""
    client_id = _client_login_required()
    if not client_id:
        return redirect(url_for("client_login_page"))

    data          = request.form
    niche         = (data.get("niche") or "").strip() or None
    icp           = (data.get("icp") or "").strip() or None
    location      = (data.get("location") or "").strip() or None
    calendar_link = (data.get("calendar_link") or "").strip() or None
    sender_name   = (data.get("sender_name") or "").strip() or None
    sender_email  = (data.get("sender_email") or "").strip().lower() or None

    _db = database.DB_PATH

    # If the sender_email is changing, reset verification so the new address
    # must be re-verified before it's used for outbound sends.
    current_client = database.get_client(client_id, db_path=_db)
    old_sender_email = ((current_client or {}).get("sender_email") or "").strip().lower()
    if sender_email != old_sender_email:
        database.reset_sender_verification(client_id, db_path=_db)

    database.update_client(
        client_id,
        niche=niche,
        icp=icp,
        location=location,
        calendar_link=calendar_link,
        sender_name=sender_name,
        sender_email=sender_email,
        db_path=_db,
    )
    return redirect(url_for("client_settings_page") + "?saved=1")


@app.route("/client/warmup/set-daily-limit", methods=["POST"])
def client_set_daily_limit():
    """Set the per-client daily outreach email limit. 0 = use warmup ramp schedule."""
    client_id = _client_login_required()
    if not client_id:
        return jsonify({"error": "not authenticated"}), 401
    _db = database.DB_PATH
    try:
        limit = int(request.get_json(silent=True, force=True).get("limit", 0))
    except (TypeError, ValueError, AttributeError):
        return jsonify({"error": "invalid limit"}), 400
    limit = max(0, min(500, limit))
    database.update_client(client_id, daily_send_limit=limit, db_path=_db)

    # Mirror to Mailivery if connected and limit > 0
    if limit > 0:
        client = database.get_client(client_id, db_path=_db)
        campaign_id = (client.get("mailivery_campaign_id") or "").strip()
        if campaign_id:
            mc = mailivery_client.get_client()
            if mc:
                mc.update_emails_per_day(campaign_id, limit)

    ramp_limit = warmup_engine.get_daily_limit()
    return jsonify({
        "ok":             True,
        "daily_send_limit": limit,
        "effective_limit":  limit if limit > 0 else ramp_limit,
        "using_ramp":       limit == 0,
    })


@app.route("/client/prospecting/settings", methods=["POST"])
def client_prospecting_settings():
    """Save niche and location for Google Maps scraping."""
    client_id = _client_login_required()
    if not client_id:
        return jsonify({"error": "not authenticated"}), 401
    data     = request.get_json(silent=True, force=True) or {}
    niche    = (data.get("niche") or "").strip()
    location = (data.get("location") or "").strip()
    icp      = (data.get("icp") or "").strip()
    if not niche or not location:
        return jsonify({"error": "niche and location are required"}), 400
    _db = database.DB_PATH
    database.update_client(client_id, niche=niche, location=location,
                           icp=icp or None, db_path=_db)
    return jsonify({"ok": True, "niche": niche, "location": location})


@app.route("/client/campaign/pause", methods=["POST"])
def client_campaign_pause():
    """Pause sequence dispatch for the logged-in client's workspace."""
    client_id = _client_login_required()
    if not client_id:
        return redirect(url_for("client_login_page"))
    database.update_client(client_id, campaign_paused=1, db_path=database.DB_PATH)
    return redirect(url_for("client_dashboard"))


@app.route("/client/campaign/resume", methods=["POST"])
def client_campaign_resume():
    """Resume sequence dispatch for the logged-in client's workspace."""
    client_id = _client_login_required()
    if not client_id:
        return redirect(url_for("client_login_page"))
    database.update_client(client_id, campaign_paused=0, db_path=database.DB_PATH)
    return redirect(url_for("client_dashboard"))


@app.route("/client/campaign/review-mode/enable", methods=["POST"])
def client_review_mode_enable():
    """Enable outreach review mode — all sequence emails held for approval."""
    client_id = _client_login_required()
    if not client_id:
        return redirect(url_for("client_login_page"))
    database.update_client(client_id, outreach_review_mode=1, db_path=database.DB_PATH)
    return redirect(url_for("client_dashboard"))


@app.route("/client/campaign/review-mode/disable", methods=["POST"])
def client_review_mode_disable():
    """Disable outreach review mode — sequence emails send automatically again."""
    client_id = _client_login_required()
    if not client_id:
        return redirect(url_for("client_login_page"))
    database.update_client(client_id, outreach_review_mode=0, db_path=database.DB_PATH)
    return redirect(url_for("client_dashboard"))


@app.route("/client/outreach-queue")
def client_outreach_queue():
    """Client-facing approval queue for outreach emails held for review."""
    client_id = _client_login_required()
    if not client_id:
        return redirect(url_for("client_login_page"))
    _db = database.DB_PATH
    client = database.get_client(client_id, db_path=_db)
    if not client:
        session.clear()
        return redirect(url_for("client_login_page"))
    pending = database.get_pending_outreach_for_review(client_id, db_path=_db)
    return render_template("client_outreach_queue.html", client=client, pending=pending)


@app.route("/client/outreach-queue/<int:outreach_id>/action", methods=["POST"])
def client_outreach_queue_action(outreach_id):
    """Approve (send) or reject a pending outreach email."""
    client_id = _client_login_required()
    if not client_id:
        return jsonify({"error": "Not authenticated"}), 401

    data   = request.get_json(silent=True) or {}
    action = (data.get("action") or "").strip().lower()
    if action not in ("approve", "reject"):
        return jsonify({"error": "action must be 'approve' or 'reject'"}), 400

    _db = database.DB_PATH
    # Load all pending outreach for this client to verify ownership
    pending = database.get_pending_outreach_for_review(client_id, db_path=_db)
    record  = next((o for o in pending if o["id"] == outreach_id), None)
    if not record:
        return jsonify({"error": "Outreach record not found or already actioned"}), 404

    if action == "reject":
        database.update_outreach_status(outreach_id, "rejected_draft", db_path=_db)
        return jsonify({"ok": True, "status": "rejected_draft"})

    # Approve: send now
    to_address = (record.get("prospect_email") or "").strip()
    if not to_address:
        p = database.get_prospect_by_id(record["prospect_id"], db_path=_db)
        to_address = ((p or {}).get("email") or "").strip()
    if not to_address:
        return jsonify({"error": "No email address on file for this prospect"}), 400

    edited_body = (data.get("body") or record["body"]).strip()
    delivery = deliver_prospect_email(
        to_address=to_address,
        subject=record["subject"],
        body=edited_body,
        prospect_id=record["prospect_id"],
        event_type="outreach_sent",
        client_id=client_id,
        db_path=_db,
        content_excerpt=edited_body[:250],
        metadata=f"outreach_id={outreach_id};source=outreach_queue_approval",
        attachment_path=(record.get("pdf_path") or "").strip(),
    )
    if not delivery["sent"]:
        return jsonify({"error": f"Send failed: {delivery['error']}"}), 500

    database.update_outreach_status(outreach_id, "sent", db_path=_db)
    database.update_status(record["prospect_id"], "contacted", db_path=_db)
    return jsonify({"ok": True, "status": "sent", "sent_to": to_address})


@app.route("/client/logout", methods=["POST"])
def client_logout():
    """Clear the client session."""
    session.clear()
    return redirect(url_for("client_login_page"))


# ---------------------------------------------------------------------------
# Sender email verification
# ---------------------------------------------------------------------------

@app.route("/client/settings/verify-sender", methods=["POST"])
def client_verify_sender_send():
    """
    Send a verification email to the client's configured sender_email.
    The email contains a one-click link that, when visited, marks the address
    as verified so it can be used for outbound sends.
    """
    client_id = _client_login_required()
    if not client_id:
        return redirect(url_for("client_login_page"))

    _db = database.DB_PATH
    client = database.get_client(client_id, db_path=_db)
    if not client:
        session.clear()
        return redirect(url_for("client_login_page"))

    sender_email = (client.get("sender_email") or "").strip().lower()
    if not sender_email:
        return redirect(url_for("client_settings_page") + "?verify_error=no_email")

    token      = str(uuid.uuid4())
    expires_at = (
        datetime.datetime.utcnow() + datetime.timedelta(hours=24)
    ).strftime("%Y-%m-%d %H:%M:%S")

    database.set_sender_verify_token(client_id, token, expires_at, db_path=_db)

    verify_url = (
        request.host_url.rstrip("/")
        + url_for("client_verify_sender_confirm")
        + f"?token={token}"
    )

    try:
        _route_send_email(
            to_address=sender_email,
            subject="Verify your sending address — OutreachEmpower",
            body=(
                f"Hi {client.get('name', '')},\n\n"
                f"Click the link below to verify {sender_email} as your campaign "
                f"sending address:\n\n"
                f"{verify_url}\n\n"
                f"This link expires in 24 hours. If you didn't request this, "
                f"you can ignore this email.\n\n"
                f"— The OutreachEmpower Team\n"
            ),
            respect_suppression=False,
            client_id=client_id,
            skip_warmup_throttle=True,
        )
    except Exception as exc:
        print(f"[SenderVerify] failed to send verification to {sender_email}: {exc}")
        return redirect(url_for("client_settings_page") + "?verify_error=send_failed")

    return redirect(url_for("client_settings_page") + "?verify_sent=1")


@app.route("/client/verify-sender")
def client_verify_sender_confirm():
    """
    Public endpoint — validate the sender verification token and mark the
    client's sender_email as verified.
    Does not require the client session since the link is sent to the email address.
    """
    token = request.args.get("token", "").strip()
    if not token:
        return redirect(url_for("client_login_page"))

    _db = database.DB_PATH
    client = database.get_client_by_sender_verify_token(token, db_path=_db)
    if not client:
        return render_template(
            "client_login.html", sent=False,
            error="Invalid or expired verification link.",
        )

    expires_at_str = (client.get("sender_verify_expires_at") or "")
    if expires_at_str:
        try:
            expires_at = datetime.datetime.strptime(expires_at_str, "%Y-%m-%d %H:%M:%S")
            if datetime.datetime.utcnow() > expires_at:
                return render_template(
                    "client_login.html", sent=False,
                    error="This verification link has expired. Please request a new one from your settings.",
                )
        except ValueError:
            pass

    database.confirm_sender_email_verified(client["id"], db_path=_db)

    # If the client already has an active session, redirect to settings with success.
    # Otherwise redirect to login (they'll see the verified badge after logging in).
    if session.get("client_id") == client["id"]:
        return redirect(url_for("client_settings_page") + "?verified=1")
    return redirect(url_for("client_login_page") + "?verified=1")


# ---------------------------------------------------------------------------
# Stripe webhook — subscription lifecycle
# ---------------------------------------------------------------------------

@app.route("/webhook/stripe", methods=["POST"])
def stripe_webhook():
    """
    Handle Stripe webhook events.
    Activate clients on checkout.session.completed.
    Mark cancelled on customer.subscription.deleted.

    Set STRIPE_WEBHOOK_SECRET in .env to enable signature verification.
    """
    import stripe as _stripe

    secret_key      = os.getenv("STRIPE_SECRET_KEY", "").strip()
    webhook_secret  = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()

    if not secret_key:
        return jsonify({"error": "Stripe not configured"}), 400

    _stripe.api_key = secret_key
    payload = request.get_data()

    if webhook_secret:
        sig = request.headers.get("Stripe-Signature", "")
        try:
            event = _stripe.Webhook.construct_event(payload, sig, webhook_secret)
        except (_stripe.error.SignatureVerificationError, ValueError) as exc:
            print(f"[Stripe webhook] signature error: {exc}")
            return jsonify({"error": "Invalid signature"}), 400
    else:
        try:
            event = _stripe.Event.construct_from(
                __import__("json").loads(payload), _stripe.api_key
            )
        except Exception as exc:
            return jsonify({"error": str(exc)}), 400

    _db = database.DB_PATH
    etype = event["type"]

    if etype == "checkout.session.completed":
        sess        = event["data"]["object"]
        cust_email  = (sess.get("customer_details") or {}).get("email") or sess.get("customer_email") or ""
        cust_email  = cust_email.strip().lower()
        if cust_email:
            client = database.get_client_by_email(cust_email, db_path=_db)
            if client:
                database.update_client(client["id"], status="active", db_path=_db)
                _pending_client_research.add(client["id"])
                print(f"[Stripe] activated client {client['id']} ({cust_email})")
            else:
                print(f"[Stripe] checkout.session.completed — no client found for {cust_email}")

    elif etype == "customer.subscription.deleted":
        sub        = event["data"]["object"]
        cust_id    = sub.get("customer", "")
        if cust_id and secret_key:
            try:
                cust       = _stripe.Customer.retrieve(cust_id)
                cust_email = (cust.get("email") or "").strip().lower()
                if cust_email:
                    client = database.get_client_by_email(cust_email, db_path=_db)
                    if client:
                        database.update_client(client["id"], status="cancelled", db_path=_db)
                        print(f"[Stripe] cancelled client {client['id']} ({cust_email})")
            except Exception as exc:
                print(f"[Stripe] could not process subscription.deleted: {exc}")

    return jsonify({"received": True})


def _apply_sendgrid_suppression(email: str, reason: str, event_type: str) -> int:
    """
    Suppress a contact across all matching workspaces and log the webhook event.

    Returns the number of matching prospects updated.
    """
    normalized = (email or "").strip().lower()
    if not normalized:
        return 0

    prospects = database.get_prospects_by_email(normalized, db_path=database.DB_PATH)
    if not prospects:
        return 0

    for prospect in prospects:
        client_id = prospect.get("client_id", 1)
        database.suppress_contact(
            normalized,
            reason=reason,
            source="sendgrid_webhook",
            db_path=database.DB_PATH,
            client_id=client_id,
        )
        database.update_status(prospect["id"], "rejected", db_path=database.DB_PATH)
        database.log_communication_event(
            prospect_id=prospect["id"],
            channel="email",
            direction="outbound",
            event_type=event_type,
            status="failed" if event_type in ("sendgrid_bounce", "sendgrid_dropped") else "skipped",
            content_excerpt=normalized[:250],
            metadata=f"source=sendgrid_webhook;reason={reason};email={normalized}",
            client_id=client_id,
            db_path=database.DB_PATH,
        )
    return len(prospects)


def _load_sendgrid_webhook_public_key(public_key: str):
    """Load a SendGrid webhook public key from PEM or base64-encoded DER text."""
    import base64
    from cryptography.hazmat.primitives import serialization

    normalized = (public_key or "").strip()
    if not normalized:
        return None

    try:
        if normalized.startswith("-----BEGIN"):
            return serialization.load_pem_public_key(normalized.encode("utf-8"))
        return serialization.load_der_public_key(base64.b64decode(normalized))
    except Exception:
        return None


def _verify_sendgrid_webhook_signature(payload: bytes) -> tuple[bool, str | None]:
    """
    Verify the SendGrid Event Webhook signature when a public key is configured.

    Twilio's docs specify ECDSA verification over the SHA-256 digest of
    timestamp + raw payload bytes, using these headers:
      - X-Twilio-Email-Event-Webhook-Signature
      - X-Twilio-Email-Event-Webhook-Timestamp
    """
    import base64
    import hashlib
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec, utils

    configured_key = (os.getenv("SENDGRID_WEBHOOK_PUBLIC_KEY") or "").strip()
    if not configured_key:
        return True, None

    signature = (request.headers.get("X-Twilio-Email-Event-Webhook-Signature") or "").strip()
    timestamp = (request.headers.get("X-Twilio-Email-Event-Webhook-Timestamp") or "").strip()
    if not signature or not timestamp:
        return False, "Missing SendGrid signature headers."

    public_key = _load_sendgrid_webhook_public_key(configured_key)
    if public_key is None:
        return False, "Invalid SENDGRID_WEBHOOK_PUBLIC_KEY configuration."

    try:
        signature_bytes = base64.b64decode(signature)
    except Exception:
        return False, "Malformed SendGrid signature."

    digest = hashlib.sha256(timestamp.encode("utf-8") + payload).digest()
    try:
        public_key.verify(
            signature_bytes,
            digest,
            ec.ECDSA(utils.Prehashed(hashes.SHA256())),
        )
    except Exception:
        return False, "Invalid SendGrid signature."
    return True, None


@app.route("/webhook/sendgrid", methods=["POST"])
def sendgrid_webhook():
    """
    Handle SendGrid Event Webhook callbacks for bounces and unsubscribes.

    Expected payload is a JSON list of event objects.
    """
    raw_payload = request.get_data(cache=True)
    is_valid, verification_error = _verify_sendgrid_webhook_signature(raw_payload)
    if not is_valid:
        return jsonify({"error": verification_error}), 400

    events = request.get_json(silent=True)
    if not isinstance(events, list):
        return jsonify({"error": "Expected a JSON array of SendGrid events."}), 400

    processed = 0
    matched = 0
    ignored = 0

    for event in events:
        if not isinstance(event, dict):
            ignored += 1
            continue

        event_name = (event.get("event") or "").strip().lower()
        email = (event.get("email") or "").strip().lower()
        reason = (
            event.get("reason")
            or event.get("response")
            or event.get("status")
            or event_name
        )
        if not email:
            ignored += 1
            continue

        if event_name == "bounce":
            matched += _apply_sendgrid_suppression(email, str(reason), "sendgrid_bounce")
            processed += 1
        elif event_name == "dropped":
            matched += _apply_sendgrid_suppression(email, str(reason), "sendgrid_dropped")
            processed += 1
        elif event_name in ("spamreport", "unsubscribe", "group_unsubscribe"):
            matched += _apply_sendgrid_suppression(email, str(reason), "sendgrid_unsubscribe")
            processed += 1
        else:
            ignored += 1

    return jsonify({
        "received": len(events),
        "processed": processed,
        "matched_prospects": matched,
        "ignored": ignored,
    })


# ---------------------------------------------------------------------------
# Import & Fire — bulk lead list → research → email → auto-send or review queue
# ---------------------------------------------------------------------------

_bulk_import_jobs: dict = {}


def _run_research_and_email(
    prospect: dict,
    db_path: str,
    pre_context: dict | None = None,
) -> dict:
    """
    Lightweight pipeline: research (if website present) + email generation.
    Skips PDF to keep bulk runs fast.  Saves a draft to the outreach table
    and returns a result dict with keys:
        prospect_id, company, prospect_email, outreach_id,
        subject, body, error

    pre_context — optional dict of already-known intel about this company.
        Supported keys: niche, icp, website_headline, product_feature,
        competitors, pain_point, growth_signal, hook, notes.
        When provided, the website scrape is skipped and these values are
        saved directly as a research record so the email gen can use them.
    """
    from research_agent import research_prospect

    prospect_id = prospect["id"]
    website     = prospect.get("website", "")

    result = {
        "prospect_id":    prospect_id,
        "company":        prospect.get("company", ""),
        "prospect_email": prospect.get("email") or "",
        "outreach_id":    None,
        "subject":        "",
        "body":           "",
        "error":          "",
    }

    # Research — use pre-provided context if available, otherwise scrape website
    if pre_context:
        try:
            # Persist the caller-supplied intel as a research record
            analysis = {
                "niche":            pre_context.get("niche", ""),
                "icp":              pre_context.get("icp", ""),
                "website_headline": pre_context.get("website_headline", ""),
                "product_feature":  pre_context.get("product_feature", ""),
                "competitors":      pre_context.get("competitors", ""),
                "pain_point":       pre_context.get("pain_point", ""),
                "growth_signal":    pre_context.get("growth_signal", ""),
                "hook":             pre_context.get("hook", ""),
            }
            database.update_enrichment_fields(prospect_id, {
                k: v for k, v in {
                    "niche":            analysis["niche"],
                    "icp":              analysis["icp"],
                    "website_headline": analysis["website_headline"],
                    "product_feature":  analysis["product_feature"],
                    "competitors":      analysis["competitors"],
                }.items() if v
            }, db_path=db_path)
            database.save_research_result(
                prospect_id=prospect_id,
                analysis=analysis,
                url=website or "",
                db_path=db_path,
            )
            # Append to notes so the email template engine picks it up
            if any(analysis.values()):
                extra_notes = (
                    f"[Research Hook]\n"
                    f"Pain Point: {analysis['pain_point']}\n"
                    f"Growth Signal: {analysis['growth_signal']}\n"
                    f"Opener: {analysis['hook']}"
                )
                existing = prospect.get("notes") or ""
                if "[Research Hook]" not in existing:
                    combined = (existing + "\n\n" + extra_notes).strip()
                    database.update_notes(prospect_id, combined, db_path=db_path)
        except Exception as exc:
            result["error"] = f"pre_context save: {exc}"
    elif website:
        try:
            research_prospect(prospect_id, db_path=db_path)
        except Exception as exc:
            result["error"] = f"research: {exc}"

    # Reload from DB so enriched fields are present
    enriched = next(
        (p for p in database.get_all_prospects(db_path=db_path) if p["id"] == prospect_id),
        prospect,
    )

    # Auto-extract email if missing
    if not enriched.get("email") and website:
        extracted = _extract_email_from_website(website)
        if extracted:
            database.update_prospect_email(prospect_id, extracted, db_path=db_path)
            enriched = dict(enriched)
            enriched["email"] = extracted
            result["prospect_email"] = extracted

    # Email generation
    try:
        has_api_key = bool(os.getenv("ANTHROPIC_API_KEY", "").strip())
        if has_api_key:
            from ai_engine import generate_hyper_personalized_email
            email_result = generate_hyper_personalized_email(enriched)
        else:
            email_result = generate_email(enriched)
    except Exception:
        try:
            email_result = generate_email(enriched)
        except Exception as exc:
            result["error"] += f" email: {exc}"
            return result

    result["subject"] = email_result.get("subject", "")
    result["body"]    = email_result.get("body", "")

    # Save as draft in outreach table
    if result["subject"] and result["body"]:
        try:
            result["outreach_id"] = database.save_outreach(
                prospect_id=prospect_id,
                subject=result["subject"],
                body=result["body"],
                db_path=db_path,
            )
        except Exception as exc:
            result["error"] += f" save: {exc}"

    return result


def _bulk_import_worker(job_id: str, leads: list, mode: str, db_path: str) -> None:
    """
    Background thread for import-and-fire jobs.

    mode: "auto_send"  — sends immediately after generation
          "review"     — leaves draft in outreach table for manual approval
    """
    job = _bulk_import_jobs[job_id]
    job["total"] = len(leads)

    for i, lead in enumerate(leads):
        name    = (lead.get("name") or "").strip()
        company = (lead.get("company") or name or "Unknown").strip()
        email   = (lead.get("email") or "").strip().lower()
        website = (lead.get("website") or "").strip()
        phone   = (lead.get("phone") or "").strip()
        linkedin= (lead.get("linkedin_url") or "").strip()

        # Context columns — pre-provided intel skips website scraping
        _ctx_niche    = (lead.get("niche") or lead.get("description") or lead.get("industry") or "").strip()
        _ctx_icp      = (lead.get("icp") or "").strip()
        _ctx_headline = (lead.get("website_headline") or "").strip()
        _ctx_feature  = (lead.get("product_feature") or lead.get("feature") or "").strip()
        _ctx_comp     = (lead.get("competitors") or "").strip()
        _ctx_pain     = (lead.get("pain_point") or lead.get("pain") or "").strip()
        _ctx_signal   = (lead.get("growth_signal") or lead.get("signal") or "").strip()
        _ctx_hook     = (lead.get("hook") or lead.get("value_prop") or "").strip()
        _ctx_notes    = (lead.get("notes") or "").strip()

        # Build pre_context only when the caller supplied at least one intel field
        _has_context = any([_ctx_niche, _ctx_icp, _ctx_headline, _ctx_feature,
                            _ctx_comp, _ctx_pain, _ctx_signal, _ctx_hook])
        pre_context: dict | None = None
        if _has_context:
            pre_context = {
                "niche":            _ctx_niche,
                "icp":              _ctx_icp,
                "website_headline": _ctx_headline,
                "product_feature":  _ctx_feature,
                "competitors":      _ctx_comp,
                "pain_point":       _ctx_pain,
                "growth_signal":    _ctx_signal,
                "hook":             _ctx_hook,
            }

        item = {
            "company":        company,
            "prospect_email": email,
            "action":         "",
            "outreach_id":    None,
            "subject":        "",
            "error":          "",
        }

        try:
            # Add prospect (skip if email already exists)
            existing = database.get_prospect_by_email(email, db_path=db_path) if email else None
            if existing:
                prospect_id = existing["id"]
            else:
                # Merge extra notes from CSV context field into prospect notes
                prospect_notes = _ctx_notes or None
                prospect_id = database.add_prospect(
                    name=name or company,
                    company=company,
                    email=email or None,
                    website=website or None,
                    phone=phone or None,
                    linkedin_url=linkedin or None,
                    notes=prospect_notes,
                    status="new",
                    db_path=db_path,
                )

            prospect = next(
                (p for p in database.get_all_prospects(db_path=db_path) if p["id"] == prospect_id),
                None,
            )
            if not prospect:
                raise RuntimeError("Prospect record not found after insert")

            pipeline_result = _run_research_and_email(prospect, db_path, pre_context=pre_context)
            item.update({
                "prospect_id":    pipeline_result["prospect_id"],
                "prospect_email": pipeline_result["prospect_email"] or email,
                "outreach_id":    pipeline_result["outreach_id"],
                "subject":        pipeline_result["subject"],
                "error":          pipeline_result["error"],
            })

            if pipeline_result["outreach_id"]:
                if mode == "auto_send":
                    to_addr = pipeline_result["prospect_email"]
                    if to_addr:
                        delivery = deliver_prospect_email(
                            to_address=to_addr,
                            subject=pipeline_result["subject"],
                            body=pipeline_result["body"],
                            prospect_id=prospect_id,
                            event_type="outreach_sent",
                            client_id=prospect.get("client_id", 1),
                            db_path=db_path,
                            content_excerpt=pipeline_result["body"][:250],
                            metadata=f"outreach_id={pipeline_result['outreach_id']};recipient={to_addr};source=import_and_fire",
                        )
                        if delivery["sent"]:
                            database.update_outreach_status(
                                pipeline_result["outreach_id"], "sent", db_path=db_path
                            )
                            database.update_status(prospect_id, "in_sequence", db_path=db_path)
                            item["action"] = "sent"
                        else:
                            item["action"] = "send_failed"
                            item["error"]  = delivery["error"]
                    else:
                        item["action"] = "no_email"
                else:
                    item["action"] = "queued"
            else:
                item["action"] = "email_failed"

        except Exception as exc:
            item["error"]  = str(exc)
            item["action"] = "error"

        job["results"].append(item)
        job["progress"] = i + 1

    job["status"] = "done"


@app.route("/api/import-and-fire", methods=["POST"])
def api_import_and_fire():
    """
    Upload a CSV of leads, run research + email gen for each, then either
    send immediately (mode=auto_send) or hold in the review queue (mode=review).

    Form fields:
        file  — CSV file upload (required)
        mode  — "auto_send" | "review"  (default: "review")

    CSV columns (header row required):
        name, company, email, website, phone, linkedin_url
        At minimum one of name/company is required per row.

    Returns: { job_id, status, total, mode }
    """
    import csv
    import io
    import threading as _threading

    uploaded = request.files.get("file")
    if not uploaded:
        return jsonify({"error": "No file uploaded"}), 400

    mode = (request.form.get("mode") or "review").strip()
    if mode not in ("auto_send", "review"):
        mode = "review"

    try:
        content = uploaded.read().decode("utf-8-sig")  # strip BOM if present
        reader  = csv.DictReader(io.StringIO(content))
        leads   = []
        for row in reader:
            # Normalise header casing
            normalised = {k.strip().lower(): (v or "").strip() for k, v in row.items()}
            if not (normalised.get("name") or normalised.get("company")):
                continue
            leads.append(normalised)
    except Exception as exc:
        return jsonify({"error": f"Could not parse CSV: {exc}"}), 400

    if not leads:
        return jsonify({"error": "CSV contained no valid rows"}), 400

    job_id = str(uuid.uuid4())
    _bulk_import_jobs[job_id] = {
        "status":   "running",
        "progress": 0,
        "total":    len(leads),
        "mode":     mode,
        "results":  [],
        "error":    None,
    }

    db_path = database.DB_PATH
    t = _threading.Thread(
        target=_bulk_import_worker,
        args=(job_id, leads, mode, db_path),
        daemon=True,
        name=f"bulk-import-{job_id[:8]}",
    )
    t.start()

    return jsonify({"job_id": job_id, "status": "running", "total": len(leads), "mode": mode})


@app.route("/api/import-and-fire/<job_id>", methods=["GET"])
def api_import_and_fire_status(job_id):
    """Poll the status of a bulk import-and-fire background job."""
    job = _bulk_import_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify({
        "job_id":   job_id,
        "status":   job["status"],
        "progress": job["progress"],
        "total":    job["total"],
        "mode":     job["mode"],
        "results":  job["results"],
        "error":    job["error"],
    })


@app.route("/api/outreach-queue", methods=["GET"])
def api_outreach_queue():
    """Return all draft outreach records waiting for review."""
    client_id = _coerce_operator_client_id(request.args.get("client_id"), 1)
    drafts = database.get_draft_outreach(client_id=client_id, db_path=database.DB_PATH)
    return jsonify(drafts)


@app.route("/api/outreach-queue/<int:outreach_id>/approve", methods=["POST"])
def api_outreach_queue_approve(outreach_id):
    """
    Send a queued draft email and mark it as sent.
    Expects optional JSON body: { "subject": "...", "body": "..." } to allow
    inline edits before sending.
    """
    client_id = _coerce_operator_client_id(request.args.get("client_id"), 1)
    drafts = database.get_draft_outreach(client_id=client_id, db_path=database.DB_PATH)
    record = next((d for d in drafts if d["id"] == outreach_id), None)
    if not record:
        return jsonify({"error": "Draft not found or already processed"}), 404

    to_addr = record.get("prospect_email") or ""
    if not to_addr:
        return jsonify({"error": "No email address on file for this prospect"}), 400

    data    = request.get_json(silent=True) or {}
    subject = (data.get("subject") or record["subject"]).strip()
    body    = (data.get("body")    or record["body"]).strip()

    delivery = deliver_prospect_email(
        to_address=to_addr,
        subject=subject,
        body=body,
        prospect_id=record["prospect_id"],
        event_type="outreach_sent",
        client_id=record.get("client_id", 1),
        db_path=database.DB_PATH,
        content_excerpt=body[:250],
        metadata=f"outreach_id={outreach_id};recipient={to_addr};source=review_queue",
    )
    if not delivery["sent"]:
        return jsonify({"error": delivery['error'] or 'Send failed'}), 500

    database.update_outreach_status(outreach_id, "sent", db_path=database.DB_PATH)
    database.update_status(record["prospect_id"], "in_sequence", db_path=database.DB_PATH)
    return jsonify({"ok": True})


@app.route("/api/outreach-queue/<int:outreach_id>/reject", methods=["POST"])
def api_outreach_queue_reject(outreach_id):
    """Remove a draft from the review queue without sending."""
    client_id = _coerce_operator_client_id(request.args.get("client_id"), 1)
    drafts = database.get_draft_outreach(client_id=client_id, db_path=database.DB_PATH)
    record = next((d for d in drafts if d["id"] == outreach_id), None)
    if not record:
        return jsonify({"error": "Draft not found"}), 404
    deleted = database.delete_outreach(outreach_id, db_path=database.DB_PATH)
    if not deleted:
        return jsonify({"error": "Draft not found"}), 404
    return jsonify({"ok": True})


def _scheduler_enabled() -> bool:
    """
    Return True unless the scheduler has been explicitly disabled.

    Disable via:
      - CLI flag:   python web_app.py --no-scheduler
      - Env var:    SCHEDULER_ENABLED=false
    """
    import sys
    if "--no-scheduler" in sys.argv:
        return False
    env = os.getenv("SCHEDULER_ENABLED", "true").strip().lower()
    return env not in ("false", "0", "no", "off")


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

_ERROR_STYLE = """
<style>
  *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'Outfit',-apple-system,sans-serif;background:#080c14;color:#e2e8f0;
       min-height:100vh;display:flex;align-items:center;justify-content:center;padding:2rem}
  .card{background:#111827;border:1px solid rgba(255,255,255,0.07);border-radius:18px;
        padding:2.75rem 2.25rem;max-width:420px;width:100%;text-align:center}
  .brand{font-size:.8rem;font-weight:700;color:#a78bfa;letter-spacing:.1em;
         text-transform:uppercase;margin-bottom:1.75rem}
  .code{font-size:3rem;font-weight:700;color:#f1f5f9;margin-bottom:.5rem}
  .msg{color:#64748b;font-size:.95rem;line-height:1.6;margin-bottom:1.75rem}
  a{display:inline-block;padding:.7rem 1.5rem;background:linear-gradient(135deg,#7c3aed,#6366f1);
    color:#fff;border-radius:8px;text-decoration:none;font-size:.9rem;font-weight:600}
</style>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;700&display=swap" rel="stylesheet">
"""


@app.route("/unsubscribe")
def unsubscribe():
    """
    One-click unsubscribe. Public — no auth required.
    Verifies an HMAC token then suppresses the prospect and shows a confirmation page.
    """
    _db = database.DB_PATH
    try:
        prospect_id = int(request.args.get("pid", ""))
        client_id   = int(request.args.get("cid", ""))
    except (TypeError, ValueError):
        return render_template("unsubscribe.html", success=False,
                               error="Invalid unsubscribe link.")

    token = request.args.get("token", "").strip()
    if not token or not verify_unsubscribe_token(prospect_id, client_id, token):
        return render_template("unsubscribe.html", success=False,
                               error="Invalid or expired unsubscribe link.")

    prospect = database.get_prospect_by_id(prospect_id, db_path=_db)
    if not prospect or prospect.get("client_id") != client_id:
        # Treat as success to avoid leaking whether the prospect exists
        return render_template("unsubscribe.html", success=True)

    database.suppress_prospect(
        prospect_id,
        reason="one_click_unsubscribe",
        source="unsubscribe_link",
        db_path=_db,
    )
    print(f"[Unsubscribe] prospect {prospect_id} suppressed via one-click link")
    return render_template("unsubscribe.html", success=True)


@app.route("/dev-login/<int:client_id>")
def dev_login(client_id: int):
    """Dev-only shortcut — sets session directly. Blocked if request is not from localhost."""
    remote = request.remote_addr or ""
    if remote not in ("127.0.0.1", "::1", "localhost"):
        return "Not available in production", 403
    session["client_id"] = client_id
    return redirect(url_for("client_dashboard"))


@app.route("/health")
def health():
    """Lightweight health check for load balancers and uptime monitors."""
    return jsonify({"status": "ok", "service": "outreachempower"}), 200


@app.route("/webhook/mailivery", methods=["POST"])
def mailivery_webhook():
    """
    Receive Mailivery event notifications.
    Supported events: campaign.disconnected, campaign.error, health_score.updated.
    """
    secret = os.getenv("MAILIVERY_WEBHOOK_SECRET", "").strip()
    provided = (
        request.headers.get("X-Mailivery-Webhook-Secret", "")
        or request.headers.get("X-Webhook-Secret", "")
    ).strip()
    auth_header = request.headers.get("Authorization", "").strip()
    if auth_header.lower().startswith("bearer "):
        provided = auth_header[7:].strip()
    if not secret or not provided or not hmac.compare_digest(secret, provided):
        return jsonify({"error": "unauthorized"}), 401

    payload = request.get_json(silent=True) or {}
    event    = payload.get("event", "")
    data     = payload.get("data", {})
    email    = (data.get("email") or "").strip().lower()

    import logging as _logging
    _logging.getLogger("mailivery_webhook").info("[Mailivery webhook] event=%s data=%s", event, data)

    if email and event in ("campaign.disconnected", "campaign.error", "health_score.updated"):
        _db = database.DB_PATH
        client = database.get_client_by_email(email, db_path=_db)
        if client:
            if event == "health_score.updated":
                score = data.get("health_score")
                if score is not None:
                    database.update_client(client["id"], mailivery_health_score=int(score), db_path=_db)
            elif event == "campaign.disconnected":
                database.clear_client_mailivery_campaign(client["id"], db_path=_db)

    return jsonify({"ok": True})


@app.errorhandler(404)
def not_found(_e):
    return (
        f"<!doctype html><html><head><title>Not found</title>{_ERROR_STYLE}</head>"
        f"<body><div class='card'><div class='brand'>OutreachEmpower</div>"
        f"<div class='code'>404</div>"
        f"<p class='msg'>This page doesn't exist.</p>"
        f"<a href='/'>Go home</a></div></body></html>"
    ), 404


@app.errorhandler(500)
def server_error(_e):
    return (
        f"<!doctype html><html><head><title>Server error</title>{_ERROR_STYLE}</head>"
        f"<body><div class='card'><div class='brand'>OutreachEmpower</div>"
        f"<div class='code'>500</div>"
        f"<p class='msg'>Something went wrong on our end. We're on it.</p>"
        f"<a href='/'>Go home</a></div></body></html>"
    ), 500


if __name__ == "__main__":
    import threading
    if _scheduler_enabled():
        t = threading.Thread(target=_background_scheduler, daemon=True, name="bg-scheduler")
        t.start()
        print("[Startup] Background scheduler started.")
    else:
        print("[Startup] Scheduler disabled (--no-scheduler or SCHEDULER_ENABLED=false).")
    debug = os.getenv("FLASK_DEBUG", "false").strip().lower() in ("1", "true", "yes")
    port  = int(os.getenv("PORT", "5000"))
    app.run(debug=debug, port=port, use_reloader=False)
