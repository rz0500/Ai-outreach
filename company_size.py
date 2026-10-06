"""
company_size.py - Is this company inside the target headcount band (default 20-250)?

No source we use (Google Maps, Adzuna) gives a headcount, so this reads the company's
own about / team / careers pages and asks Claude for an explicit employee count. Only
statements that appear verbatim on the page count ("team of 45", "200+ people"), and
the quoted evidence is checked against the fetched text. A page that merely lists a few
team members only gives a lower bound. Never raises.

Verdicts: "in" (stated size inside the band), "out" (stated size outside it),
"unknown" (no usable statement). `SIZE_UNKNOWN_POLICY` (settings) decides what the
pipeline does with "unknown".
"""

from __future__ import annotations

import json
import logging
import os
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from company_news import _norm, _page_text
from contact_finder import _fetch, _host

logger = logging.getLogger(__name__)

_MODEL = "claude-haiku-4-5"
MIN_EMPLOYEES = 20
MAX_EMPLOYEES = 250
_MAX_PAGES = 4
_PATHS = ("/about", "/about-us", "/company", "/team", "/our-team", "/people", "/who-we-are", "/careers")
_LINK = re.compile(r"about|team|company|people|who-we-are|careers|culture|story|join", re.I)
_SKIP = re.compile(r"login|signin|cart|privacy|cookie|terms|\.pdf|mailto:|tel:|blog|news", re.I)


def _pages(base_url: str, homepage_html: str) -> list[str]:
    host = _host(base_url)
    found: list[str] = []
    soup = BeautifulSoup(homepage_html or "", "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if _SKIP.search(href) or not (_LINK.search(href) or _LINK.search(a.get_text(" ", strip=True))):
            continue
        url = urljoin(base_url, href).split("#")[0]
        if _host(url) == host and url.rstrip("/") != base_url.rstrip("/") and url not in found:
            found.append(url)
    for path in _PATHS:
        url = urljoin(base_url, path)
        if url not in found:
            found.append(url)
    return found


def classify(low: int | None, high: int | None, basis: str,
             minimum: int = MIN_EMPLOYEES, maximum: int = MAX_EMPLOYEES) -> str:
    """'in' / 'out' / 'unknown' for a stated or counted headcount range."""
    if basis not in ("stated", "counted", "estimated") or (low is None and high is None):
        return "unknown"
    lo = low if low is not None else high
    hi = high                      # None means open-ended ("200+")
    if basis == "counted":
        # a team page only proves "at least this many"
        return "out" if lo > maximum else "unknown"
    if lo > maximum:
        return "out"
    if basis == "estimated":
        # A rough range: decide on its midpoint, with some slack at the upper edge.
        mid = (lo + (hi if hi is not None else lo)) / 2
        if mid >= maximum * 1.2:
            return "out"
        return "out" if mid < minimum else "in"
    if hi is not None and hi < minimum:
        return "out"
    if hi is not None and lo >= minimum and hi <= maximum:
        return "in"
    return "unknown"               # open-ended ("100+") or straddling an edge


def _extract(company: str, source: str) -> dict:
    import anthropic

    prompt = (
        f"Below is text copied from the website of {company}. Work out how many people work at the company.\n"
        '1) If the text explicitly states it (for example "a team of 45", "120 employees", '
        '"200+ people", "50-100 staff"), use that with "basis":"stated". '
        '2) Else if a team page lists named staff, count them: "basis":"counted", employees_low = the count. '
        '3) Else ESTIMATE the headcount range from the text (offices, product breadth, customers, how many roles '
        'or team members appear) and from anything you already know about this company, and set "basis":"estimated". '
        'You are expected to estimate: many companies are well known (a bank with millions of customers has thousands '
        'of staff) and a one-office local firm is usually under 20. Give "confidence":"high" when you recognise '
        'the company or the scale is obvious, "medium" when reasoned from the text, "low" when truly guessing. '
        'Use "basis":"none" only if there is no basis at all. Ignore customer counts, years, and revenue.\n'
        'Respond with ONLY JSON: {"employees_low": int|null, "employees_high": int|null, '
        '"basis": "stated"|"counted"|"estimated"|"none", "confidence": "high"|"medium"|"low", '
        '"evidence": "<exact verbatim quote of 3-25 words for stated/counted, else empty>"}\n\n'
        "TEXT:\n" + source
    )
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=_MODEL, max_tokens=250, messages=[{"role": "user", "content": prompt}]
    )
    raw = "".join(getattr(b, "text", "") for b in response.content)
    match = re.search(r"\{.*\}", raw, re.S)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except ValueError:
        return {}


def check_company_size(website: str, company: str,
                       minimum: int = MIN_EMPLOYEES, maximum: int = MAX_EMPLOYEES) -> dict:
    """{'verdict','low','high','basis','evidence'}; verdict 'unknown' on any failure or no API key."""
    unknown = {"verdict": "unknown", "low": None, "high": None, "basis": "none", "evidence": ""}
    if not website or not os.getenv("ANTHROPIC_API_KEY", "").strip():
        return unknown
    try:
        base = website if website.startswith("http") else f"https://{website}"
        home = _fetch(base)
        chunks = [_page_text(home)] if home else []
        fetched = 0
        for url in _pages(base, home):
            if fetched >= _MAX_PAGES:
                break
            html = _fetch(url)
            if html:
                fetched += 1
                chunks.append(_page_text(html))
        source = "\n\n".join(c for c in chunks if c)
        if len(source) < 150:
            return unknown
        data = _extract(company, source)
        basis = str(data.get("basis", "none"))
        evidence = str(data.get("evidence", "")).strip()
        if basis == "none":
            return unknown
        if basis != "estimated" and (not evidence or _norm(evidence) not in _norm(source)):
            return unknown          # a stated/counted size needs a verified quote
        if basis == "estimated" and str(data.get("confidence", "low")) == "low":
            return unknown          # a low-confidence guess is not evidence
        low, high = data.get("employees_low"), data.get("employees_high")
        low = int(low) if isinstance(low, (int, float)) else None
        high = int(high) if isinstance(high, (int, float)) else None
        return {"verdict": classify(low, high, basis, minimum, maximum), "low": low, "high": high,
                "basis": basis, "evidence": evidence}
    except Exception as exc:
        logger.warning("[Size] check failed for %s: %s", company, exc)
        return unknown


def screen_names(companies: list[tuple[str, str]],
                 minimum: int = MIN_EMPLOYEES, maximum: int = MAX_EMPLOYEES) -> dict[str, str]:
    """
    Cheap pre-filter on names alone (one batched call, no website fetch): {name: 'out'} for
    companies the model confidently knows are outside the band. Anything it does not recognise is
    simply absent (kept), so this only ever removes obvious large corporates / tiny firms.
    """
    if not companies or not os.getenv("ANTHROPIC_API_KEY", "").strip():
        return {}
    try:
        import anthropic

        listing = "\n".join(f"{i}. {name} ({loc})" if loc else f"{i}. {name}"
                            for i, (name, loc) in enumerate(companies, 1))
        prompt = (
            "For each company below, estimate its total employee count range ONLY if you genuinely "
            'recognise it (well-known corporates, banks, listed firms, big consultancies, NHS/universities). '
            "Skip companies you do not recognise.\n"
            'Respond with ONLY JSON: {"results": [{"n": <number>, "low": int, "high": int, '
            '"confidence": "high"|"medium"}]}\n\n' + listing
        )
        response = anthropic.Anthropic().messages.create(
            model=_MODEL, max_tokens=1500, messages=[{"role": "user", "content": prompt}]
        )
        raw = "".join(getattr(b, "text", "") for b in response.content)
        match = re.search(r"\{.*\}", raw, re.S)
        items = json.loads(match.group(0)).get("results", []) if match else []
    except Exception as exc:
        logger.warning("[Size] name screen failed: %s", exc)
        return {}
    out: dict[str, str] = {}
    for item in items:
        try:
            name = companies[int(item["n"]) - 1][0]
            if str(item.get("confidence")) not in ("high", "medium"):
                continue
            if classify(int(item["low"]), int(item["high"]), "estimated", minimum, maximum) == "out":
                out[name] = "out"
        except (KeyError, ValueError, TypeError, IndexError):
            continue
    return out
