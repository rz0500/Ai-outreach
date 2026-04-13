"""
scorer.py - Rule-Based Lead Scoring Module
===========================================
Module 2 of the AI Lead Generation & Outreach System.

Scores each prospect 1-100 based on profile completeness and keyword
signals in their notes. Results are written back to the database.

Scoring rules:
    +20  has email
    +20  has linkedin_url
    +20  has website
    +15  has phone
    +10  company name is not empty
    +15  notes contain a growth keyword (growing, hiring, new, launch, expand)
    ---
    100  maximum

# TODO: Replace rule-based scoring with Claude AI scoring for higher accuracy.
#       Will require ANTHROPIC_API_KEY in a .env file.

Usage:
    from scorer import score_prospect, score_and_update, score_all_new

    result = score_and_update(prospect_id=3)
    print(result["score"], result["reasoning"])

    results = score_all_new()
"""

from database import DB_PATH, get_all_prospects, update_lead_score, update_notes

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Keywords in notes that signal a prospect is in active growth mode.
GROWTH_KEYWORDS = {"growing", "hiring", "new", "launch", "expand"}

# Point values for each rule.
POINTS = {
    "email":    20,
    "linkedin": 20,
    "website":  20,
    "phone":    15,
    "company":  10,
    "keywords": 15,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def score_prospect(prospect: dict) -> dict:
    """
    Score a single prospect using profile-completeness and keyword rules.

    Does NOT touch the database - just evaluates and returns the result.
    Use score_and_update() to also save the result to the DB.

    Args:
        prospect: A prospect dict (as returned by database.get_all_prospects).

    Returns:
        A dict with:
            "score"     - integer 1-100
            "reasoning" - human-readable breakdown of points awarded
    """
    score = 0
    reasons = []

    if prospect.get("email"):
        score += POINTS["email"]
        reasons.append(f"has email (+{POINTS['email']})")

    if prospect.get("linkedin_url"):
        score += POINTS["linkedin"]
        reasons.append(f"has LinkedIn (+{POINTS['linkedin']})")

    if prospect.get("website"):
        score += POINTS["website"]
        reasons.append(f"has website (+{POINTS['website']})")

    if prospect.get("phone"):
        score += POINTS["phone"]
        reasons.append(f"has phone (+{POINTS['phone']})")

    if prospect.get("company", "").strip():
        score += POINTS["company"]
        reasons.append(f"has company (+{POINTS['company']})")

    notes_lower = (prospect.get("notes") or "").lower()
    matched = [kw for kw in GROWTH_KEYWORDS if kw in notes_lower]
    if matched:
        score += POINTS["keywords"]
        reasons.append(f"growth keywords {matched} (+{POINTS['keywords']})")

    # Clamp to 1-100 (minimum 1 so no prospect scores zero)
    score = max(1, min(score, 100))

    reasoning = "; ".join(reasons) if reasons else "no signals found"
    return {"score": score, "reasoning": reasoning}


def score_and_update(prospect_id: int, db_path: str = DB_PATH) -> dict:
    """
    Score a prospect and write the result back to the database.

    The reasoning breakdown is appended to the prospect's existing notes
    (prefixed with "[Score]" so it's easy to identify).

    Args:
        prospect_id: ID of the prospect to score.
        db_path:     Path to the database file.

    Returns:
        A dict with "prospect_id", "score", and "reasoning".

    Raises:
        ValueError: If the prospect ID is not found.
    """
    all_prospects = get_all_prospects(db_path)
    prospect = next((p for p in all_prospects if p["id"] == prospect_id), None)

    if prospect is None:
        raise ValueError(f"No prospect found with id={prospect_id}")

    result = score_prospect(prospect)

    update_lead_score(prospect_id, result["score"], db_path)

    score_note = f"[Score] {result['reasoning']}"
    existing = (prospect.get("notes") or "").strip()
    combined = f"{existing}\n{score_note}" if existing else score_note
    update_notes(prospect_id, combined, db_path)

    return {
        "prospect_id": prospect_id,
        "score": result["score"],
        "reasoning": result["reasoning"],
    }


def score_all_new(db_path: str = DB_PATH) -> list:
    """
    Score every prospect whose status is 'new'.

    Args:
        db_path: Path to the database file.

    Returns:
        A list of result dicts, each with "prospect_id", "score", "reasoning".
    """
    new_prospects = [
        p for p in get_all_prospects(db_path) if p["status"] == "new"
    ]

    if not new_prospects:
        print("No 'new' prospects to score.")
        return []

    print(f"Scoring {len(new_prospects)} prospect(s) with status='new'...\n")
    results = []

    for prospect in new_prospects:
        result = score_and_update(prospect["id"], db_path)
        print(
            f"  {prospect['name']:<20} {prospect['company']:<22} "
            f"score: {result['score']:>3}"
        )
        results.append(result)

    return results
