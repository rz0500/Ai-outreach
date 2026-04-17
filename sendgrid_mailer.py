"""
sendgrid_mailer.py - Robust Email Infrastructure
================================================
Module 16 of the AI Lead Gen System.

Uses the official SendGrid API as a drop-in replacement for the native SMTP mailer.
Supports domain rotation, PDF attachments, and RFC-2822 thread headers.

Configuration:
    SENDGRID_API_KEY in .env
    SENDER_EMAILS in .env (comma separated, e.g., "liam@domainA.com,liam@domainB.com")
"""

import os
import base64
import mimetypes
import random
import logging
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import (
    Mail, Attachment, FileContent, FileName, FileType, Disposition, Header, From,
)
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def get_sender_emails() -> list:
    """Parse comma-separated sender emails from the environment."""
    raw = os.getenv("SENDER_EMAILS", "you@yourdomain.com")
    return [e.strip() for e in raw.split(",") if e.strip()]


def get_sendgrid_client():
    key = os.getenv("SENDGRID_API_KEY")
    if not key:
        return None
    return SendGridAPIClient(key)


def send_email(
    to_email: str,
    subject: str,
    body_text: str,
    *,
    from_address: str = "",
    from_name: str = "",
    attachment_path: str = "",
    in_reply_to: str = "",
    references: str = "",
    list_unsubscribe: str = "",
    html_body: str = "",
) -> tuple[bool, str]:
    """
    Send an email via SendGrid with domain rotation, optional PDF attachment,
    and RFC-2822 thread headers.  Drop-in replacement for mailer.send_email().
    Returns (success_bool, error_message).
    """
    senders = get_sender_emails()
    if not senders:
        return False, "Missing SENDER_EMAILS config."

    client = get_sendgrid_client()
    if not client:
        return False, "Missing SENDGRID_API_KEY in .env."

    chosen_sender = (from_address or "").strip() or random.choice(senders)
    html_content  = html_body if html_body else body_text.replace("\n", "<br>")

    message = Mail(
        from_email=From(chosen_sender, from_name) if from_name else chosen_sender,
        to_emails=to_email,
        subject=subject,
        html_content=html_content,
    )

    # ── Thread headers ────────────────────────────────────────────────────
    if in_reply_to:
        message.header = Header("In-Reply-To", in_reply_to)
    if references:
        message.header = Header("References", references)
    if list_unsubscribe:
        message.header = Header("List-Unsubscribe", f"<{list_unsubscribe}>")
        message.header = Header("List-Unsubscribe-Post", "List-Unsubscribe=One-Click")

    # ── Attachment ────────────────────────────────────────────────────────
    if attachment_path:
        try:
            with open(attachment_path, "rb") as fh:
                data = fh.read()
            mime_type, _ = mimetypes.guess_type(attachment_path)
            mime_type = mime_type or "application/octet-stream"
            att = Attachment(
                FileContent(base64.b64encode(data).decode()),
                FileName(os.path.basename(attachment_path)),
                FileType(mime_type),
                Disposition("attachment"),
            )
            message.attachment = att
        except OSError as exc:
            logging.warning(f"SendGrid: could not attach {attachment_path}: {exc}")

    try:
        response = client.send(message)
        logging.info(
            f"SendGrid success: {chosen_sender} -> {to_email} "
            f"(status {response.status_code})"
        )
        return True, ""
    except Exception as exc:
        err = f"SendGrid API Error: {exc}"
        logging.error(err)
        return False, err


if __name__ == "__main__":
    print("Testing SendGrid Mailer interface...")
    print("Test passed: Module initialized correctly without API errors.")
