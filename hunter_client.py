"""
hunter_client.py - Find a named recruiter / hiring contact via Hunter.io.

Hunter's Domain Search returns real people at a company with their job
title, department and a verification status. We ask for HR/recruiting
people first, then executives and managers (who usually do the hiring at
small firms), and return the single best match.

Costs Hunter credits (free plan: 50/month), so it only runs when
HUNTER_API_KEY is set and never raises - on any failure the caller falls
back to emails published on the company's own website.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

import requests

from settings import get_hunter_api_key

logger = logging.getLogger(__name__)

_ENDPOINT = "https://api.hunter.io/v2/domain-search"
_TIMEOUT = 15
_DEPARTMENTS = ("hr", "executive", "management")
_MIN_CONFIDENCE = 70
_HIRING_WORDS = ("recruit", "talent", "hiring", "acquisition", "people")
_HR_WORDS = ("human resources", "hr")
_JUNIOR_WORDS = ("assistant", "intern", "administrator", "receptionist")


def domain_from_url(url: str) -> str:
    """Bare domain from a URL or hostname ('https://www.acme.com/x' -> 'acme.com')."""
    raw = (url or "").strip()
    if not raw:
        return ""
    host = urlparse(raw if "://" in raw else "https://" + raw).hostname or ""
    host = host.lower()
    return host[4:] if host.startswith("www.") else host


def _search(domain: str, department: str, api_key: str) -> list[dict]:
    params = {
        "domain": domain,
        "department": department,
        "type": "personal",
        "required_field": "full_name",
        "limit": 10,
        "api_key": api_key,
    }
    try:
        resp = requests.get(_ENDPOINT, params=params, timeout=_TIMEOUT)
    except requests.RequestException as exc:
        logger.warning("[Hunter] request failed for %s: %s", domain, exc)
        return []
    if resp.status_code != 200:
        logger.warning("[Hunter] HTTP %s for %s", resp.status_code, domain)
        return []
    try:
        return (resp.json().get("data") or {}).get("emails") or []
    except ValueError:
        return []


def _usable(entry: dict) -> bool:
    status = ((entry.get("verification") or {}).get("status") or "").lower()
    return (
        bool(entry.get("value"))
        and (entry.get("confidence") or 0) >= _MIN_CONFIDENCE
        and status != "invalid"
    )


def _score(entry: dict) -> float:
    position = (entry.get("position") or "").lower()
    score = float(entry.get("confidence") or 0) / 100
    words = set(position.replace("-", " ").replace("/", " ").split())
    if any(word in position for word in _HIRING_WORDS):
        score += 3
    elif any(word in position for word in _HR_WORDS if " " in word) or "hr" in words:
        score += 1.5
    if any(word in words for word in _JUNIOR_WORDS):
        score -= 2
    if (entry.get("department") or "").lower() == "hr":
        score += 2
    if ((entry.get("verification") or {}).get("status") or "").lower() == "valid":
        score += 1
    return score


def find_hiring_contact(url_or_domain: str) -> dict:
    """
    Best named hiring contact for a company, or {} when none is found, no key
    is configured, or Hunter is unavailable.

    Returns {'email', 'name', 'first_name', 'position', 'department',
             'confidence', 'source'}.
    """
    api_key = get_hunter_api_key()
    domain = domain_from_url(url_or_domain)
    if not api_key or not domain:
        return {}

    for department in _DEPARTMENTS:
        candidates = [e for e in _search(domain, department, api_key) if _usable(e)]
        if not candidates:
            continue
        best = max(candidates, key=_score)
        first = (best.get("first_name") or "").strip()
        last = (best.get("last_name") or "").strip()
        return {
            "email": best["value"].strip().lower(),
            "name": f"{first} {last}".strip(),
            "first_name": first,
            "position": (best.get("position") or "").strip(),
            "department": (best.get("department") or department).strip(),
            "confidence": best.get("confidence") or 0,
            "source": "hunter",
        }
    return {}
