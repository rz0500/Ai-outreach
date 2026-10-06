"""
company_news.py - Real, recent facts about a company, taken from its own website.

Reads the company's news / blog / press / case-study pages and asks Claude to pull
out one or two concrete recent things they did (a launch, a funding round, a new
office, a partnership, an award). Every fact must come with a verbatim quote from
the page, and the quote is checked against the fetched text, so an email can only
mention something the company actually published. Returns "" when nothing solid is
found (never raises); the email then makes no "recent" claim.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import date
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from contact_finder import _fetch, _host

logger = logging.getLogger(__name__)

_MODEL = "claude-haiku-4-5"
_MAX_PAGES = 3
_PAGE_CHARS = 3500
_FALLBACK_PATHS = ("/news", "/blog", "/press", "/insights", "/latest", "/media", "/case-studies")
_NEWS_LINK = re.compile(
    r"news|blog|press|insight|case-stud|latest|media|updates|stories|announce|article", re.I
)
_SKIP_LINK = re.compile(r"login|signin|cart|privacy|cookie|terms|careers|jobs|\.pdf|mailto:|tel:", re.I)


def _news_pages(base_url: str, homepage_html: str) -> list[str]:
    """Same-site pages most likely to hold recent news, homepage links first."""
    host = _host(base_url)
    found: list[str] = []
    soup = BeautifulSoup(homepage_html or "", "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        label = a.get_text(" ", strip=True)
        if _SKIP_LINK.search(href):
            continue
        if not (_NEWS_LINK.search(href) or _NEWS_LINK.search(label)):
            continue
        url = urljoin(base_url, href).split("#")[0]
        if _host(url) == host and url.rstrip("/") != base_url.rstrip("/") and url not in found:
            found.append(url)
    for path in _FALLBACK_PATHS:
        url = urljoin(base_url, path)
        if url not in found:
            found.append(url)
    return found


def _page_text(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
        tag.decompose()
    text = re.sub(r"[ \t]+", " ", soup.get_text("\n", strip=True))
    return text[:_PAGE_CHARS]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _extract(company: str, source: str, today: date) -> list[str]:
    """Ask Claude for up to two recent facts; keep only those whose quote is in `source`."""
    import anthropic

    prompt = (
        f"Today is {today.isoformat()}. Below is text copied from the website of {company}.\n"
        "Pick at most TWO concrete, specific things the company itself did recently "
        "(product launch, funding, partnership, new office or hire, award, notable client "
        "win, report published). Prefer items dated within the last 12 months; ignore anything "
        "older than 24 months, generic marketing claims, and anything not stated in the text.\n"
        'For each, give "fact" (one plain sentence, no hype) and "evidence" (an exact, '
        "verbatim quote of 5-25 words copied from the text that proves it).\n"
        'Respond with ONLY JSON: {"facts": [{"fact": "...", "evidence": "..."}]}. '
        'If nothing qualifies, respond {"facts": []}.\n\nTEXT:\n' + source
    )
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=_MODEL, max_tokens=400, messages=[{"role": "user", "content": prompt}]
    )
    raw = "".join(getattr(b, "text", "") for b in response.content)
    match = re.search(r"\{.*\}", raw, re.S)
    if not match:
        return []
    try:
        items = json.loads(match.group(0)).get("facts", [])
    except ValueError:
        return []
    haystack = _norm(source)
    facts: list[str] = []
    for item in items[:2]:
        fact = str((item or {}).get("fact", "")).strip()
        quote = _norm(str((item or {}).get("evidence", "")))
        if fact and len(quote) >= 20 and quote in haystack:
            facts.append(fact)
    return facts


def find_recent_facts(website: str, company: str, today: date | None = None) -> str:
    """Up to two verified recent facts joined by ' | ', or '' when none (or no API key)."""
    if not website or not os.getenv("ANTHROPIC_API_KEY", "").strip():
        return ""
    try:
        base = website if website.startswith("http") else f"https://{website}"
        home = _fetch(base)
        chunks = [_page_text(home)] if home else []
        fetched = 0
        for url in _news_pages(base, home):
            if fetched >= _MAX_PAGES:
                break
            html = _fetch(url)
            if not html:
                continue
            fetched += 1
            chunks.append(_page_text(html))
        source = "\n\n".join(c for c in chunks if c)
        if len(source) < 200:
            return ""
        return " | ".join(_extract(company, source, today or date.today()))
    except Exception as exc:
        logger.warning("[News] recent-facts lookup failed for %s: %s", company, exc)
        return ""
