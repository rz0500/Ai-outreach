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

from __future__ import annotations

from copy import deepcopy

from database import (
    DB_PATH,
    get_all_prospects,
    get_outreach_by_prospect,
    initialize_outreach_table,
    save_outreach,
    update_outreach_status,
)
from email_validator import (
    check_enrichment_sufficiency,
    score_internal_quality,
    validate_email,
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

OPT_OUT_LINE = (
    "If not relevant, reply no thanks."
)
PRIMARY_ANGLES = (
    "positioning",
    "hiring signal",
    "competitor",
    "outbound gap",
    "product feature",
    "ICP mismatch",
    "funnel weakness",
)
CALENDAR_LINK = "[Calendar link]"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _first_name(full_name: str) -> str:
    """Return just the first word of a name."""
    return full_name.strip().split()[0] if full_name.strip() else "there"


def _clean(value: str | None) -> str:
    """Normalize optional text fields."""
    return (value or "").strip()


def _extract_competitors(raw: str | None) -> list[str]:
    """Return a clean list of competitor names."""
    if not raw:
        return []
    parts = [p.strip() for p in raw.split(",")]
    return [p for p in parts if p and len(p) > 1]


def _evidence_count(analysis: dict) -> int:
    """Count how many structured evidence slots contain real data."""
    keys = (
        "company_positioning",
        "target_customer",
        "key_offer_or_feature",
        "recent_signal",
        "outbound_evidence",
        "possible_gap",
        "relevant_competitor",
    )
    return sum(1 for key in keys if _clean(analysis.get(key)))


def _operator_market_label(prospect: dict, analysis: dict) -> str:
    """Return a concise market label for operator-style outreach."""
    niche = _clean(prospect.get("niche")) or _clean(analysis.get("company_positioning"))
    icp = _clean(prospect.get("icp")) or _clean(analysis.get("target_customer"))
    company = _clean(prospect.get("company")) or "this company"
    low = f"{niche} {icp}".lower()

    if any(word in low for word in ("studio", "photography", "photo booth", "wedding")):
        return "studios"
    if any(word in low for word in ("agency", "creative", "design", "branding")):
        return "agencies"
    if any(word in low for word in ("saas", "software", "crm", "platform")):
        return "SaaS teams"
    if any(word in low for word in ("cyber", "security vendor", "security vendors")):
        return "cybersecurity vendors"
    if any(word in low for word in ("clinic", "health", "dental", "med")):
        return "healthcare teams"
    if any(word in low for word in ("law", "legal", "firm", "attorney")):
        return "law firms"
    if any(word in low for word in ("freight", "logistics", "shipping", "supply chain")):
        return "logistics teams"
    if any(word in low for word in ("tax", "account", "finance", "cpa")):
        return "advisory firms"
    if any(word in low for word in ("coach", "coaching", "learning", "training", "education")):
        return "coaching businesses"
    if any(word in low for word in ("consult", "advisor", "coach")):
        return "consultancies"
    return "teams in this market"


def _possessive(name: str) -> str:
    """Return a readable possessive form for a company name."""
    if not name:
        return "This company's"
    return f"{name}'" if name.endswith("s") else f"{name}'s"


def _operator_truth(angle: str, market_label: str) -> str:
    """Return a blunt market truth based on the chosen angle."""
    truths = {
        "hiring signal": "New hires do not fix demand. They expose the gap faster.",
        "competitor": f"Most {market_label} do not lose on offer. They lose on who gets to buyers first.",
        "outbound gap": f"Most {market_label} rely on referrals and inbound. That is not a pipeline, it is drift.",
        "product feature": "A sharp offer still gets ignored if nobody is putting it in front of the right buyers.",
        "ICP mismatch": "A defined buyer is wasted if the outreach still feels broad.",
        "funnel weakness": "When one channel carries demand, growth gets fragile fast.",
        "positioning": f"Clear positioning is useless if it never leaves the website.",
    }
    return truths.get(angle, f"Most {market_label} rely on inbound longer than they should.")


def _operator_offer(market_label: str) -> str:
    """Return a blunt explanation of the service."""
    return f"We build outbound pipelines for {market_label}. Custom emails, real prospects, booked calls."


def _operator_risk_reversal(company: str) -> str:
    """Return a simple risk-reversal line."""
    return f"I'm opening 5 pilot slots this month. {company} is on the shortlist."


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


def analyze_company(prospect: dict) -> dict:
    """
    === COMPANY ANALYSIS ===

    Extract only evidence-backed observations from the provided prospect data.
    No guessing, no hallucination.
    """
    notes = _clean(prospect.get("notes"))
    headline = _clean(prospect.get("website_headline"))
    niche = _clean(prospect.get("niche"))
    icp = _clean(prospect.get("icp"))
    product_feature = _clean(prospect.get("product_feature"))
    hiring_signal = _clean(prospect.get("hiring_signal"))
    linkedin_activity = _clean(prospect.get("linkedin_activity"))
    outbound_status = _clean(prospect.get("outbound_status"))
    ad_status = _clean(prospect.get("ad_status"))
    competitors = _extract_competitors(prospect.get("competitors"))
    company = _clean(prospect.get("company"))

    company_positioning = headline or niche
    recent_signal = hiring_signal or linkedin_activity
    inferred_icp = ""
    inferred_motion = ""

    if not icp and company_positioning:
        inferred_icp = "Clear positioning usually means the team knows exactly which buyer it wants."
    if niche and "saas" in niche.lower():
        inferred_motion = "SaaS teams usually grow through inbound, sales-led motion, or both."

    if outbound_status == "no_outbound":
        outbound_evidence = f"{company} is marked as no_outbound"
    elif outbound_status:
        outbound_evidence = f"{company} outbound status is {outbound_status}"
    elif ad_status == "running_ads":
        outbound_evidence = f"{company} is running_ads"
    elif inferred_motion:
        outbound_evidence = inferred_motion
    else:
        outbound_evidence = ""

    possible_gap = ""
    logical_inference = ""
    if hiring_signal:
        possible_gap = "New hiring usually exposes whether the pipeline is already strong enough to feed the team."
        logical_inference = "Derived from the provided hiring signal."
    elif competitors and outbound_status == "no_outbound":
        possible_gap = "Named competitors are present while outbound activity is marked as absent."
        logical_inference = "Derived from explicit competitor and outbound-status fields."
    elif outbound_status == "no_outbound":
        possible_gap = "When no outbound motion is visible, high-intent buyers are usually left to inbound alone."
        logical_inference = "Derived from the explicit outbound_status field."
    elif ad_status == "running_ads":
        possible_gap = "When paid acquisition carries demand, the funnel usually gets fragile."
        logical_inference = "Derived from the explicit ad_status field."
    elif product_feature and icp:
        possible_gap = "A specific offer and buyer usually means there is room for sharper outbound."
        logical_inference = "Derived from the product feature and ICP fields."
    elif company_positioning:
        possible_gap = "Clear positioning usually means the buyer is defined well enough to support direct outbound."
        logical_inference = "Derived from the provided positioning data."

    sufficient, missing_mandatory, missing_optional = check_enrichment_sufficiency(prospect)
    weak_data_mode = _evidence_count({
        "company_positioning": company_positioning,
        "target_customer": icp or inferred_icp,
        "key_offer_or_feature": product_feature,
        "recent_signal": recent_signal,
        "outbound_evidence": outbound_evidence,
        "possible_gap": possible_gap,
        "relevant_competitor": competitors[0] if competitors else "",
    }) < 2

    return {
        "company_positioning": company_positioning,
        "target_customer": icp or inferred_icp,
        "key_offer_or_feature": product_feature,
        "recent_signal": recent_signal,
        "outbound_evidence": outbound_evidence,
        "possible_gap": possible_gap,
        "relevant_competitor": competitors[0] if competitors else "",
        "all_competitors": competitors,
        "logical_inference": logical_inference,
        "notes": notes,
        "weak_data_mode": weak_data_mode,
        "needs_enrichment": (not sufficient) or weak_data_mode,
        "missing_mandatory": missing_mandatory,
        "missing_optional": missing_optional,
    }


def choose_primary_angle(analysis: dict) -> str:
    """
    Pick one strongest angle and build the email around it.
    """
    if _clean(analysis.get("recent_signal")) and "hiring" in analysis["recent_signal"].lower():
        return "hiring signal"
    if _clean(analysis.get("relevant_competitor")) and (
        "absent" in analysis.get("possible_gap", "").lower()
        or "no_outbound" in analysis.get("outbound_evidence", "").lower()
        or "no outbound" in analysis.get("possible_gap", "").lower()
    ):
        return "competitor"
    if "no outbound" in analysis.get("possible_gap", "").lower():
        return "outbound gap"
    if _clean(analysis.get("key_offer_or_feature")):
        return "product feature"
    if _clean(analysis.get("company_positioning")) and _clean(analysis.get("target_customer")):
        return "positioning"
    if _clean(analysis.get("target_customer")) and not _clean(analysis.get("company_positioning")):
        return "ICP mismatch"
    if "paid acquisition" in analysis.get("possible_gap", "").lower():
        return "funnel weakness"
    return "positioning"


def _weak_data_email(prospect: dict, analysis: dict) -> dict:
    """Return a short operator-style email when evidence is thin."""
    first = _first_name(prospect.get("name", "there"))
    company = prospect.get("company", "your company")
    market_label = _operator_market_label(prospect, analysis)
    subject = f"{company} outbound"
    body = (
        f"Hi {first},\n\n"
        f"{company} already looks specific enough to sell directly.\n"
        f"Most {market_label} still lean on inbound. That is not a growth plan.\n"
        f"{_operator_offer(market_label)}\n"
        f"{_operator_risk_reversal(company)}\n"
        f"If it sounds useful, grab a time here: {CALENDAR_LINK}\n\n"
        f"{OPT_OUT_LINE}\n\n"
        f"[Name]"
    )
    return {"subject": subject, "body": body, "needs_enrichment": True}


def _build_data_driven_email(
    prospect: dict,
    analysis: dict,
    angle: str,
    rewrite_pass: int = 0,
) -> dict:
    """
    Build an email from structured analysis and a single primary angle.
    """
    first = _first_name(prospect.get("name", "there"))
    company = prospect.get("company", "your company")
    positioning = analysis.get("company_positioning") or company
    icp = analysis.get("target_customer") or "their buyer"
    feature = analysis.get("key_offer_or_feature") or positioning
    recent_signal = analysis.get("recent_signal") or ""
    competitor = analysis.get("relevant_competitor") or ""
    possible_gap = analysis.get("possible_gap") or ""

    market_label = _operator_market_label(prospect, analysis)

    if angle == "hiring signal":
        subject = f"{company} hiring"
        opening = f"{company} is {recent_signal}."
    elif angle == "competitor":
        subject = f"{company} and {competitor}"
        opening = f"{competitor} is already in the lane with {company}."
    elif angle == "outbound gap":
        subject = f"{company} outbound"
        opening = f"{company} looks built for direct outbound."
    elif angle == "product feature":
        feature_words = " ".join(feature.split()[:4]).strip()
        subject = f"{company} {feature_words}".strip()
        opening = f"{_possessive(company)} {feature} is the kind of offer that should travel well in cold outreach."
    elif angle == "funnel weakness":
        subject = f"{company} funnel"
        opening = f"{company} looks too dependent on paid demand."
    elif angle == "ICP mismatch":
        subject = f"{company} ICP"
        opening = f"{company} already knows the buyer: {icp}."
    else:
        subject = f"{company} positioning"
        opening = f"{company} is positioned around {positioning}."

    truth = _operator_truth(angle, market_label)
    offer = _operator_offer(market_label)
    risk_reversal = _operator_risk_reversal(company)
    ctas = [
        f"If it sounds useful, grab a time here: {CALENDAR_LINK}",
        f"If it is worth 15 minutes, book here: {CALENDAR_LINK}",
        f"If you want to see it, grab a slot here: {CALENDAR_LINK}",
    ]
    cta = ctas[min(rewrite_pass, len(ctas) - 1)]

    body = (
        f"Hi {first},\n\n"
        f"{opening}\n"
        f"{truth}\n"
        f"{offer}\n"
        f"{risk_reversal}\n"
        f"{cta}\n\n"
        f"{OPT_OUT_LINE}\n\n"
        f"[Name]"
    )
    return {"subject": subject, "body": body, "needs_enrichment": False}


def debug_email_reasoning(prospect: dict) -> dict:
    """
    Return analysis, chosen angle, quality score, and final email for debugging.
    """
    analysis = analyze_company(prospect)
    angle = choose_primary_angle(analysis)
    draft = _weak_data_email(prospect, analysis) if analysis["weak_data_mode"] else None

    if not draft:
        for rewrite_pass in range(2):
            candidate = _build_data_driven_email(prospect, analysis, angle, rewrite_pass=rewrite_pass)
            validation = validate_email(candidate["subject"], candidate["body"], prospect)
            quality = score_internal_quality(candidate["subject"], candidate["body"], prospect, analysis, validation)
            if not quality.rewrite_required:
                draft = {**candidate, "validation": validation, "internal_quality": quality}
                break
        if not draft:
            candidate = _weak_data_email(prospect, analysis)
            validation = validate_email(candidate["subject"], candidate["body"], prospect)
            quality = score_internal_quality(candidate["subject"], candidate["body"], prospect, analysis, validation)
            draft = {**candidate, "validation": validation, "internal_quality": quality}
    else:
        validation = validate_email(draft["subject"], draft["body"], prospect)
        quality = score_internal_quality(draft["subject"], draft["body"], prospect, analysis, validation)
        draft = {**draft, "validation": validation, "internal_quality": quality}

    return {
        "analysis": analysis,
        "angle": angle,
        "email": {
            "subject": draft["subject"],
            "body": draft["body"],
        },
        "validation": draft["validation"],
        "internal_quality": draft["internal_quality"],
    }


def _build_subject(first_name: str, company: str, signals: dict) -> str:
    """Pick a specific subject line based on available signals."""
    if signals["warm_intro"]:
        return f"Introduction for {first_name}"
    if signals["funding"]:
        return f"{company} post-raise"
    if signals["growth"]:
        return f"{company} growth"
    if signals["pain"]:
        return f"{company} outbound gap"
    if signals["content"]:
        return f"Your post + a thought for {company}"
    return f"{company} outbound"


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
    Generate a cold email from structured evidence, not loose text generation.

    Internally this runs:
      1. COMPANY ANALYSIS
      2. primary-angle decision
      3. email generation
      4. validation and internal quality scoring
      5. one rewrite if needed, then weak-data fallback

    Final output remains clean: subject + body, plus internal scores for callers.
    """
    debug = debug_email_reasoning(prospect)
    quality = debug["internal_quality"]
    return {
        "subject": debug["email"]["subject"],
        "body": debug["email"]["body"],
        "quality_score": (quality.specificity * 10 + quality.credibility * 10) // 2,
        "specificity": quality.specificity,
        "credibility": quality.credibility,
        "generic_risk": quality.generic_risk,
        "angle": debug["angle"],
        "needs_enrichment": debug["analysis"]["needs_enrichment"],
    }


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
