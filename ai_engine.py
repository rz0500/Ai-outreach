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
You are an expert B2B cold email copywriter who writes short, casual, \
hyper-personalised outreach emails. Your emails feel human, not templated. \
They reference specific details from the prospect's profile and notes.

Rules:
- Subject line: conversational, under 10 words, no clickbait
- Opening: one sentence referencing something specific about them
- Value proposition: one or two sentences, benefit-focused, not feature-focused
- CTA: one soft question asking for a short call — no pressure
- Sign-off: casual ("Best," or "Cheers,") followed by "[Your name]"
- Total length: 80-120 words
- Tone: warm, direct, peer-to-peer — not salesy

You MUST respond with ONLY a JSON object in this exact format:
{"subject": "<subject line>", "body": "<full email body with newlines as \\n>"}
No markdown, no explanation — only the JSON object.\
"""

_SCORE_SYSTEM_PROMPT = """\
You are an expert B2B sales qualification analyst. You evaluate prospects \
on a 1-100 scale based on all available signals in their profile.

Scoring rubric:
  71-100  Hot  — strong fit, clear buying signals, easy to reach, act now
  41-70   Warm — reasonable fit, some signals, worth pursuing
  1-40    Cold — poor fit, missing data, unlikely to convert soon

Signals to weigh:
  - Seniority and decision-making authority (title, role)
  - Company size and growth trajectory (funding, hiring, expansion)
  - Contact data completeness (email, LinkedIn, phone, website)
  - Explicit pain points or intent signals in notes
  - Pipeline status (qualified > new > other)
  - Keywords suggesting urgency (launch, hiring, new, expand, raised)

You MUST respond with ONLY a JSON object in this exact format:
{"score": <integer 1-100>, "reasoning": "<2-3 sentence rationale>"}
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
            try:
                return json.loads(block.text.strip())
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"AI returned invalid JSON: {block.text!r}"
                ) from exc
    raise ValueError("AI response contained no text block.")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_hyper_personalized_email(prospect: dict) -> dict:
    """
    Generate a hyper-personalised cold outreach email for a prospect.

    The system prompt is cache-controlled so repeated bulk calls reuse
    the cached prefix instead of re-sending it each time.

    Args:
        prospect: A prospect dict as returned by database.get_all_prospects().

    Returns:
        A dict with:
            "subject" — personalised subject line
            "body"    — full email body (plain text)

    Raises:
        anthropic.AuthenticationError: ANTHROPIC_API_KEY is missing or invalid.
        anthropic.RateLimitError:       Too many requests — back off and retry.
        anthropic.APIStatusError:       Other API-level error.
        ValueError:                     AI returned unparseable output.
    """
    profile = _prospect_to_text(prospect)

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
        messages=[
            {
                "role": "user",
                "content": (
                    f"Write a cold outreach email for this prospect:\n\n{profile}"
                ),
            }
        ],
    )

    result = _extract_json(response)

    if "subject" not in result or "body" not in result:
        raise ValueError(
            f"AI response missing 'subject' or 'body' keys: {result}"
        )

    return {"subject": str(result["subject"]), "body": str(result["body"])}


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
