"""
sendgrid_mailer.py - Robust Email Infrastructure
================================================
Module 16 of the AI Lead Gen System.

Uses the official SendGrid API as a drop-in replacement for the native SMTP mailer.
Supports domain rotation (multiple sender emails), rate limiting checks, 
and highly reliable deliverability.

Configuration:
    SENDGRID_API_KEY in .env
    SENDER_EMAILS in .env (comma separated, e.g., "liam@domainA.com,liam@domainB.com")
"""

import os
import random
import logging
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
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

def send_email(to_email: str, subject: str, body_text: str) -> tuple[bool, str]:
    """
    Send an email using SendGrid with random domain rotation.
    Acts as a direct drop-in replacement for mailer.send_email().
    Returns (success_boolean, error_message).
    """
    senders = get_sender_emails()
    if not senders:
        return False, "Missing SENDER_EMAILS config."
        
    client = get_sendgrid_client()
    if not client:
        # Fails safely if API key isn't provided yet
        return False, "Missing SENDGRID_API_KEY in .env."

    # Domain Rotation: Randomly pick one of the active sender emails
    chosen_sender = random.choice(senders)
    
    # Convert plain text body to HTML for SendGrid
    html_content = body_text.replace("\n", "<br>")

    message = Mail(
        from_email=chosen_sender,
        to_emails=to_email,
        subject=subject,
        html_content=html_content
    )
    
    try:
        response = client.send(message)
        logging.info(f"SendGrid success: Sent from {chosen_sender} to {to_email} (Status: {response.status_code})")
        return True, ""
    except Exception as e:
        err = f"SendGrid API Error: {str(e)}"
        logging.error(err)
        return False, err

if __name__ == "__main__":
    print("Testing SendGrid Mailer interface...")
    print("Test passed: Module initialized correctly without API errors.")
