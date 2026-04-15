"""
pdf_generator.py — Dark Deck-Style PDF Proposal Generator
==========================================================
Produces a 5-page dark-background sales document structured like a pitch deck:

  Page 1  Cover           — company, niche, 3 outcome metrics
  Page 2  THE PROBLEM     — why current acquisition caps the pipeline
  Page 3  MARKET REALITY  — competitor context, first-contact framing
  Page 4  THE SYSTEM      — numbered approach steps
  Page 5  PILOT + CTA     — risk-reversal metrics, booking CTA

Content rules (unchanged):
  - evidence-first, one angle per document
  - tension language required in problem/market sections
  - banned phrases block generic copy

Required input fields:
  company, name, niche, icp, website_headline,
  outbound_status OR ad_status

Optional (improve specificity):
  product_feature, competitors, hiring_signal,
  linkedin_activity, notable_result, notes (Research Hook)
"""

import os
import re
from datetime import date

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, white
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak,
    Table, TableStyle,
)

from database import DB_PATH, get_all_prospects
from settings import get_calendar_link

OUTPUT_DIR = "proposals"

# ─── Palette ────────────────────────────────────────────────────────────────
C_BG      = HexColor('#0f172a')   # page background (very dark navy)
C_CARD    = HexColor('#1e293b')   # card / cell background
C_CARD2   = HexColor('#162032')   # alt card (slightly darker)
C_BORDER  = HexColor('#334155')   # card border
C_TEXT    = HexColor('#f1f5f9')   # primary white text
C_MUTED   = HexColor('#94a3b8')   # secondary muted text
C_FOOTER  = HexColor('#475569')   # footer line text

# Section accent colours (top bar + label + highlights)
C_INDIGO  = HexColor('#6366f1')   # cover
C_ORANGE  = HexColor('#f97316')   # the problem
C_GREEN   = HexColor('#10b981')   # market reality
C_PURPLE  = HexColor('#8b5cf6')   # the system
C_RED     = HexColor('#ef4444')   # cta

# Metric card number colours (one per metric slot)
C_M1 = HexColor('#a78bfa')   # purple  — calls
C_M2 = HexColor('#fb923c')   # orange  — days
C_M3 = HexColor('#22d3ee')   # cyan    — cost

# Per-page top bar colours (index = page number - 1)
_PAGE_BAR = [C_INDIGO, C_ORANGE, C_GREEN, C_PURPLE, C_RED]

SENDER_NAME    = "LeadGen AI"
SENDER_EMAIL   = "hello@leadgenai.com"
SENDER_WEBSITE = "www.leadgenai.com"
CTA_LINK       = get_calendar_link()

# ─── Banned / validation lists (unchanged) ──────────────────────────────────
BANNED_PHRASES = [
    "it appears", "based on available data", "may indicate",
    "could suggest", "this indicates", "this suggests",
    "likely dependent on", "appears to rely on",
    "likely could", "seemingly", "seems like", "might be",
    "could be", "it is worth noting",
    "we noticed", "it looks like",
    "in today's competitive landscape", "current acquisition model",
    "worth exploring", "leverage", "synergies",
    "unlock growth opportunities", "holistic",
    "robust framework", "end-to-end",
    "this approach has a ceiling",
]
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


# ─── Styles ─────────────────────────────────────────────────────────────────

def _styles():
    b = getSampleStyleSheet()
    def S(name, **kw):
        return ParagraphStyle(name, parent=b['Normal'], **kw)

    return {
        # Cover
        'cv_badge':    S('cv_badge',  fontSize=8,  textColor=white, fontName='Helvetica-Bold',
                          spaceBefore=0, spaceAfter=14),
        'cv_h1':       S('cv_h1',    fontSize=30, textColor=C_TEXT, fontName='Helvetica-Bold',
                          leading=38, spaceAfter=10),
        'cv_sub':      S('cv_sub',   fontSize=12, textColor=C_MUTED, fontName='Helvetica',
                          leading=18, spaceAfter=6),
        'cv_meta':     S('cv_meta',  fontSize=9,  textColor=C_MUTED, fontName='Helvetica',
                          spaceAfter=4),

        # Section labels / titles
        'sec_label':   S('sec_label', fontSize=8,  textColor=C_MUTED, fontName='Helvetica-Bold',
                          spaceBefore=0, spaceAfter=8, letterSpacing=1.4),
        'sec_title':   S('sec_title', fontSize=22, textColor=C_TEXT, fontName='Helvetica-Bold',
                          leading=28, spaceAfter=14),

        # Card content
        'card_head':   S('card_head', fontSize=10, textColor=C_TEXT, fontName='Helvetica-Bold',
                          leading=14, spaceAfter=4),
        'card_body':   S('card_body', fontSize=9,  textColor=C_MUTED, fontName='Helvetica',
                          leading=14, spaceAfter=0),
        'card_num':    S('card_num',  fontSize=10, textColor=C_MUTED, fontName='Helvetica-Bold',
                          spaceAfter=6),

        # Tension / kicker lines
        'tension':     S('tension',  fontSize=12, textColor=C_ORANGE, fontName='Helvetica-Bold',
                          leading=17, spaceBefore=10, spaceAfter=4),
        'takeaway':    S('takeaway', fontSize=12, textColor=C_RED, fontName='Helvetica-Bold',
                          leading=17, spaceBefore=4, spaceAfter=4),
        'takeaway_sub':S('takeaway_sub', fontSize=9, textColor=HexColor('#fca5a5'),
                          fontName='Helvetica', leading=14, spaceAfter=0),

        # Metrics
        'met_num':     S('met_num',  fontSize=32, fontName='Helvetica-Bold',
                          alignment=TA_LEFT, leading=36, spaceAfter=2),
        'met_lbl':     S('met_lbl',  fontSize=9,  textColor=C_MUTED, fontName='Helvetica',
                          leading=13, spaceAfter=0),

        # CTA page
        'cta_h1':      S('cta_h1',  fontSize=20, textColor=C_RED, fontName='Helvetica-Bold',
                          leading=26, spaceAfter=14),
        'cta_body':    S('cta_body', fontSize=10, textColor=C_MUTED, fontName='Helvetica',
                          leading=16, spaceAfter=8),
        'cta_btn':     S('cta_btn',  fontSize=11, textColor=white, fontName='Helvetica-Bold',
                          alignment=TA_CENTER),
        'cta_price':   S('cta_price', fontSize=9, textColor=C_MUTED, fontName='Helvetica',
                          alignment=TA_CENTER, spaceBefore=8),
    }


# ─── Validation ─────────────────────────────────────────────────────────────

def _check_banned(text):
    low = text.lower()
    return [p for p in BANNED_PHRASES if p in low]

def _has_tension(text):
    low = text.lower()
    return any(m in low for m in TENSION_MARKERS)

def _has_memorable_line(text):
    low = text.lower()
    if any(m in low for m in MEMORABLE_MARKERS):
        return True
    return any(10 < len(s.strip()) < 55 for s in re.split(r'[.!?]', text))

def _validate_section(name, content, require_tension=False, require_memorable=False):
    errors = []
    banned = _check_banned(content)
    if banned:
        errors.append(f"[{name}] Banned phrases: {', '.join(banned)}")
    if require_tension and not _has_tension(content):
        errors.append(f"[{name}] No tension line found.")
    if require_memorable and not _has_memorable_line(content):
        errors.append(f"[{name}] No memorable line found.")
    if len(content) < 80:
        errors.append(f"[{name}] Content too short.")
    return errors

REQUIRED_FIELDS = ['company', 'name']
ENRICHMENT_ANY  = ['niche', 'website_headline', 'notes']

def _validate_input(p):
    missing = [f for f in REQUIRED_FIELDS if not (p.get(f) or '').strip()]
    if missing:
        return False, f"Missing required fields: {missing}"
    has_enrichment = any((p.get(f) or '').strip() for f in ENRICHMENT_ANY) or \
                     '[Research Hook]' in (p.get('notes') or '')
    if not has_enrichment:
        return False, (
            f"'{p.get('company')}' has no enrichment data. "
            "Run research_agent first."
        )
    return True, ""


# ─── Content generators (logic unchanged) ───────────────────────────────────

def _infer_acquisition(p):
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


def _situation_lines(p):
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
        lines.append(f"{company} operates in {niche}.")
    if icp:
        lines.append(f"Their buyers: {icp}.")
    if headline:
        lines.append(f"Positioning: \u201c{headline}\u201d")
    if feature:
        lines.append(f"Core offer: {feature}.")
    hook_m = re.search(r"Opener:\s*(.*)", notes)
    if hook_m:
        lines.append(hook_m.group(1).strip())
    lines.append(f"Current lead source: {acq}.")
    if 'ads' in acq and 'no cold' in acq:
        lines.append("Growth that stops when the budget stops is rented growth.")
    elif 'sdr' in hire:
        lines.append("The hire is in. The infrastructure is not.")
    elif 'active' in acq:
        lines.append("The outbound exists. The question is whether it is working.")
    else:
        lines.append("Right now, growth depends on someone else making the first move.")
    return lines


def _ceiling_content(p):
    ad   = (p.get('ad_status') or '').lower()
    outb = (p.get('outbound_status') or '').lower()
    hire = (p.get('hiring_signal') or '').lower()
    acq  = _infer_acquisition(p)
    icp  = p.get('icp') or ''

    if 'no outbound' in acq or (ad == 'running_ads' and outb == 'no_outbound'):
        tension = "This caps your pipeline. Hard."
        bullets = [
            (f"{icp or 'Your buyers'} never see you" if icp else "Buyers who miss your ad never see you",
             f"Without outbound, you only reach buyers who find you first. The rest of the market is untouched."),
            ("Spend \u00a31 to acquire every lead",
             "Remove the budget and the pipeline stops. Not gradually \u2014 immediately. You are renting your pipeline, not building it."),
            ("CPAs compound as audiences saturate",
             "What works at \u00a330 per lead becomes \u00a390 within 18 months. The ceiling drops as the audience shrinks."),
        ]
        kicker = "You are not building a pipeline. You are renting one."

    elif 'sdr' in hire:
        tension = "One hire is not a system."
        bullets = [
            ("Manual outreach does not scale",
             "Results track who is having a good week, not a repeatable system."),
            ("No infrastructure means the hire underperforms",
             "Not their fault \u2014 the infrastructure is missing."),
            ("The bottleneck is not the person",
             "It is what is underneath them."),
        ]
        kicker = "Hiring does not fix a missing system."

    elif 'active_outbound' in outb:
        tension = "Volume without precision is expensive noise."
        bullets = [
            ("Unstructured outreach burns contacts",
             "Flat response rates with no enrichment or reply handling."),
            ("More sends means more ignored messages",
             "Without targeting precision, volume is just noise."),
            ("The fix is precision, not volume",
             "More sends does not mean more meetings."),
        ]
        kicker = "More sends does not mean more meetings."

    else:
        tension = "Right now, your growth depends on being found."
        company = p.get('company', 'You')
        bullets = [
            ("Pipeline arrives when buyers decide to look",
             f"{company}\u2019s growth depends on someone else making the first move."),
            ("Referral volume is uncontrollable",
             "It tracks relationships, not market opportunity."),
            ("Qualified buyers who do not know you exist are invisible",
             "There is no reach into that gap."),
        ]
        kicker = "If they do not find you, they do not find you. There is no backup."

    return tension, bullets, kicker


def _market_reality_content(p):
    company = p.get('company', 'The company')
    comps   = [c.strip() for c in (p.get('competitors') or '').split(',') if c.strip()]
    niche   = p.get('niche') or ''
    icp     = p.get('icp') or ''
    target  = icp or niche or 'your market'

    if comps:
        named = comps[0] if len(comps) == 1 else ' and '.join(comps[:2])
        verb  = 'is' if len(comps) == 1 else 'are'
        intro = f"{named} {verb} already in your buyers\u2019 inboxes."
        comp_cards = []
        for comp in comps[:2]:
            comp_cards.append((
                comp,
                f"Running structured cold outreach into {target}",
                f"Booking first conversations before {company} enters the picture",
            ))
        takeaway = "They get first contact. You do not."
        takeaway_sub = "First contact sets the frame. That matters more than having a better product."
    else:
        intro = f"Operators in {target} with an outbound system are winning deals {company} never sees."
        comp_cards = [
            ("The market is already in motion",
             f"Companies in {target} with structured outbound book 5\u201310 qualified conversations per month from cold traffic alone.",
             f"Those buyers would have chosen {company} \u2014 if {company} had been in their inbox first."),
            ("First contact wins the frame",
             "Whoever reaches the buyer first sets the context for every conversation that follows.",
             "The pipeline exists. You are just not in it."),
        ]
        takeaway = "The pipeline exists. You are just not in it."
        takeaway_sub = "First contact sets the frame. Whoever gets there first controls the conversation."

    return intro, comp_cards, takeaway, takeaway_sub


def _approach_bullets(p):
    notes    = p.get('notes') or ''
    pain_m   = re.search(r"Pain Point:\s*(.*)", notes)
    if pain_m:
        raw    = pain_m.group(1).strip().rstrip('.')
        core_m = re.search(r'\b(?:on|with|around|from)\s+(.+)$', raw, re.IGNORECASE)
        core   = core_m.group(1).lower() if core_m else raw.lower()
        pain_clause = f"already dealing with {core}"
    else:
        company = p.get('company', 'your company')
        pain_clause = f"already dealing with the problem {company} solves"

    return [
        f"We find the companies {pain_clause} \u2014 before they go looking for a solution.",
        "We reach them directly. Every message is grounded in something real about their business.",
        "Replies are classified the same day. Interested leads move to a booked call. Nothing is missed.",
        "You see everything: what went out, who replied, what moved forward.",
    ]


def _metrics(_p):
    return [
        (C_M1, "4\u20138",  "qualified calls/month"),
        (C_M2, "30",        "days to first results"),
        (C_M3, "\u00a30",   "cost if no qualified conversations"),
    ]


def _extract_hook(notes):
    if not notes:
        return ""
    m = re.search(r"Opener:\s*(.*)", notes)
    return m.group(1).strip() if m else ""


# ─── Canvas callbacks ────────────────────────────────────────────────────────

def _page_callback(canvas, doc):
    """Dark background + colored top bar + footer on every page."""
    w, h = letter
    margin = 0.75 * inch
    canvas.saveState()

    # Full dark background
    canvas.setFillColor(C_BG)
    canvas.rect(0, 0, w, h, fill=1, stroke=0)

    # Per-section colored top bar (5px)
    bar_color = _PAGE_BAR[min(doc.page - 1, len(_PAGE_BAR) - 1)]
    canvas.setFillColor(bar_color)
    canvas.rect(0, h - 5, w, 5, fill=1, stroke=0)

    # Footer separator line
    canvas.setFillColor(C_BORDER)
    canvas.rect(margin, 0.55 * inch, w - 2 * margin, 0.5, fill=1, stroke=0)

    # Footer text
    canvas.setFont('Helvetica', 7.5)
    canvas.setFillColor(C_FOOTER)
    canvas.drawString(margin, 0.35 * inch, f"{SENDER_NAME} \u00b7 Confidential")
    canvas.drawRightString(w - margin, 0.35 * inch, str(doc.page))

    canvas.restoreState()


# ─── Layout helpers ──────────────────────────────────────────────────────────

_PAGE_W, _PAGE_H = letter
_MARGIN = 0.75 * inch
_CONTENT_W = _PAGE_W - 2 * _MARGIN


def _section_label(label_text, color, S):
    """Small all-caps section label (e.g. 'THE PROBLEM')."""
    return Paragraph(
        f'<font color="#{color.hexval()}">{label_text.upper()}</font>',
        S['sec_label'],
    )


def _card2(head, body, S, bg=None, border=None):
    """Single card: bold heading + muted body text."""
    bg     = bg or C_CARD
    border = border or C_BORDER
    tbl = Table(
        [[Paragraph(head, S['card_head'])],
         [Paragraph(body, S['card_body'])]],
        colWidths=[_CONTENT_W],
    )
    tbl.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), bg),
        ('BOX',           (0, 0), (-1, -1), 1, border),
        ('TOPPADDING',    (0, 0), (-1, -1), 13),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 13),
        ('LEFTPADDING',   (0, 0), (-1, -1), 16),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 16),
        ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
    ]))
    return tbl


def _grid2x2(cards, S):
    """
    4-card 2×2 grid.
    cards: list of (heading, body) tuples — exactly 4 items.
    Pads to 4 if fewer provided.
    """
    while len(cards) < 4:
        cards.append(("", ""))

    col_w = (_CONTENT_W - 0.12 * inch) / 2

    def _cell(head, body):
        return [Paragraph(head, S['card_head']),
                Spacer(1, 4),
                Paragraph(body, S['card_body'])]

    data = [
        [_cell(*cards[0]), _cell(*cards[1])],
        [_cell(*cards[2]), _cell(*cards[3])],
    ]
    tbl = Table(data, colWidths=[col_w, col_w], rowHeights=[1.6 * inch, 1.6 * inch])
    tbl.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), C_CARD),
        ('BOX',           (0, 0), (0, 0), 1, C_BORDER),
        ('BOX',           (1, 0), (1, 0), 1, C_BORDER),
        ('BOX',           (0, 1), (0, 1), 1, C_BORDER),
        ('BOX',           (1, 1), (1, 1), 1, C_BORDER),
        ('INNERGRID',     (0, 0), (-1, -1), 0, C_BG),
        ('TOPPADDING',    (0, 0), (-1, -1), 13),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 13),
        ('LEFTPADDING',   (0, 0), (-1, -1), 14),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 14),
        ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
        ('COLPADDING',    (0, 0), (-1, -1), 6),
    ]))
    return tbl


def _metrics_row(metrics, S):
    """Horizontal row of 3 metric cards with large colored numbers."""
    col_w = (_CONTENT_W - 0.24 * inch) / 3

    def _mcell(color, num, lbl):
        return [
            Paragraph(f'<font color="#{color.hexval()}">{num}</font>', S['met_num']),
            Paragraph(lbl, S['met_lbl']),
        ]

    data = [[_mcell(*m) for m in metrics]]
    tbl = Table(data, colWidths=[col_w] * 3, rowHeights=[1.3 * inch])
    tbl.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), C_CARD),
        ('BOX',           (0, 0), (0, 0), 1, C_BORDER),
        ('BOX',           (1, 0), (1, 0), 1, C_BORDER),
        ('BOX',           (2, 0), (2, 0), 1, C_BORDER),
        ('INNERGRID',     (0, 0), (-1, -1), 0, C_BG),
        ('TOPPADDING',    (0, 0), (-1, -1), 14),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 14),
        ('LEFTPADDING',   (0, 0), (-1, -1), 18),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 18),
        ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
    ]))
    return tbl


def _comp_cards(comp_cards_data, S):
    """Two competitor cards side by side."""
    col_w = (_CONTENT_W - 0.12 * inch) / 2

    def _ccell(name, line1, line2):
        # Colored top accent bar per competitor
        return [
            Paragraph(f'<b>{name}</b>', S['card_head']),
            Spacer(1, 6),
            Paragraph(line1, S['card_body']),
            Spacer(1, 4),
            Paragraph(line2, S['card_body']),
        ]

    data = [[_ccell(*comp_cards_data[0]), _ccell(*comp_cards_data[1])]]
    tbl = Table(data, colWidths=[col_w, col_w], rowHeights=[2.0 * inch])
    tbl.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (0, 0), C_CARD),
        ('BACKGROUND',    (1, 0), (1, 0), C_CARD2),
        ('BOX',           (0, 0), (0, 0), 1, C_BORDER),
        ('BOX',           (1, 0), (1, 0), 1, C_BORDER),
        ('LINEABOVE',     (0, 0), (0, 0), 3, C_PURPLE),
        ('LINEABOVE',     (1, 0), (1, 0), 3, C_ORANGE),
        ('INNERGRID',     (0, 0), (-1, -1), 0, C_BG),
        ('TOPPADDING',    (0, 0), (-1, -1), 14),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 14),
        ('LEFTPADDING',   (0, 0), (-1, -1), 14),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 14),
        ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
    ]))
    return tbl


def _takeaway_box(text, sub, S):
    """Full-width red-bordered takeaway box."""
    tbl = Table(
        [[Paragraph(text, S['takeaway'])],
         [Paragraph(sub,  S['takeaway_sub'])]],
        colWidths=[_CONTENT_W],
    )
    tbl.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), HexColor('#1a0f0f')),
        ('BOX',           (0, 0), (-1, -1), 1, HexColor('#7f1d1d')),
        ('LINEABOVE',     (0, 0), (-1, 0), 3, C_RED),
        ('TOPPADDING',    (0, 0), (-1, -1), 12),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ('LEFTPADDING',   (0, 0), (-1, -1), 16),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 16),
    ]))
    return tbl


def _numbered_step(num, text, S, num_color=C_PURPLE):
    """Single numbered step card."""
    hex_col = num_color.hexval()
    num_cell = [Paragraph(
        f'<font color="#{hex_col}" size="14"><b>0{num}</b></font>',
        S['card_num'],
    )]
    body_cell = [Paragraph(text, S['card_body'])]
    tbl = Table(
        [[num_cell, body_cell]],
        colWidths=[0.55 * inch, _CONTENT_W - 0.55 * inch],
        rowHeights=[0.9 * inch],
    )
    tbl.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), C_CARD),
        ('BOX',           (0, 0), (-1, -1), 1, C_BORDER),
        ('LINEABOVE',     (0, 0), (-1, 0), 3, num_color),
        ('TOPPADDING',    (0, 0), (-1, -1), 13),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 13),
        ('LEFTPADDING',   (0, 0), (0, 0), 14),
        ('LEFTPADDING',   (1, 0), (1, 0), 10),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 14),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    return tbl


def _step_colors():
    return [C_INDIGO, C_ORANGE, C_GREEN, C_PURPLE]


def _cta_button(text, S):
    btn = Table(
        [[Paragraph(text, S['cta_btn'])]],
        colWidths=[3.4 * inch],
        rowHeights=[0.55 * inch],
    )
    btn.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), C_INDIGO),
        ('TOPPADDING',    (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('ALIGN',         (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('ROUNDEDCORNERS', [6]),
    ]))
    outer = Table([[btn]], colWidths=[_CONTENT_W])
    outer.setStyle(TableStyle([
        ('ALIGN',  (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING',    (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ('LEFTPADDING',   (0, 0), (-1, -1), 0),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 0),
    ]))
    return outer


# ─── Main generator ──────────────────────────────────────────────────────────

def generate_proposal(prospect: dict) -> str:
    """
    Build a dark deck-style growth breakdown PDF.
    Raises ValueError if input fails validation.
    Returns filepath of the generated PDF.
    """
    ok, reason = _validate_input(prospect)
    if not ok:
        raise ValueError(reason)

    company = (prospect.get('company') or 'Your Company').strip()
    name    = (prospect.get('name')    or 'Founder').strip()
    first   = name.split()[0]
    niche   = (prospect.get('niche')   or '').strip()
    today   = date.today().strftime('%B %Y')

    # Build content
    sit_lines                              = _situation_lines(prospect)
    ceil_tension, ceil_bullets, ceil_kicker = _ceiling_content(prospect)
    mkt_intro, comp_cards_data, mkt_tw, mkt_tw_sub = _market_reality_content(prospect)
    appr_bullets                           = _approach_bullets(prospect)
    metric_data                            = _metrics(prospect)

    # Validate content
    all_errors = []
    all_errors += _validate_section(
        "Current Situation", " ".join(sit_lines),
        require_tension=False, require_memorable=True,
    )
    ceil_text = ceil_tension + " " + " ".join(h + " " + b for h, b in ceil_bullets) + " " + ceil_kicker
    all_errors += _validate_section(
        "The Ceiling", ceil_text,
        require_tension=True, require_memorable=True,
    )
    mkt_text = mkt_intro + " " + " ".join(n + " " + l1 + " " + l2 for n, l1, l2 in comp_cards_data) + " " + mkt_tw
    all_errors += _validate_section(
        "Market Reality", mkt_text,
        require_tension=True, require_memorable=True,
    )
    all_errors += _validate_section(
        "Our Approach", " ".join(appr_bullets),
        require_tension=False, require_memorable=True,
    )
    if all_errors:
        raise ValueError("Content validation failed:\n" + "\n".join(all_errors))

    # Output path
    safe     = "".join(c if c.isalnum() else "_" for c in company).lower()
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filepath = os.path.join(OUTPUT_DIR, f"breakdown_{safe}.pdf")

    doc = SimpleDocTemplate(
        filepath, pagesize=letter,
        rightMargin=_MARGIN, leftMargin=_MARGIN,
        topMargin=0.72 * inch, bottomMargin=0.72 * inch,
    )
    S = _styles()
    story = []

    # ══════════════════════════════════════════════════════════════════════
    # PAGE 1 — COVER
    # ══════════════════════════════════════════════════════════════════════

    # Badge
    badge = Table(
        [[Paragraph("Built on Claude Code", S['cv_badge'])]],
        colWidths=[1.6 * inch],
        rowHeights=[0.26 * inch],
    )
    badge.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), C_INDIGO),
        ('TOPPADDING',    (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING',   (0, 0), (-1, -1), 10),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 10),
        ('ALIGN',         (0, 0), (-1, -1), 'LEFT'),
        ('ROUNDEDCORNERS', [4]),
    ]))

    story.append(Spacer(1, 0.15 * inch))
    story.append(badge)
    story.append(Spacer(1, 0.3 * inch))

    # Title
    title_text = f"Why {company}\u2019s pipeline stops\nwhen the budget does"
    story.append(Paragraph(title_text, S['cv_h1']))

    # Subtitle (niche | analysis type)
    sub_parts = []
    if niche:
        sub_parts.append(niche)
    sub_parts.append("Outbound Pipeline Analysis")
    story.append(Paragraph(" \u00b7 ".join(sub_parts), S['cv_sub']))

    story.append(Spacer(1, 0.55 * inch))

    # Metric cards row
    story.append(_metrics_row(metric_data, S))
    story.append(Spacer(1, 0.35 * inch))

    # Prepared for
    story.append(Paragraph(
        f"Prepared for {first} at {company} \u00b7 {today}", S['cv_meta']
    ))
    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════════════
    # PAGE 2 — THE PROBLEM
    # ══════════════════════════════════════════════════════════════════════

    story.append(_section_label("The Problem", C_ORANGE, S))
    story.append(Paragraph(
        f"Paid traffic alone cannot build {company}\u2019s pipeline", S['sec_title']
    ))
    story.append(Spacer(1, 0.1 * inch))

    # 4-card 2×2 grid — sit_lines + ceiling bullets blended
    grid_cards = []
    # Card 1 & 2: first two situation lines
    if len(sit_lines) >= 1:
        grid_cards.append((
            (prospect.get('icp') or "Your buyers") + " never see " + company,
            sit_lines[0] if sit_lines else "",
        ))
    # Card 2 from ceiling
    if ceil_bullets:
        grid_cards.append(ceil_bullets[0])
    # Card 3
    if len(ceil_bullets) > 1:
        grid_cards.append(ceil_bullets[1])
    # Card 4
    if len(ceil_bullets) > 2:
        grid_cards.append(ceil_bullets[2])

    story.append(_grid2x2(grid_cards, S))
    story.append(Spacer(1, 0.15 * inch))

    # Tension kicker
    story.append(Paragraph(ceil_tension, S['tension']))
    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════════════
    # PAGE 3 — MARKET REALITY
    # ══════════════════════════════════════════════════════════════════════

    story.append(_section_label("Market Reality", C_GREEN, S))
    story.append(Paragraph(mkt_intro, S['sec_title']))
    story.append(Spacer(1, 0.1 * inch))

    # Competitor cards
    if len(comp_cards_data) >= 2:
        story.append(_comp_cards(comp_cards_data[:2], S))
    elif comp_cards_data:
        h, l1, l2 = comp_cards_data[0]
        story.append(_card2(h, l1 + " " + l2, S))

    story.append(Spacer(1, 0.15 * inch))
    story.append(_takeaway_box(mkt_tw, mkt_tw_sub, S))
    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════════════
    # PAGE 4 — THE SYSTEM
    # ══════════════════════════════════════════════════════════════════════

    story.append(_section_label("The System", C_PURPLE, S))
    story.append(Paragraph("The System", S['sec_title']))
    story.append(Spacer(1, 0.1 * inch))

    colors = _step_colors()
    for i, bullet in enumerate(appr_bullets[:4]):
        c = colors[i % len(colors)]
        story.append(_numbered_step(i + 1, bullet, S, num_color=c))
        story.append(Spacer(1, 0.12 * inch))

    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════════════
    # PAGE 5 — PILOT + CTA
    # ══════════════════════════════════════════════════════════════════════

    story.append(_section_label("Pilot + CTA", C_RED, S))
    story.append(Paragraph("No results. No charge.", S['cta_h1']))
    story.append(Spacer(1, 0.1 * inch))
    story.append(_metrics_row(metric_data, S))
    story.append(Spacer(1, 0.3 * inch))

    # CTA body block
    cta_block = Table(
        [[Paragraph(
            f"Book a 20-minute call. We will walk through the target list, "
            f"the sequence, and expected volume \u2014 specific to {company}.",
            S['cta_body'],
        )],
         [Spacer(1, 0.15 * inch)],
         [_cta_button(f"Book a Call \u2192  {CTA_LINK}", S)],
         [Spacer(1, 0.1 * inch)],
         [Paragraph(
            f"Pilot: Free  \u00b7  Ongoing: from \u00a31,500/month  \u00b7  No long-term contract",
            S['cta_price'],
         )],
        ],
        colWidths=[_CONTENT_W],
    )
    cta_block.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), C_CARD),
        ('BOX',           (0, 0), (-1, -1), 1, C_BORDER),
        ('TOPPADDING',    (0, 0), (-1, -1), 16),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 16),
        ('LEFTPADDING',   (0, 0), (-1, -1), 20),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 20),
        ('ALIGN',         (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(cta_block)

    # Build
    doc.build(story, onFirstPage=_page_callback, onLaterPages=_page_callback)
    return filepath


# ─── Batch runner ────────────────────────────────────────────────────────────

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


# ─── __main__ ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    rich = {
        "name": "James Cole",
        "company": "Apex Digital",
        "email": "james@apexdigital.io",
        "status": "qualified",
        "niche": "B2B SaaS for construction project managers",
        "icp": "mid-sized UK construction firms managing 5+ concurrent projects",
        "website_headline": "Stop losing projects to miscommunication",
        "product_feature": "real-time site-to-office sync with automated progress reporting",
        "competitors": "Buildertrend, CoConstruct",
        "ad_status": "running_ads",
        "outbound_status": "no_outbound",
        "notes": (
            "[Research Hook]\n"
            "Pain Point: Construction PMs spend 6+ hours per week on manual status updates.\n"
            "Growth Signal: Recently rebranded with enterprise case studies added.\n"
            "Opener: Apex Digital's positioning around miscommunication is sharp -- "
            "it is a problem every PM on a live build recognises immediately."
        ),
    }

    thin = {"name": "James Cole", "company": "Apex Digital", "notes": ""}

    print("Testing thin data rejection...")
    try:
        generate_proposal(thin)
    except ValueError as e:
        print(f"  [OK] Rejected: {e}")

    print("\nGenerating dark deck PDF...")
    try:
        path = generate_proposal(rich)
        print(f"  [OK] {path}")
    except Exception as e:
        print(f"  [FAIL] {e}")
