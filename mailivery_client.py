"""
mailivery_client.py
===================
Thin client for the Mailivery warmup API (https://app.mailivery.io/api/v1).

All Mailivery HTTP calls go through this module.  The rest of the codebase
imports MailiveryClient and calls methods on it — no direct requests calls
elsewhere.

Behaviour contract:
  - All methods return a dict.  On success the dict contains at least {"ok": True}.
  - On failure the dict contains {"ok": False, "error": "<message>"} and the
    exception is printed but NOT re-raised — callers should check "ok".
  - A single automatic retry is made on HTTP 429 (rate-limited), after a 1-second
    pause.
"""

from __future__ import annotations

import time
import uuid
import logging

import requests

logger = logging.getLogger(__name__)

_BASE_URL = "https://app.mailivery.io/api/v1"
_TIMEOUT  = 20  # seconds per request


class MailiveryClient:
    """Mailivery REST API client."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        })

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        data: dict | None = None,
        files: dict | None = None,
        retry: bool = True,
    ) -> dict:
        url = f"{_BASE_URL}{path}"
        headers = {"X-Request-ID": str(uuid.uuid4())}
        try:
            resp = self._session.request(
                method, url, json=json, data=data, files=files, headers=headers, timeout=_TIMEOUT
            )
            if resp.status_code == 429 and retry:
                logger.warning("[Mailivery] rate-limited, retrying in 1 s")
                time.sleep(1)
                return self._request(method, path, json=json, data=data, files=files, retry=False)
            resp.raise_for_status()
            try:
                body = resp.json()
            except Exception:
                body = {}
            if isinstance(body, dict):
                body.setdefault("ok", True)
                return body
            return {"ok": True, "data": body}
        except requests.HTTPError as exc:
            msg = f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"
            logger.error("[Mailivery] %s %s → %s", method.upper(), path, msg)
            return {"ok": False, "error": msg}
        except Exception as exc:
            logger.error("[Mailivery] %s %s → %s", method.upper(), path, exc)
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Mailbox management
    # ------------------------------------------------------------------

    def connect_smtp_mailbox(
        self,
        first_name: str,
        last_name: str,
        email: str,
        owner_email: str,
        smtp_host: str,
        smtp_port: int,
        smtp_username: str,
        smtp_password: str,
        imap_host: str,
        imap_port: int,
        imap_username: str,
        imap_password: str,
        emails_per_day: int = 30,
        response_rate: int = 30,
        ramp_up: bool = True,
    ) -> dict:
        """Connect a new mailbox via SMTP/IMAP credentials. Returns campaign data."""
        data = {
            "first_name":     first_name,
            "last_name":      last_name,
            "email":          email,
            "owner_email":    owner_email,
            "smtp_host":      smtp_host,
            "smtp_port":      str(smtp_port),
            "smtp_username":  smtp_username,
            "smtp_password":  smtp_password,
            "imap_host":      imap_host,
            "imap_port":      str(imap_port),
            "imap_username":  imap_username,
            "imap_password":  imap_password,
            "email_per_day":  str(emails_per_day),
            "response_rate":  str(response_rate),
            "ramp_up":        "true" if ramp_up else "false",
        }
        return self._request("POST", "/campaigns/smtp", data=data)

    def connect_google_mailbox(
        self,
        first_name: str,
        last_name: str,
        email: str,
        owner_email: str,
        refresh_token: str,
        emails_per_day: int = 30,
        response_rate: int = 30,
        ramp_up: bool = True,
    ) -> dict:
        """Connect a Gmail mailbox via OAuth refresh token."""
        data = {
            "first_name":    first_name,
            "last_name":     last_name,
            "email":         email,
            "owner_email":   owner_email,
            "refresh_token": refresh_token,
            "email_per_day": str(emails_per_day),
            "response_rate": str(response_rate),
            "ramp_up":       "true" if ramp_up else "false",
        }
        return self._request("POST", "/campaigns/gmail", data=data)

    def list_mailboxes(self) -> list[dict]:
        """List all campaigns under the account."""
        result = self._request("GET", "/campaigns")
        if not result.get("ok"):
            return []
        data = result.get("data", result)
        if isinstance(data, list):
            return data
        return []

    def get_mailbox(self, campaign_id: str) -> dict:
        """Fetch a single campaign by ID."""
        return self._request("GET", f"/campaigns/{campaign_id}")

    def get_mailbox_by_email(self, email: str) -> dict | None:
        """
        Fetch campaign by email address.
        Returns None if not found (404) or on error.
        """
        result = self._request("GET", f"/campaigns/email/{email}")
        if not result.get("ok"):
            return None
        return result

    def delete_campaign(self, campaign_id: str) -> dict:
        """Delete a campaign."""
        return self._request("DELETE", f"/campaigns/{campaign_id}")

    # ------------------------------------------------------------------
    # Warmup control
    # ------------------------------------------------------------------

    def start_warmup(self, campaign_id: str) -> dict:
        """Start warmup for a campaign."""
        return self._request("PATCH", f"/campaigns/{campaign_id}/start")

    def pause_warmup(self, campaign_id: str) -> dict:
        """Pause warmup for a campaign."""
        return self._request("PATCH", f"/campaigns/{campaign_id}/pause")

    def resume_warmup(self, campaign_id: str) -> dict:
        """Resume a paused warmup campaign."""
        return self._request("PATCH", f"/campaigns/{campaign_id}/resume")

    def enable_ramp_up(self, campaign_id: str) -> dict:
        """Enable the automatic daily ramp-up for a campaign."""
        return self._request("PATCH", f"/campaigns/{campaign_id}/ramp-up/enable")

    def update_emails_per_day(self, campaign_id: str, count: int) -> dict:
        """Update the number of warmup emails sent per day."""
        return self._request(
            "PATCH", f"/campaigns/{campaign_id}/emails-per-day",
            json={"emails_per_day": count},
        )

    def update_response_rate(self, campaign_id: str, rate: int) -> dict:
        """Update the reply rate target (percentage, 0-100)."""
        return self._request(
            "PATCH", f"/campaigns/{campaign_id}/response-rate",
            json={"response_rate": rate},
        )

    # ------------------------------------------------------------------
    # Analytics
    # ------------------------------------------------------------------

    def get_metrics(self, campaign_id: str) -> dict:
        """Fetch warmup metrics — derived from the campaign GET endpoint."""
        r = self._request("GET", f"/campaigns/{campaign_id}")
        if not r.get("ok"):
            return r
        d = r.get("data", {})
        return {
            "ok": True,
            "emails_sent_today": d.get("emails_sent_today", 0),
            "outreach_today": d.get("outreach_today", 0),
            "response_today": d.get("response_today", 0),
            "remaining_for_today": d.get("remaining_for_today", 0),
            "sent_in_last_45_days": d.get("sent_in_last_45_days", 0),
            "spam_in_last_14_days": d.get("spam_in_last_14_days", 0),
            "spam_rate_in_last_14_days": d.get("spam_rate_in_last_14_days", -1),
        }

    def get_health_score(self, campaign_id: str) -> dict:
        """
        Derive a health score from campaign data.
        Returns dict with keys: health_score (int 0-100), status_code, spam_rate.
        """
        r = self._request("GET", f"/campaigns/{campaign_id}")
        if not r.get("ok"):
            return r
        d = r.get("data", {})
        status = d.get("status_code", "unknown")
        spam_rate = d.get("spam_rate_in_last_14_days", -1)
        if status == "active" and (spam_rate < 0 or spam_rate == 0):
            score = 85
        elif status == "active" and spam_rate <= 2:
            score = 70
        elif status == "active":
            score = max(20, 70 - int(spam_rate * 5))
        else:
            score = 30
        return {"ok": True, "health_score": score, "status_code": status, "spam_rate": spam_rate}

    def get_activity_log(self, campaign_id: str) -> dict:
        """Fetch recent activity — derived from the campaign GET endpoint."""
        return self.get_metrics(campaign_id)


# ---------------------------------------------------------------------------
# Module-level singleton helper
# ---------------------------------------------------------------------------

def get_client() -> MailiveryClient | None:
    """
    Return a MailiveryClient if MAILIVERY_ENABLED=true and MAILIVERY_API_KEY is set.
    Returns None otherwise — callers should guard: `if client := mailivery_client.get_client()`.
    """
    from settings import get_mailivery_api_key, get_mailivery_enabled
    if not get_mailivery_enabled():
        return None
    key = get_mailivery_api_key()
    if not key:
        return None
    return MailiveryClient(key)
