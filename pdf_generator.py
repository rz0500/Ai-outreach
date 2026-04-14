"""
pdf_generator.py — Sharp Growth Breakdown PDF Generator
========================================================
Produces a sales document disguised as analysis.

NOT a report. NOT a consultant deck. NOT agency fluff.

It must feel like: "They understand our business, they found the gap,
and they know how to fix it."

8-section structure:
  Cover               Growth Breakdown for [Company]
  01  Current Situation
  02  The Ceiling
  03  Market Reality
  04  Our Approach
  05  Expected Outcomes  (metrics panel)
  06  Risk-Free 30-Day Pilot
  CTA page            Standalone closer with styled button

Required input fields:
  company, name, niche, icp, website_headline,
  outbound_status OR ad_status

Optional (improve specificity):
  product_feature, competitors, hiring_signal,
  linkedin_activity, notable_result, notes (Research Hook)

Validation: each section is checked for banned phrases,
            mandatory tension, and at least one memorable line before rendering.
"""

import os
import re
from datetime import date

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak,
    HRFlowable, Table, TableStyle,
)

from database import DB_PATH, get_all_prospects

OUTPUT_DIR = "proposals"

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------
C_INK      = HexColor('#0f172a')
C_BODY     = HexColor('#1e293b')
C_MUTED    = HexColor('#64748b')
C_ACCENT   = HexColor('#3b82f6')
C_INDIGO   = HexColor('#6366f1')
C_DANGER   = HexColor('#dc2626')
C_RULE     = HexColor('#e2e8f0')
C_COVER    = HexColor('#0f172a')
C_COVER_HL = HexColor('#818cf8')
C_PANEL    = HexColor('#f8fafc')
C_METRIC   = HexColor('#0f172a')

SENDER_NAME    = "LeadGen AI"
SENDER_EMAIL   = "hello@leadgenai.com"
SENDER_WEBSITE = "www.leadgenai.com"
CTA_LINK       = "calendly.com/leadgenai/30min"

# ---------------------------------------------------------------------------
# Banned phrases — any section containing these will fail validation
# ---------------------------------------------------------------------------
BANNED_PHRASES = [
    # Hedging / consultant-speak
    "it appears", "based on available data", "may indicate",
    "could suggest", "this indicates", "this suggests",
    "likely dependent on", "appears to rely on",
    "likely could", "seemingly", "seems like", "might be",
    "could be", "it is worth noting",
    # Passive openers
    "we noticed", "it looks like",
    # Cliches
    "in today's competitive landscape", "current acquisition model",
    "worth exploring", "leverage", "synergies",
    "unlock growth opportunities", "holistic",
    "robust framework", "end-to-end",
    "this approach has a ceiling",
]

# Tension markers — at least one must appear in sections that require tension
TENSION_MARKERS = [
    "caps your", "caps growth", "this caps", "hard.",
    "pipeline stops", "invisible", "first contact",
    "you don't", "you do not", "you are renting", "rented growth",
    "by default", "no backup", "hostage",
    "depends on being found", "if they do not find",
    "remove the spend", "remove the budget",
    "not a system", "hiring does not fix",
    "already in your", "just not in it",
    "no other way in", "that is what matters",
    "volume without precision", "immediately.",
    "before they start searching",
]

# Memorable line markers — short, punchy phrases that prove the section is scannable
MEMORABLE_MARKERS = [
    "hard.", "you do not.", "you do not exist", "this caps",
    "caps your", "not a system.", "no backup.", "rented growth.",
    "you are renting", "the pipeline stops", "immediately.",
    "more sends does not", "hiring does not fix",
    "not their fault", "infrastructure is missing",
    "just not in it", "already in your buyers",
    "that is what matters", "no other way in",
    "first contact.", "first contact sets",
    "before they go looking", "before they start searching",
    "you are not building", "nothing is missed.",
]


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------

def _styles():
    b = getSampleStyleSheet()
    return {
        # --- COVER (dark bg) ---
        'cv_eyebrow':   ParagraphStyle('cv_eyebrow', parent=b['Normal'],
                            fontSize=9, textColor=C_INDIGO,
                            fontName='Helvetica-Bold', spaceAfter=10),
        'cv_h1':        ParagraphStyle('cv_h1', parent=b['Normal'],
                            fontSize=36, textColor=white,
                            fontName='Helvetica-Bold', leading=44, spaceAfter=14),
        'cv_sub':       ParagraphStyle('cv_sub', parent=b['Normal'],
                            fontSize=14, textColor=HexColor('#94a3b8'),
                            fontName='Helvetica', leading=20, spaceAfter=28),
        'cv_company':   ParagraphStyle('cv_company', parent=b['Normal'],
                            fontSize=22, textColor=C_COVER_HL,
                            fontName='Helvetica-Bold', spaceAfter=36),
        'cv_meta':      ParagraphStyle('cv_meta', parent=b['Normal'],
                            fontSize=10, textColor=HexColor('#94a3b8'),
                            fontName='Helvetica', spaceAfter=5),
        'cv_wi_head':   ParagraphStyle('cv_wi_head', parent=b['Normal'],
                            fontSize=8, textColor=HexColor('#94a3b8'),
                            fontName='Helvetica-Bold', spaceAfter=6),
        'cv_wi_item':   ParagraphStyle('cv_wi_item', parent=b['Normal'],
                            fontSize=10, textColor=white,
                            fontName='Helvetica', leading=16, spaceAfter=4),

        # --- BODY SECTIONS ---
        'sec_num':      ParagraphStyle('sec_num', parent=b['Normal'],
                            fontSize=9, textColor=C_ACCENT,
                            fontName='Helvetica-Bold', spaceBefore=24, spaceAfter=2),
        'sec_title':    ParagraphStyle('sec_title', parent=b['Normal'],
                            fontSize=20, textColor=C_INK,
                            fontName='Helvetica-Bold', leading=26, spaceAfter=10),
        'body':         ParagraphStyle('body', parent=b['Normal'],
                            fontSize=11, textColor=C_BODY,
                            fontName='Helvetica', leading=17, spaceAfter=8),
        'label':        ParagraphStyle('label', parent=b['Normal'],
                            fontSize=8, textColor=C_MUTED,
                            fontName='Helvetica-Bold', spaceBefore=8, spaceAfter=3),
        'bullet':       ParagraphStyle('bullet', parent=b['Normal'],
                            fontSize=11, textColor=C_BODY,
                            fontName='Helvetica', leading=17,
                            leftIndent=12, spaceAfter=5),
        'tension':      ParagraphStyle('tension', parent=b['Normal'],
                            fontSize=13, textColor=C_DANGER,
                            fontName='Helvetica-Bold', leading=19,
                            spaceBefore=6, spaceAfter=8),
        'takeaway':     ParagraphStyle('takeaway', parent=b['Normal'],
                            fontSize=12, textColor=C_INDIGO,
                            fontName='Helvetica-Bold', leading=18,
                            spaceBefore=6, spaceAfter=10),

        # --- METRICS ---
        'metric_num':   ParagraphStyle('metric_num', parent=b['Normal'],
                            fontSize=28, textColor=C_ACCENT,
                            fontName='Helvetica-Bold', leading=32,
                            alignment=TA_CENTER, spaceAfter=2),
        'metric_lbl':   ParagraphStyle('metric_lbl', parent=b['Normal'],
                            fontSize=9, textColor=C_MUTED,
                            fontName='Helvetica', leading=13,
                            alignment=TA_CENTER),

        # --- CTA PAGE ---
        'cta_h1':       ParagraphStyle('cta_h1', parent=b['Normal'],
                            fontSize=22, textColor=C_INK,
                            fontName='Helvetica-Bold', leading=30,
                            alignment=TA_CENTER, spaceAfter=12),
        'cta_body':     ParagraphStyle('cta_body', parent=b['Normal'],
                            fontSize=11, textColor=C_MUTED,
                            fontName='Helvetica', leading=18,
                            alignment=TA_CENTER, spaceAfter=8),
        'cta_btn':      ParagraphStyle('cta_btn', parent=b['Normal'],
                            fontSize=12, textColor=white,
                            fontName='Helvetica-Bold', alignment=TA_CENTER),
        'cta_pricing':  ParagraphStyle('cta_pricing', parent=b['Normal'],
                            fontSize=10, textColor=C_MUTED,
                            fontName='Helvetica', alignment=TA_CENTER,
                            spaceBefore=10, spaceAfter=4),
        'contact':      ParagraphStyle('contact', parent=b['Normal'],
                            fontSize=9, textColor=C_MUTED,
                            fontName='Helvetica', alignment=TA_CENTER,
                            spaceAfter=3),
    }


# ---------------------------------------------------------------------------
# Content validators
# ---------------------------------------------------------------------------

def _check_banned(text: str) -> list:
    """Return list of banned phrases found in text."""
    low = text.lower()
    return [p for p in BANNED_PHRASES if p in low]


def _has_tension(text: str) -> bool:
    """Return True if at least one tension marker is present."""
    low = text.lower()
    return any(m in low for m in TENSION_MARKERS)


def _has_memorable_line(text: str) -> bool:
    """
    Return True if the section contains at least one line worth remembering.
    Checks known markers first, then falls back to sentence-length heuristic
    (any sentence between 10 and 55 chars is short enough to be punchy).
    """
    low = text.lower()
    if any(m in low for m in MEMORABLE_MARKERS):
        return True
    sentences = re.split(r'[.!?]', text)
    return any(10 < len(s.strip()) < 55 for s in sentences)


def _validate_section(
    name: str,
    content: str,
    require_tension: bool = False,
    require_memorable: bool = False,
) -> list:
    """Return list of validation errors for a section."""
    errors = []
    banned = _check_banned(content)
    if banned:
        errors.append(f"[{name}] Banned phrases: {', '.join(banned)}")
    if require_tension and not _has_tension(content):
        errors.append(f"[{name}] No tension line found. Add consequence language.")
    if require_memorable and not _has_memorable_line(content):
        errors.append(
            f"[{name}] No memorable line found. "
            "Every section needs one short, punchy sentence."
        )
    if len(content) < 80:
        errors.append(f"[{name}] Content too short — may be generic or empty.")
    return errors


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = ['company', 'name']
ENRICHMENT_ANY  = ['niche', 'website_headline', 'notes']   # at least one required


def _validate_input(p: dict) -> tuple:
    """Returns (ok: bool, reason: str)."""
    missing = [f for f in REQUIRED_FIELDS if not (p.get(f) or '').strip()]
    if missing:
        return False, f"Missing required fields: {missing}"
    has_enrichment = any((p.get(f) or '').strip() for f in ENRICHMENT_ANY) or \
                     '[Research Hook]' in (p.get('notes') or '')
    if not has_enrichment:
        return False, (
            f"'{p.get('company')}' has no enrichment (niche, headline, or research hook). "
            "Run research_agent first or the PDF will be generic and will not pass validation."
        )
    return True, ""


# ---------------------------------------------------------------------------
# Intelligence layer — build section content from enrichment data
# ---------------------------------------------------------------------------

def _infer_acquisition(p: dict) -> str:
    ad   = (p.get('ad_status') or '').lower()
    outb = (p.get('outbound_status') or '').lower()
    hire = (p.get('hiring_signal') or '').lower()

    if outb == 'active_outbound':
        return "some structured outbound"
    if 'sdr' in hire:
        return "an early SDR hire with no outbound infrastructure yet"
    if ad == 'running_ads' and outb == 'no_outbound':
        return "paid ads — no cold outbound"
    if ad == 'running_ads':
        return "paid ads and inbound"
    return "inbound and referrals"


def _situation_lines(p: dict) -> list:
    """Return 3–5 short body lines for Current Situation, ending with a consequence line."""
    company  = p.get('company', '')
    niche    = p.get('niche', '')
    icp      = p.get('icp', '')
    headline = p.get('website_headline', '')
    feature  = p.get('product_feature', '')
    acq      = _infer_acquisition(p)
    hire     = (p.get('hiring_signal') or '').lower()
    notes    = p.get('notes') or ''

    lines = []
    if niche:
        lines.append(f"{company} operates in <b>{niche}</b>.")
    if icp:
        lines.append(f"Their buyers: {icp}.")
    if headline:
        lines.append(f"Positioning: <i>\u201c{headline}\u201d</i>")
    if feature:
        lines.append(f"Core offer: {feature}.")

    # Research hook opener if available
    hook_m = re.search(r"Opener:\s*(.*)", notes)
    if hook_m:
        lines.append(hook_m.group(1).strip())

    lines.append(f"Current lead source: <b>{acq}</b>.")

    # Consequence line — sets up The Ceiling
    if 'ads' in acq and 'no cold' in acq:
        lines.append("Growth that stops when the budget stops is rented growth.")
    elif 'sdr' in hire:
        lines.append("The hire is in. The infrastructure is not.")
    elif 'active' in acq:
        lines.append("The outbound exists. The question is whether it is working.")
    else:
        lines.append("Right now, growth depends on someone else making the first move.")

    return lines


def _ceiling_content(p: dict) -> tuple:
    """Return (tension_line, bullets, kicker) for The Ceiling section."""
    company = p.get('company', 'The company')
    ad      = (p.get('ad_status') or '').lower()
    outb    = (p.get('outbound_status') or '').lower()
    hire    = (p.get('hiring_signal') or '').lower()
    acq     = _infer_acquisition(p)

    if 'no outbound' in acq or (ad == 'running_ads' and outb == 'no_outbound'):
        tension = "This caps your pipeline. Hard."
        bullets = [
            f"If they do not see your ad, they do not exist to you. "
            f"There is no other way in.",
            "CPAs compound as audiences saturate. "
            "What works at \u00a330 per lead becomes \u00a390 within 18 months.",
            f"Remove the spend and the pipeline stops. "
            f"Not gradually \u2014 immediately.",
        ]
        kicker = "You are not building a pipeline. You are renting one."

    elif 'sdr' in hire:
        tension = "One hire is not a system."
        bullets = [
            "Manual outreach is not repeatable. Results track who is having a good week.",
            f"Without validated lists and sequences, the hire at {company} underperforms. "
            f"Not their fault \u2014 the infrastructure is missing.",
            "The bottleneck is not the person. It is what is underneath them.",
        ]
        kicker = "Hiring does not fix a missing system."

    elif 'active_outbound' in outb:
        tension = "Volume without precision is expensive noise."
        bullets = [
            "Unstructured outreach burns contacts and produces flat response rates.",
            "Without enrichment and reply handling, more sends just means more ignored messages.",
            "More volume is not the fix. More precision is.",
        ]
        kicker = "More sends does not mean more meetings."

    else:
        # Inbound / referral
        tension = "Right now, your growth depends on being found."
        bullets = [
            f"{company}\u2019s pipeline arrives when someone decides to look. "
            "Not when you decide to grow.",
            "Referral volume is uncontrollable. It tracks relationships, not market opportunity.",
            "Qualified buyers who do not know you exist are invisible. "
            "You have no reach into that gap.",
        ]
        kicker = "If they do not find you, they do not find you. There is no backup."

    return tension, bullets, kicker


def _market_reality_content(p: dict) -> tuple:
    """Return (intro_line, bullets, takeaway) for Market Reality."""
    company = p.get('company', 'The company')
    comps   = [c.strip() for c in (p.get('competitors') or '').split(',') if c.strip()]
    niche   = p.get('niche') or ''
    icp     = p.get('icp') or ''
    target  = icp or niche or 'your market'

    if comps:
        named = comps[0] if len(comps) == 1 else ' and '.join(comps[:2])
        verb  = 'is' if len(comps) == 1 else 'are'
        intro = f"{named} {verb} already in your buyers' inboxes."
        bullets = [
            f"That conversation happened without {company}. "
            f"{named} reached out first and set the frame.",
            "Not because they have a better product. Because they showed up before you did.",
            "First contact sets the context. "
            "The buyer already has a reference point. It is not you.",
        ]
        takeaway = "They get first contact. You do not. That is what matters."
    else:
        intro = (
            f"Operators in {target} with an outbound system "
            f"are winning deals {company} never sees."
        )
        bullets = [
            "They book 5\u201310 qualified conversations a month from cold traffic alone.",
            f"Those buyers would have chosen {company} \u2014 "
            f"if {company} had been in their inbox first.",
            "First contact sets the frame. "
            "Whoever gets there first controls the conversation.",
        ]
        takeaway = "The pipeline exists. You are just not in it."

    return intro, bullets, takeaway


def _approach_bullets(p: dict) -> list:
    """Outcome-and-mechanism framing — not a process list."""
    company = p.get('company', 'your company')
    notes   = p.get('notes') or ''
    # Pull pain point from research hook if available
    pain_m = re.search(r"Pain Point:\s*(.*)", notes)
    if pain_m:
        # Strip "Subject verb…" down to the core problem noun phrase.
        # "Construction PMs spend 6+ hours per week on manual status updates"
        # → "manual status updates"
        raw = pain_m.group(1).strip().rstrip('.')
        # Pull everything after " on ", " with ", " around ", or fall back to full phrase
        core_m = re.search(r'\b(?:on|with|around|from)\s+(.+)$', raw, re.IGNORECASE)
        core = core_m.group(1).lower() if core_m else raw.lower()
        pain_clause = f"already dealing with {core}"
    else:
        pain_clause = f"already dealing with the problem {company} solves"

    return [
        f"We find the companies {pain_clause} \u2014 before they go looking for a solution.",
        "We reach them directly. Every message is grounded in something real about their business.",
        "Replies are classified the same day. "
        "Interested leads move to a booked call. Nothing is missed.",
        "You see everything: what went out, who replied, what moved forward.",
    ]


def _metrics(_p: dict) -> list:
    """Return list of (number, label) tuples for the metrics panel."""
    return [
        ("4\u20138",   "qualified conversations\nper month"),
        ("1\u20132",   "new clients per month\nat a realistic close rate"),
        ("30",         "days to\nfirst results"),
        ("\u00a30",    "cost if no\nqualified conversations"),
    ]


def _extract_hook(notes: str) -> str:
    if not notes:
        return ""
    m = re.search(r"Opener:\s*(.*)", notes)
    return m.group(1).strip() if m else ""


# ---------------------------------------------------------------------------
# Canvas callbacks
# ---------------------------------------------------------------------------

def _on_cover(canvas, doc):  # noqa: ARG001
    w, h = letter
    canvas.saveState()
    # Full dark background
    canvas.setFillColor(C_COVER)
    canvas.rect(0, 0, w, h, fill=1, stroke=0)
    # Top indigo bar
    canvas.setFillColor(C_INDIGO)
    canvas.rect(0, h - 5, w, 5, fill=1, stroke=0)
    # Bottom accent line
    canvas.setFillColor(HexColor('#1e293b'))
    canvas.rect(0, 0, w, 0.6 * inch, fill=1, stroke=0)
    canvas.restoreState()


def _on_body_pages(canvas, doc):
    w, h = letter
    canvas.saveState()
    # Subtle top rule
    canvas.setFillColor(C_RULE)
    canvas.rect(0.85 * inch, h - 0.55 * inch, w - 1.7 * inch, 0.5, fill=1, stroke=0)
    # Footer
    canvas.setFillColor(C_RULE)
    canvas.rect(0.85 * inch, 0.5 * inch, w - 1.7 * inch, 0.5, fill=1, stroke=0)
    canvas.setFont('Helvetica', 8)
    canvas.setFillColor(C_MUTED)
    canvas.drawString(0.85 * inch, 0.33 * inch, SENDER_NAME)
    canvas.drawRightString(w - 0.85 * inch, 0.33 * inch, f"Page {doc.page}")
    canvas.restoreState()


# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------

def _rule(story, color=C_RULE, thickness=0.5):
    story.append(HRFlowable(width="100%", thickness=thickness,
                             color=color, spaceBefore=4, spaceAfter=14))


def _section(story, S, num: int, title: str):
    story.append(Paragraph(f"{num:02d}", S['sec_num']))
    story.append(Paragraph(title, S['sec_title']))


def _bullets(story, S, items: list):
    for item in items:
        story.append(Paragraph(f"\u2014\u2002{item}", S['bullet']))


def _metrics_table(story, S, metrics: list):
    """Render a 4-cell horizontal metrics panel."""
    cells = []
    for _i, (num, lbl) in enumerate(metrics):
        cell = [
            Paragraph(num, S['metric_num']),
            Paragraph(lbl, S['metric_lbl']),
        ]
        cells.append(cell)

    col_w = (letter[0] - 1.7 * inch) / 4
    tbl = Table([cells], colWidths=[col_w] * 4, rowHeights=[0.95 * inch])
    tbl.setStyle(TableStyle([
        ('BACKGROUND',  (0, 0), (-1, -1), C_PANEL),
        ('BOX',         (0, 0), (-1, -1), 0.5, C_RULE),
        ('LINEAFTER',   (0, 0), (2,  0),  0.5, C_RULE),
        ('TOPPADDING',  (0, 0), (-1, -1), 12),
        ('BOTTOMPADDING',(0,0), (-1, -1), 12),
        ('VALIGN',      (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN',       (0, 0), (-1, -1), 'CENTER'),
        ('ROUNDEDCORNERS', [6]),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 0.15 * inch))


def _cta_button(story, S, text: str):
    """Render a styled CTA button using a 1-cell table."""
    btn = Table(
        [[Paragraph(text, S['cta_btn'])]],
        colWidths=[3.2 * inch],
        rowHeights=[0.52 * inch],
    )
    btn.setStyle(TableStyle([
        ('BACKGROUND',   (0, 0), (-1, -1), C_INDIGO),
        ('TOPPADDING',   (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 10),
        ('ALIGN',        (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN',       (0, 0), (-1, -1), 'MIDDLE'),
        ('ROUNDEDCORNERS', [6]),
    ]))
    # Centre the button
    outer = Table([[btn]], colWidths=[letter[0] - 1.7 * inch])
    outer.setStyle(TableStyle([
        ('ALIGN',  (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(outer)


def _whats_inside_table(company: str, S) -> Table:  # noqa: ARG001
    """Render the 'What's Inside' panel for the cover page."""
    items = [
        "\u2192  What is capping your pipeline right now",
        "\u2192  Where competitors are already winning",
        "\u2192  The outbound system and what it delivers",
        "\u2192  Risk-free 30-day pilot",
    ]
    rows = [[Paragraph("WHAT\u2019S INSIDE", S['cv_wi_head'])]]
    for item in items:
        rows.append([Paragraph(item, S['cv_wi_item'])])

    tbl = Table(rows, colWidths=[4.5 * inch])
    tbl.setStyle(TableStyle([
        ('BACKGROUND',   (0, 0), (-1, -1), HexColor('#1e293b')),
        ('BOX',          (0, 0), (-1, -1), 0.5, HexColor('#334155')),
        ('TOPPADDING',   (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 8),
        ('LEFTPADDING',  (0, 0), (-1, -1), 14),
        ('RIGHTPADDING', (0, 0), (-1, -1), 14),
        ('LINEBELOW',    (0, 0), (0,  0),  0.5, HexColor('#334155')),
    ]))
    return tbl


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------

def generate_proposal(prospect: dict) -> str:
    """
    Build a sharp, data-driven growth breakdown PDF.

    Raises ValueError if input fails validation.
    Returns filepath of the generated PDF.
    """
    ok, reason = _validate_input(prospect)
    if not ok:
        raise ValueError(reason)

    # Pull fields
    company    = (prospect.get('company') or 'Your Company').strip()
    name       = (prospect.get('name') or 'Founder').strip()
    first      = name.split()[0]
    today      = date.today().strftime('%d %B %Y')

    # Build section content
    sit_lines                                = _situation_lines(prospect)
    ceil_tension, ceil_bullets, ceil_kicker  = _ceiling_content(prospect)
    mkt_intro, mkt_bullets, mkt_takeaway     = _market_reality_content(prospect)
    approach_bullets                         = _approach_bullets(prospect)
    metric_data                              = _metrics(prospect)

    # ---- Content validation ----
    all_errors = []
    all_errors += _validate_section(
        "Current Situation",
        " ".join(sit_lines),
        require_tension=False,
        require_memorable=True,
    )
    ceil_text = ceil_tension + " " + " ".join(ceil_bullets) + " " + ceil_kicker
    all_errors += _validate_section(
        "The Ceiling", ceil_text,
        require_tension=True, require_memorable=True,
    )
    mkt_text = mkt_intro + " " + " ".join(mkt_bullets) + " " + mkt_takeaway
    all_errors += _validate_section(
        "Market Reality", mkt_text,
        require_tension=True, require_memorable=True,
    )
    appr_text = " ".join(approach_bullets)
    all_errors += _validate_section(
        "Our Approach", appr_text,
        require_tension=False, require_memorable=True,
    )
    if all_errors:
        raise ValueError("Content validation failed:\n" + "\n".join(all_errors))

    # ---- Output path ----
    safe = "".join(c if c.isalnum() else "_" for c in company).lower()
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filepath = os.path.join(OUTPUT_DIR, f"breakdown_{safe}.pdf")

    doc = SimpleDocTemplate(
        filepath, pagesize=letter,
        rightMargin=0.85 * inch, leftMargin=0.85 * inch,
        topMargin=0.85 * inch, bottomMargin=0.72 * inch,
    )
    S = _styles()
    story = []

    # ==========================================================
    # COVER
    # ==========================================================
    story.append(Spacer(1, 1.2 * inch))
    story.append(Paragraph("GROWTH BREAKDOWN", S['cv_eyebrow']))
    story.append(Paragraph("What is capping your\npipeline\u2014and the fix for it.", S['cv_h1']))
    story.append(Paragraph(
        "A personalised pipeline analysis prepared exclusively for:", S['cv_sub']
    ))
    story.append(Paragraph(company, S['cv_company']))
    story.append(_whats_inside_table(company, S))
    story.append(Spacer(1, 0.35 * inch))
    story.append(Paragraph(f"Prepared by {SENDER_NAME}  \u00b7  {today}", S['cv_meta']))
    if first.lower() not in ('founder', 'there', 'n/a', ''):
        story.append(Paragraph(f"For the attention of {first}", S['cv_meta']))
    story.append(PageBreak())

    # ==========================================================
    # PAGE 2 — 01 CURRENT SITUATION  +  02 THE CEILING
    # ==========================================================

    _section(story, S, 1, "Current Situation")
    for line in sit_lines:
        story.append(Paragraph(line, S['body']))

    _rule(story)

    _section(story, S, 2, "The Ceiling")
    story.append(Paragraph(ceil_tension, S['tension']))
    _bullets(story, S, ceil_bullets)
    story.append(Paragraph(ceil_kicker, S['tension']))
    story.append(PageBreak())

    # ==========================================================
    # PAGE 3 — 03 MARKET REALITY  +  04 OUR APPROACH
    # ==========================================================

    _section(story, S, 3, "Market Reality")
    story.append(Paragraph(mkt_intro, S['body']))
    _bullets(story, S, mkt_bullets)
    story.append(Paragraph(mkt_takeaway, S['takeaway']))

    _rule(story)

    _section(story, S, 4, "Our Approach")
    story.append(Paragraph("We build the system. You take the calls.", S['tension']))
    _bullets(story, S, approach_bullets)
    story.append(PageBreak())

    # ==========================================================
    # PAGE 4 — 05 EXPECTED OUTCOMES  +  06 RISK-FREE PILOT
    # ==========================================================

    _section(story, S, 5, "Expected Outcomes")
    story.append(Paragraph(
        f"A working outbound system for {company} delivers:", S['body']
    ))
    story.append(Spacer(1, 0.1 * inch))
    _metrics_table(story, S, metric_data)
    _bullets(story, S, [
        "Pipeline that does not stop when ads pause or referrals dry up.",
        "A repeatable system \u2014 not a one-time campaign.",
        "Full tracking from day one: what went out, who replied, what moved.",
    ])

    _rule(story)

    _section(story, S, 6, "Risk-Free 30-Day Pilot")
    story.append(Paragraph("No results. No charge.", S['tension']))
    _bullets(story, S, [
        "We run a full 30-day pilot before any ongoing commitment.",
        "No long-term contract. Cancel with 30 days notice after the pilot.",
        "You own the prospect list we build \u2014 regardless of outcome.",
        "Results are measurable and tracked from day one.",
    ])
    story.append(PageBreak())

    # ==========================================================
    # CTA PAGE — standalone closer
    # ==========================================================

    story.append(Spacer(1, 0.8 * inch))
    story.append(Paragraph(
        f"Ready to see if it works for {company}?", S['cta_h1']
    ))
    story.append(Paragraph(
        f"Book a 20-minute call. We will walk through the target list, "
        f"the sequence, and the expected volume \u2014 specific to {company}.\n\n"
        f"No pitch. No deck. Just the plan.",
        S['cta_body']
    ))
    story.append(Spacer(1, 0.3 * inch))
    _cta_button(story, S, f"Book a Call  \u2192  {CTA_LINK}")
    story.append(Spacer(1, 0.25 * inch))
    _rule(story, color=C_RULE, thickness=0.5)
    story.append(Paragraph(
        "No pitch. No hard sell. If the fit is not there, we will tell you.",
        S['cta_pricing']
    ))
    story.append(Spacer(1, 0.2 * inch))
    story.append(Paragraph(SENDER_NAME, S['contact']))
    story.append(Paragraph(SENDER_EMAIL, S['contact']))
    story.append(Paragraph(SENDER_WEBSITE, S['contact']))

    doc.build(story, onFirstPage=_on_cover, onLaterPages=_on_body_pages)
    return filepath


# ---------------------------------------------------------------------------
# Batch runner
# ---------------------------------------------------------------------------

def run_proposal_batch(db_path: str = DB_PATH) -> int:
    """Generate PDFs for all qualified/in-sequence prospects with enrichment data."""
    print("Starting Growth Breakdown PDF Generator...")
    prospects = [
        p for p in get_all_prospects(db_path)
        if p['status'] in ('qualified', 'in_sequence')
    ]
    if not prospects:
        print("  No qualified/in_sequence prospects found.")
        return 0

    count = skipped = 0
    for p in prospects:
        try:
            path = generate_proposal(p)
            print(f"  [OK]  {path}")
            count += 1
        except ValueError as e:
            print(f"  SKIP  {p.get('company')}: {e}")
            skipped += 1

    print(f"\nGenerated: {count}  |  Skipped: {skipped}")
    return count


# ---------------------------------------------------------------------------
# __main__ — before/after demonstration fixture
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    # --- BEFORE: thin data, no enrichment (should be rejected) ---
    thin = {
        "name": "James Cole",
        "company": "Apex Digital",
        "email": "james@apexdigital.io",
        "status": "qualified",
        "notes": "",
    }

    # --- AFTER: full enrichment fixture ---
    rich = {
        "name": "James Cole",
        "company": "Apex Digital",
        "email": "james@apexdigital.io",
        "status": "qualified",
        "niche": "B2B SaaS for construction project managers",
        "icp": "mid-sized UK construction firms running 5+ concurrent projects",
        "website_headline": "Stop losing projects to miscommunication",
        "product_feature": "real-time site-to-office sync with automated progress reporting",
        "competitors": "Buildertrend, CoConstruct",
        "ad_status": "running_ads",
        "outbound_status": "no_outbound",
        "notable_result": "Cut project overruns by 40% for Morrison Construction",
        "notes": (
            "[Research Hook]\n"
            "Pain Point: Construction PMs spend 6+ hours per week on manual status updates.\n"
            "Growth Signal: Recently rebranded with enterprise case studies added.\n"
            "Opener: Apex Digital's positioning around miscommunication is sharp -- "
            "it is a problem every PM on a live build recognises immediately."
        ),
    }

    print("=" * 60)
    print("BEFORE -- thin data (should be rejected)")
    print("=" * 60)
    try:
        generate_proposal(thin)
    except ValueError as e:
        print(f"  [OK] Correctly rejected:\n  {e}")

    print()
    print("=" * 60)
    print("AFTER -- full enrichment")
    print("=" * 60)

    # ---------- BEFORE/AFTER COPY COMPARISON ----------

    # PROBLEM (Current Situation + The Ceiling)
    OLD_CEILING_TENSION = "Paid ads alone will cap your growth."
    OLD_CEILING_BULLETS = [
        "Every lead Apex Digital gets requires someone to click an ad. Remove the spend and the pipeline stops.",
        "CPAs compound as audiences saturate. What works at £30 per lead costs £90 within 18 months.",
        "Qualified buyers who are not served your ad do not exist in your pipeline. There is no proactive reach.",
        "You are not growing your pipeline. You are renting it.",
    ]
    OLD_CEILING_KICKER = "Remove the spend. The pipeline stops. Hard."

    # OUR APPROACH — old process-heavy version
    OLD_APPROACH = [
        "Identify the right companies — mid-sized UK construction firms running 5+ concurrent projects — before they start searching for a solution.",
        "Research and enrich every contact. No message goes out without a real data point behind it.",
        "Reach them with sequences that sound like a peer sent them, not a sales tool.",
        "Every reply is monitored, classified, and routed. Interested prospects are flagged the same day.",
        "Full reporting: what went out, who responded, what moved forward.",
    ]

    # MARKET REALITY / COMPETITORS — old version
    OLD_MKT_INTRO  = "Buildertrend and CoConstruct are already in those inboxes."
    OLD_MKT_BULLETS = [
        "Buildertrend and CoConstruct are running structured cold outreach into mid-sized UK construction firms running 5+ concurrent projects — the same buyers Apex Digital is trying to reach.",
        "Those conversations go to them by default. Not because they have a better product. Because they showed up first.",
        "Cold outbound is not volume. It is showing up in the right inbox before the buyer starts searching.",
    ]
    OLD_MKT_TAKEAWAY = "They get first contact. You don't."

    print()
    print("-" * 60)
    print("SECTION: The Ceiling")
    print("-" * 60)
    print("  BEFORE:")
    print(f"  TENSION: {OLD_CEILING_TENSION}")
    for b in OLD_CEILING_BULLETS:
        print(f"    -- {b}")
    print(f"  KICKER:  {OLD_CEILING_KICKER}")
    print()
    t, b_new, k = _ceiling_content(rich)
    print("  AFTER:")
    print(f"  TENSION: {t}")
    for b in b_new:
        print(f"    -- {b}")
    print(f"  KICKER:  {k}")

    print()
    print("-" * 60)
    print("SECTION: Market Reality (Competitors)")
    print("-" * 60)
    print("  BEFORE:")
    print(f"  INTRO:    {OLD_MKT_INTRO}")
    for b in OLD_MKT_BULLETS:
        print(f"    -- {b}")
    print(f"  TAKEAWAY: {OLD_MKT_TAKEAWAY}")
    print()
    mi, mb, mt = _market_reality_content(rich)
    print("  AFTER:")
    print(f"  INTRO:    {mi}")
    for b in mb:
        print(f"    -- {b}")
    print(f"  TAKEAWAY: {mt}")

    print()
    print("-" * 60)
    print("SECTION: Our Approach")
    print("-" * 60)
    print("  BEFORE:")
    for b in OLD_APPROACH:
        print(f"    -- {b}")
    print()
    new_appr = _approach_bullets(rich)
    print("  AFTER:")
    for b in new_appr:
        print(f"    -- {b}")

    # ---------- TENSION LINES SUMMARY ----------
    print()
    print("=" * 60)
    print("TENSION LINES CHOSEN FOR EACH SECTION")
    print("=" * 60)
    sit = _situation_lines(rich)
    print(f"  01 Current Situation : {sit[-1]}")  # consequence line is last
    print(f"  02 The Ceiling       : {t}")
    print(f"  02 Kicker            : {k}")
    print(f"  03 Market Reality    : {mt}")
    print(f"  04 Our Approach      : We build the system. You take the calls.")

    # ---------- GENERATE PDF ----------
    print()
    print("=" * 60)
    print("GENERATING FULL SAMPLE PDF")
    print("=" * 60)
    try:
        path = generate_proposal(rich)
        print(f"  [OK] Generated: {path}")
    except ValueError as e:
        print(f"  ERROR: {e}")
        sys.exit(1)
