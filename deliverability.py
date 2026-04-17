"""
deliverability.py
=================
Shared outbound email decision layer.

Centralizes suppression enforcement, SMTP/SendGrid routing, failure mapping,
and communication-event logging so all outbound email paths behave consistently.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Callable

import database
from mailer import send_email as _smtp_send_email
from settings import get_use_sendgrid, get_secret_key, get_app_base_url


SendCallable = Callable[..., tuple[bool, str]]

# ---------------------------------------------------------------------------
# Unsubscribe token helpers
# ---------------------------------------------------------------------------

def _make_unsubscribe_token(prospect_id: int, client_id: int) -> str:
    """Return a deterministic HMAC token for the given prospect/client pair."""
    key = get_secret_key().encode()
    msg = f"{prospect_id}:{client_id}".encode()
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def make_unsubscribe_url(prospect_id: int, client_id: int, base_url: str = "") -> str:
    """Return the full one-click unsubscribe URL for a prospect."""
    token = _make_unsubscribe_token(prospect_id, client_id)
    root  = (base_url or get_app_base_url()).rstrip("/")
    return f"{root}/unsubscribe?pid={prospect_id}&cid={client_id}&token={token}"


def verify_unsubscribe_token(prospect_id: int, client_id: int, token: str) -> bool:
    """Return True if the token matches the expected HMAC for this prospect."""
    expected = _make_unsubscribe_token(prospect_id, client_id)
    return hmac.compare_digest(expected, token)


def _get_send_callable() -> tuple[str, SendCallable]:
    """Return the active email provider name and send function."""
    if get_use_sendgrid():
        from sendgrid_mailer import send_email as sg_send

        return "sendgrid", sg_send

    return "smtp", _smtp_send_email


def classify_delivery_failure(error: str) -> str:
    """Map a raw provider error string to a normalized delivery outcome."""
    text = (error or "").strip().lower()
    if not text:
        return "transient_send_error"
    if "recipient refused" in text:
        return "invalid_recipient"
    if "authentication failed" in text or "missing .env keys" in text:
        return "auth_or_config_error"
    return "transient_send_error"


def route_outbound_email(
    to_address: str,
    subject: str,
    body: str,
    *,
    attachment_path: str = "",
    in_reply_to: str = "",
    references: str = "",
    respect_suppression: bool = True,
    db_path: str = database.DB_PATH,
    client_id: int = 1,
    html_body: str = "",
) -> tuple[bool, str]:
    """
    Compatibility wrapper used by existing callers that only need (ok, err).
    """
    normalized = (to_address or "").strip().lower()
    if respect_suppression and database.is_suppressed(normalized, db_path=db_path, client_id=client_id):
        return False, "Recipient is suppressed (suppressed_skip)."

    sender_name, sender_email = _resolve_sender_identity(client_id, db_path)
    _, send_callable = _get_send_callable()
    return send_callable(
        normalized,
        subject,
        body,
        from_address=sender_email,
        from_name=sender_name,
        attachment_path=attachment_path,
        in_reply_to=in_reply_to,
        references=references,
        html_body=html_body,
    )


def _compose_metadata(*parts: str) -> str:
    """Join non-empty metadata fragments with semicolons."""
    return ";".join(part for part in parts if part)


def _resolve_sender_identity(client_id: int, db_path: str) -> tuple[str, str]:
    """
    Return (sender_name, sender_email) for the given client workspace.

    Custom sender_email is only used when the client has verified ownership.
    Unverified addresses fall back to the system SMTP_USER so sends don't break.
    """
    import os

    client = database.get_client(client_id, db_path=db_path) if client_id else None
    sender_name = ((client or {}).get("sender_name") or os.getenv("SENDER_NAME") or "").strip()

    custom_email = ((client or {}).get("sender_email") or "").strip().lower()
    verified = bool((client or {}).get("sender_email_verified"))
    if custom_email and verified:
        sender_email = custom_email
    else:
        sender_email = (os.getenv("SMTP_USER") or "").strip().lower()

    return sender_name, sender_email


def deliver_prospect_email(
    *,
    to_address: str,
    subject: str,
    body: str,
    prospect_id: int | None,
    event_type: str,
    client_id: int = 1,
    db_path: str = database.DB_PATH,
    content_excerpt: str = "",
    metadata: str = "",
    attachment_path: str = "",
    in_reply_to: str = "",
    references: str = "",
    send_callable: SendCallable | None = None,
) -> dict:
    """
    Deliver a prospect-facing email with suppression and failure handling.

    Returns a dict with:
      sent, error, outcome, event_status, provider
    """
    normalized = (to_address or "").strip().lower()
    provider_name = "custom" if send_callable else _get_send_callable()[0]
    sender = send_callable or _get_send_callable()[1]
    sender_name, sender_email = _resolve_sender_identity(client_id, db_path)

    # Build unsubscribe URL when we have a real prospect to suppress
    unsubscribe_url = ""
    if prospect_id is not None:
        unsubscribe_url = make_unsubscribe_url(prospect_id, client_id)

    # Append one-click unsubscribe footer to the body
    if unsubscribe_url:
        body = body.rstrip() + f"\n\n---\nTo unsubscribe: {unsubscribe_url}"

    result = {
        "sent": False,
        "error": "",
        "outcome": "",
        "event_status": "failed",
        "provider": provider_name,
    }

    if database.is_suppressed(normalized, db_path=db_path, client_id=client_id):
        result["error"] = "Recipient is suppressed."
        result["outcome"] = "suppressed_skip"
        result["event_status"] = "skipped"
    else:
        ok, err = sender(
            normalized,
            subject,
            body,
            from_address=sender_email,
            from_name=sender_name,
            attachment_path=attachment_path,
            in_reply_to=in_reply_to,
            references=references,
            list_unsubscribe=unsubscribe_url,
        )
        result["sent"] = ok
        result["error"] = err
        if ok:
            result["outcome"] = "sent"
            result["event_status"] = "sent"
        else:
            result["outcome"] = classify_delivery_failure(err)
            result["event_status"] = "failed"

            if result["outcome"] == "invalid_recipient":
                if prospect_id:
                    database.suppress_prospect(
                        prospect_id,
                        reason="invalid_recipient_bounce",
                        source="deliverability",
                        db_path=db_path,
                    )
                elif normalized:
                    database.suppress_contact(
                        normalized,
                        reason="invalid_recipient_bounce",
                        source="deliverability",
                        db_path=db_path,
                        client_id=client_id,
                    )

    if prospect_id is not None:
        delivery_meta = _compose_metadata(
            metadata,
            f"provider={result['provider']}",
            f"delivery_outcome={result['outcome']}",
            f"detail={result['error']}" if result["error"] else "",
        )
        database.log_communication_event(
            prospect_id=prospect_id,
            channel="email",
            direction="outbound",
            event_type=event_type,
            status=result["event_status"],
            content_excerpt=(content_excerpt or subject)[:250],
            metadata=delivery_meta,
            client_id=client_id,
            db_path=db_path,
        )

    return result
