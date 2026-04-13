"""
outreach.py - Email Outreach Writer
=====================================
Module 5 of the AI Lead Generation & Outreach System.

Generates personalised cold email drafts based on each prospect's
profile, notes, and detected signals. Drafts are saved to the
database with status 'draft' -> 'approved' -> 'sent'.

Signal detection (from notes):
    funding   : raised, series, funding, investment
    growth    : hiring, expand, growing, launch, new
    pain point: pain, struggle, challenge, broken, problem
    content   : podcast, article, post, tweet, mentioned, blog
    warm intro: intro, warm, referred, recommend

The detected signals determine the subject line and opening hook so
each email feels relevant rather than generic.

# TODO: Replace template generation with Claude AI for higher quality
#       and more natural-sounding emails. Will require ANTHROPIC_API_KEY.

Usage:
    from outreach import generate_email, generate_and_save, generate_batch

    # Preview an email without saving
    draft = generate_email(prospect_dict)
    print(draft["subject"])
    print(draft["body"])

    # Generate and save to DB
    record = generate_and_save(prospect_id=3)

    # Batch-generate for all prospects scoring >= 60 with no existing draft
    results = generate_batch(min_score=60)
"""

from database import (
    DB_PATH,
    get_all_prospects,
    get_outreach_by_prospect,
    initialize_outreach_table,
    save_outreach,
    update_outreach_status,
)

# ---------------------------------------------------------------------------
# Signal keywords
# ---------------------------------------------------------------------------

SIGNAL_KEYWORDS = {
    "funding":    {"raised", "series", "funding", "investment", "investor"},
    "growth":     {"hiring", "expand", "expanding", "growing", "launch", "launching"},
    "pain":       {"pain", "struggle", "struggling", "challenge", "broken", "problem"},
    "content":    {"podcast", "article", "post", "tweet", "mentioned", "blog", "wrote"},
    "warm_intro": {"intro", "warm", "referred", "recommend", "recommended"},
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _first_name(full_name: str) -> str:
    """Return just the first word of a name."""
    return full_name.strip().split()[0] if full_name.strip() else "there"


def _detect_signals(notes: str) -> dict:
    """
    Scan notes for signal keywords.

    Returns a dict like: {"funding": True, "growth": False, ...}
    """
    lower = notes.lower()
    return {
        signal: any(kw in lower for kw in keywords)
        for signal, keywords in SIGNAL_KEYWORDS.items()
    }


def _build_subject(first_name: str, company: str, signals: dict) -> str:
    """Pick a subject line based on the strongest detected signal."""
    if signals["warm_intro"]:
        return f"Introduction - quick note for {first_name}"
    if signals["funding"]:
        return f"Congrats on the raise, {first_name} - idea for {company}"
    if signals["growth"]:
        return f"{first_name}, quick thought on scaling {company}'s pipeline"
    if signals["pain"]:
        return f"Re: the challenge at {company}"
    if signals["content"]:
        return f"Your recent content + a thought for {company}"
    return f"Quick idea for {company}"


def _build_hook(first_name: str, company: str, signals: dict) -> str:
    """Write the opening sentence based on the strongest signal."""
    if signals["warm_intro"]:
        return (
            f"A mutual connection suggested I reach out - "
            f"they thought there might be a good fit between "
            f"{company} and what we do."
        )
    if signals["funding"]:
        return (
            f"Congrats on the recent funding round - "
            f"exciting times ahead for {company}."
        )
    if signals["growth"]:
        return f"I noticed {company} is in a strong growth phase - impressive momentum."
    if signals["content"]:
        return (
            f"I came across your recent content and wanted to reach out - "
            f"it really resonated."
        )
    if signals["pain"]:
        return (
            f"I came across some of the challenges {company} has been working through "
            f"and thought we might be able to help."
        )
    return f"I've been looking at companies like {company} and wanted to reach out."


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_email(prospect: dict) -> dict:
    """
    Generate a personalised cold email draft for a prospect.

    Does NOT save to the database. Use generate_and_save() for that.

    Args:
        prospect: A prospect dict (as returned by database.get_all_prospects).

    Returns:
        A dict with "subject" and "body" strings.
    """
    first  = _first_name(prospect.get("name", "there"))
    company = prospect.get("company", "your company")
    notes   = prospect.get("notes") or ""
    signals = _detect_signals(notes)

    subject = _build_subject(first, company, signals)
    hook    = _build_hook(first, company, signals)

    body = (
        f"Hi {first},\n\n"
        f"{hook}\n\n"
        f"I help B2B teams build a predictable outbound pipeline - "
        f"fewer hours on manual prospecting, more time closing. "
        f"Most teams we work with book 3-5 extra meetings per week "
        f"within their first month.\n\n"
        f"Would a 15-minute call this week make sense to see if "
        f"there's a fit?\n\n"
        f"Best,\n"
        f"[Your name]\n"
        f"[Your title] | [Your company]\n"
        f"[Your phone]  | [Your email]"
    )

    return {"subject": subject, "body": body}


def generate_and_save(
    prospect_id: int,
    overwrite: bool = False,
    db_path: str = DB_PATH,
) -> dict:
    """
    Generate an email draft for a prospect and save it to the database.

    Args:
        prospect_id: ID of the prospect to write for.
        overwrite:   If False (default), skip prospects that already have
                     a draft. If True, always generate a new draft.
        db_path:     Path to the database file.

    Returns:
        A dict with "outreach_id", "prospect_id", "subject", "body",
        and "skipped" (True if the prospect already had a draft and
        overwrite=False).

    Raises:
        ValueError: If the prospect ID is not found.
    """
    initialize_outreach_table(db_path)

    all_prospects = get_all_prospects(db_path)
    prospect = next((p for p in all_prospects if p["id"] == prospect_id), None)
    if prospect is None:
        raise ValueError(f"No prospect found with id={prospect_id}")

    # Skip if a draft already exists and overwrite is off
    if not overwrite:
        existing = get_outreach_by_prospect(prospect_id, db_path)
        if existing:
            return {
                "outreach_id": existing[0]["id"],
                "prospect_id": prospect_id,
                "subject":     existing[0]["subject"],
                "body":        existing[0]["body"],
                "skipped":     True,
            }

    draft = generate_email(prospect)
    outreach_id = save_outreach(prospect_id, draft["subject"], draft["body"], db_path)

    return {
        "outreach_id": outreach_id,
        "prospect_id": prospect_id,
        "subject":     draft["subject"],
        "body":        draft["body"],
        "skipped":     False,
    }


def generate_batch(
    min_score: int = 60,
    overwrite: bool = False,
    db_path: str = DB_PATH,
) -> list:
    """
    Generate email drafts for all prospects at or above a score threshold.

    Prospects that already have a draft are skipped unless overwrite=True.

    Args:
        min_score: Only generate for prospects with lead_score >= this value.
        overwrite: Regenerate even if a draft already exists.
        db_path:   Path to the database file.

    Returns:
        A list of result dicts (same shape as generate_and_save).
    """
    initialize_outreach_table(db_path)

    prospects = [
        p for p in get_all_prospects(db_path)
        if p["lead_score"] >= min_score
    ]

    if not prospects:
        print(f"No prospects with score >= {min_score}.")
        return []

    print(f"Generating emails for {len(prospects)} prospect(s) "
          f"with score >= {min_score}...\n")

    results = []
    for p in prospects:
        result = generate_and_save(p["id"], overwrite=overwrite, db_path=db_path)
        tag = "SKIPPED" if result["skipped"] else "GENERATED"
        print(f"  [{tag}] {p['name']:<22} {p['company']:<22} "
              f"score={p['lead_score']}")
        results.append(result)

    return results


def approve_draft(outreach_id: int, db_path: str = DB_PATH) -> bool:
    """Mark an outreach draft as approved and ready to send."""
    return update_outreach_status(outreach_id, "approved", db_path)


def mark_sent(outreach_id: int, db_path: str = DB_PATH) -> bool:
    """Mark an outreach record as sent."""
    return update_outreach_status(outreach_id, "sent", db_path)
