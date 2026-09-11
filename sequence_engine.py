"""
sequence_engine.py - Channel-aware sequence foundation
======================================================
Defines the future multi-channel sequence plan, computes which
touchpoints are due, and builds simple per-channel messages.
"""

from datetime import date
import re

from database import DB_PATH, get_active_sequence_enrollments, get_communication_events
from outreach import generate_email
from settings import get_candidate_cv_url, get_sender_name

DEFAULT_SEQUENCE_NAME = "default_multichannel"

# Original blueprint mapped to zero-based offsets from enrollment date:
# Day 1 -> 0, Day 2 -> 1, Day 4 -> 3, etc.
DEFAULT_MULTI_CHANNEL_SEQUENCE = [
    {"step": 1, "day_offset": 0, "channel": "email", "label": "Initial email", "message_type": "email_initial"},
    {"step": 2, "day_offset": 1, "channel": "linkedin", "label": "LinkedIn connection request", "message_type": "linkedin_connect"},
    {"step": 3, "day_offset": 3, "channel": "linkedin", "label": "LinkedIn DM", "message_type": "linkedin_dm"},
    {"step": 4, "day_offset": 4, "channel": "email", "label": "Email follow-up 1", "message_type": "email_followup_1"},
    {"step": 5, "day_offset": 6, "channel": "instagram", "label": "Instagram DM", "message_type": "instagram_dm"},
    {"step": 6, "day_offset": 9, "channel": "email", "label": "Email follow-up 2", "message_type": "email_followup_2"},
    {"step": 7, "day_offset": 13, "channel": "email", "label": "Email follow-up 3", "message_type": "email_followup_3"},
    {"step": 8, "day_offset": 24, "channel": "email", "label": "Breakup email", "message_type": "email_breakup"},
]


def _first_name(name: str | None) -> str:
    """Return the first token from a name, or a fallback."""
    raw = (name or "").strip()
    return raw.split()[0] if raw else "there"


def get_sequence_definition(sequence_name: str = DEFAULT_SEQUENCE_NAME) -> list:
    """Return the touchpoint plan for a named sequence."""
    if sequence_name != DEFAULT_SEQUENCE_NAME:
        raise ValueError(f"Unknown sequence '{sequence_name}'")
    return [dict(step) for step in DEFAULT_MULTI_CHANNEL_SEQUENCE]


def _extract_sent_sequence_steps(events: list, sequence_name: str) -> set[int]:
    """Parse step numbers from communication event metadata."""
    steps = set()
    pattern = re.compile(r"(?:^|[;, ])step=(\d+)(?:$|[;, ])")
    name_pattern = re.compile(r"(?:^|[;, ])sequence=([a-zA-Z0-9_]+)(?:$|[;, ])")

    for event in events:
        if event.get("event_type") != "sequence_step" or event.get("status") != "sent":
            continue
        metadata = event.get("metadata") or ""
        name_match = name_pattern.search(metadata)
        if name_match and name_match.group(1) != sequence_name:
            continue
        step_match = pattern.search(metadata)
        if step_match:
            steps.add(int(step_match.group(1)))
    return steps


def get_due_touchpoints(
    db_path: str = DB_PATH,
    sequence_name: str = DEFAULT_SEQUENCE_NAME,
    today: date | None = None,
) -> list:
    """Return currently due touchpoints for active sequence enrollments."""
    today = today or date.today()
    due = []
    definition = get_sequence_definition(sequence_name)

    for enrollment in get_active_sequence_enrollments(db_path, sequence_name=sequence_name):
        enrolled_at = date.fromisoformat(enrollment["enrolled_at"])
        days_since_enrollment = (today - enrolled_at).days
        sent_steps = _extract_sent_sequence_steps(
            get_communication_events(enrollment["id"], db_path=db_path),
            sequence_name=sequence_name,
        )

        for touchpoint in definition:
            if touchpoint["step"] in sent_steps:
                continue
            if days_since_enrollment >= touchpoint["day_offset"]:
                due.append(
                    {
                        **enrollment,
                        "next_touchpoint": dict(touchpoint),
                        "days_since_enrollment": days_since_enrollment,
                    }
                )
            break

    return due


def build_touchpoint_message(prospect: dict, touchpoint: dict) -> dict:
    """
    Build a channel-specific message payload for a due touchpoint.

    Returns:
        For email:
            {"subject": ..., "body": ...}
        For social/SMS:
            {"body": ...}
    """
    first = _first_name(prospect.get("name"))
    company = prospect.get("company") or "your company"
    message_type = touchpoint["message_type"]

    if message_type == "email_initial":
        return generate_email(prospect)

    if message_type == "email_followup_1":
        return {
            "subject": f"Re: {company}",
            "body": (
                f"Hi {first},\n\n"
                f"Following up in case my last note got buried. I'm a recent FinTech & Data "
                f"Analytics graduate (Westminster) with hands-on experience in Python, SQL, and "
                f"Power BI, plus practical automation work building Harmony Booths.\n\n"
                f"Still keen to hear if {company} has room for a graduate analyst — even a brief "
                f"chat would help me understand if it's a fit.\n\n"
                f"Best,\n"
                f"{get_sender_name()}\n"
                f"CV: {get_candidate_cv_url()}"
            ),
        }

    if message_type == "email_followup_2":
        return {
            "subject": f"{company} — one more from me",
            "body": (
                f"Hi {first},\n\n"
                f"Didn't want to be a pest, but wanted to try once more. I've spent the past year "
                f"building and running end-to-end automations for a real business (Harmony Booths) "
                f"alongside my degree — happy to walk through that or my CV if it's useful context "
                f"for a Graduate Data/Business Analyst role at {company}.\n\n"
                f"Best,\n"
                f"{get_sender_name()}\n"
                f"CV: {get_candidate_cv_url()}"
            ),
        }

    if message_type == "email_followup_3":
        return {
            "subject": f"Last one from me, {first}",
            "body": (
                f"Hi {first},\n\n"
                f"Final follow-up — if now isn't the right time, no worries at all. If a graduate "
                f"analyst opening does come up at {company}, I'd still love to be considered.\n\n"
                f"Best,\n"
                f"{get_sender_name()}\n"
                f"CV: {get_candidate_cv_url()}"
            ),
        }

    if message_type == "email_breakup":
        return {
            "subject": f"Closing the loop, {first}",
            "body": (
                f"Hi {first},\n\n"
                f"Haven't heard back, so I'll leave it here for now. If a graduate analyst role "
                f"opens up at {company} down the line, I'd welcome the chance to talk then.\n\n"
                f"Best,\n"
                f"{get_sender_name()}"
            ),
        }

    if message_type == "linkedin_connect":
        return {
            "body": (
                f"Hi {first}, I'm a Data & FinTech Analytics graduate exploring analyst roles and "
                f"wanted to connect — {company}'s work caught my eye."
            )
        }

    if message_type == "linkedin_dm":
        return {
            "body": (
                f"Hi {first}, thanks for connecting. I recently finished my BSc in FinTech & Data "
                f"Analytics and have hands-on experience in Python, SQL, Power BI, and workflow "
                f"automation. Happy to share my CV if a graduate analyst role at {company} comes up."
            )
        }

    if message_type == "instagram_dm":
        return {
            "body": (
                f"Hi {first}, following up here in case email got missed — I'm a graduate looking "
                f"for a Data/Business Analyst role and {company} stood out. Happy to send my CV over."
            )
        }

    if message_type == "sms_followup":
        return {
            "body": (
                f"Hi {first}, this is {get_sender_name()} — following up on my email about a "
                f"graduate analyst role at {company}. Happy to send my CV if useful."
            )
        }

    raise ValueError(f"Unsupported message_type '{message_type}'")
