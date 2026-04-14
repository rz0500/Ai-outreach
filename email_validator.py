"""
email_validator.py - Email Output Quality Gate
===============================================
Validates AI-generated cold emails before they are saved or sent.

An email fails if it:
- Contains banned phrases
- Lacks the company name in the body
- Opens with a generic first sentence
- Contains vague competitor references
- Exceeds 150 words

A validation result includes a quality score (0-100), a list of hard
errors (auto-reject), and soft warnings (flag for review).
"""

from __future__ import annotations
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Banned phrases — hard block. No exceptions.
# ---------------------------------------------------------------------------

BANNED_PHRASES: list[str] = [
    "companies like yours",
    "businesses like yours",
    "teams like yours",
    "clients like you",
    "in your space",
    "in your industry",
    "in the industry",
    "ai-powered outreach",
    "ai powered outreach",
    "aggressive outreach",
    "just wanted to reach out",
    "i just wanted to",
    "hope you're well",
    "hope you are well",
    "i hope this finds you",
    "hope this email finds",
    "book more meetings",
    "scale your pipeline",
    "quick 15 minutes",
    "quick 15-minute",
    "worth a quick chat",
    "i was browsing your website",
    "i came across your website",
    "i noticed your website",
    "i found your website",
    "game changer",
    "game-changer",
    "revolutionary",
    "supercharge",
    "skyrocket",
    "explosive growth",
    "unlock your potential",
    "take your business to the next level",
    "synergy",
    "leverage",
    "circle back",
    "touch base",
    "add value",
    "looking forward to connecting",
    "excited to connect",
    "would love to connect",
    "i'd love to learn more",
    "perfect fit",
    "world-class",
    "cutting-edge",
    "state of the art",
    "best in class",
    "industry leader",
    "innovative solution",
    "proven solution",
    "several companies",
    "many companies",
    "other businesses",
    "others in your",
    "competitors are winning",
    "competitors in your",
    "several competitors",
    "many competitors",
    "doesn't look like you're",
    "seems like you're not",
    "looks like you aren't",
    "i only have a limited read",
    "if there is",
    "might be",
    "could be",
    "happy to share",
    "noticed that",
    "if helpful",
    "worth a quick chat",
    "that’s a tight angle",
    "that's a tight angle",
    "clearly aimed at a specific group",
    "open to a quick look at how this would work",
]

# Soft warnings — penalise score but do not auto-reject
DISCOURAGED_PHRASES: list[str] = [
    "we help businesses",
    "we help companies",
    "we work with companies",
    "4-8 calls",
    "3-5 meetings",
    "book a call",
    "schedule a call",
    "let me know if you're interested",
    "would love to chat",
    "happy to jump on",
    "feel free to",
    "reach out anytime",
    "don't hesitate",
    "open to a brief conversation",
    "usually means there is",
    "it looks built for",
    "stands out because",
]

# Opening sentences that are too generic to be acceptable
GENERIC_OPENERS: list[str] = [
    "i wanted to reach out",
    "i am reaching out",
    "my name is",
    "i'm reaching out",
    "we help",
    "we work with",
    "i came across",
    "i noticed your",
    "hope you're",
    "hope you are",
]

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    passed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    quality_score: int = 100  # deducted per issue

    def summary(self) -> str:
        lines = [f"Quality score: {self.quality_score}/100"]
        if self.errors:
            lines.append(f"ERRORS ({len(self.errors)}):")
            lines.extend(f"  - {e}" for e in self.errors)
        if self.warnings:
            lines.append(f"WARNINGS ({len(self.warnings)}):")
            lines.extend(f"  - {w}" for w in self.warnings)
        return "\n".join(lines)


@dataclass
class InternalQualityScore:
    specificity: int
    credibility: int
    generic_risk: int
    rewrite_required: bool


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_email(subject: str, body: str, prospect: dict) -> ValidationResult:
    """
    Run quality checks on a generated email draft.

    Returns a ValidationResult. The email is rejected (passed=False) if
    any hard error is found.
    """
    result = ValidationResult(passed=True)
    body_lower = body.lower()
    subject_lower = subject.lower()
    company = (prospect.get("company") or "").strip().lower()
    full_text = body_lower + " " + subject_lower

    # --- Hard errors (each costs 20+ points and triggers rejection) ---

    # 1. Banned phrases
    for phrase in BANNED_PHRASES:
        if phrase in full_text:
            result.errors.append(f"Banned phrase: '{phrase}'")
            result.quality_score -= 20

    # 2. Company name must appear in the body
    if company and company not in body_lower:
        result.errors.append(
            f"Company name '{prospect.get('company')}' missing from body. Email is too generic."
        )
        result.quality_score -= 30

    # 3. Generic opening sentence
    first_sentence = body.split(".")[0].lower() if "." in body else body[:120].lower()
    for opener in GENERIC_OPENERS:
        if opener in first_sentence:
            result.errors.append(
                f"Generic opening: starts with '{opener}'. Must open with a specific observation."
            )
            result.quality_score -= 25
            break

    # 4. Body word count (new conversational structure runs 90-130 words)
    word_count = len(body.split())
    if word_count > 140:
        result.errors.append(
            f"Email body is {word_count} words. Maximum is 140. Tighten it."
        )
        result.quality_score -= 10

    # 5. Vague competitor reference without a real name
    vague_competitor_phrases = [
        "in your space", "others in your space", "competitors are",
        "several competitors", "many competitors", "companies in your",
    ]
    if any(p in body_lower for p in vague_competitor_phrases):
        # Check if any proper noun follows (rough heuristic: a word starting with capital)
        if not any(
            (word[0].isupper() and len(word) > 2)
            for word in body.split()
            if word.strip(".,") not in {"I", "Hi", "Hey", "Best", "Thanks", "Dear"}
        ):
            result.errors.append(
                "Vague competitor reference. Name a specific competitor or remove the mention."
            )
            result.quality_score -= 20

    # --- Soft warnings (cost 5-10 points each, no auto-reject) ---

    for phrase in DISCOURAGED_PHRASES:
        if phrase in body_lower:
            result.warnings.append(f"Discouraged phrase: '{phrase}'")
            result.quality_score -= 5

    # CTA too eager
    eager_signs = ["love to", "excited to", "would love", "let me know if you're interested"]
    if any(s in body_lower for s in eager_signs):
        result.warnings.append("CTA sounds eager. Should be calm and low-pressure.")
        result.quality_score -= 5

    # Subject line too long
    if len(subject.split()) > 10:
        result.warnings.append(
            f"Subject is {len(subject.split())} words. Keep it under 8."
        )
        result.quality_score -= 5

    # Overly polished pacing
    if body.count("\n") < 5:
        result.warnings.append("Body lacks line-by-line rhythm. Break it up so it reads faster.")
        result.quality_score -= 5

    # Em dashes in body
    if "\u2014" in body or " - " in body.replace("Best,", ""):
        result.warnings.append("Em dash or spaced dash found. Use plain punctuation.")
        result.quality_score -= 3

    # --- Final verdict ---
    result.quality_score = max(0, result.quality_score)
    if result.errors:
        result.passed = False

    return result


def score_internal_quality(
    subject: str,
    body: str,
    prospect: dict,
    analysis: dict,
    validation: ValidationResult | None = None,
) -> InternalQualityScore:
    """
    Score an email on specificity, credibility, and generic risk (1-10).

    Rules:
      - Specificity should reward grounded use of real evidence
      - Credibility should reward low-claim, evidence-backed phrasing
      - Generic risk should stay low when the draft avoids filler and vague language
    """
    validation = validation or validate_email(subject, body, prospect)
    full_text = f"{subject}\n{body}".lower()

    evidence_values = []
    for key in (
        "company_positioning",
        "target_customer",
        "key_offer_or_feature",
        "recent_signal",
        "outbound_evidence",
        "possible_gap",
        "relevant_competitor",
    ):
        value = (analysis.get(key) or "").strip()
        if value:
            evidence_values.append(value)

    matched_evidence = 0
    for value in evidence_values:
        snippet = value.lower().strip()
        if len(snippet) < 6:
            continue
        if snippet in full_text:
            matched_evidence += 1
            continue
        compact = " ".join(snippet.split()[:5])
        if compact and compact in full_text:
            matched_evidence += 1

    evidence_count = max(1, len(evidence_values))
    weak_data_mode = bool(analysis.get("weak_data_mode"))

    specificity = min(10, 4 + matched_evidence + min(2, evidence_count // 2))
    if weak_data_mode:
        specificity = max(5, specificity - 1)

    credibility = 9
    credibility -= min(4, len(validation.errors))
    credibility -= min(2, len(validation.warnings) // 2)
    if "logical_inference" in analysis and analysis["logical_inference"]:
        credibility = min(10, credibility + 1)
    if weak_data_mode and analysis.get("needs_enrichment"):
        credibility = max(7, credibility)
    credibility = max(1, min(10, credibility))

    generic_risk = 1
    generic_risk += min(4, len(validation.warnings))
    if validation.errors:
        generic_risk += 2
    for phrase in DISCOURAGED_PHRASES[:]:
        if phrase in full_text:
            generic_risk += 1
    generic_risk = max(1, min(10, generic_risk))

    if weak_data_mode:
        rewrite_required = specificity < 5 or credibility < 7 or generic_risk > 3
    else:
        rewrite_required = specificity < 7 or credibility < 7 or generic_risk > 3
    return InternalQualityScore(
        specificity=specificity,
        credibility=credibility,
        generic_risk=generic_risk,
        rewrite_required=rewrite_required,
    )


def check_enrichment_sufficiency(prospect: dict) -> tuple[bool, list[str], list[str]]:
    """
    Check whether a prospect has enough enrichment data for a hyper-specific email.

    Returns:
        (sufficient, missing_mandatory, missing_optional)

    Mandatory fields: name, company
    Required-for-best-output: niche, website, website_headline OR notes with research hook
    Optional enrichment: competitors, hiring_signal, linkedin_activity, icp, ad_status, product_feature
    """
    mandatory = ["name", "company"]
    important = ["niche", "website"]
    optional = [
        "website_headline", "competitors", "hiring_signal",
        "linkedin_activity", "icp", "ad_status", "outbound_status",
        "product_feature",
    ]

    missing_mandatory = [f for f in mandatory if not prospect.get(f)]
    missing_optional = [
        f for f in (important + optional) if not prospect.get(f)
    ]

    sufficient = len(missing_mandatory) == 0

    # Even if mandatory fields present, warn if no enrichment at all
    has_any_enrichment = any(
        prospect.get(f) for f in important + optional + ["notes"]
    )
    if not has_any_enrichment:
        missing_optional.insert(0, "(no enrichment data at all - email will be weak)")

    return sufficient, missing_mandatory, missing_optional
