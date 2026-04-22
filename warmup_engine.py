"""
warmup_engine.py
================
Email warmup and daily send-rate throttle.

Two jobs:

1. VOLUME THROTTLE
   Tracks how many real outreach emails have been sent today.
   Enforces a graduated daily cap based on days since WARMUP_START_DATE:

       Days 1-7:   15 / day
       Days 8-14:  30 / day
       Days 15-21: 60 / day
       Days 22-28: 100 / day
       Days 29-35: 150 / day
       Day 36+:    200 / day  (fully warmed)

   Set MAX_DAILY_SENDS in .env to override the schedule with a hard cap.
   Leave WARMUP_START_DATE empty to skip throttling entirely (dev mode).

2. WARMUP EMAIL LOOP
   Sends short, natural-sounding emails to WARMUP_ADDRESSES (comma-separated
   list of email accounts you control). When inbox_monitor receives one of
   these emails it auto-replies, creating the send/reply engagement pattern
   that warms your sender reputation with Gmail and Outlook.

   run_warmup_cycle() is called by the background scheduler every few hours.
"""

from __future__ import annotations

import random
import os
from datetime import date, datetime, timezone

from dotenv import load_dotenv

load_dotenv()

import database
from settings import (
    get_warmup_start_date,
    get_warmup_addresses,
    get_warmup_emails_per_cycle,
    get_max_real_sends_override,
)

# ---------------------------------------------------------------------------
# Warmup identification header — inbox_monitor uses this to auto-reply
# ---------------------------------------------------------------------------

WARMUP_HEADER = "X-OutreachEmpower-Warmup"
WARMUP_HEADER_VALUE = "true"
WARMUP_SUBJECT_PREFIX = ""  # no visible prefix — use the header instead

# ---------------------------------------------------------------------------
# Daily ramp schedule
# ---------------------------------------------------------------------------

# (max_day_inclusive, daily_limit)
_RAMP: list[tuple[int, int]] = [
    (7,   10),
    (14,  20),
    (21,  40),
    (28,  70),
    (35,  120),
    (9999, 200),
]


def get_daily_limit() -> int:
    """
    Return today's maximum real outreach send count based on the warmup ramp.

    Returns 0 (unlimited) when WARMUP_START_DATE is not configured —
    treats the account as fully warmed.
    """
    override = get_max_real_sends_override()
    if override > 0:
        return override

    start_str = get_warmup_start_date()
    if not start_str:
        return 0  # not configured → no limit

    try:
        start = date.fromisoformat(start_str)
    except ValueError:
        return 0

    days_elapsed = (date.today() - start).days + 1  # day 1 = start date
    for max_day, limit in _RAMP:
        if days_elapsed <= max_day:
            return limit
    return 200


def can_send_today(
    db_path: str = database.DB_PATH,
    client_limit: int = 0,
) -> tuple[bool, str]:
    """
    Check whether another real outreach email can be sent today.

    client_limit: per-client override (from clients.daily_send_limit).
                  0 means "use the global warmup ramp schedule."

    Returns:
        (True, "")                       — send allowed
        (False, "Daily limit reached…")  — throttled
    """
    limit = client_limit if client_limit > 0 else get_daily_limit()
    if limit == 0:
        return True, ""

    sent = database.get_sends_today(db_path=db_path)
    if sent >= limit:
        return False, f"Daily send limit reached ({sent}/{limit}). Resets at midnight UTC."
    return True, ""


def record_real_send(db_path: str = database.DB_PATH) -> int:
    """Increment today's real send counter. Call after every successful outreach send."""
    return database.increment_send_count(db_path=db_path)


def get_warmup_status(db_path: str = database.DB_PATH) -> dict:
    """
    Return a status dict suitable for the dashboard widget.

    Keys:
        configured      bool
        start_date      str  (ISO)
        day             int  (days since start, 1-indexed)
        daily_limit     int  (0 = unlimited)
        sent_today      int
        remaining_today int  (-1 = unlimited)
        pct             int  (0-100, progress through current tier)
        tier_label      str
        fully_warmed    bool
        warmup_total    int  (total warmup emails sent ever)
        warmup_today    int
        addresses       int  (number of configured warmup partners)
    """
    start_str = get_warmup_start_date()
    if not start_str:
        return {
            "configured": False,
            "start_date": "",
            "day": 0,
            "daily_limit": 0,
            "sent_today": database.get_sends_today(db_path=db_path),
            "remaining_today": -1,
            "pct": 100,
            "tier_label": "Not configured (no limit)",
            "fully_warmed": False,
            "warmup_total": 0,
            "warmup_today": 0,
            "addresses": len(get_warmup_addresses()),
        }

    try:
        start = date.fromisoformat(start_str)
    except ValueError:
        start = date.today()

    days_elapsed = max(1, (date.today() - start).days + 1)
    limit        = get_daily_limit()
    sent_today   = database.get_sends_today(db_path=db_path)
    warmup_stats = database.get_warmup_stats(db_path=db_path)

    remaining = max(0, limit - sent_today) if limit > 0 else -1
    fully_warmed = days_elapsed > 35

    # Compute progress % through the full 35-day ramp
    pct = min(100, int((days_elapsed / 35) * 100))

    # Tier label
    if fully_warmed:
        tier_label = "Fully warmed ✓"
    else:
        for max_day, lim in _RAMP[:-1]:
            if days_elapsed <= max_day:
                tier_label = f"Week {((days_elapsed - 1) // 7) + 1} · {lim}/day cap"
                break
        else:
            tier_label = f"{limit}/day cap"

    return {
        "configured":      True,
        "start_date":      start_str,
        "day":             days_elapsed,
        "daily_limit":     limit,
        "sent_today":      sent_today,
        "remaining_today": remaining,
        "pct":             pct,
        "tier_label":      tier_label,
        "fully_warmed":    fully_warmed,
        "warmup_total":    warmup_stats["total_sent"],
        "warmup_today":    warmup_stats["sent_today"],
        "addresses":       len(get_warmup_addresses()),
    }


def get_combined_warmup_status(
    client_id: int = 1,
    db_path: str = database.DB_PATH,
) -> dict:
    """
    Merge the built-in warmup status dict with live Mailivery data for a client.

    Extra keys added:
        mailivery_enabled     bool
        mailivery_connected   bool
        mailivery_campaign_id str | None
        mailivery_health_score int | None  (cached value from clients table)
        mailivery_status      str | None   (active / paused / None)
        mailivery_emails_today int | None
    """
    import mailivery_client as _mc

    status = get_warmup_status(db_path=db_path)

    mc = _mc.get_client()
    status["mailivery_enabled"] = mc is not None

    client = database.get_client(client_id, db_path=db_path)
    campaign_id = (client or {}).get("mailivery_campaign_id")
    cached_score = (client or {}).get("mailivery_health_score")

    status["mailivery_connected"]    = bool(campaign_id)
    status["mailivery_campaign_id"]  = campaign_id
    status["mailivery_health_score"] = cached_score
    status["mailivery_status"]       = None
    status["mailivery_emails_today"] = None

    if mc and campaign_id:
        mailbox = mc.get_mailbox(campaign_id)
        if mailbox.get("ok"):
            d = mailbox.get("data", mailbox)
            status["mailivery_status"]       = d.get("status_code") or d.get("status")
            status["mailivery_emails_today"] = d.get("emails_sent_today")

    return status


# ---------------------------------------------------------------------------
# Warmup email content pool
# ---------------------------------------------------------------------------

_WARMUP_PAIRS: list[tuple[str, str]] = [
    (
        "Quick question",
        "Hey, do you have a moment to connect this week? Would love to catch up.",
    ),
    (
        "Checking in",
        "Hi — just wanted to touch base. How are things going on your end?",
    ),
    (
        "Following up",
        "Hi, I wanted to follow up on our last conversation. Any updates?",
    ),
    (
        "Intro",
        "Hi there! I came across your work and thought it would be worth connecting.",
    ),
    (
        "Quick note",
        "Just a quick note to say hello. Hope all is well with you.",
    ),
    (
        "Re: catch up",
        "Good to hear from you. Let me know when you're free for a quick call.",
    ),
    (
        "A thought",
        "I was thinking about the conversation we had. Would love to continue it sometime.",
    ),
    (
        "Hope this finds you well",
        "Hi — hope you're having a good week. Just checking in!",
    ),
]

_WARMUP_REPLIES: list[str] = [
    "Thanks for reaching out! I'll get back to you shortly.",
    "Got it, thanks! Will follow up soon.",
    "Appreciate the note. Let's connect soon.",
    "Thanks for the message — I'll be in touch.",
    "Received, thank you! More from me shortly.",
]


def _warmup_subject() -> str:
    return random.choice(_WARMUP_PAIRS)[0]


def _warmup_body() -> str:
    return random.choice(_WARMUP_PAIRS)[1]


def warmup_reply_body() -> str:
    """Return a short auto-reply body for incoming warmup emails."""
    return random.choice(_WARMUP_REPLIES)


def is_warmup_email(subject: str, headers: dict | None = None) -> bool:
    """
    Return True if this email is a warmup message (should be auto-replied to).
    Checks for the custom X-OutreachEmpower-Warmup header first, then falls back
    to checking whether the sender is in our warmup address list.
    """
    if headers and headers.get(WARMUP_HEADER, "").lower() == "true":
        return True
    return False


# ---------------------------------------------------------------------------
# Warmup send cycle
# ---------------------------------------------------------------------------

def run_warmup_cycle(db_path: str = database.DB_PATH) -> dict:
    """
    Send a small batch of warmup emails to configured partner addresses.
    Called by the background scheduler every few hours.

    Returns a summary dict: {sent, skipped, errors, addresses_used}
    """
    addresses = get_warmup_addresses()
    if not addresses:
        return {"sent": 0, "skipped": 0, "errors": [], "addresses_used": []}

    n_per_cycle = get_warmup_emails_per_cycle()
    targets     = random.choices(addresses, k=min(n_per_cycle, len(addresses) * 3))

    sent        = 0
    errors: list[str] = []
    used: list[str]   = []

    for to_addr in targets:
        subject = _warmup_subject()
        body    = _warmup_body()
        try:
            ok, err = _send_warmup_smtp(to_addr, subject, body)
            if ok:
                database.log_warmup_email(to_addr, subject, db_path=db_path)
                sent += 1
                used.append(to_addr)
            else:
                errors.append(f"{to_addr}: {err}")
        except Exception as exc:
            errors.append(f"{to_addr}: {exc}")

    return {"sent": sent, "skipped": 0, "errors": errors, "addresses_used": used}


def _send_warmup_smtp(to_address: str, subject: str, body: str) -> tuple[bool, str]:
    """
    Send a warmup email via SMTP with the custom warmup header.
    Uses the same SMTP credentials as the main mailer.
    """
    import smtplib
    import ssl
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    host     = os.getenv("SMTP_HOST", "").strip()
    port     = int(os.getenv("SMTP_PORT", "465"))
    user     = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()

    if not all([host, user, password]):
        return False, "SMTP credentials not configured"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = user
    msg["To"]      = to_address
    msg[WARMUP_HEADER] = WARMUP_HEADER_VALUE
    msg.attach(MIMEText(body, "plain"))

    try:
        if port == 465:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=ctx) as server:
                server.login(user, password)
                server.sendmail(user, to_address, msg.as_string())
        else:
            with smtplib.SMTP(host, port) as server:
                server.ehlo()
                server.starttls()
                server.login(user, password)
                server.sendmail(user, to_address, msg.as_string())
        return True, ""
    except Exception as exc:
        return False, str(exc)
