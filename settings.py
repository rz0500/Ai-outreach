"""
settings.py
===========
Runtime settings helpers loaded from environment variables.
All helpers return typed values with sensible defaults.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


DEFAULT_CALENDAR_LINK = "https://calendly.com/leadgenai/30min"


def get_calendar_link() -> str:
    """Return the configured booking link used across emails and PDFs."""
    return (os.getenv("CALENDAR_LINK") or DEFAULT_CALENDAR_LINK).strip()


def get_sender_name() -> str:
    """Return the sender's first name used in email sign-offs."""
    return (os.getenv("SENDER_NAME") or "Alex").strip()


def get_inbox_poll_interval() -> int:
    """
    Return how often (in seconds) the background scheduler checks the inbox.
    Minimum 60 s, default 300 s (5 minutes).
    """
    raw = os.getenv("INBOX_POLL_INTERVAL", "300")
    try:
        val = int(raw)
    except ValueError:
        val = 300
    return max(60, val)


def get_imap_max_messages_per_poll() -> int:
    """
    Return how many unread IMAP messages to process in one polling cycle.
    Minimum 1, default 25.
    """
    raw = os.getenv("IMAP_MAX_MESSAGES_PER_POLL", "25")
    try:
        val = int(raw)
    except ValueError:
        val = 25
    return max(1, val)


def get_sequence_run_hour() -> int:
    """
    Return the hour of day (0-23, UTC) at which the sequence dispatcher runs.
    Default: 9 (09:00 UTC).
    """
    raw = os.getenv("SEQUENCE_RUN_HOUR", "9")
    try:
        val = int(raw)
    except ValueError:
        val = 9
    return max(0, min(23, val))


def get_use_sendgrid() -> bool:
    """Return True if SendGrid should be used for outbound email delivery."""
    return os.getenv("USE_SENDGRID", "false").strip().lower() in ("1", "true", "yes")


def get_linkedin_dry_run() -> bool:
    """Return True if LinkedIn outreach should run in dry-run (no real sends) mode."""
    return os.getenv("LINKEDIN_DRY_RUN", "true").strip().lower() not in ("0", "false", "no")


# ---------------------------------------------------------------------------
# Self-prospecting (autonomous lead discovery for house account)
# ---------------------------------------------------------------------------

def get_self_prospect_niche() -> str:
    """Niche/query to search Google Maps for as self-prospecting targets."""
    return (os.getenv("SELF_PROSPECT_NICHE") or "").strip()


def get_self_prospect_location() -> str:
    """Location string passed to Google Maps self-prospecting search."""
    return (os.getenv("SELF_PROSPECT_LOCATION") or "").strip()


def get_self_prospect_daily_limit() -> int:
    """Max new prospects to add per self-prospecting run. Default 5, minimum 1."""
    raw = os.getenv("SELF_PROSPECT_DAILY_LIMIT", "5")
    try:
        val = int(raw)
    except ValueError:
        val = 5
    return max(1, val)


def get_self_prospect_run_hour() -> int:
    """
    Hour of day (0-23, UTC) at which autonomous self-prospecting runs.
    Default: 7 (07:00 UTC), runs before the sequence dispatch hour.
    """
    raw = os.getenv("SELF_PROSPECT_RUN_HOUR", "7")
    try:
        val = int(raw)
    except ValueError:
        val = 7
    return max(0, min(23, val))


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

def get_secret_key() -> str:
    """Return the Flask session secret key. Falls back to a fixed dev default."""
    return (os.getenv("SECRET_KEY") or "dev-secret-change-in-production").strip()


def get_app_base_url() -> str:
    """
    Return the public base URL for this deployment (no trailing slash).
    Used to generate absolute URLs (e.g. unsubscribe links) in background threads
    that don't have a Flask request context.
    Defaults to http://localhost:5000 when APP_BASE_URL is not set.
    """
    raw = (os.getenv("APP_BASE_URL") or "http://localhost:5000").strip().rstrip("/")
    return raw


# ---------------------------------------------------------------------------
# Email warmup
# ---------------------------------------------------------------------------

def get_warmup_start_date() -> str:
    """
    ISO date (YYYY-MM-DD) when warmup started. Used to compute the current
    ramp tier. Empty string means warmup is not yet configured.
    """
    return (os.getenv("WARMUP_START_DATE") or "").strip()


def get_warmup_addresses() -> list[str]:
    """
    Comma-separated list of warmup partner email addresses.
    The warmup engine sends short emails to these and auto-replies when they land.
    """
    raw = os.getenv("WARMUP_ADDRESSES", "").strip()
    return [a.strip() for a in raw.split(",") if a.strip()]


def get_warmup_emails_per_cycle() -> int:
    """How many warmup emails to send per scheduler cycle. Default 3."""
    raw = os.getenv("WARMUP_EMAILS_PER_CYCLE", "3")
    try:
        val = int(raw)
    except ValueError:
        val = 3
    return max(1, val)


def get_max_real_sends_override() -> int:
    """
    Hard cap for real outreach sends per day, bypassing the ramp schedule.
    0 = use the ramp schedule automatically. Set this to override.
    """
    raw = os.getenv("MAX_DAILY_SENDS", "0")
    try:
        val = int(raw)
    except ValueError:
        val = 0
    return max(0, val)


# ---------------------------------------------------------------------------
# Mailivery external warmup
# ---------------------------------------------------------------------------

def get_mailivery_api_key() -> str:
    """Return the Mailivery API key, or empty string if not configured."""
    return os.getenv("MAILIVERY_API_KEY", "").strip()


def get_mailivery_enabled() -> bool:
    """Return True if Mailivery warmup integration is enabled."""
    return os.getenv("MAILIVERY_ENABLED", "false").strip().lower() in ("1", "true", "yes")


def get_operator_email() -> str:
    """Return the operator notification email address (receives lead alerts and daily reports)."""
    return (os.getenv("OPERATOR_EMAIL") or "").strip()
