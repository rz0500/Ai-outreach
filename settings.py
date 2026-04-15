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
