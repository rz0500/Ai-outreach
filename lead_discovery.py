"""
lead_discovery.py - Daily company discovery for hands-free outreach.

Rotates through analyst-friendly company searches (fintech, data, SaaS,
consultancies...) across UK and nearby English-speaking cities, reads up to
a few pages of Google Maps results per search, and returns ONLY companies
that are new to the database (by name and by website domain), so nothing is
researched or emailed twice. The rotation position is stored next to the
database so each day picks up where the last one stopped.
"""

from __future__ import annotations

import json
import logging
import os
import time
from urllib.parse import urlparse

import database
from google_maps_finder import get_googlemaps_client

logger = logging.getLogger(__name__)

QUERIES = [
    "fintech company",
    "data analytics company",
    "software company",
    "SaaS startup",
    "business intelligence consultancy",
    "data consultancy",
    "financial technology startup",
    "management consultancy",
    "e-commerce company",
    "digital product company",
    "insurance technology company",
    "market research company",
]

CITIES = [
    "London, UK", "Manchester, UK", "Birmingham, UK", "Leeds, UK", "Bristol, UK",
    "Edinburgh, UK", "Glasgow, UK", "Cambridge, UK", "Reading, UK",
    "Newcastle upon Tyne, UK", "Liverpool, UK", "Nottingham, UK", "Sheffield, UK",
    "Cardiff, UK", "Belfast, UK", "Dublin, Ireland", "Amsterdam, Netherlands",
]

_SKIP_TYPES = {
    "school", "primary_school", "secondary_school", "university", "church",
    "place_of_worship", "restaurant", "cafe", "bar", "lodging", "gym", "hair_care",
    "beauty_salon", "doctor", "dentist", "hospital", "pharmacy", "lawyer",
    "local_government_office", "city_hall", "courthouse", "police",
}
_SKIP_NAME_WORDS = ("university", "college", "school", "council", "nhs ", "academy")


def combos() -> list[tuple[str, str]]:
    """Every (query, city) pair, biggest job markets first."""
    return [(q, c) for c in CITIES for q in QUERIES]


def _state_path(db_path: str) -> str:
    """One rotation file per database, so a test or copy can never move the live rotation."""
    return os.path.splitext(os.path.abspath(db_path))[0] + "_discovery_state.json"


def _load_index(db_path: str) -> int:
    try:
        with open(_state_path(db_path), encoding="utf-8") as fh:
            return int(json.load(fh).get("index", 0))
    except (OSError, ValueError):
        return 0


def _save_index(index: int, db_path: str) -> None:
    try:
        with open(_state_path(db_path), "w", encoding="utf-8") as fh:
            json.dump({"index": index}, fh)
    except OSError as exc:
        logger.warning("[Discovery] could not save rotation state: %s", exc)


def domain_of(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    host = (urlparse(raw if "://" in raw else "https://" + raw).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _irrelevant(place: dict) -> bool:
    if place.get("business_status") == "CLOSED_PERMANENTLY":
        return True
    if _SKIP_TYPES.intersection(place.get("types") or []):
        return True
    name = (place.get("name") or "").lower() + " "
    return any(word in name for word in _SKIP_NAME_WORDS)


def _next_page(client, token: str):
    """
    Next results page, or None. A fresh next-page token is rejected with
    INVALID_REQUEST until Google has it ready (a few seconds), so wait and retry.
    """
    for attempt in range(4):
        time.sleep(2.0 + 1.5 * attempt)
        try:
            return client.places(page_token=token)
        except Exception as exc:
            if "INVALID_REQUEST" not in str(exc):
                logger.warning("[Discovery] next page failed: %s", exc)
                return None
    logger.warning("[Discovery] next page token never became valid; using the pages we have")
    return None


def _search_pages(client, query: str, pages: int):
    """Yield places from up to `pages` result pages (Maps allows 20 per page)."""
    res = client.places(query=query)
    yield from res.get("results", [])
    token = res.get("next_page_token")
    for _ in range(max(0, pages - 1)):
        if not token:
            break
        res = _next_page(client, token)
        if res is None:
            break  # keep everything from the earlier pages
        yield from res.get("results", [])
        token = res.get("next_page_token")


def discover_new_leads(
    target: int,
    client_id: int = 1,
    pages: int = 3,
    max_searches: int = 6,
    db_path: str | None = None,
) -> list[dict]:
    """
    Find up to `target` companies not yet in the database. Each returned dict is
    a freshly-inserted prospect row (status 'qualified'). Returns [] when the
    Maps key is missing.
    """
    db_path = db_path or database.DB_PATH
    client = get_googlemaps_client()
    if not client:
        logger.error("[Discovery] GOOGLE_MAPS_API_KEY is missing.")
        return []

    known = database.get_all_prospects(client_id=client_id, db_path=db_path)
    known_names = {(p.get("company") or "").strip().lower() for p in known}
    known_domains = {domain_of(p.get("website") or "") for p in known} - {""}

    pairs = combos()
    index = _load_index(db_path)
    found: list[dict] = []
    searches = 0

    while len(found) < target and searches < max_searches:
        query, city = pairs[index % len(pairs)]
        index += 1
        searches += 1
        logger.info("[Discovery] searching '%s in %s'", query, city)
        try:
            places = list(_search_pages(client, f"{query} in {city}", pages))
        except Exception as exc:
            logger.error("[Discovery] search failed: %s", exc)
            continue

        for place in places:
            if len(found) >= target:
                break
            name = (place.get("name") or "").strip()
            if not name or name.lower() in known_names or _irrelevant(place):
                continue
            try:
                details = client.place(
                    place["place_id"],
                    fields=["name", "formatted_address", "formatted_phone_number", "website"],
                ).get("result", {})
            except Exception as exc:
                logger.error("[Discovery] details failed for %s: %s", name, exc)
                continue

            website = details.get("website") or ""
            domain = domain_of(website)
            if not domain or domain in known_domains:
                continue

            prospect_id = database.add_prospect(
                name="Owner/Manager",
                company=details.get("name") or name,
                phone=details.get("formatted_phone_number") or "",
                website=website,
                notes=f"Address: {details.get('formatted_address') or place.get('formatted_address') or ''}",
                status="qualified",
                lead_score=55,
                client_id=client_id,
                db_path=db_path,
            )
            known_names.add(name.lower())
            known_domains.add(domain)
            prospect = database.get_prospect_by_id(prospect_id, db_path=db_path)
            if prospect:
                found.append(dict(prospect))

    _save_index(index % len(pairs), db_path)
    logger.info("[Discovery] %d new leads from %d searches", len(found), searches)
    return found
