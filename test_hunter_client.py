"""Tests for hunter_client: selection, fallbacks and failure handling (HTTP mocked)."""

import unittest
from unittest.mock import MagicMock, patch

import hunter_client as hc


def _entry(email, first, last, position, dept, conf=90, status="valid"):
    return {
        "value": email, "first_name": first, "last_name": last, "position": position,
        "department": dept, "confidence": conf, "verification": {"status": status},
    }


def _resp(emails, status=200):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = {"data": {"emails": emails}}
    return r


class TestDomain(unittest.TestCase):
    def test_domain_from_url(self):
        self.assertEqual(hc.domain_from_url("https://www.Acme.com/about"), "acme.com")
        self.assertEqual(hc.domain_from_url("acme.co.uk"), "acme.co.uk")
        self.assertEqual(hc.domain_from_url(""), "")


class TestFindHiringContact(unittest.TestCase):
    def test_no_key_means_no_call(self):
        with patch.object(hc, "get_hunter_api_key", return_value=""), \
             patch.object(hc.requests, "get") as get:
            self.assertEqual(hc.find_hiring_contact("acme.com"), {})
            get.assert_not_called()

    def test_prefers_recruiter_in_hr(self):
        emails = [
            _entry("hr.assistant@acme.com", "Ann", "Lee", "HR Assistant", "hr", 95),
            _entry("tom@acme.com", "Tom", "Ray", "Talent Acquisition Manager", "hr", 85),
        ]
        with patch.object(hc, "get_hunter_api_key", return_value="k"), \
             patch.object(hc.requests, "get", return_value=_resp(emails)):
            best = hc.find_hiring_contact("https://acme.com")
        self.assertEqual(best["email"], "tom@acme.com")
        self.assertEqual(best["name"], "Tom Ray")
        self.assertEqual(best["first_name"], "Tom")
        self.assertEqual(best["source"], "hunter")

    def test_falls_back_to_executives_when_no_hr(self):
        exec_entry = _entry("ceo@acme.com", "Sam", "Doe", "CEO", "executive", 88)
        with patch.object(hc, "get_hunter_api_key", return_value="k"), \
             patch.object(hc.requests, "get", side_effect=[_resp([]), _resp([exec_entry])]) as get:
            best = hc.find_hiring_contact("acme.com")
        self.assertEqual(best["email"], "ceo@acme.com")
        self.assertEqual(get.call_count, 2)

    def test_low_confidence_and_invalid_are_ignored(self):
        emails = [
            _entry("low@acme.com", "A", "B", "Recruiter", "hr", conf=40),
            _entry("bad@acme.com", "C", "D", "Recruiter", "hr", conf=95, status="invalid"),
        ]
        with patch.object(hc, "get_hunter_api_key", return_value="k"), \
             patch.object(hc.requests, "get", return_value=_resp(emails)):
            self.assertEqual(hc.find_hiring_contact("acme.com"), {})

    def test_http_errors_return_empty(self):
        for status in (401, 429, 500):
            with patch.object(hc, "get_hunter_api_key", return_value="k"), \
                 patch.object(hc.requests, "get", return_value=_resp([], status=status)):
                self.assertEqual(hc.find_hiring_contact("acme.com"), {})

    def test_network_error_returns_empty(self):
        with patch.object(hc, "get_hunter_api_key", return_value="k"), \
             patch.object(hc.requests, "get", side_effect=hc.requests.ConnectionError("boom")):
            self.assertEqual(hc.find_hiring_contact("acme.com"), {})


if __name__ == "__main__":
    unittest.main()
