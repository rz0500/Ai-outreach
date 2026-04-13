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

import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from dotenv import load_dotenv
import os

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
) -> tuple[bool, str]:
    """
    Send a plain-text email via SMTP.

    Supports two connection modes based on SMTP_PORT:
      - Port 465 : SMTP_SSL  (SSL from the start — common for Gmail)
      - Any other : STARTTLS (plain connection upgraded to TLS — common for port 587)

    Args:
        to_address:   Recipient email address.
        subject:      Email subject line.
        body:         Plain-text email body.
        from_address: Sender address. Defaults to SMTP_USER from .env.

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

    # Build the message
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = from_address
    msg["To"]      = to_address
    msg.attach(MIMEText(body, "plain"))

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
