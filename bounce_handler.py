"""
bounce_handler.py - Detect delivery-failure notices and act on hard bounces.

Many mail servers accept a message and only later send a bounce notice
("Failure Notice", "Undelivered Mail Returned to Sender") to the sending
mailbox. Repeatedly emailing addresses that hard-bounce damages a small
mailbox's reputation, so a hard bounce suppresses the prospect, pauses the
follow-up sequence and cancels anything still queued for that address.
Temporary failures (mailbox full, try again later) are ignored.
"""

from __future__ import annotations

import logging
import re
from email.message import Message

import database

logger = logging.getLogger(__name__)

_SYSTEM_LOCALS = {"mailer-daemon", "postmaster"}
_BOUNCE_SUBJECT_RE = re.compile(
    r"failure notice|undeliver|delivery status notification|delivery failure|"
    r"returned mail|mail delivery (failed|system)|could not be delivered|message not delivered",
    re.IGNORECASE,
)
_HARD_TEXT_RE = re.compile(
    r"\b(550|551|553|554)\b|user unknown|no such user|does not exist|unknown user|"
    r"mailbox (unavailable|not found)|address rejected|invalid (recipient|address)|"
    r"recipient (address )?rejected|account (is )?disabled|no mailbox here|"
    r"domain (not found|does not exist)|host or domain name not found",
    re.IGNORECASE,
)
_RECIPIENT_RE = re.compile(r"(?:Final|Original)-Recipient:\s*rfc822;\s*<?([^\s>;]+)", re.IGNORECASE)
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")


def is_bounce(msg: Message, sender_email: str, subject: str) -> bool:
    """True for delivery-failure notices (RFC 3464 reports and plain MTA bounces)."""
    if msg.get_content_maintype() == "multipart" and msg.get_content_subtype() == "report":
        report_type = (msg.get_param("report-type") or "").lower()
        return report_type in ("", "delivery-status")
    local = (sender_email or "").partition("@")[0].lower()
    return local in _SYSTEM_LOCALS and bool(_BOUNCE_SUBJECT_RE.search(subject or ""))


def _collect_text(msg: Message) -> str:
    parts: list[str] = []
    for part in msg.walk():
        content_type = part.get_content_type()
        if content_type == "message/delivery-status":
            payload = part.get_payload()
            if isinstance(payload, list):
                parts.extend(str(sub) for sub in payload)
            else:
                parts.append(str(payload))
        elif part.get_content_maintype() == "text" and content_type != "text/rfc822-headers":
            raw = part.get_payload(decode=True)
            if raw:
                parts.append(raw.decode(part.get_content_charset() or "utf-8", errors="replace"))
    return "\n".join(parts)


def parse_bounce(msg: Message) -> dict:
    """
    Interpret a bounce: {'hard': bool, 'recipients': [addresses], 'detail': str}.
    Only permanent failures (status 5.x.x / clear "no such user" text) are hard.
    """
    text = _collect_text(msg)

    recipients: list[str] = []
    for found in _RECIPIENT_RE.findall(text):
        addr = found.strip().lower()
        if addr not in recipients:
            recipients.append(addr)
    if not recipients:
        for found in _EMAIL_RE.findall(text):
            addr = found.lower()
            local = addr.partition("@")[0]
            if local not in _SYSTEM_LOCALS and addr not in recipients:
                recipients.append(addr)

    action = (re.search(r"^Action:\s*(\w+)", text, re.IGNORECASE | re.MULTILINE) or [None, ""])[1].lower()
    status = re.search(r"^Status:\s*([245])\.\d+\.\d+", text, re.IGNORECASE | re.MULTILINE)

    if action in ("delivered", "relayed", "expanded"):
        hard = False                      # a success/relay notice, not a failure
    elif action == "delayed":
        hard = False
    elif status:
        hard = status.group(1) == "5"
    else:
        hard = bool(_HARD_TEXT_RE.search(text))

    first_line = next((ln.strip() for ln in text.splitlines() if _HARD_TEXT_RE.search(ln)), "")
    return {"hard": hard, "recipients": recipients if hard else [], "detail": first_line[:200]}


def process_bounce(msg: Message, db_path: str | None = None) -> int:
    """
    Apply a bounce notice: suppress each hard-bounced prospect, pause their
    sequence and cancel queued emails. Returns how many prospects were suppressed.
    """
    db_path = db_path or database.DB_PATH
    info = parse_bounce(msg)
    if not info["hard"]:
        logger.info("[Bounce] temporary or non-failure notice ignored")
        return 0

    suppressed = 0
    for address in info["recipients"]:
        prospect = database.get_prospect_by_email(address, db_path=db_path)
        if not prospect or prospect.get("status") in ("replied", "booked", "rejected"):
            # unknown address, someone who answered us (address works), or already handled
            continue
        database.suppress_prospect(
            prospect["id"], reason="hard_bounce", source="bounce_handler", db_path=db_path
        )
        database.update_sequence_enrollment_status(
            prospect["id"], "paused", paused_reason="hard_bounce", db_path=db_path
        )
        database.skip_pending_outreach(prospect["id"], db_path=db_path)
        database.log_communication_event(
            prospect["id"], "email", "inbound", "bounce", "received",
            content_excerpt=info["detail"] or "hard bounce",
            metadata="hard_bounce", db_path=db_path,
        )
        logger.info("[Bounce] suppressed %s after a hard bounce", address)
        suppressed += 1
    return suppressed
