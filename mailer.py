"""
mailer.py - SMTP Email Sender
==============================
Module 7 of the AI Lead Generation & Outreach System.

Sends emails via SMTP using credentials loaded from a .env file.
Wraps Python's built-in smtplib so no extra mail library is needed.

Required .env keys:
    SMTP_HOST      - e.g. smtp.gmail.com
    SMTP_PORT      - e.g. 465 (SSL) or 587 (STARTTLS)
    SMTP_USER      - your sender email address
    SMTP_PASSWORD  - your app password (not your account password)

Usage:
    from mailer import send_email

    ok, err = send_email(
        to_address="prospect@example.com",
        subject="Quick idea for Acme",
        body="Hi Jane, ...",
    )
    if not ok:
        print(f"Send failed: {err}")
"""

import os
import smtplib
import ssl
from email.utils import formataddr
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

load_dotenv()

SMTP_HOST     = os.getenv("SMTP_HOST", "")
SMTP_PORT     = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER     = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def send_email(
    to_address: str,
    subject: str,
    body: str,
    from_address: str = SMTP_USER,
    from_name: str = "",
    in_reply_to: str = "",
    references: str = "",
    attachment_path: str = "",
    list_unsubscribe: str = "",
    html_body: str = "",
) -> tuple[bool, str]:
    """
    Send an email via SMTP, with an optional file attachment and optional HTML body.
    When html_body is provided the message is sent as multipart/alternative with
    both plain-text and HTML parts; mail clients that support HTML will render it.

    Supports two connection modes based on SMTP_PORT:
      - Port 465 : SMTP_SSL  (SSL from the start — common for Gmail)
      - Any other : STARTTLS (plain connection upgraded to TLS — common for port 587)

    Args:
        to_address:      Recipient email address.
        subject:         Email subject line.
        body:            Plain-text email body.
        from_address:    Sender address. Defaults to SMTP_USER from .env.
        in_reply_to:     Message-ID of the email being replied to.
        references:      Thread reference chain (defaults to in_reply_to).
        attachment_path: Local filesystem path to a file to attach (e.g. a PDF
                         proposal). Silently skipped if the path is empty or the
                         file does not exist.

    Returns:
        A (success, error_message) tuple.
        On success : (True,  "")
        On failure : (False, human-readable error string)
    """
    # Guard: make sure credentials are configured
    missing = [k for k, v in {
        "SMTP_HOST": SMTP_HOST,
        "SMTP_USER": SMTP_USER,
        "SMTP_PASSWORD": SMTP_PASSWORD,
    }.items() if not v]

    if missing:
        return False, f"Missing .env keys: {', '.join(missing)}"

    # Use "mixed" when there is an attachment, "alternative" for text-only.
    has_attachment = bool(attachment_path and os.path.isfile(attachment_path))
    msg = MIMEMultipart("mixed" if has_attachment else "alternative")
    msg["Subject"] = subject
    msg["From"]    = formataddr((from_name, from_address)) if from_name else from_address
    msg["To"]      = to_address
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"]  = references or in_reply_to
    if list_unsubscribe:
        msg["List-Unsubscribe"]      = f"<{list_unsubscribe}>"
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg.attach(MIMEText(body, "plain"))
    if html_body:
        msg.attach(MIMEText(html_body, "html"))

    if has_attachment:
        with open(attachment_path, "rb") as fh:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(fh.read())
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            "attachment",
            filename=os.path.basename(attachment_path),
        )
        msg.attach(part)

    context = ssl.create_default_context()

    try:
        if SMTP_PORT == 465:
            # SSL from the start
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context) as server:
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.sendmail(from_address, to_address, msg.as_string())
        else:
            # Plain connection, then upgrade with STARTTLS
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.sendmail(from_address, to_address, msg.as_string())

        return True, ""

    except smtplib.SMTPAuthenticationError:
        return False, "Authentication failed — check SMTP_USER and SMTP_PASSWORD in .env."
    except smtplib.SMTPRecipientsRefused:
        return False, f"Recipient refused by server: {to_address}"
    except smtplib.SMTPException as exc:
        return False, f"SMTP error: {exc}"
    except OSError as exc:
        return False, f"Connection error ({SMTP_HOST}:{SMTP_PORT}): {exc}"
