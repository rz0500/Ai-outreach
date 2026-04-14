"""
sms_agent.py - Twilio SMS Integration
=====================================
Module 15 of the AI Lead Gen System.

Uses the Twilio API to send SMS text messages to warm prospects
who have provided their phone numbers. Automatically formats phone 
numbers to the required E.164 standard.

Configuration:
    TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER in .env
"""

import os
import re
import logging
from twilio.rest import Client
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def _format_phone_number(phone: str) -> str:
    """Format an arbitrary phone string into E.164 format (e.g., +1234567890)."""
    digits = re.sub(r'\D', '', phone)
    
    # Assume US number if exactly 10 digits
    if len(digits) == 10:
        return f"+1{digits}"
    # Otherwise just append the plus
    elif len(digits) > 10:
        return f"+{digits}"
        
    return phone

def send_sms(to_phone: str, message: str, dry_run: bool = True) -> bool:
    """
    Send an SMS message to a prospect using Twilio.
    Returns True on success, False on failure.
    """
    if not to_phone:
        logging.warning("Cannot send SMS: No phone number provided for prospect.")
        return False
        
    formatted_phone = _format_phone_number(to_phone)
    
    sid = os.getenv("TWILIO_ACCOUNT_SID")
    token = os.getenv("TWILIO_AUTH_TOKEN")
    from_phone = os.getenv("TWILIO_PHONE_NUMBER")
    
    if not dry_run and (not sid or not token or not from_phone):
        logging.error("Missing Twilio credentials in environment (SID, Token, or Phone).")
        return False
        
    if dry_run:
        logging.info(f"[DRY RUN] Would send SMS to {formatted_phone}: '{message}'")
        return True
        
    try:
        client = Client(sid, token)
        msg_record = client.messages.create(
            body=message,
            from_=from_phone,
            to=formatted_phone
        )
        logging.info(f"SMS successfully sent to {formatted_phone} (Message SID: {msg_record.sid})")
        return True
    except Exception as e:
        logging.error(f"Failed to send SMS via Twilio: {e}")
        return False

if __name__ == "__main__":
    print("Testing Twilio SMS Agent...")
    send_sms("(555) 123-4567", "Hey, this is LeadGen AI. We generated a proposal for you.", dry_run=True)
