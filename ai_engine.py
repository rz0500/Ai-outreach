"""
ai_engine.py - AI Engine (Claude-Powered)
==========================================
Module 9 of the AI Lead Generation & Outreach System.

Uses the Anthropic SDK to provide two AI-powered functions:

  generate_hyper_personalized_email(prospect)
      Writes a casual, personalised cold outreach email based on the
      prospect's profile, role, company, and notes. Returns a subject
      line and full email body.

  analyze_prospect_score(prospect)
      Qualifies a prospect on a 1-100 scale using AI reasoning across
      all available data points. Returns a score and written rationale.

Both functions share a single Anthropic client and use prompt caching on
their system prompts so repeated bulk calls don't re-send the same tokens.

Model is set to claude-haiku-4-5 by default (fast and cheap for bulk runs).
Change MODEL at the top of the file for higher-quality output.

Configuration:
    Set ANTHROPIC_API_KEY in your .env file (see .env.example).

Usage:
    from ai_engine import generate_hyper_personalized_email, analyze_prospect_score

    prospect = {
        "name": "Jane Doe", "company": "Acme Corp",
        "email": "jane@acme.com", "linkedin_url": "...",
        "website": "...", "phone": "...",
        "lead_score": 85, "status": "qualified",
        "notes": "VP of Sales. Company just raised Series B.",
    }

    email  = generate_hyper_personalized_email(prospect)
    result = analyze_prospect_score(prospect)
    print(email["subject"], email["body"])
    print(result["score"], result["reasoning"])
"""

import json

import anthropic
from dotenv import load_dotenv
from settings import get_calendar_link

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Cheap and fast for bulk runs. Swap to "claude-opus-4-6" for higher quality.
MODEL = "claude-haiku-4-5"

# Single client instance shared by both functions.
# Reads ANTHROPIC_API_KEY from the environment automatically.
_client = anthropic.Anthropic()

# ---------------------------------------------------------------------------
# System prompts (stable — cached on first call, ~90% cheaper on repeats)
# ---------------------------------------------------------------------------

_EMAIL_SYSTEM_PROMPT = """\
You write cold outbound email. Conversational. Human. Commercially sharp. Not corporate.

You are not writing a pitch. You are writing something that reads like a smart person sent it in 5 minutes.

Internal workflow you must follow:
1. COMPANY ANALYSIS
Extract, using only provided data:
- what market/niche they are in
- who their buyer is (ICP)
- key product or offer
- any growth signal (hiring, ads, funding, launch)
- outbound activity or lack of it
- relevant competitor, only if explicitly mentioned

2. ANGLE DECISION
Pick exactly one primary angle:
- positioning / outbound gap / competitor / hiring signal / product feature / funnel weakness

3. TRACEABILITY CHECK
Every sentence must be traceable to provided data or a clear logical inference.
Remove anything that is not.

Email structure — follow this exactly:

Paragraph 1 (market truth opener):
Describe how businesses in their market typically grow — empathetically, not critically.
Example: "Most photography studios grow the same way: word of mouth, the occasional referral, waiting for the right inquiry to land."
Make it specific to their industry. Use their actual niche if you know it.

Paragraph 2 (tension line — standalone, 1 sentence):
A short, isolated line that introduces the gap without being aggressive.
Example: "It works — until it doesn't."
Other patterns: "That changes when you bring on headcount." / "It works — until a competitor shows up first."

Paragraph 3 (what we do + mechanism):
Name the company. Explain what we do specifically for their type of business. Then add "That means..." with 2-3 concrete things.
Example: "We build outbound pipelines specifically for studios like Harbor. That means researching real prospects, writing emails that don't sound like blasts, and getting you on calls with people who are actually a fit."

Paragraph 4 (risk reversal + personal selection):
Frame it as a limited pilot offer. Make them feel chosen, not mass-blasted.
Example: "We're opening this up to 5 studios for free to prove it works. Harbor's one of the ones I had in mind."

CTA line (soft question — not a command):
"Worth a 15-minute call?"

Then on its own line: {calendar_link}

Sign-off: — [Name]

Rules:
- Total body: 90-130 words
- No bullet points in the email body
- No fake compliments ("I love what you're doing")
- No generic openers ("I wanted to reach out", "I noticed your website")
- No "companies like yours", "businesses like yours", "in your space"
- No "AI-powered", "game-changer", "leverage", "synergy"
- No opt-out line ("If not relevant, reply no thanks")
- No exclamation marks
- No long paragraphs — each paragraph is 1-3 sentences
- Use em dash (—) only in the tension line
- The company name must appear in paragraph 3 at minimum
- CTA must be a question, not a command

Subject line: short (3-6 words), plain, no clickbait.
Vary it with the angle when possible.
Examples: "Harbor hiring" / "Harbor and 6sense" / "Harbor pipeline" / "quick question, Leah"

Before answering, check:
- Does it read like a human wrote it?
- Is the market truth opener specific to their industry?
- Is paragraph 3 naming the company and explaining the mechanism?
- Is the CTA a question?
If any check fails, rewrite.

Respond with ONLY this JSON object and nothing else:
{{"subject": "<subject line>", "body": "<email body with \\n for newlines>"}}\
""".format(calendar_link=get_calendar_link())

_SCORE_SYSTEM_PROMPT = """\
You are an expert B2B sales qualification analyst. You evaluate prospects \
on a 1-100 scale based on all available signals in their profile.

Scoring rubric:
  71-100  Hot  -- strong fit, clear buying signals, easy to reach, act now
  41-70   Warm -- reasonable fit, some signals, worth pursuing
  1-40    Cold -- poor fit, missing data, unlikely to convert soon

Signals to weigh:
  - Seniority and decision-making authority (title, role)
  - Company size and growth trajectory (funding, hiring, expansion)
  - Contact data completeness (email, LinkedIn, phone, website)
  - Explicit pain points or intent signals in notes
  - Pipeline status (qualified > new > other)
  - Keywords suggesting urgency (launch, hiring, new, expand, raised)
  - Visible outbound gap: no ads, no cold sequence, no SDR team

You MUST respond with ONLY a JSON object in this exact format:
{"score": <integer 1-100>, "reasoning": "<2-3 sentence explanation>"}
No markdown, no explanation -- only the JSON object.\
"""

_WEBSITE_SYSTEM_PROMPT = """\
You are an expert B2B sales researcher. Analyze the website text and extract structured intelligence for outreach personalization.

You MUST respond with ONLY a JSON object in this exact format (all fields required, use empty string "" if you cannot determine a value):
{
  "niche": "<what this company specifically does, 1 concise sentence>",
  "icp": "<who their ideal customer is, based on site language>",
  "website_headline": "<exact hero/H1 copy from their homepage, verbatim if visible>",
  "product_feature": "<their most distinctive product feature or unique angle>",
  "competitors": "<comma-separated real competitor names if mentioned on the site, else empty string>",
  "pain_point": "<1 sentence potential pain point their customers face>",
  "growth_signal": "<1 sentence growth signal visible on the site>",
  "hook": "<1 personalized sentence to use as a cold email opening — must cite something specific from the site>"
}
No markdown, no explanation — only the JSON object.\
"""

_REPLY_SYSTEM_PROMPT = """\
You are an expert SDR reply analyst. Classify the intent of an inbound reply to a cold outreach email.

Categories:
- "interested"      — they want to learn more, asked a question, or expressed positive intent
- "booked"          — they have confirmed a meeting, accepted a calendar invite, or said "see you then"
- "not_interested"  — explicitly declined or said timing is wrong
- "opt_out"         — asked to be removed, unsubscribe, stop emailing
- "out_of_office"   — automated OOO message
- "auto_reply"      — generic auto-reply (not a real human response)

If the classification is "interested" or "booked", also draft a short (2-3 sentence) warm reply from the sender.
For "booked" replies, the drafted reply should confirm the meeting and express enthusiasm.
Keep it low-pressure, specific, and human. No fluff.

Respond with ONLY this JSON:
{"classification": "<category>", "reasoning": "<1 sentence>", "drafted_reply": "<reply body if interested or booked, else empty string>"}
No markdown, no explanation — only the JSON object.\
"""

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _prospect_to_text(prospect: dict) -> str:
    """Render a prospect dict as a compact profile string for the prompt."""
    fields = [
        ("Name",        prospect.get("name")),
        ("Company",     prospect.get("company")),
        ("Email",       prospect.get("email")),
        ("LinkedIn",    prospect.get("linkedin_url")),
        ("Website",     prospect.get("website")),
        ("Phone",       prospect.get("phone")),
        ("Lead score",  prospect.get("lead_score")),
        ("Status",      prospect.get("status")),
        ("Notes",       prospect.get("notes")),
    ]
    lines = [f"{label}: {value}" for label, value in fields if value is not None]
    return "\n".join(lines)


def _extract_json(response: anthropic.types.Message) -> dict:
    """
    Pull the text from the first TextBlock in the response and parse it as
    JSON. Raises ValueError if parsing fails.
    """
    for block in response.content:
        if block.type == "text":
            raw = block.text.strip()
            cleaned = raw
            if cleaned.startswith("```"):
                lines = cleaned.splitlines()
                if lines and lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                cleaned = "\n".join(lines).strip()
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"AI returned invalid JSON: {block.text!r}"
                ) from exc
    raise ValueError("AI response contained no text block.")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _build_enrichment_block(prospect: dict) -> str:
    """
    Build a structured enrichment context block from all available prospect fields.
    Only includes fields that have real data so the model knows exactly what it has.
    """
    lines = ["PROSPECT DATA:"]

    # Core identity
    if prospect.get("name"):        lines.append(f"Name: {prospect['name']}")
    if prospect.get("company"):     lines.append(f"Company: {prospect['company']}")
    if prospect.get("email"):       lines.append(f"Email: {prospect['email']}")
    if prospect.get("website"):     lines.append(f"Website: {prospect['website']}")
    if prospect.get("linkedin_url"): lines.append(f"LinkedIn: {prospect['linkedin_url']}")
    if prospect.get("lead_score"):  lines.append(f"Lead score: {prospect['lead_score']}")

    # Enrichment fields (new schema fields)
    if prospect.get("niche"):
        lines.append(f"\nWhat they do (niche): {prospect['niche']}")
    if prospect.get("icp"):
        lines.append(f"Their ideal customer (ICP): {prospect['icp']}")
    if prospect.get("website_headline"):
        lines.append(f"Website hero copy: {prospect['website_headline']}")
    if prospect.get("competitors"):
        lines.append(f"Known competitors: {prospect['competitors']}")
    if prospect.get("product_feature"):
        lines.append(f"Product feature / angle: {prospect['product_feature']}")
    if prospect.get("hiring_signal"):
        lines.append(f"Hiring signal: {prospect['hiring_signal']}")
    if prospect.get("linkedin_activity"):
        lines.append(f"Recent LinkedIn activity: {prospect['linkedin_activity']}")
    if prospect.get("ad_status"):
        lines.append(f"Ad presence: {prospect['ad_status']}")
    if prospect.get("outbound_status"):
        lines.append(f"Outbound activity: {prospect['outbound_status']}")
    if prospect.get("notable_result"):
        lines.append(f"Notable case study / result we can reference: {prospect['notable_result']}")

    # Research hook from website crawl
    notes = prospect.get("notes") or ""
    if notes:
        if "[Research Hook]" in notes:
            lines.append(f"\nWEBSITE RESEARCH HOOK:\n{notes}")
        else:
            lines.append(f"\nAdditional notes: {notes}")

    return "\n".join(lines)


def generate_hyper_personalized_email(prospect: dict) -> dict:
    """
    Generate a hyper-specific, observation-driven cold outreach email.

    Uses all available enrichment fields (niche, competitors, hiring signals,
    website headline, ICP, LinkedIn activity) to give Claude the real
    intelligence needed to write an email that sounds researched, not templated.

    Validates the output before returning it. If validation fails, raises
    ValueError so the caller can handle the fallback.

    Args:
        prospect: A prospect dict as returned by database.get_all_prospects().

    Returns:
        A dict with:
            "subject"         -- specific subject line
            "body"            -- full email body (plain text)
            "quality_score"   -- integer 0-100 from validator
            "warnings"        -- list of soft warnings from validator

    Raises:
        anthropic.AuthenticationError: ANTHROPIC_API_KEY is missing or invalid.
        ValueError: AI returned unparseable output or email failed quality gate.
    """
    from email_validator import (
        check_enrichment_sufficiency,
        score_internal_quality,
        validate_email,
    )
    from outreach import analyze_company, choose_primary_angle

    # Enrichment check - warn if data is weak
    sufficient, missing_mandatory, missing_optional = check_enrichment_sufficiency(prospect)
    if not sufficient:
        raise ValueError(
            f"Prospect is missing mandatory fields: {missing_mandatory}. Cannot generate email."
        )
    if len(missing_optional) >= 6:
        import logging
        logging.warning(
            f"[ai_engine] Prospect '{prospect.get('company')}' has minimal enrichment. "
            f"Missing: {missing_optional[:4]}. Email quality may be low."
        )

    enrichment_block = _build_enrichment_block(prospect)

    user_prompt = (
        f"{enrichment_block}\n\n"
        f"TASK:\n"
        f"Write a cold outreach email for {prospect.get('company', 'this company')}.\n"
        f"The email must be specific to them only. "
        f"Use the data above to find one real, grounded observation to open with.\n"
        f"If competitor names are listed above, you may reference them by name. "
        f"If none are listed, do not invent competitors.\n"
        f"If the enrichment data is thin, write a shorter honest email rather than "
        f"faking specificity."
    )

    response = _client.messages.create(
        model=MODEL,
        max_tokens=512,
        system=[
            {
                "type": "text",
                "text": _EMAIL_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_prompt}],
    )

    result = _extract_json(response)

    if "subject" not in result or "body" not in result:
        raise ValueError(f"AI response missing 'subject' or 'body' keys: {result}")

    subject = str(result["subject"])
    body = str(result["body"])

    # --- Output quality gate ---
    analysis = analyze_company(prospect)
    angle = choose_primary_angle(analysis)
    validation = validate_email(subject, body, prospect)
    internal_quality = score_internal_quality(subject, body, prospect, analysis, validation)
    if not validation.passed:
        raise ValueError(
            f"Generated email failed quality gate for '{prospect.get('company')}'.\n"
            f"{validation.summary()}"
        )
    if internal_quality.rewrite_required:
        raise ValueError(
            f"Generated email failed internal quality thresholds for '{prospect.get('company')}'. "
            f"Specificity={internal_quality.specificity}, "
            f"Credibility={internal_quality.credibility}, "
            f"GenericRisk={internal_quality.generic_risk}"
        )

    return {
        "subject": subject,
        "body": body,
        "quality_score": validation.quality_score,
        "warnings": validation.warnings,
        "specificity": internal_quality.specificity,
        "credibility": internal_quality.credibility,
        "generic_risk": internal_quality.generic_risk,
        "angle": angle,
    }


def analyze_prospect_score(prospect: dict) -> dict:
    """
    Score a prospect 1-100 using AI reasoning across all available signals.

    The system prompt is cache-controlled so repeated bulk calls reuse
    the cached prefix instead of re-sending it each time.

    Args:
        prospect: A prospect dict as returned by database.get_all_prospects().

    Returns:
        A dict with:
            "score"     — integer 1-100 (1-40 cold, 41-70 warm, 71-100 hot)
            "reasoning" — 2-3 sentence rationale

    Raises:
        anthropic.AuthenticationError: ANTHROPIC_API_KEY is missing or invalid.
        anthropic.RateLimitError:       Too many requests — back off and retry.
        anthropic.APIStatusError:       Other API-level error.
        ValueError:                     AI returned unparseable output or out-of-range score.
    """
    profile = _prospect_to_text(prospect)

    response = _client.messages.create(
        model=MODEL,
        max_tokens=256,
        system=[
            {
                "type": "text",
                "text": _SCORE_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": (
                    f"Qualify this prospect and return their score:\n\n{profile}"
                ),
            }
        ],
    )

    result = _extract_json(response)

    if "score" not in result or "reasoning" not in result:
        raise ValueError(
            f"AI response missing 'score' or 'reasoning' keys: {result}"
        )

    score = int(result["score"])
    if not (1 <= score <= 100):
        raise ValueError(f"AI returned out-of-range score: {score}")

    return {"score": score, "reasoning": str(result["reasoning"])}


def analyze_website(company: str, website_text: str) -> dict:
    """
    Analyze scraped website text to extract enrichment intelligence:
    niche, ICP, hero copy, product feature, competitors, pain point,
    growth signal, and a personalized opener hook.
    """
    response = _client.messages.create(
        model=MODEL,
        max_tokens=512,
        system=[
            {
                "type": "text",
                "text": _WEBSITE_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": f"Analyze this website text for {company}:\n\n{website_text[:15000]}"
            }
        ],
    )

    result = _extract_json(response)

    required_keys = ["niche", "icp", "website_headline", "product_feature",
                     "competitors", "pain_point", "growth_signal", "hook"]
    missing = [k for k in required_keys if k not in result]
    if missing:
        raise ValueError(f"AI response missing required keys {missing}: {result}")

    # Normalise: ensure all values are strings
    for k in required_keys:
        result[k] = str(result.get(k) or "")

    return result


def classify_reply(prospect: dict, reply_body: str) -> dict:
    """
    Classify the intent of an inbound reply to a cold outreach email.

    Args:
        prospect:   Prospect dict (for context).
        reply_body: Plain-text body of the reply email.

    Returns:
        A dict with:
            "classification" — one of: interested, not_interested, opt_out,
                               out_of_office, auto_reply
            "reasoning"      — 1-sentence rationale
            "drafted_reply"  — suggested reply body if classification is
                               "interested", else empty string

    Raises:
        anthropic.AuthenticationError: ANTHROPIC_API_KEY missing or invalid.
        ValueError:                    AI returned unparseable JSON.
    """
    profile = _prospect_to_text(prospect)

    response = _client.messages.create(
        model=MODEL,
        max_tokens=300,
        system=[
            {
                "type": "text",
                "text": _REPLY_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": (
                    f"Prospect context:\n{profile}\n\n"
                    f"Inbound reply:\n{reply_body[:2000]}"
                ),
            }
        ],
    )

    result = _extract_json(response)

    valid_categories = {"interested", "booked", "not_interested", "opt_out", "out_of_office", "auto_reply"}
    classification = result.get("classification", "")
    if classification not in valid_categories:
        raise ValueError(f"AI returned unknown classification '{classification}'")

    return {
        "classification": classification,
        "reasoning": str(result.get("reasoning") or ""),
        "drafted_reply": str(result.get("drafted_reply") or ""),
    }
