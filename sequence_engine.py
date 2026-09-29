"""
sequence_engine.py - Channel-aware sequence foundation
======================================================
Defines the future multi-channel sequence plan, computes which
touchpoints are due, and builds simple per-channel messages.
"""

from datetime import date
import re

from database import DB_PATH, get_active_sequence_enrollments, get_communication_events
from email_validator import _company_core_name
from outreach import generate_email
from settings import get_candidate_linkedin, get_sender_name

DEFAULT_SEQUENCE_NAME = "default_multichannel"
# Email-only sequence used for personal outreach: LinkedIn/Instagram/SMS steps
# cannot run without profile URLs, and would otherwise stall the whole sequence.
CANDIDATE_EMAIL_SEQUENCE_NAME = "candidate_email"

CANDIDATE_EMAIL_SEQUENCE = [
    {"step": 1, "day_offset": 0,  "channel": "email", "label": "Initial email",    "message_type": "email_initial"},
    {"step": 2, "day_offset": 5,  "channel": "email", "label": "Email follow-up 1", "message_type": "email_followup_1"},
    {"step": 3, "day_offset": 12, "channel": "email", "label": "Email follow-up 2", "message_type": "email_followup_2"},
]

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


_GENERIC_NAMES = {"owner/manager", "owner", "manager", "team", "there", "sir/madam"}


def _first_name(name: str | None) -> str:
    """First token of a name; "there" for empty or placeholder names like Owner/Manager."""
    raw = (name or "").strip()
    if not raw or raw.lower() in _GENERIC_NAMES:
        return "there"
    return raw.split()[0]


def get_sequence_definition(sequence_name: str = DEFAULT_SEQUENCE_NAME) -> list:
    """Return the touchpoint plan for a named sequence."""
    if sequence_name == CANDIDATE_EMAIL_SEQUENCE_NAME:
        return [dict(step) for step in CANDIDATE_EMAIL_SEQUENCE]
    if sequence_name != DEFAULT_SEQUENCE_NAME:
        raise ValueError(f"Unknown sequence '{sequence_name}'")
    return [dict(step) for step in DEFAULT_MULTI_CHANNEL_SEQUENCE]


def _extract_sent_sequence_steps(events: list, sequence_name: str) -> set[int]:
    """Parse step numbers from communication event metadata."""
    steps = set()
    pattern = re.compile(r"(?:^|[;, ])step=(\d+)(?:$|[;, ])")
    name_pattern = re.compile(r"(?:^|[;, ])sequence=([a-zA-Z0-9_]+)(?:$|[;, ])")

    for event in events:
        if event.get("event_type") != "sequence_step" or event.get("status") not in ("sent", "skipped"):
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


def _signoff() -> str:
    """Follow-up sign-off: name plus LinkedIn when configured."""
    lines = ["Thanks,", get_sender_name()]
    linkedin = get_candidate_linkedin()
    if linkedin:
        lines.append(f"LinkedIn: {linkedin}")
    return "\n".join(lines)


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
    company = _company_core_name(prospect.get("company") or "") or prospect.get("company") or "your company"
    message_type = touchpoint["message_type"]

    if message_type == "email_initial":
        return generate_email(prospect)

    if message_type == "email_followup_1":
        return {
            "subject": f"Re: {company}",
            "body": (
                f"Hi {first},\n\n"
                f"Following up in case my last note got buried. I'm a recent FinTech & Data "
                f"Analytics graduate (Westminster) looking to build a career in analytics, and "
                f"I'd really value 15 minutes to hear how the team at {company} works with data.\n\n"
                f"Would a coffee chat or short call suit you sometime soon?\n\n"
                f"{_signoff()}"
            ),
        }

    if message_type == "email_followup_2":
        return {
            "subject": f"{company}: one more from me",
            "body": (
                f"Hi {first},\n\n"
                f"One line of context in case it helps: alongside my degree I run the data and "
                f"automation side of my own business (Harmony Booths), where A/B testing took "
                f"booking conversion from 5% to 20%. That's why I'm keen to learn how "
                f"{company} approaches analytics.\n\n"
                f"Are you open to a short chat in the next week or two?\n\n"
                f"{_signoff()}"
            ),
        }

    if message_type == "email_followup_3":
        return {
            "subject": f"Last one from me, {first}",
            "body": (
                f"Hi {first},\n\n"
                f"Final note from me. If a coffee chat about analytics at {company} ever makes "
                f"sense, I'd be glad to make time. If not, no worries at all.\n\n"
                f"{_signoff()}"
            ),
        }

    if message_type == "email_breakup":
        return {
            "subject": f"Closing the loop, {first}",
            "body": (
                f"Hi {first},\n\n"
                f"Haven't heard back, so I'll leave it here for now. If you're ever open to a "
                f"conversation about analytics at {company}, I'd welcome it.\n\n"
                f"{_signoff()}"
            ),
        }

    if message_type == "linkedin_connect":
        return {
            "body": (
                f"Hi {first}, I'm a Data & FinTech Analytics graduate looking to build a career "
                f"in analytics. {company}'s work caught my eye and I'd love to be connected."
            )
        }

    if message_type == "linkedin_dm":
        return {
            "body": (
                f"Hi {first}, thanks for connecting. I recently finished a BSc in FinTech & Data "
                f"Analytics and I'm keen to learn how {company} uses data. Would you be open to a "
                f"short coffee chat or call in the next couple of weeks?"
            )
        }

    if message_type == "instagram_dm":
        return {
            "body": (
                f"Hi {first}, following up here in case email got missed. I'm a graduate building "
                f"a career in analytics and {company} stood out. Open to a short chat sometime?"
            )
        }

    if message_type == "sms_followup":
        return {
            "body": (
                f"Hi {first}, this is {get_sender_name()}. I emailed about a short coffee chat on "
                f"analytics at {company}. Open to it if you have a moment?"
            )
        }

    raise ValueError(f"Unsupported message_type '{message_type}'")
