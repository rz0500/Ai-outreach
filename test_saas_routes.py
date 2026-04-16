"""
test_saas_routes.py
===================
Flask test-client coverage for the SaaS-layer routes added in Session 7:
  GET  /onboard
  POST /onboard
  GET  /onboard/confirm
  GET  /client/login
  POST /client/login
  GET  /client/verify
  GET  /client
  POST /client/logout
"""

import os
import datetime
import tempfile
import unittest

# Prevent any real outbound sends or API calls during tests
os.environ.setdefault("ANTHROPIC_API_KEY", "")
os.environ.setdefault("SMTP_HOST", "")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

import database
import web_app


def _make_test_db():
    """Create a fresh isolated SQLite database for a test."""
    db = tempfile.mktemp(suffix=".db")
    database.initialize_database(db)
    database.initialize_outreach_table(db)
    return db


class TestOnboardRoutes(unittest.TestCase):
    """Tests for GET/POST /onboard."""

    def setUp(self):
        self.db = _make_test_db()
        web_app.app.config["TESTING"] = True
        # Patch web_app's database calls to use our temp DB
        self._orig_db_path = database.DB_PATH
        database.DB_PATH = self.db
        self.client = web_app.app.test_client()

    def tearDown(self):
        database.DB_PATH = self._orig_db_path
        try:
            os.unlink(self.db)
        except OSError:
            pass

    def test_get_onboard_returns_200(self):
        resp = self.client.get("/onboard")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Antigravity", resp.data)

    def test_post_onboard_missing_name_returns_form_with_error(self):
        resp = self.client.post("/onboard", data={
            "name": "",
            "email": "owner@test.com",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"required", resp.data.lower())

    def test_post_onboard_missing_email_returns_form_with_error(self):
        resp = self.client.post("/onboard", data={
            "name": "Acme Corp",
            "email": "",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"required", resp.data.lower())

    def test_post_onboard_valid_creates_client_and_redirects(self):
        resp = self.client.post("/onboard", data={
            "name": "Test Business",
            "niche": "consulting",
            "icp": "SMEs",
            "website": "https://testbusiness.com",
            "calendar_link": "https://calendly.com/test/30min",
            "email": "owner@testbusiness.com",
        }, follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/onboard/confirm", resp.headers["Location"])

        # Client record was created
        client = database.get_client_by_email("owner@testbusiness.com", db_path=self.db)
        self.assertIsNotNone(client)
        self.assertEqual(client["name"], "Test Business")

    def test_post_onboard_duplicate_email_redirects_without_duplicate(self):
        # Create a client first
        database.add_client("Existing Co", "existing@test.com", db_path=self.db)

        resp = self.client.post("/onboard", data={
            "name": "Duplicate Co",
            "email": "existing@test.com",
        }, follow_redirects=False)
        self.assertEqual(resp.status_code, 302)

        # Still only one client with that email
        all_clients = database.get_all_clients(db_path=self.db)
        matching = [c for c in all_clients if c["email"] == "existing@test.com"]
        self.assertEqual(len(matching), 1)

    def test_get_onboard_confirm_returns_200(self):
        resp = self.client.get("/onboard/confirm")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"in", resp.data.lower())


class TestClientDashboardRoutes(unittest.TestCase):
    """Tests for /client/* magic-link auth and dashboard."""

    def setUp(self):
        self.db = _make_test_db()
        web_app.app.config["TESTING"] = True
        web_app.app.config["WTF_CSRF_ENABLED"] = False
        self._orig_db_path = database.DB_PATH
        database.DB_PATH = self.db
        self.client = web_app.app.test_client()

        # Create a test client workspace
        self.client_id = database.add_client(
            "Widget Co", "owner@widgets.com", db_path=self.db
        )

    def tearDown(self):
        database.DB_PATH = self._orig_db_path
        try:
            os.unlink(self.db)
        except OSError:
            pass

    def test_client_dashboard_without_session_redirects_to_login(self):
        resp = self.client.get("/client", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/client/login", resp.headers["Location"])

    def test_client_login_page_returns_200(self):
        resp = self.client.get("/client/login")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"login", resp.data.lower())

    def test_client_login_unknown_email_does_not_reveal_existence(self):
        # Should still return 200 and show "check your email" — no info leak
        resp = self.client.post("/client/login", data={
            "email": "nobody@unknown.com"
        })
        self.assertEqual(resp.status_code, 200)
        # No error message about the email not existing
        self.assertNotIn(b"not found", resp.data.lower())

    def test_client_verify_invalid_token_shows_error(self):
        resp = self.client.get("/client/verify?token=not-a-real-token")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"invalid", resp.data.lower())

    def test_client_verify_expired_token_shows_error(self):
        import uuid as _uuid
        token = str(_uuid.uuid4())
        # Create an already-expired session
        expired_at = (
            datetime.datetime.utcnow() - datetime.timedelta(hours=1)
        ).strftime("%Y-%m-%d %H:%M:%S")
        database.create_client_session(self.client_id, token, expired_at, db_path=self.db)

        resp = self.client.get(f"/client/verify?token={token}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"expired", resp.data.lower())

    def test_client_verify_used_token_shows_error(self):
        import uuid as _uuid
        token = str(_uuid.uuid4())
        expires = (
            datetime.datetime.utcnow() + datetime.timedelta(hours=24)
        ).strftime("%Y-%m-%d %H:%M:%S")
        database.create_client_session(self.client_id, token, expires, db_path=self.db)
        database.mark_session_used(token, db_path=self.db)

        resp = self.client.get(f"/client/verify?token={token}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"already been used", resp.data.lower())

    def test_client_verify_valid_token_sets_session_and_redirects(self):
        import uuid as _uuid
        token = str(_uuid.uuid4())
        expires = (
            datetime.datetime.utcnow() + datetime.timedelta(hours=24)
        ).strftime("%Y-%m-%d %H:%M:%S")
        database.create_client_session(self.client_id, token, expires, db_path=self.db)

        resp = self.client.get(f"/client/verify?token={token}", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/client", resp.headers["Location"])

        # Token is now marked used
        sess = database.get_client_session(token, db_path=self.db)
        self.assertEqual(sess["used"], 1)

    def test_client_dashboard_with_valid_session_returns_200(self):
        with self.client.session_transaction() as sess:
            sess["client_id"] = self.client_id

        resp = self.client.get("/client")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Widget Co", resp.data)

    def test_client_logout_clears_session_and_redirects(self):
        with self.client.session_transaction() as sess:
            sess["client_id"] = self.client_id

        resp = self.client.post("/client/logout", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)

        # Session cleared — dashboard now redirects to login
        resp2 = self.client.get("/client", follow_redirects=False)
        self.assertEqual(resp2.status_code, 302)
        self.assertIn("/client/login", resp2.headers["Location"])


if __name__ == "__main__":
    unittest.main()
