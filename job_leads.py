"""
job_leads.py - Companies with live analyst vacancies, from the Adzuna job-search API.

A company advertising an analyst role right now is the best possible cold-email
target: it has a data function, it is spending money on it, and the email can
say why we are writing. This module rotates through analyst-type searches,
keeps relevant roles only, drops recruitment agencies and job boards, finds each
employer's website through Google Maps, and inserts new companies as prospects
carrying a `hiring_signal` ("Advertising: <role>") so they are emailed first.
"""

from __future__ import annotations

import json
import logging
import os
import re

import requests

import database
from google_maps_finder import get_googlemaps_client
from lead_discovery import domain_of
from settings import get_adzuna_credentials

logger = logging.getLogger(__name__)

_URL = "https://api.adzuna.com/v1/api/jobs/gb/search/{page}"
_TIMEOUT = 30
_PAGES_PER_SEARCH = 3
_MAX_PAGE = 20          # 1,000 jobs deep, then start over (new postings keep arriving)

# Rotated one after another; each returns UK jobs from the last 30 days, newest first.
SEARCHES: list[dict] = [
    {"title_only": "analyst", "what_or": "graduate junior entry associate trainee apprentice"},
    {"what": "data analyst"},
    {"what": "business analyst"},
    {"what": "product analyst"},
    {"what": "commercial analyst"},
    {"what": "revenue operations analyst"},
    {"what": "insights analyst"},
    {"what": "bi analyst"},
    {"what": "reporting analyst"},
    {"what": "operations analyst"},
    {"what": "fintech analyst"},
]

_EARLY_CAREER = re.compile(r"graduate|junior|entry|associate|trainee|apprentice|intern|placement", re.I)
_SENIOR = re.compile(r"senior|lead|principal|head of|director|manager|staff|architect|snr", re.I)
_ANALYST = re.compile(r"analyst|analytics", re.I)
_FIT = re.compile(
    r"data|business|product|commercial|financ|fintech|credit|risk|insight|\bbi\b|reporting|pricing|"
    r"strateg|operations|revenue|revops|marketing|performance|research|quantitative|investment|"
    r"management information|\bmi\b|crm|growth|customer|market|econom",
    re.I,
)
_NOT_OUR_ROLE = re.compile(
    r"cyber|security|\bsoc\b|support|help ?desk|service desk|desk|test|\bqa\b|technical|network|"
    r"infrastructure|clinical|laborator|\blab\b|nurse|planner|second line|first line|engineer|"
    r"developer|devops|sap |salesforce admin|payroll|underwrit|claims|mortgage|fraud|aml|kyc|sanction",
    re.I,
)
_AGENCY = re.compile(
    r"recruit|staffing|resourc|personnel|search & selection|selection|talent|appointments|"
    r"\bhays\b|harnham|robert half|michael page|page personnel|adecco|randstad|\breed\b|hackajob|"
    r"efinancialcareers|jobs|careers|agency|people first|teksystems|sanderson|morgan mckinley|"
    r"hunter bond|client server|venturi|nigel frank|computer futures|walters people|manpower|"
    r"spencer ogden|badenoch|kelly services|hudson|randstad|robert walters|\bnfp\b|executive search|"
    r"oliver james|selby jennings|spectrum it|harvey nash|jefferson frank|pontoon|xpertise|lorien|"
    r"sthree|jonathan lee|cathcart|ashdown|rise technical|understanding recruitment|hunter bond|"
    r"nicholas associates|glocomms|la fosse|aquent|experis|modis|capita resourcing",
    re.I,
)
_LEGAL_WORDS = {
    "ltd", "limited", "plc", "llp", "llc", "inc", "uk", "group", "holdings", "the", "and",
    "company", "co", "services", "international", "gb", "europe", "emea",
}
_AGENCY_PLACE_TYPES = {"employment_agency", "staffing_agency", "job_board"}
_NOT_A_COMPANY_SITE = (
    "linkedin.com", "indeed.com", "reed.co.uk", "facebook.com", "twitter.com", "glassdoor",
    "totaljobs.com", "cv-library.co.uk", "adzuna", "google.com", "wikipedia.org", "gov.uk",
)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def is_relevant_title(title: str) -> bool:
    """Analyst-type roles a FinTech & Data Analytics graduate would plausibly want."""
    title = title or ""
    return bool(
        _ANALYST.search(title) and _FIT.search(title) and not _NOT_OUR_ROLE.search(title)
    )


def is_agency(company: str) -> bool:
    """Recruitment agencies, job boards and staffing firms are not target employers."""
    return bool(_AGENCY.search(company or ""))


def name_tokens(name: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", (name or "").lower()) if t not in _LEGAL_WORDS}


def names_match(a: str, b: str) -> bool:
    """True when two company names plausibly refer to the same business."""
    ta, tb = name_tokens(a), name_tokens(b)
    if not ta or not tb:
        return False
    shared = ta & tb
    return len(shared) / min(len(ta), len(tb)) >= 0.6 and len(shared) / max(len(ta), len(tb)) >= 0.4


def role_score(title: str) -> int:
    """Higher = better fit for an early-career candidate (used to pick one role per employer)."""
    score = 0
    if _EARLY_CAREER.search(title):
        score += 2
    if _SENIOR.search(title):
        score -= 2
    return score


def clean_company(name: str) -> str:
    return " ".join((name or "").replace(" ,", ",").split())


# ---------------------------------------------------------------------------
# Adzuna + website lookup
# ---------------------------------------------------------------------------

def _fetch_page(app_id: str, app_key: str, search: dict, page: int) -> list[dict]:
    params = {
        "app_id": app_id, "app_key": app_key, "results_per_page": 50,
        "max_days_old": 30, "sort_by": "date", "content-type": "application/json", **search,
    }
    try:
        resp = requests.get(_URL.format(page=page), params=params, timeout=_TIMEOUT)
    except requests.RequestException as exc:
        logger.warning("[Jobs] Adzuna request failed: %s", exc)
        return []
    if resp.status_code != 200:
        logger.warning("[Jobs] Adzuna HTTP %s", resp.status_code)
        return []
    try:
        return resp.json().get("results", []) or []
    except ValueError:
        return []


def find_website(client, company: str, location: str = "") -> tuple[str, str]:
    """(matched business name, website) via Google Maps, or ('', '') when no confident match."""
    try:
        results = client.places(query=f"{company} {location}".strip()).get("results", [])[:3]
    except Exception as exc:
        logger.warning("[Jobs] Maps search failed for %s: %s", company, exc)
        return "", ""
    for place in results:
        if not names_match(company, place.get("name", "")):
            continue
        if _AGENCY_PLACE_TYPES.intersection(place.get("types") or []):
            return "", ""      # Google itself files this business as an employment agency
        try:
            details = client.place(place["place_id"], fields=["name", "website"]).get("result", {})
        except Exception as exc:
            logger.warning("[Jobs] Maps details failed for %s: %s", company, exc)
            return "", ""
        website = details.get("website") or ""
        domain = domain_of(website)
        if domain and not any(bad in domain for bad in _NOT_A_COMPANY_SITE):
            return details.get("name") or place.get("name", ""), website
        return "", ""
    return "", ""


# ---------------------------------------------------------------------------
# Rotation state (one file per database)
# ---------------------------------------------------------------------------

def _state_path(db_path: str) -> str:
    return os.path.splitext(os.path.abspath(db_path))[0] + "_job_state.json"


def _load_state(db_path: str) -> dict:
    try:
        with open(_state_path(db_path), encoding="utf-8") as fh:
            state = json.load(fh)
            return {"search": int(state.get("search", 0)), "pages": dict(state.get("pages", {}))}
    except (OSError, ValueError):
        return {"search": 0, "pages": {}}


def _save_state(db_path: str, state: dict) -> None:
    try:
        with open(_state_path(db_path), "w", encoding="utf-8") as fh:
            json.dump(state, fh)
    except OSError as exc:
        logger.warning("[Jobs] could not save state: %s", exc)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def discover_job_leads(
    target: int,
    client_id: int = 1,
    db_path: str | None = None,
    max_searches: int = 4,
) -> list[dict]:
    """
    Insert up to `target` NEW companies that are advertising a relevant analyst role
    and return them (status 'qualified', `hiring_signal` set). [] when Adzuna or Google
    Maps credentials are missing.
    """
    db_path = db_path or database.DB_PATH
    app_id, app_key = get_adzuna_credentials()
    maps = get_googlemaps_client()
    if not (app_id and app_key and maps):
        return []

    known = database.get_all_prospects(client_id=client_id, db_path=db_path)
    known_names = {name_key(p.get("company") or "") for p in known}
    known_domains = {domain_of(p.get("website") or "") for p in known} - {""}

    state = _load_state(db_path)
    found: list[dict] = []
    searches_done = 0

    while len(found) < target and searches_done < max_searches:
        index = state["search"] % len(SEARCHES)
        search = SEARCHES[index]
        start_page = int(state["pages"].get(str(index), 1))
        state["search"] = index + 1
        searches_done += 1

        employers: dict[str, dict] = {}
        pages_read = 0
        for page in range(start_page, start_page + _PAGES_PER_SEARCH):
            jobs = _fetch_page(app_id, app_key, search, page)
            pages_read += 1
            for job in jobs:
                title = job.get("title", "")
                company = clean_company((job.get("company") or {}).get("display_name", ""))
                if not company or is_agency(company) or not is_relevant_title(title):
                    continue
                if name_key(company) in known_names:
                    continue
                current = employers.get(name_key(company))
                if current is None or role_score(title) > role_score(current["title"]):
                    employers[name_key(company)] = {
                        "company": company,
                        "title": title,
                        "location": (job.get("location") or {}).get("display_name", ""),
                        "url": job.get("redirect_url", ""),
                    }
            if len(jobs) < 50:
                break
        next_page = start_page + pages_read
        state["pages"][str(index)] = next_page if next_page <= _MAX_PAGE else 1

        for key, info in employers.items():
            if len(found) >= target:
                break
            matched_name, website = find_website(maps, info["company"], info["location"])
            domain = domain_of(website)
            if not website or domain in known_domains:
                known_names.add(key)     # do not pay to look this employer up again this run
                continue
            prospect_id = database.add_prospect(
                name="Owner/Manager",
                company=matched_name or info["company"],
                website=website,
                notes=f"Advertised role: {info['title']} ({info['location']}). {info['url']}",
                status="qualified",
                lead_score=70,
                client_id=client_id,
                db_path=db_path,
            )
            database.update_enrichment_fields(
                prospect_id,
                {"hiring_signal": f"Advertising: {info['title']}"},
                db_path=db_path,
            )
            known_names.add(key)
            known_domains.add(domain)
            prospect = database.get_prospect_by_id(prospect_id, db_path=db_path)
            if prospect:
                found.append(dict(prospect))

    _save_state(db_path, state)
    logger.info("[Jobs] %d new companies with live analyst roles", len(found))
    return found


def name_key(name: str) -> str:
    """Stable lowercase key for an employer name."""
    return " ".join(sorted(name_tokens(name))) or (name or "").strip().lower()
