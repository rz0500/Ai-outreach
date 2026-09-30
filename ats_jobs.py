"""
ats_jobs.py - Real job openings from a company's public applicant-tracking board.

Most fintech / SaaS companies list their vacancies on Greenhouse, Lever, Ashby,
Workable or SmartRecruiters and embed or link that board from their careers page,
so the careers page's own HTML shows no roles. Each of those services publishes
the board as public JSON meant for exactly this kind of read-only use. We find the
board link on the company's pages and pull analyst / analytics / graduate titles,
which is the strongest reason to reach out to a company right now.
"""

from __future__ import annotations

import logging
import re

import requests

logger = logging.getLogger(__name__)

_TIMEOUT = 8
_MAX_BOARDS = 2

# Titles worth mentioning: analyst-type roles and graduate / early-careers programmes.
_TITLE_RE = re.compile(
    r"analyst|analytics|insights?\b|business intelligence|\bBI\b|data scien|data engineer|"
    r"graduate|early careers|junior data",
    re.IGNORECASE,
)

_BOARD_PATTERNS = (
    ("greenhouse", re.compile(
        r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?([a-z0-9_-]+)", re.I)),
    ("lever", re.compile(r"jobs(?:\.eu)?\.lever\.co/([a-z0-9_-]+)", re.I)),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([a-z0-9_.%-]+)", re.I)),
    ("workable", re.compile(r"apply\.workable\.com/([a-z0-9_-]+)", re.I)),
    ("smartrecruiters", re.compile(r"(?:jobs|careers)\.smartrecruiters\.com/([A-Za-z0-9_-]+)", re.I)),
)
_NOT_A_BOARD = {"embed", "api", "v1", "jobs", "js", "static", "assets", "widget", "job_board"}


def find_boards(html: str) -> list[tuple[str, str]]:
    """Unique (provider, board slug) pairs linked or embedded in a page's HTML."""
    found: list[tuple[str, str]] = []
    for provider, pattern in _BOARD_PATTERNS:
        for slug in pattern.findall(html or ""):
            slug = slug.strip().strip("/")
            if slug and slug.lower() not in _NOT_A_BOARD and (provider, slug) not in found:
                found.append((provider, slug))
    return found


def _get_json(url: str):
    try:
        resp = requests.get(url, timeout=_TIMEOUT, headers={"Accept": "application/json"})
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception as exc:
        logger.debug("[ATS] %s failed: %s", url, exc)
        return None


def board_titles(provider: str, slug: str) -> list[str]:
    """All open job titles on one board, or [] if the board cannot be read."""
    if provider == "greenhouse":
        data = _get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
        return [j.get("title", "") for j in (data or {}).get("jobs", [])] if isinstance(data, dict) else []
    if provider == "lever":
        data = _get_json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
        return [p.get("text", "") for p in data] if isinstance(data, list) else []
    if provider == "ashby":
        data = _get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
        return [j.get("title", "") for j in (data or {}).get("jobs", [])] if isinstance(data, dict) else []
    if provider == "workable":
        data = _get_json(f"https://apply.workable.com/api/v1/widget/accounts/{slug}")
        return [j.get("title", "") for j in (data or {}).get("jobs", [])] if isinstance(data, dict) else []
    if provider == "smartrecruiters":
        data = _get_json(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings")
        return [p.get("name", "") for p in (data or {}).get("content", [])] if isinstance(data, dict) else []
    return []


def analyst_jobs(html_pages: list[str], limit: int = 4) -> list[str]:
    """Analyst / analytics / graduate openings on any ATS board linked from these pages."""
    boards: list[tuple[str, str]] = []
    for html in html_pages:
        for board in find_boards(html):
            if board not in boards:
                boards.append(board)

    titles: list[str] = []
    for provider, slug in boards[:_MAX_BOARDS]:
        for title in board_titles(provider, slug):
            title = " ".join((title or "").split())
            if title and _TITLE_RE.search(title) and title.lower() not in {t.lower() for t in titles}:
                titles.append(title)
    return titles[:limit]
