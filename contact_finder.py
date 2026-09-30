"""
contact_finder.py - Find the best contact email on a company website.

Crawls the homepage plus contact / about / team / careers pages, decodes
obfuscated addresses (Cloudflare email protection, "name [at] domain"),
drops junk and third-party addresses, then ranks what is left so a
graduate application goes to careers/jobs first, a named person second,
and a generic inbox last. Only addresses that actually appear on the
company's own site are ever returned - nothing is guessed.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

import ats_jobs

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

_EXTRA_PATHS = (
    "/contact", "/contact-us", "/about", "/about-us", "/team", "/our-team",
    "/people", "/careers", "/jobs", "/join-us", "/work-with-us",
)
_LINK_KEYWORDS = ("contact", "about", "team", "people", "career", "job", "join", "hiring")
_MAX_EXTRA_PAGES = 8

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_OBFUSCATED_RE = re.compile(
    r"([a-zA-Z0-9._%+\-]+)\s*[\[\(]\s*at\s*[\]\)]\s*([a-zA-Z0-9.\-]+?)\s*[\[\(]\s*dot\s*[\]\)]\s*([a-zA-Z]{2,})",
    re.IGNORECASE,
)
_FILE_TLDS = {"png", "jpg", "jpeg", "gif", "svg", "webp", "css", "js", "ico", "pdf", "woff", "woff2"}

# Addresses that never reach a person who hires.
_JUNK = {
    "noreply", "no-reply", "donotreply", "do-not-reply", "bounce", "postmaster",
    "webmaster", "mailer", "daemon", "abuse", "privacy", "legal", "gdpr", "dpo",
    "security", "press", "media", "pr", "editor", "editorial", "marketing",
    "advertising", "ads", "accounts", "accounting", "billing", "invoice",
    "invoices", "payments", "complaints",
}
_LOW = {"sales", "support", "help", "helpdesk", "service", "customerservice"}
_CAREERS = {
    "careers", "career", "jobs", "job", "recruitment", "recruiting", "recruiter",
    "talent", "hr", "people", "hiring", "apply", "graduates", "graduate",
    "earlycareers", "join", "joinus", "work",
}
_CAREERS_SUBSTRINGS = ("career", "recruit", "hiring", "graduate", "talent", "vacanc")
_GENERIC = {
    "hello", "hi", "hey", "contact", "contactus", "enquiries", "enquiry", "info",
    "team", "office", "admin", "general", "mail", "business", "reception", "welcome",
    "partners", "partner", "partnerships", "enquire", "bookings", "studio",
}
_FREEMAIL = {
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.uk", "outlook.com",
    "hotmail.com", "hotmail.co.uk", "icloud.com", "live.com", "aol.com",
}

_KIND_SCORE = {"careers": 5, "personal": 4, "generic": 3, "low": 1}


def _fetch(url: str) -> str:
    try:
        resp = requests.get(url, timeout=8, headers=_HEADERS)
        resp.raise_for_status()
        return resp.text
    except Exception:
        return ""


def _decode_cfemail(encoded: str) -> str:
    """Decode a Cloudflare email-protection hex string."""
    try:
        key = int(encoded[:2], 16)
        return "".join(
            chr(int(encoded[i:i + 2], 16) ^ key) for i in range(2, len(encoded), 2)
        )
    except (ValueError, IndexError):
        return ""


def _emails_from_html(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    found: list[str] = []

    for tag in soup.find_all(attrs={"data-cfemail": True}):
        addr = _decode_cfemail(tag["data-cfemail"])
        if addr:
            found.append(addr.lower())

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().startswith("mailto:"):
            found.append(href[7:].split("?")[0].strip().lower())
        elif "/cdn-cgi/l/email-protection#" in href:
            addr = _decode_cfemail(href.split("#", 1)[1])
            if addr:
                found.append(addr.lower())

    text = soup.get_text(" ")
    found.extend(m.lower() for m in _EMAIL_RE.findall(text))
    found.extend(f"{u}@{d}.{t}".lower() for u, d, t in _OBFUSCATED_RE.findall(text))
    return found


def _valid(addr: str) -> bool:
    if " " in addr or len(addr) > 254 or addr.count("@") != 1:
        return False
    local, domain = addr.split("@")
    if not local or len(local) > 64 or "." not in domain or len(domain) > 63:
        return False
    tld = domain.rsplit(".", 1)[-1]
    if len(tld) > 6 or not tld.isalpha() or tld in _FILE_TLDS:
        return False
    return True


def _host(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _domain_matches(addr: str, site_host: str) -> bool:
    domain = addr.split("@")[1]
    return domain == site_host or domain.endswith("." + site_host) or site_host.endswith("." + domain)


def _classify(local: str) -> str:
    """Return junk | low | careers | generic | personal for an email local part."""
    key = re.sub(r"[._\-+0-9]", "", local.lower())
    if key in _JUNK or local.lower() in _JUNK:
        return "junk"
    if key in _LOW:
        return "low"
    if key in _CAREERS or any(w in key for w in _CAREERS_SUBSTRINGS):
        return "careers"
    if key in _GENERIC:
        return "generic"
    parts = re.split(r"[._\-]", local.lower())
    if (
        re.fullmatch(r"[a-z]+([._\-][a-z]+)?", local.lower())
        and len(key) >= 3
        and all(len(p) <= 14 for p in parts)
    ):
        return "personal"
    return "generic"


def _person_name(local: str) -> str:
    """Title-cased name from first.last / first_last / first, else ''."""
    parts = re.split(r"[._\-]", local.lower())
    if not 1 <= len(parts) <= 2 or not all(p.isalpha() and len(p) >= 2 for p in parts):
        return ""
    return " ".join(p.capitalize() for p in parts)


def rank_emails(emails: list[str], site_host: str) -> list[dict]:
    """Filter and rank raw addresses; best first. Order among equals is stable."""
    seen: set[str] = set()
    on_domain: list[dict] = []
    freemail: list[dict] = []
    for addr in emails:
        addr = addr.strip().lower()
        if addr in seen or not _valid(addr):
            continue
        seen.add(addr)
        kind = _classify(addr.split("@")[0])
        if kind == "junk":
            continue
        item = {"email": addr, "kind": kind, "name": _person_name(addr.split("@")[0]) if kind == "personal" else ""}
        if _domain_matches(addr, site_host):
            on_domain.append(item)
        elif addr.split("@")[1] in _FREEMAIL:
            item["kind"] = "low" if kind != "careers" else "careers"
            item["name"] = ""
            freemail.append(item)
    ranked = sorted(on_domain, key=lambda i: -_KIND_SCORE[i["kind"]])
    return ranked + sorted(freemail, key=lambda i: -_KIND_SCORE[i["kind"]])


def _candidate_pages(base_url: str, homepage_html: str) -> list[str]:
    pages: list[str] = []
    host = _host(base_url)

    def add(url: str) -> None:
        url = url.split("#")[0]
        if url and url not in pages and url.rstrip("/") != base_url.rstrip("/"):
            pages.append(url)

    soup = BeautifulSoup(homepage_html, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().startswith(("mailto:", "tel:", "javascript:")):
            continue
        full = urljoin(base_url, href)
        if _host(full) != host:
            continue
        if any(k in (urlparse(full).path + " " + a.get_text(" ")).lower() for k in _LINK_KEYWORDS):
            add(full)
    for path in _EXTRA_PATHS:
        add(urljoin(base_url, path))
    return pages[:_MAX_EXTRA_PAGES]


_CAREER_URL_HINTS = ("career", "job", "vacanc", "join", "hiring", "work-with", "opportunit", "recruit")
_ROLE_RE = re.compile(
    r"\b(?:(?:senior|junior|graduate|associate|lead|principal|entry[- ]level)\s+)?"
    r"(?:(?:data|business|product|commercial|financial|fintech|revenue|operations|insights?|bi|"
    r"reporting|strategy|marketing|risk|credit|pricing|quantitative|growth|performance|research)\s+){1,2}"
    r"analyst\b",
    re.IGNORECASE,
)
_GRAD_RE = re.compile(
    r"graduate (?:scheme|programme|program|analyst|role|opportunit)|early[- ]careers?|entry[- ]level",
    re.IGNORECASE,
)
_MAX_ROLES = 4


def _is_career_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    return any(hint in path for hint in _CAREER_URL_HINTS)


def _scan_roles(html: str) -> tuple[list[str], bool]:
    """Analyst-type job titles and graduate/early-careers wording on a careers page."""
    text = BeautifulSoup(html, "html.parser").get_text(" ")
    text = re.sub(r"\s+", " ", text)
    roles = [" ".join(m.group(0).split()).title() for m in _ROLE_RE.finditer(text)]
    return roles, bool(_GRAD_RE.search(text))


def describe_hiring(intel: dict) -> str:
    """Short hiring-signal sentence for the email prompt, or '' when there is none."""
    roles = intel.get("hiring_roles") or []
    if roles:
        return "Careers page lists: " + ", ".join(roles)
    if intel.get("graduate_friendly"):
        return "Careers page mentions a graduate / early-careers programme"
    return ""


def find_site_intel(url: str) -> dict:
    """
    One crawl, two answers: ranked contact candidates plus a hiring signal.

    Returns {'contacts': [...], 'hiring_roles': [analyst-type titles found on careers
    pages], 'graduate_friendly': bool}. Only careers-style pages are scanned for roles,
    so marketing copy about "analysts" is not mistaken for a vacancy.
    """
    intel = {"contacts": [], "hiring_roles": [], "graduate_friendly": False}
    if not url:
        return intel
    if not url.startswith("http"):
        url = "https://" + url

    home = _fetch(url)
    host = _host(url)
    emails = _emails_from_html(home) if home else []

    roles: list[str] = []
    raw_pages = [home] if home else []
    pages = _candidate_pages(url, home)
    with ThreadPoolExecutor(4) as ex:
        for page_url, html in zip(pages, ex.map(_fetch, pages)):
            if not html:
                continue
            raw_pages.append(html)
            emails.extend(_emails_from_html(html))
            if _is_career_url(page_url):
                found, graduate = _scan_roles(html)
                roles.extend(found)
                intel["graduate_friendly"] = intel["graduate_friendly"] or graduate

    # Real openings from the company's public job board (Greenhouse, Lever, ...) come first:
    # careers pages usually load their job list with JavaScript, so their HTML shows none.
    roles = ats_jobs.analyst_jobs(raw_pages) + roles
    seen: set[str] = set()
    for role in roles:
        if role.lower() not in seen:
            seen.add(role.lower())
            intel["hiring_roles"].append(role)
    intel["hiring_roles"] = intel["hiring_roles"][:_MAX_ROLES]
    intel["contacts"] = rank_emails(emails, host)
    return intel


def find_contacts(url: str) -> list[dict]:
    """Return ranked contact candidates found on the company's own site."""
    return find_site_intel(url)["contacts"]


def find_best_contact(url: str) -> dict:
    """Best single contact: {'email','kind','name'} or {} when nothing usable is found."""
    ranked = find_contacts(url)
    return ranked[0] if ranked else {}
