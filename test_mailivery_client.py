"""
test_mailivery_client.py
========================
Unit tests for mailivery_client.py.
All HTTP calls are mocked via unittest.mock so no real network traffic occurs.
"""

import unittest
from unittest.mock import MagicMock, patch
import json


def _mock_response(status_code: int, body: dict | list | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = json.dumps(body or {})
    if status_code >= 400:
        from requests import HTTPError
        resp.raise_for_status.side_effect = HTTPError(response=resp)
    else:
        resp.raise_for_status.return_value = None
    resp.json.return_value = body or {}
    return resp


class TestMailiveryClientRequest(unittest.TestCase):
    def setUp(self):
        import mailivery_client
        self.mc = mailivery_client.MailiveryClient("test-key")

    def _patch(self, status_code, body=None):
        return patch.object(
            self.mc._session, "request",
            return_value=_mock_response(status_code, body),
        )

    def test_successful_get_returns_ok(self):
        with self._patch(200, {"id": "abc", "status": "active"}) as m:
            result = self.mc.get_mailbox("abc")
        self.assertTrue(result.get("ok"))
        self.assertEqual(result["id"], "abc")

    def test_http_error_returns_ok_false(self):
        with self._patch(404, {"message": "not found"}):
            result = self.mc.get_mailbox("missing")
        self.assertFalse(result.get("ok"))
        self.assertIn("404", result["error"])

    def test_429_retries_once(self):
        ok_resp  = _mock_response(200, {"id": "x"})
        r429     = _mock_response(429)
        r429.raise_for_status.side_effect = None  # 429 is handled before raise_for_status
        with patch.object(self.mc._session, "request", side_effect=[r429, ok_resp]) as m:
            with patch("time.sleep"):
                result = self.mc.get_mailbox("x")
        self.assertEqual(m.call_count, 2)
        self.assertTrue(result.get("ok"))

    def test_429_no_retry_on_second_call(self):
        r429 = _mock_response(429)
        r429.raise_for_status.side_effect = None
        # Both calls return 429; second has retry=False so raise_for_status fires
        r429b = _mock_response(429)
        with patch.object(self.mc._session, "request", side_effect=[r429, r429b]):
            with patch("time.sleep"):
                result = self.mc.get_mailbox("x")
        self.assertFalse(result.get("ok"))

    def test_network_error_returns_ok_false(self):
        with patch.object(self.mc._session, "request", side_effect=Exception("timeout")):
            result = self.mc.get_mailbox("x")
        self.assertFalse(result.get("ok"))
        self.assertIn("timeout", result["error"])

    def test_non_dict_response_wrapped(self):
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status.return_value = None
        resp.json.return_value = [{"id": "1"}, {"id": "2"}]
        with patch.object(self.mc._session, "request", return_value=resp):
            result = self.mc._request("GET", "/campaigns")
        self.assertTrue(result.get("ok"))
        self.assertIsInstance(result["data"], list)


class TestMailiveryClientMethods(unittest.TestCase):
    def setUp(self):
        import mailivery_client
        self.mc = mailivery_client.MailiveryClient("test-key")

    def _patch(self, body=None, status=200):
        return patch.object(
            self.mc._session, "request",
            return_value=_mock_response(status, body or {}),
        )

    def test_connect_smtp_mailbox_posts_to_correct_path(self):
        with patch.object(self.mc._session, "request",
                          return_value=_mock_response(200, {"id": "cmp1"})) as m:
            result = self.mc.connect_smtp_mailbox(
                "Alice", "Smith", "alice@example.com", "owner@example.com",
                "smtp.example.com", 587, "alice", "pass",
                "imap.example.com", 993, "alice", "pass",
            )
        self.assertTrue(result.get("ok"))
        call_args = m.call_args
        self.assertIn("/campaigns/smtp", call_args[0][1])

    def test_connect_google_mailbox(self):
        with patch.object(self.mc._session, "request",
                          return_value=_mock_response(200, {"id": "gmp1"})) as m:
            result = self.mc.connect_google_mailbox(
                "Bob", "Jones", "bob@gmail.com", "owner@example.com", "refresh-tok"
            )
        self.assertTrue(result.get("ok"))
        self.assertIn("/campaigns/gmail", m.call_args[0][1])

    def test_list_mailboxes_returns_list(self):
        data = [{"id": "1"}, {"id": "2"}]
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status.return_value = None
        resp.json.return_value = data
        with patch.object(self.mc._session, "request", return_value=resp):
            result = self.mc.list_mailboxes()
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2)

    def test_list_mailboxes_returns_empty_on_error(self):
        with self._patch(status=500):
            result = self.mc.list_mailboxes()
        self.assertEqual(result, [])

    def test_get_mailbox_by_email_found(self):
        with self._patch({"id": "abc", "email": "x@x.com"}):
            result = self.mc.get_mailbox_by_email("x@x.com")
        self.assertIsNotNone(result)
        self.assertTrue(result.get("ok"))

    def test_get_mailbox_by_email_not_found(self):
        with self._patch(status=404):
            result = self.mc.get_mailbox_by_email("missing@x.com")
        self.assertIsNone(result)

    def test_start_warmup(self):
        with patch.object(self.mc._session, "request",
                          return_value=_mock_response(200, {"status": "active"})) as m:
            result = self.mc.start_warmup("cmp1")
        self.assertTrue(result.get("ok"))
        self.assertIn("/cmp1/start", m.call_args[0][1])

    def test_pause_warmup(self):
        with patch.object(self.mc._session, "request",
                          return_value=_mock_response(200, {"status": "paused"})) as m:
            result = self.mc.pause_warmup("cmp1")
        self.assertIn("/cmp1/pause", m.call_args[0][1])

    def test_resume_warmup(self):
        with patch.object(self.mc._session, "request",
                          return_value=_mock_response(200, {"status": "active"})) as m:
            result = self.mc.resume_warmup("cmp1")
        self.assertIn("/cmp1/resume", m.call_args[0][1])

    def test_get_health_score(self):
        mock_data = {"data": {"status_code": "active", "spam_rate_in_last_14_days": 0}, "ok": True}
        with self._patch(mock_data):
            result = self.mc.get_health_score("cmp1")
        self.assertIn("health_score", result)
        self.assertTrue(result["ok"])

    def test_update_emails_per_day(self):
        with patch.object(self.mc._session, "request",
                          return_value=_mock_response(200, {})) as m:
            self.mc.update_emails_per_day("cmp1", 40)
        call_kwargs = m.call_args[1]
        self.assertEqual(call_kwargs["json"]["emails_per_day"], 40)

    def test_update_response_rate(self):
        with patch.object(self.mc._session, "request",
                          return_value=_mock_response(200, {})) as m:
            self.mc.update_response_rate("cmp1", 35)
        self.assertEqual(m.call_args[1]["json"]["response_rate"], 35)


class TestGetClientFactory(unittest.TestCase):
    def test_disabled_returns_none(self):
        import mailivery_client
        with patch("settings.get_mailivery_enabled", return_value=False):
            result = mailivery_client.get_client()
        self.assertIsNone(result)

    def test_enabled_no_key_returns_none(self):
        import mailivery_client
        with patch("settings.get_mailivery_enabled", return_value=True), \
             patch("settings.get_mailivery_api_key", return_value=""):
            result = mailivery_client.get_client()
        self.assertIsNone(result)

    def test_enabled_with_key_returns_client(self):
        import mailivery_client
        with patch("settings.get_mailivery_enabled", return_value=True), \
             patch("settings.get_mailivery_api_key", return_value="real-key"):
            result = mailivery_client.get_client()
        self.assertIsNotNone(result)
        self.assertIsInstance(result, mailivery_client.MailiveryClient)


if __name__ == "__main__":
    unittest.main()
