"""
sequence_dispatcher.py - Multi-channel touchpoint dispatcher
============================================================
Routes due touchpoints from sequence_engine to the appropriate
delivery channel and logs the result.
"""

from datetime import date

from database import DB_PATH, log_communication_event, update_sequence_enrollment_status
from sendgrid_mailer import send_email
from sms_agent import send_sms
from social_agent import send_instagram_dm, send_linkedin_connection
from settings import get_linkedin_dry_run
from sequence_engine import (
    DEFAULT_SEQUENCE_NAME,
    build_touchpoint_message,
    get_due_touchpoints,
    get_sequence_definition,
)


def _safe_metadata(sequence_name: str, step: int, channel: str, extra: str = "") -> str:
    """
    Build a compact metadata string for communication events.
    """
    base = f"sequence={sequence_name};step={step};channel={channel}"
    return f"{base};{extra}" if extra else base


def _dispatch_single_touchpoint(item: dict, dry_run: bool, db_path: str) -> dict:
    """
    Dispatch one touchpoint and log the result.
    """
    touchpoint = item["next_touchpoint"]
    prospect_id = item["id"]
    channel = touchpoint["channel"]
    message = build_touchpoint_message(item, touchpoint)
    step = touchpoint["step"]
    sequence_name = item["sequence_name"]

    result = {
        "prospect_id": prospect_id,
        "name": item.get("name", ""),
        "channel": channel,
        "step": step,
        "label": touchpoint["label"],
        "sent": False,
        "error": "",
        "dry_run": dry_run,
    }

    if dry_run:
        return result

    if channel == "email":
        email = item.get("email") or ""
        if not email:
            result["error"] = "No email address on file."
        else:
            ok, err = send_email(email, message["subject"], message["body"])
            result["sent"] = ok
            result["error"] = err

    elif channel == "linkedin":
        profile_url = item.get("linkedin_url") or ""
        if not profile_url:
            result["error"] = "No LinkedIn URL on file."
        else:
            li_dry = get_linkedin_dry_run()
            ok = send_linkedin_connection(profile_url, message["body"], dry_run=li_dry)
            result["sent"] = ok
            result["dry_run"] = li_dry
            result["error"] = "" if ok else "LinkedIn automation failed."

    elif channel == "instagram":
        profile_url = item.get("instagram_url") or item.get("instagram_profile") or ""
        if not profile_url:
            result["error"] = "No Instagram profile URL on file."
        else:
            li_dry = get_linkedin_dry_run()
            ok = send_instagram_dm(profile_url, message["body"], dry_run=li_dry)
            result["sent"] = ok
            result["error"] = "" if ok else "Instagram automation failed."

    elif channel == "sms":
        phone = item.get("phone") or ""
        if not phone:
            result["error"] = "No phone number on file."
        else:
            ok = send_sms(phone, message["body"], dry_run=False)
            result["sent"] = ok
            result["error"] = "" if ok else "SMS send failed."

    else:
        result["error"] = f"Unsupported channel '{channel}'."

    status = "sent" if result["sent"] else "failed"
    log_communication_event(
        prospect_id,
        channel,
        "outbound",
        "sequence_step",
        status,
        content_excerpt=message.get("subject", message.get("body", ""))[:120],
        metadata=_safe_metadata(sequence_name, step, channel, result["error"]),
        db_path=db_path,
    )

    if result["sent"] and step == get_sequence_definition(sequence_name)[-1]["step"]:
        update_sequence_enrollment_status(prospect_id, "completed", db_path=db_path)

    return result


def run_multichannel_sequence(
    dry_run: bool = True,
    db_path: str = DB_PATH,
    sequence_name: str = DEFAULT_SEQUENCE_NAME,
    today: date | None = None,
) -> list:
    """
    Dispatch all currently due touchpoints for the given sequence.
    """
    due = get_due_touchpoints(
        db_path=db_path,
        sequence_name=sequence_name,
        today=today,
    )
    return [
        _dispatch_single_touchpoint(item, dry_run=dry_run, db_path=db_path)
        for item in due
    ]
