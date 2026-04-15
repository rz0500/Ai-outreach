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

# Sequence follow-ups use a soft opt-out line (separate from cold outbound rules)
OPT_OUT_LINE = "If now's not the right time, just reply and I'll leave you alone."

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
            "subject": f"Re: Quick idea for {company}",
            "body": (
                f"Hi {first},\n\n"
                f"Wanted to follow up with a different angle. We help service businesses "
                f"turn cold outreach into a steady pipeline without adding manual admin.\n\n"
                f"Would a quick 15-minute chat this week be worth exploring?\n\n"
                f"{OPT_OUT_LINE}\n\n"
                f"Best,\n"
                f"[Your name]"
            ),
        }

    if message_type == "email_followup_2":
        return {
            "subject": f"Proof this can work for {company}",
            "body": (
                f"Hi {first},\n\n"
                f"Quick note with a little more context: teams we support usually care most "
                f"about consistent meetings, not more tools. That is where our outbound systems help.\n\n"
                f"If useful, I can share a short example of what this could look like for {company}.\n\n"
                f"{OPT_OUT_LINE}\n\n"
                f"Best,\n"
                f"[Your name]"
            ),
        }

    if message_type == "email_followup_3":
        return {
            "subject": f"Worth exploring for {company}?",
            "body": (
                f"Hi {first},\n\n"
                f"One last follow-up before I close the loop. If outbound growth is on your radar "
                f"this quarter, I think there is a strong fit.\n\n"
                f"If not, totally fine.\n\n"
                f"{OPT_OUT_LINE}\n\n"
                f"Best,\n"
                f"[Your name]"
            ),
        }

    if message_type == "email_breakup":
        return {
            "subject": f"Closing the loop, {first}",
            "body": (
                f"Hi {first},\n\n"
                f"I have not heard back, so I will close the loop here. If outbound growth becomes "
                f"a priority for {company} later, I am happy to reconnect.\n\n"
                f"{OPT_OUT_LINE}\n\n"
                f"Best,\n"
                f"[Your name]"
            ),
        }

    if message_type == "linkedin_connect":
        return {
            "body": (
                f"Hi {first}, we help service businesses build predictable outbound pipelines. "
                f"Wanted to connect because I think a few ideas could be relevant for {company}."
            )
        }

    if message_type == "linkedin_dm":
        return {
            "body": (
                f"Hi {first}, thanks for connecting. We found you the same way we help clients find "
                f"their prospects: automatically, but with research and personalization. "
                f"Happy to share a quick example if useful."
            )
        }

    if message_type == "instagram_dm":
        return {
            "body": (
                f"Hi {first}, quick note because {company} looks like the kind of business our outbound "
                f"systems can help. If helpful, I can send a short idea."
            )
        }

    if message_type == "sms_followup":
        return {
            "body": (
                f"Hi {first}, this is [Your name]. We help businesses like {company} automate outbound. "
                f"Happy to share a quick idea if useful."
            )
        }

    raise ValueError(f"Unsupported message_type '{message_type}'")
