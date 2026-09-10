"""
pdf_generator.py — Candidate Portfolio & Pitch PDF Generator
==============================================================
Produces a dark-background candidate pitch document for graduate career
outreach: cover badge, degree/university header, core-skills grid,
tailored alignment card, and a CTA box.

Required input fields:
  company

Optional (improve specificity):
  name, niche, icp, website_headline, product_feature, competitors,
  hiring_signal, notes
"""

import os
from datetime import date

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, white
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer,
    Table, TableStyle,
)

from database import DB_PATH, get_all_prospects
from settings import get_candidate_cv_url

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
C_ORANGE  = HexColor('#f97316')
C_GREEN   = HexColor('#10b981')   # tailored alignment
C_PURPLE  = HexColor('#8b5cf6')
C_RED     = HexColor('#ef4444')   # cta

# Per-page top bar colours (index = page number - 1)
_PAGE_BAR = [C_INDIGO, C_ORANGE, C_GREEN, C_PURPLE, C_RED]

SENDER_NAME = "Ritish"


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

def _validate_input(p):
    missing = [f for f in ['company'] if not (p.get(f) or '').strip()]
    if missing:
        return False, f"Missing required fields: {missing}"
    return True, ""


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
    canvas.drawString(margin, 0.35 * inch, f"{SENDER_NAME} · Confidential")
    canvas.drawRightString(w - margin, 0.35 * inch, str(doc.page))

    canvas.restoreState()


# ─── Layout helpers ──────────────────────────────────────────────────────────

_PAGE_W, _PAGE_H = letter
_MARGIN = 0.75 * inch
_CONTENT_W = _PAGE_W - 2 * _MARGIN


def _section_label(label_text, color, S):
    """Small all-caps section label (e.g. 'TAILORED ALIGNMENT')."""
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


# ─── Main generator ──────────────────────────────────────────────────────────

def generate_proposal(prospect: dict) -> str:
    """
    Build a dark deck-style Candidate Portfolio & Pitch PDF for Ritish.
    Returns filepath of the generated PDF.
    """
    ok, reason = _validate_input(prospect)
    if not ok:
        raise ValueError(reason)

    company = (prospect.get('company') or 'Target Employer').strip()
    today   = date.today().strftime('%B %Y')

    # Output path
    safe     = "".join(c if c.isalnum() else "_" for c in company).lower()
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filepath = os.path.join(OUTPUT_DIR, f"candidate_pitch_{safe}.pdf")

    doc = SimpleDocTemplate(
        filepath, pagesize=letter,
        rightMargin=_MARGIN, leftMargin=_MARGIN,
        topMargin=0.72 * inch, bottomMargin=0.72 * inch,
    )
    S = _styles()
    story = []

    # Badge
    badge = Table(
        [[Paragraph("CANDIDATE PROFILE & PORTFOLIO", S['cv_badge'])]],
        colWidths=[2.2 * inch],
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

    story.append(Spacer(1, 0.1 * inch))
    story.append(badge)
    story.append(Spacer(1, 0.2 * inch))

    # Title & Degree Header
    story.append(Paragraph("Ritish — BSc FinTech & Data Analytics", S['cv_h1']))
    story.append(Paragraph(f"Tailored Candidate Pitch for <b>{company}</b> · {today}", S['cv_sub']))
    story.append(Paragraph("University of Westminster · UK & EU Work Rights (Italian Passport)", S['cv_meta']))

    story.append(Spacer(1, 0.3 * inch))

    # Core Competencies Grid
    skills_cards = [
        ("Data Stack & Technical Skills", "Python, SQL, Power BI, Excel, Data Modeling, Dashboard Development"),
        ("Workflow Automation & APIs", "n8n automation pipelines, REST APIs, Twilio API, Stripe API, NoCode tools"),
        ("Performance & Growth Analytics", "Conversion Funnel Tracking, CPL & ROAS Optimization, A/B Testing, User Metrics"),
        ("Commercial & Client Experience", "Built and operated Harmony Booths (harmonybooths.com), sales & client communication"),
    ]
    story.append(_grid2x2(skills_cards, S))
    story.append(Spacer(1, 0.25 * inch))

    # Value Proposition for Company
    story.append(_section_label("Tailored Alignment", C_GREEN, S))
    story.append(_card2(
        f"How Ritish can contribute to {company}'s Analytics & Operations",
        f"With a solid academic foundation in FinTech & Data Analytics and practical experience building end-to-end commercial automations and managing funnels for Harmony Booths, Ritish brings a rare mix of technical capability (Python/SQL/Power BI) and sharp commercial thinking. Ideal for Graduate Data, Business Analyst, or RevOps roles at {company}.",
        S,
    ))

    story.append(Spacer(1, 0.25 * inch))

    # CTA Box
    story.append(_takeaway_box(
        "Open to a brief 10-minute coffee chat or portfolio review",
        f"Contact: info@outreachempower.com · CV: {get_candidate_cv_url()} · Tailored for {company}",
        S,
    ))

    doc.build(story, onFirstPage=_page_callback, onLaterPages=_page_callback)
    return filepath


# ─── Batch runner ────────────────────────────────────────────────────────────

def run_proposal_batch(db_path: str = DB_PATH) -> int:
    """Generate candidate pitch PDFs for all qualified/in-sequence target employers."""
    print("Starting Candidate Pitch PDF Generator...")
    prospects = [
        p for p in get_all_prospects(db_path)
        if p['status'] in ('qualified', 'in_sequence')
    ]
    if not prospects:
        print("  No qualified/in_sequence target employers found.")
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

    thin = {"name": "James Cole", "company": ""}

    print("Testing missing-company rejection...")
    try:
        generate_proposal(thin)
    except ValueError as e:
        print(f"  [OK] Rejected: {e}")

    print("\nGenerating candidate pitch PDF...")
    try:
        path = generate_proposal(rich)
        print(f"  [OK] {path}")
    except Exception as e:
        print(f"  [FAIL] {e}")
