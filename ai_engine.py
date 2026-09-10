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
from settings import get_candidate_cv_url

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
You write cold outreach emails for graduate job hunting and direct career prospecting. Conversational. Human. Sharply observant. Never desperate or templated.

You represent Ritish — a BSc FinTech & Data Analytics graduate from the University of Westminster.
Ritish's profile:
- Degree: BSc FinTech & Data Analytics (University of Westminster)
- Technical Stack: Python, SQL, Power BI, Data Analysis, n8n workflow automation, Twilio & Stripe APIs
- Commercial Experience: Built & operated Harmony Booths (harmonybooths.com) managing sales, conversion funnels (CPL, ROAS), and client growth
- Work Rights: Full right to work in the UK & EU (Italian Passport)
- Target Roles: Graduate Data Analyst, Business Analyst, Product Analyst, RevOps Analyst, Commercial Analyst, FinTech Analyst, Junior Strategy/Ops Analyst

Your goal is to write a short, sharp 90-130 word email to a hiring manager, lead analyst, or operations leader at a target company.

Internal workflow:
1. COMPANY ANALYSIS
Extract from provided data:
- what product/niche they build
- their data stack, tech platform, or user focus
- growth signal (hiring, product launch, scale)

2. TRACEABILITY CHECK
Every sentence must be traceable to provided company data or a clear logical inference connecting Ritish's background.

Email structure — follow this exactly:

Paragraph 1 (Observation Opener):
Open with a specific, grounded observation about the target company's product, tech stack, data platform, or recent growth/hiring signal.
Example: "Noticed how [Company] is scaling [Product/Feature] and expanding your analytics team." or "Saw that [Company] relies heavily on real-time data pipelines for your [Niche/ICP] customers."

Paragraph 2 (Candidate Bridge & Proof):
Briefly connect Ritish's background directly to their work. Cite Ritish's BSc FinTech & Data Analytics degree from Westminster, Python/SQL/Power BI skills, and practical experience building Harmony Booths and automating workflows (n8n/APIs).
Example: "I recently finished my BSc in FinTech & Data Analytics at Westminster. Alongside Python, SQL, and Power BI, I've spent the past year building commercial automations and managing funnels for Harmony Booths."

Paragraph 3 (Value Alignment):
State 1-2 concrete ways Ritish could contribute to their team (e.g., building automated reporting dashboards, optimizing RevOps funnels, analyzing user metrics, streamlining API data flows).

CTA line (Low-friction question):
"Open to a brief 10-minute coffee chat or quick portfolio review this week?"

Sign-off:
Best regards,
Ritish
BSc FinTech & Data Analytics | University of Westminster
{{CV_LINK}}

Rules:
- Total body: 90-130 words
- No generic openers ("I hope this email finds you well", "I am writing to express my interest in a role")
- No desperate language ("Please give me a chance", "I am looking for any entry-level job")
- No buzzwords ("passionate", "synergy", "hardworking self-starter")
- Must name the target company in paragraph 1 & 3
- CTA must be a low-friction question

Subject line: short (3-6 words), plain, direct, e.g. "[Company] data & analytics — Ritish", "question for [Company] team", "Ritish / [Company] analytics".

Respond with ONLY this JSON object:
{"subject": "<subject line>", "body": "<email body with \\n for newlines>"}
"""

_EMAIL_SYSTEM_PROMPT = _EMAIL_SYSTEM_PROMPT.replace(
    "{{CV_LINK}}", f"CV: {get_candidate_cv_url()}"
)

_SCORE_SYSTEM_PROMPT = """\
You are an expert graduate career analyst. You evaluate target companies and hiring leads \
on a 1-100 scale based on how strong a target fit they are for a Graduate Data/Business/RevOps Analyst.

Scoring rubric:
  71-100  Hot  -- tech/fintech/SaaS company, active hiring signals, clear data/analytics focus, strong match
  41-70   Warm -- growing company, potential analytics needs, good target
  1-40    Cold -- non-tech, missing data, unlikely fit for analytical role

You MUST respond with ONLY a JSON object in this exact format:
{"score": <integer 1-100>, "reasoning": "<2-3 sentence explanation>"}
No markdown, no explanation -- only the JSON object.\
"""

_WEBSITE_SYSTEM_PROMPT = """\
You are an expert company & tech stack researcher. Analyze website text to extract structured intelligence for personalized graduate outreach.

You MUST respond with ONLY a JSON object in this exact format (all fields required, use empty string "" if you cannot determine a value):
{
  "niche": "<what this company specifically does, 1 concise sentence>",
  "icp": "<who their ideal customer is>",
  "website_headline": "<exact hero/H1 copy from homepage>",
  "product_feature": "<their core product feature, tech stack element, or data aspect>",
  "competitors": "<comma-separated competitor names if mentioned, else empty string>",
  "pain_point": "<1 sentence data/analytics/ops challenge relevant to their scale>",
  "growth_signal": "<1 sentence growth/hiring signal visible on site>",
  "hook": "<1 personalized sentence opening citing a specific product/tech detail from the site>"
}
No markdown, no explanation — only the JSON object.\
"""

_REPLY_SYSTEM_PROMPT = """\
You are an expert career outreach reply analyst. Classify the intent of an inbound reply from a target employer to a graduate cold email.

Categories:
- "interested"      — they want to chat, set up a call, ask for a CV/portfolio, or explore opportunities
- "booked"          — they confirmed an interview or coffee chat date/time
- "not_interested"  — no hiring right now, role filled, or not a fit
- "opt_out"         — asked to be removed from future emails
- "out_of_office"   — automated OOO message
- "auto_reply"      — generic system auto-reply

If the classification is "interested" or "booked", draft a short (2-3 sentence) warm, professional reply from Ritish confirming enthusiasm and availability.

Respond with ONLY this JSON:
{"classification": "<category>", "reasoning": "<1 sentence>", "drafted_reply": "<reply body if interested or booked, else empty string>"}
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
        f"faking specificity.\n"
        f"IMPORTANT: Always respond with the JSON object only. Never refuse or explain — "
        f"if data is limited, write a shorter simpler email but always return valid JSON."
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


def get_warmup_advice(warmup_status: dict, delivery_metrics: dict | None = None) -> dict:
    """
    Analyse warmup and real deliverability data, return a safe daily send
    recommendation with plain-English reasoning.

    Args:
        warmup_status:     dict from warmup_engine.get_combined_warmup_status().
        delivery_metrics:  dict from database.get_delivery_metrics() — real
                           bounce/reply/delivery rates from communication_events.
                           Pass None if no data yet (new account).

    Returns:
        {
            "recommended_limit": int,
            "confidence":        str,   # "high" | "medium" | "low"
            "summary":           str,
            "reasoning":         str,
            "warnings":          list[str],
        }
    """
    score        = warmup_status.get("mailivery_health_score")
    connected    = warmup_status.get("mailivery_connected", False)
    m_status     = warmup_status.get("mailivery_status")
    emails_today = warmup_status.get("mailivery_emails_today")
    ramp_day     = warmup_status.get("day", 0)
    ramp_limit   = warmup_status.get("daily_limit", 0)
    sent_today   = warmup_status.get("sent_today", 0)
    warmup_tot   = warmup_status.get("warmup_total", 0)
    warmup_td    = warmup_status.get("warmup_today", 0)
    fully_warmed = warmup_status.get("fully_warmed", False)
    tier_label   = warmup_status.get("tier_label", "unknown")
    configured   = warmup_status.get("configured", False)

    dm = delivery_metrics or {}

    snapshot = f"""
WARMUP SNAPSHOT
===============
Ramp configured:  {configured}
Day in warmup:    {ramp_day} {'(fully warmed)' if fully_warmed else ''}
Current tier:     {tier_label}
Schedule limit:   {ramp_limit if ramp_limit else 'no cap'} emails/day
Sent today:       {sent_today}
Warmup sent today: {warmup_td}
Warmup sent total: {warmup_tot}

MAILIVERY REPUTATION
Connected:        {connected}
Campaign status:  {m_status or 'not connected'}
Health score:     {score if score is not None else 'not available'} / 100
Warmup emails today (Mailivery): {emails_today if emails_today is not None else 'n/a'}

REAL DELIVERY SIGNAL (last {dm.get('days_window', 30)} days from actual sends)
Total emails sent:   {dm.get('total_sent', 'no data')}
Delivery rate:       {dm.get('delivery_rate_pct', 'n/a')}%
Bounce rate:         {dm.get('bounce_rate_pct', 'n/a')}%  ← danger if >3%
Spam reports:        {dm.get('spam_reports', 'n/a')}      ← danger if >0
Unsubscribes:        {dm.get('unsubscribes', 'n/a')}
Reply rate:          {dm.get('reply_rate_pct', 'n/a')}%
Recent failures:     {'; '.join(dm.get('recent_failures') or []) or 'none'}
""".strip()

    response = _client.messages.create(
        model=MODEL,
        max_tokens=600,
        system=[
            {
                "type": "text",
                "text": (
                    "You are a senior email deliverability advisor. "
                    "You analyse warmup progress AND real delivery metrics (bounces, spam reports, reply rates) "
                    "to give precise, conservative, actionable send-volume recommendations.\n\n"
                    "Key rules you must apply:\n"
                    "- Bounce rate >3% → recommend cutting volume by 50% immediately\n"
                    "- Any spam reports → recommend pausing until resolved\n"
                    "- Mailivery health score <50 → reduce volume, focus on warmup\n"
                    "- Delivery rate <85% → flag as serious risk\n"
                    "- Reply rate >5% → positive signal, can be slightly more aggressive\n"
                    "- If no real delivery data yet, base advice on warmup schedule + reputation score only\n"
                    "- Never recommend more than the warmup schedule limit unless fully warmed\n\n"
                    "Return valid JSON only — no markdown, no prose outside JSON:\n"
                    '{"recommended_limit": <int>, "confidence": "<high|medium|low>", '
                    '"summary": "<one-line headline under 12 words>", '
                    '"reasoning": "<2-4 sentences — reference the actual numbers>", '
                    '"warnings": ["<short specific warning>", ...]}'
                ),
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": (
                    f"Here is my deliverability data:\n\n{snapshot}\n\n"
                    "How many outreach emails per day is safe to send right now? "
                    "Reference the specific numbers in your reasoning — bounce rate, score, ramp day, etc. "
                    "Be conservative. Return JSON only."
                ),
            }
        ],
    )

    result = _extract_json(response)
    return {
        "recommended_limit": int(result.get("recommended_limit", ramp_limit or 10)),
        "confidence":        str(result.get("confidence", "medium")),
        "summary":           str(result.get("summary", "")),
        "reasoning":         str(result.get("reasoning", "")),
        "warnings":          list(result.get("warnings") or []),
    }
