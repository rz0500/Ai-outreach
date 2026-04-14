"""
inbox_monitor.py - IMAP Reply Monitor with Classification
==========================================================
Connects to an IMAP inbox, fetches unread emails, and checks whether
the sender matches a prospect in the database.

For each matched reply it:
  1. Extracts the plain-text body.
  2. Uses Claude to classify the intent:
       interested / not_interested / opt_out / out_of_office / auto_reply
  3. Acts on the classification:
       interested     -> status stays 'replied', sequence paused, drafted reply logged
       not_interested -> status set to 'rejected', sequence paused
       opt_out        -> contact suppressed, status set to 'rejected'
       out_of_office  -> no status change, sequence left active (they're away)
       auto_reply     -> no status change, email skipped silently
"""

import os
import imaplib
import email
from email.header import decode_header
import logging
from dotenv import load_dotenv

import database
from database import save_reply_draft
from ai_engine import classify_reply

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

load_dotenv()

IMAP_HOST     = os.getenv("IMAP_HOST", "")
IMAP_PORT     = int(os.getenv("IMAP_PORT", "993"))
IMAP_USER     = os.getenv("IMAP_USER", os.getenv("SMTP_USER", ""))
IMAP_PASSWORD = os.getenv("IMAP_PASSWORD", os.getenv("SMTP_PASSWORD", ""))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def decode_mime_words(s: str) -> str:
    """Decode MIME-encoded header words to a plain Python string."""
    if not s:
        return ""
    words = decode_header(s)
    result = []
    for word, charset in words:
        if isinstance(word, bytes):
            result.append(word.decode(charset or "utf-8", errors="ignore"))
        else:
            result.append(word)
    return "".join(result)


def extract_email_address(from_header: str) -> str:
    """Pull just the address from a 'From' header (handles 'Name <addr>' format)."""
    if "<" in from_header and ">" in from_header:
        return from_header.split("<")[1].split(">")[0].strip().lower()
    return from_header.strip().lower()


def extract_body(msg: email.message.Message) -> str:
    """
    Walk a MIME message and return the first plain-text part.
    Falls back to the raw payload for non-multipart messages.
    """
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                disposition = str(part.get("Content-Disposition") or "")
                if "attachment" in disposition:
                    continue
                charset = part.get_content_charset() or "utf-8"
                try:
                    return part.get_payload(decode=True).decode(charset, errors="ignore").strip()
                except Exception:
                    continue
        return ""
    else:
        charset = msg.get_content_charset() or "utf-8"
        try:
            return msg.get_payload(decode=True).decode(charset, errors="ignore").strip()
        except Exception:
            return ""


# ---------------------------------------------------------------------------
# Classification handler
# ---------------------------------------------------------------------------

def _handle_classified_reply(
    prospect: dict,
    classification: str,
    reasoning: str,
    drafted_reply: str,
    sender_email: str,
    inbound_body: str = "",
) -> None:
    """
    Act on a classified reply: update DB, pause sequence, log events.
    """
    prospect_id = prospect["id"]

    if classification == "auto_reply":
        logging.info(f"  Auto-reply detected from {sender_email} — ignoring.")
        return

    if classification == "out_of_office":
        logging.info(f"  OOO reply from {sender_email} — leaving sequence active.")
        database.log_communication_event(
            prospect_id, "email", "inbound", "reply_ooo", "received",
            content_excerpt=reasoning,
            metadata=f"classification=out_of_office",
        )
        return

    # For all real human replies, log the event
    database.log_communication_event(
        prospect_id, "email", "inbound", "reply_received", "received",
        content_excerpt=reasoning,
        metadata=f"classification={classification}",
    )

    if classification == "opt_out":
        logging.info(f"  Opt-out from {sender_email} — suppressing and rejecting.")
        database.suppress_prospect(prospect_id, reason="opt_out_reply", source="inbox_monitor")
        # suppress_prospect already sets status to 'rejected'

    elif classification == "not_interested":
        logging.info(f"  Not interested reply from {sender_email} — pausing sequence.")
        database.update_status(prospect_id, "rejected")
        database.update_sequence_enrollment_status(
            prospect_id, "paused", paused_reason="not_interested_reply"
        )

    elif classification == "interested":
        logging.info(f"  INTERESTED reply from {sender_email} — pausing sequence, drafting response.")
        database.update_sequence_enrollment_status(
            prospect_id, "paused", paused_reason="interested_reply_awaiting_response"
        )
        if drafted_reply:
            # Save to structured reply_drafts table (queryable, reviewable in UI)
            save_reply_draft(
                prospect_id=prospect_id,
                inbound_from=sender_email,
                inbound_body=inbound_body,
                classification=classification,
                classification_reasoning=reasoning,
                drafted_reply=drafted_reply,
            )
            # Also append to notes for backward-compat
            existing_notes = prospect.get("notes") or ""
            draft_note = f"\n\n[DRAFTED REPLY — review before sending]\n{drafted_reply}"
            database.update_notes(prospect_id, (existing_notes + draft_note).strip())
            database.log_communication_event(
                prospect_id, "email", "internal", "drafted_reply", "draft",
                content_excerpt=drafted_reply[:120],
                metadata="source=inbox_monitor;status=awaiting_review",
            )
            logging.info(f"  Drafted reply saved to reply_drafts table.")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check_for_replies(mark_as_read: bool = True) -> int:
    """
    Connect to IMAP, fetch unread emails, classify any replies from prospects.

    Args:
        mark_as_read: If True, marks processed emails as read in the inbox.

    Returns:
        Number of prospects whose status was updated.
    """
    if not all([IMAP_HOST, IMAP_USER, IMAP_PASSWORD]):
        logging.error("IMAP configuration is missing in .env file.")
        return 0

    try:
        logging.info(f"Connecting to IMAP server {IMAP_HOST}:{IMAP_PORT}...")
        mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
        mail.login(IMAP_USER, IMAP_PASSWORD)

        status, _ = mail.select("INBOX")
        if status != "OK":
            logging.error("Could not select INBOX.")
            return 0

        status, response = mail.search(None, "UNREAD")
        if status != "OK":
            logging.error("Could not search for unread messages.")
            return 0

        message_ids = response[0].split()
        logging.info(f"Found {len(message_ids)} unread message(s).")

        updated_count = 0

        for msg_id in message_ids:
            # Fetch full message so we can read the body
            status, msg_data = mail.fetch(msg_id, "(RFC822)")
            if status != "OK":
                continue

            for response_part in msg_data:
                if not isinstance(response_part, tuple):
                    continue

                msg = email.message_from_bytes(response_part[1])
                from_header   = decode_mime_words(msg.get("From", ""))
                sender_email  = extract_email_address(from_header)

                if not sender_email:
                    continue

                prospect = database.get_prospect_by_email(sender_email)
                if not prospect:
                    continue

                current_status = prospect["status"]
                if current_status in ("booked",):
                    # Already won — don't touch
                    continue

                body = extract_body(msg)

                # Classify with Claude (gracefully degrade if API unavailable)
                try:
                    classified = classify_reply(prospect, body or "(no body)")
                    classification = classified["classification"]
                    reasoning      = classified["reasoning"]
                    drafted_reply  = classified["drafted_reply"]
                    logging.info(
                        f"Reply from {sender_email} classified as '{classification}': {reasoning}"
                    )
                except Exception as exc:
                    logging.warning(
                        f"Could not classify reply from {sender_email}: {exc}. "
                        f"Defaulting to 'replied' status update."
                    )
                    classification = "interested"
                    reasoning      = "classification failed — manual review needed"
                    drafted_reply  = ""

                # Mark as replied in DB before handling (so suppress_prospect
                # doesn't double-set rejected on an already-rejected record)
                if current_status not in ("replied", "rejected"):
                    database.update_status(prospect["id"], "replied")
                    updated_count += 1

                _handle_classified_reply(
                    prospect, classification, reasoning, drafted_reply,
                    sender_email, inbound_body=body,
                )

            if mark_as_read:
                mail.store(msg_id, "+FLAGS", "\\Seen")

        mail.close()
        mail.logout()
        return updated_count

    except imaplib.IMAP4.error as e:
        logging.error(f"IMAP error: {e}")
        return 0
    except Exception as e:
        logging.error(f"Failed to check for replies: {e}")
        return 0


if __name__ == "__main__":
    print("Testing reply monitor (dry run)...")
    if all([IMAP_HOST, IMAP_USER, IMAP_PASSWORD]):
        print(f"Config loaded successfully for user: {IMAP_USER}")
    else:
        print("Missing IMAP config in .env — please fill out IMAP variables.")
