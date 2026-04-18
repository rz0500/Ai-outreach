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

import base64

import database
import web_app

# Basic Auth header for /ops and /api/ops/* routes (default admin:admin in tests)
_OPS_AUTH = {"Authorization": "Basic " + base64.b64encode(b"admin:admin").decode()}


def _make_test_db():
    """Create a fresh isolated SQLite database for a test."""
    db = tempfile.mktemp(suffix=".db")
    database.initialize_database(db)
    database.initialize_outreach_table(db)
    return db


def _seed_reply_draft_for_test(
    *,
    prospect_id: int,
    client_id: int,
    db_path: str,
) -> int:
    return database.save_reply_draft(
        prospect_id=prospect_id,
        inbound_from="reply@example.com",
        inbound_body="Interested in learning more.",
        classification="interested",
        classification_reasoning="Positive buying signal",
        drafted_reply="Happy to chat next week.",
        inbound_message_id="<msg@example.com>",
        inbound_subject="Interested",
        client_id=client_id,
        db_path=db_path,
    )


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

    def test_get_landing_page_returns_200(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Antigravity", resp.data)

    def test_get_checkout_returns_200(self):
        resp = self.client.get("/checkout")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"antigravity", resp.data.lower())

    def test_get_operator_dashboard_route_returns_200(self):
        resp = self.client.get("/ops", headers=_OPS_AUTH)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Antigravity", resp.data)

    def test_ops_route_requires_basic_auth(self):
        resp = self.client.get("/ops")
        self.assertEqual(resp.status_code, 401)

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

    def test_client_prospects_without_session_redirects_to_login(self):
        resp = self.client.get("/client/prospects", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/client/login", resp.headers["Location"])

    def test_client_prospects_shows_only_workspace_leads(self):
        other_client_id = database.add_client("Other Co", "other@test.com", db_path=self.db)
        database.add_prospect(
            name="Widget Lead",
            company="Widget Co",
            email="lead@widget.com",
            client_id=self.client_id,
            db_path=self.db,
        )
        database.add_prospect(
            name="Other Lead",
            company="Other Co",
            email="lead@other.com",
            client_id=other_client_id,
            db_path=self.db,
        )

        with self.client.session_transaction() as sess:
            sess["client_id"] = self.client_id

        resp = self.client.get("/client/prospects")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Widget Lead", resp.data)
        self.assertNotIn(b"Other Lead", resp.data)

    def test_client_prospects_search_filter_works(self):
        database.add_prospect(
            name="Alpha Lead",
            company="Alpha Co",
            email="alpha@company.com",
            client_id=self.client_id,
            db_path=self.db,
        )
        database.add_prospect(
            name="Beta Lead",
            company="Beta Co",
            email="beta@company.com",
            client_id=self.client_id,
            db_path=self.db,
        )

        with self.client.session_transaction() as sess:
            sess["client_id"] = self.client_id

        resp = self.client.get("/client/prospects?q=alpha")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Alpha Lead", resp.data)
        self.assertNotIn(b"Beta Lead", resp.data)

    def test_client_prospects_status_filter_works(self):
        database.add_prospect(
            name="Booked Lead",
            company="Booked Co",
            email="booked@company.com",
            status="booked",
            client_id=self.client_id,
            db_path=self.db,
        )
        database.add_prospect(
            name="New Lead",
            company="New Co",
            email="new@company.com",
            status="new",
            client_id=self.client_id,
            db_path=self.db,
        )

        with self.client.session_transaction() as sess:
            sess["client_id"] = self.client_id

        resp = self.client.get("/client/prospects?status=booked")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Booked Lead", resp.data)
        self.assertNotIn(b"New Lead", resp.data)

    def test_client_prospects_pagination_works(self):
        for i in range(12):
            database.add_prospect(
                name=f"Lead {i}",
                company=f"Company {i}",
                email=f"lead{i}@company.com",
                client_id=self.client_id,
                db_path=self.db,
            )

        with self.client.session_transaction() as sess:
            sess["client_id"] = self.client_id

        resp = self.client.get("/client/prospects?page=2")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Page 2 of 2", resp.data)
        self.assertIn(b"Lead 10", resp.data)
        self.assertNotIn(b"Lead 0", resp.data)

    def test_client_prospects_sorting_works(self):
        database.add_prospect(
            name="Zeta Lead",
            company="Zeta Co",
            email="zeta@company.com",
            client_id=self.client_id,
            db_path=self.db,
        )
        database.add_prospect(
            name="Alpha Lead",
            company="Alpha Co",
            email="alpha@company.com",
            client_id=self.client_id,
            db_path=self.db,
        )

        with self.client.session_transaction() as sess:
            sess["client_id"] = self.client_id

        resp = self.client.get("/client/prospects?sort=name&dir=asc")
        self.assertEqual(resp.status_code, 200)
        self.assertLess(resp.data.find(b"Alpha Lead"), resp.data.find(b"Zeta Lead"))

    def test_client_prospects_page_shows_bulk_controls(self):
        database.add_prospect(
            name="Bulk Lead",
            company="Bulk Co",
            email="bulk@company.com",
            client_id=self.client_id,
            db_path=self.db,
        )

        with self.client.session_transaction() as sess:
            sess["client_id"] = self.client_id

        resp = self.client.get("/client/prospects")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Enroll in sequence", resp.data)
        self.assertIn(b"Apply status", resp.data)

    def test_client_prospect_detail_requires_session(self):
        resp = self.client.get("/client/prospects/1", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/client/login", resp.headers["Location"])

    def test_client_prospect_detail_is_workspace_scoped(self):
        other_client_id = database.add_client("Other Co", "other2@test.com", db_path=self.db)
        own_prospect_id = database.add_prospect(
            name="Own Lead",
            company="Own Co",
            email="own@company.com",
            client_id=self.client_id,
            db_path=self.db,
        )
        other_prospect_id = database.add_prospect(
            name="Other Lead",
            company="Other Co",
            email="other@company.com",
            client_id=other_client_id,
            db_path=self.db,
        )

        with self.client.session_transaction() as sess:
            sess["client_id"] = self.client_id

        own_resp = self.client.get(f"/client/prospects/{own_prospect_id}", follow_redirects=False)
        self.assertEqual(own_resp.status_code, 200)
        self.assertIn(b"Own Lead", own_resp.data)

        other_resp = self.client.get(f"/client/prospects/{other_prospect_id}", follow_redirects=False)
        self.assertEqual(other_resp.status_code, 302)
        self.assertIn("/client/prospects", other_resp.headers["Location"])

    def test_client_prospect_detail_shows_pending_reply_actions(self):
        prospect_id = database.add_prospect(
            name="Reply Lead",
            company="Reply Co",
            email="replylead@company.com",
            client_id=self.client_id,
            db_path=self.db,
        )
        _seed_reply_draft_for_test(
            prospect_id=prospect_id,
            client_id=self.client_id,
            db_path=self.db,
        )

        with self.client.session_transaction() as sess:
            sess["client_id"] = self.client_id

        resp = self.client.get(f"/client/prospects/{prospect_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Send reply", resp.data)
        self.assertIn(b"Dismiss", resp.data)

    def test_client_reply_draft_action_updates_status(self):
        prospect_id = database.add_prospect(
            name="Dismiss Lead",
            company="Dismiss Co",
            email="dismiss@company.com",
            client_id=self.client_id,
            db_path=self.db,
        )
        draft_id = _seed_reply_draft_for_test(
            prospect_id=prospect_id,
            client_id=self.client_id,
            db_path=self.db,
        )

        with self.client.session_transaction() as sess:
            sess["client_id"] = self.client_id

        resp = self.client.post(
            f"/client/reply-drafts/{draft_id}/action",
            json={"action": "dismiss"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["status"], "dismissed")

        draft = database.get_reply_draft_by_id(draft_id, db_path=self.db)
        self.assertEqual(draft["status"], "dismissed")

    def test_client_bulk_enrol_updates_only_own_workspace(self):
        other_client_id = database.add_client("Other Bulk Co", "other-bulk@test.com", db_path=self.db)
        own_prospect_id = database.add_prospect(
            name="Own Bulk Lead",
            company="Own Bulk Co",
            email="ownbulk@company.com",
            client_id=self.client_id,
            db_path=self.db,
        )
        other_prospect_id = database.add_prospect(
            name="Other Bulk Lead",
            company="Other Bulk Co",
            email="otherbulk@company.com",
            client_id=other_client_id,
            db_path=self.db,
        )

        with self.client.session_transaction() as sess:
            sess["client_id"] = self.client_id

        bad_resp = self.client.post(
            "/client/prospects/bulk-action",
            json={"action": "enrol", "prospect_ids": [own_prospect_id, other_prospect_id]},
        )
        self.assertEqual(bad_resp.status_code, 404)

        ok_resp = self.client.post(
            "/client/prospects/bulk-action",
            json={"action": "enrol", "prospect_ids": [own_prospect_id]},
        )
        self.assertEqual(ok_resp.status_code, 200)
        self.assertEqual(ok_resp.get_json()["updated"], 1)
        self.assertEqual(
            database.get_prospect_by_id(own_prospect_id, db_path=self.db)["status"],
            "in_sequence",
        )

    def test_client_bulk_status_update_works(self):
        prospect_one = database.add_prospect(
            name="Status One",
            company="Status Co",
            email="status1@company.com",
            client_id=self.client_id,
            db_path=self.db,
        )
        prospect_two = database.add_prospect(
            name="Status Two",
            company="Status Co",
            email="status2@company.com",
            client_id=self.client_id,
            db_path=self.db,
        )

        with self.client.session_transaction() as sess:
            sess["client_id"] = self.client_id

        resp = self.client.post(
            "/client/prospects/bulk-action",
            json={"action": "status", "status": "qualified", "prospect_ids": [prospect_one, prospect_two]},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["updated"], 2)
        self.assertEqual(database.get_prospect_by_id(prospect_one, db_path=self.db)["status"], "qualified")
        self.assertEqual(database.get_prospect_by_id(prospect_two, db_path=self.db)["status"], "qualified")

    def test_client_prospects_export_requires_session(self):
        resp = self.client.get("/client/prospects/export", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/client/login", resp.headers["Location"])

    def test_client_prospects_export_respects_filters(self):
        database.add_prospect(
            name="Booked Lead",
            company="Booked Co",
            email="booked-export@company.com",
            status="booked",
            client_id=self.client_id,
            db_path=self.db,
        )
        database.add_prospect(
            name="New Lead",
            company="New Co",
            email="new-export@company.com",
            status="new",
            client_id=self.client_id,
            db_path=self.db,
        )

        with self.client.session_transaction() as sess:
            sess["client_id"] = self.client_id

        resp = self.client.get("/client/prospects/export?status=booked")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.mimetype, "text/csv")
        self.assertIn(b"Booked Lead", resp.data)
        self.assertNotIn(b"New Lead", resp.data)

    def test_client_logout_clears_session_and_redirects(self):
        with self.client.session_transaction() as sess:
            sess["client_id"] = self.client_id

        resp = self.client.post("/client/logout", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)

        # Session cleared — dashboard now redirects to login
        resp2 = self.client.get("/client", follow_redirects=False)
        self.assertEqual(resp2.status_code, 302)
        self.assertIn("/client/login", resp2.headers["Location"])

    def test_client_settings_can_save_sender_identity(self):
        with self.client.session_transaction() as sess:
            sess["client_id"] = self.client_id

        resp = self.client.post("/client/settings", data={
            "niche": "Consulting",
            "icp": "SMBs",
            "location": "London",
            "calendar_link": "https://calendly.com/widget/intro",
            "sender_name": "Alex Widget",
            "sender_email": "alex@widgetco.com",
        }, follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/client/settings?saved=1", resp.headers["Location"])

        client = database.get_client(self.client_id, db_path=self.db)
        self.assertEqual(client["sender_name"], "Alex Widget")
        self.assertEqual(client["sender_email"], "alex@widgetco.com")


class TestCampaignPauseResume(unittest.TestCase):
    """Tests for POST /client/campaign/pause and /client/campaign/resume."""

    def setUp(self):
        self.db = _make_test_db()
        web_app.app.config["TESTING"] = True
        self._orig_db_path = database.DB_PATH
        database.DB_PATH = self.db
        self.client = web_app.app.test_client()
        self.client_id = database.add_client(
            name="Pause Co", email="pause@example.com", db_path=self.db
        )

    def tearDown(self):
        database.DB_PATH = self._orig_db_path
        if os.path.exists(self.db):
            os.unlink(self.db)

    def _login(self):
        with self.client.session_transaction() as sess:
            sess["client_id"] = self.client_id

    def test_pause_sets_flag_and_redirects(self):
        self._login()
        resp = self.client.post("/client/campaign/pause", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        client = database.get_client(self.client_id, db_path=self.db)
        self.assertEqual(client["campaign_paused"], 1)

    def test_resume_clears_flag_and_redirects(self):
        self._login()
        database.update_client(self.client_id, campaign_paused=1, db_path=self.db)
        resp = self.client.post("/client/campaign/resume", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        client = database.get_client(self.client_id, db_path=self.db)
        self.assertEqual(client["campaign_paused"], 0)

    def test_pause_requires_session(self):
        resp = self.client.post("/client/campaign/pause", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/client/login", resp.headers["Location"])

    def test_resume_requires_session(self):
        resp = self.client.post("/client/campaign/resume", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/client/login", resp.headers["Location"])


class TestOperatorClientFiltering(unittest.TestCase):
    """Tests for operator dashboard client workspace filtering."""

    def setUp(self):
        self.db = _make_test_db()
        web_app.app.config["TESTING"] = True
        self._orig_db_path = database.DB_PATH
        database.DB_PATH = self.db
        self.client = web_app.app.test_client()

        self.client_two_id = database.add_client(
            "Client Two",
            "owner@clienttwo.com",
            db_path=self.db,
        )
        database.add_prospect(
            name="House Lead",
            company="House Co",
            email="house@example.com",
            client_id=1,
            db_path=self.db,
        )
        database.add_prospect(
            name="Client Two Lead",
            company="Client Two Co",
            email="two@example.com",
            client_id=self.client_two_id,
            db_path=self.db,
        )

    def tearDown(self):
        database.DB_PATH = self._orig_db_path
        try:
            os.unlink(self.db)
        except OSError:
            pass

    def test_operator_dashboard_can_filter_to_selected_client(self):
        resp = self.client.get(f"/ops?client_id={self.client_two_id}", headers=_OPS_AUTH)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Client Two Lead", resp.data)
        self.assertIn(b"Client Two Co", resp.data)
        self.assertNotIn(b"House Lead", resp.data)

    def test_operator_analytics_endpoint_uses_client_filter(self):
        resp = self.client.get(f"/api/analytics?client_id={self.client_two_id}")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["prospects"]["total"], 1)
        self.assertEqual(data["funnel"]["counts"]["new"], 1)

    def test_outreach_queue_endpoint_uses_client_filter(self):
        house_prospect = database.get_prospect_by_email("house@example.com", db_path=self.db)
        client_two_prospect = database.get_prospect_by_email("two@example.com", db_path=self.db)

        database.save_outreach(
            prospect_id=house_prospect["id"],
            subject="House draft",
            body="House body",
            client_id=1,
            db_path=self.db,
        )
        database.save_outreach(
            prospect_id=client_two_prospect["id"],
            subject="Client two draft",
            body="Client two body",
            client_id=self.client_two_id,
            db_path=self.db,
        )

        resp = self.client.get(f"/api/outreach-queue?client_id={self.client_two_id}")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["subject"], "Client two draft")

    def test_reply_draft_action_respects_selected_client(self):
        house_prospect = database.get_prospect_by_email("house@example.com", db_path=self.db)
        client_two_prospect = database.get_prospect_by_email("two@example.com", db_path=self.db)
        house_draft_id = _seed_reply_draft_for_test(
            prospect_id=house_prospect["id"],
            client_id=1,
            db_path=self.db,
        )
        client_two_draft_id = _seed_reply_draft_for_test(
            prospect_id=client_two_prospect["id"],
            client_id=self.client_two_id,
            db_path=self.db,
        )

        resp_wrong_client = self.client.post(
            f"/api/reply-drafts/{house_draft_id}/action?client_id={self.client_two_id}",
            json={"action": "dismiss"},
        )
        self.assertEqual(resp_wrong_client.status_code, 404)

        resp_correct_client = self.client.post(
            f"/api/reply-drafts/{client_two_draft_id}/action?client_id={self.client_two_id}",
            json={"action": "dismiss"},
        )
        self.assertEqual(resp_correct_client.status_code, 200)
        self.assertEqual(resp_correct_client.get_json()["status"], "dismissed")

    def test_prospect_actions_respect_selected_client(self):
        house_prospect = database.get_prospect_by_email("house@example.com", db_path=self.db)
        client_two_prospect = database.get_prospect_by_email("two@example.com", db_path=self.db)

        wrong_update = self.client.patch(
            f"/api/prospects/{house_prospect['id']}?client_id={self.client_two_id}",
            json={"notes": "should fail"},
        )
        self.assertEqual(wrong_update.status_code, 404)

        wrong_enrol = self.client.post(
            f"/api/prospects/{house_prospect['id']}/enrol?client_id={self.client_two_id}"
        )
        self.assertEqual(wrong_enrol.status_code, 404)

        wrong_delete = self.client.delete(
            f"/api/prospects/{house_prospect['id']}?client_id={self.client_two_id}"
        )
        self.assertEqual(wrong_delete.status_code, 404)

        ok_update = self.client.patch(
            f"/api/prospects/{client_two_prospect['id']}?client_id={self.client_two_id}",
            json={"notes": "updated"},
        )
        self.assertEqual(ok_update.status_code, 200)

        ok_enrol = self.client.post(
            f"/api/prospects/{client_two_prospect['id']}/enrol?client_id={self.client_two_id}"
        )
        self.assertEqual(ok_enrol.status_code, 200)

        ok_delete = self.client.delete(
            f"/api/prospects/{client_two_prospect['id']}?client_id={self.client_two_id}"
        )
        self.assertEqual(ok_delete.status_code, 200)


class TestUnsubscribe(unittest.TestCase):
    """Tests for GET /unsubscribe."""

    def setUp(self):
        self.db = _make_test_db()
        web_app.app.config["TESTING"] = True
        self._orig_db_path = database.DB_PATH
        database.DB_PATH = self.db
        self.client = web_app.app.test_client()

        # Create a prospect to unsubscribe
        self.client_id = database.add_client(
            name="Unsub Client", email="unsub@example.com", db_path=self.db
        )
        self.prospect_id = database.add_prospect(
            name="Target", company="Corp", email="target@corp.com",
            client_id=self.client_id, db_path=self.db,
        )

    def tearDown(self):
        database.DB_PATH = self._orig_db_path
        if os.path.exists(self.db):
            os.unlink(self.db)

    def _unsub_url(self, pid=None, cid=None, token=None):
        from deliverability import _make_unsubscribe_token
        pid   = pid   if pid   is not None else self.prospect_id
        cid   = cid   if cid   is not None else self.client_id
        token = token if token is not None else _make_unsubscribe_token(pid, cid)
        return f"/unsubscribe?pid={pid}&cid={cid}&token={token}"

    def test_valid_token_suppresses_prospect_and_returns_200(self):
        resp = self.client.get(self._unsub_url())
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"unsubscribed", resp.data.lower())
        self.assertTrue(database.is_suppressed(
            "target@corp.com", db_path=self.db, client_id=self.client_id
        ))

    def test_invalid_token_shows_error_without_suppressing(self):
        resp = self.client.get(self._unsub_url(token="badtoken"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"invalid", resp.data.lower())
        self.assertFalse(database.is_suppressed(
            "target@corp.com", db_path=self.db, client_id=self.client_id
        ))

    def test_missing_params_shows_error(self):
        resp = self.client.get("/unsubscribe")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"invalid", resp.data.lower())

    def test_wrong_client_id_does_not_suppress(self):
        # Token is valid for client_id but prospect doesn't belong to client 999
        from deliverability import _make_unsubscribe_token
        token = _make_unsubscribe_token(self.prospect_id, 999)
        resp  = self.client.get(
            f"/unsubscribe?pid={self.prospect_id}&cid=999&token={token}"
        )
        self.assertEqual(resp.status_code, 200)
        # Should show success page (no existence leak) but not suppress
        self.assertFalse(database.is_suppressed(
            "target@corp.com", db_path=self.db, client_id=self.client_id
        ))


class TestProspectStatusUpdate(unittest.TestCase):
    """Tests for POST /client/prospects/<id>/update-status."""

    def setUp(self):
        self.db = _make_test_db()
        web_app.app.config["TESTING"] = True
        self._orig_db_path = database.DB_PATH
        database.DB_PATH = self.db
        self.http = web_app.app.test_client()
        self.client_id = database.add_client(
            name="Status Co", email="status@example.com", db_path=self.db
        )
        self.prospect_id = database.add_prospect(
            name="Alice", company="Acme", email="alice@acme.com",
            client_id=self.client_id, db_path=self.db,
        )

    def tearDown(self):
        database.DB_PATH = self._orig_db_path
        if os.path.exists(self.db):
            os.unlink(self.db)

    def _login(self):
        with self.http.session_transaction() as sess:
            sess["client_id"] = self.client_id

    def _update_url(self, pid=None):
        pid = pid or self.prospect_id
        return f"/client/prospects/{pid}/update-status"

    def test_mark_booked_updates_status_and_redirects(self):
        self._login()
        resp = self.http.post(
            self._update_url(),
            data={"new_status": "booked"},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)
        p = database.get_prospect_by_id(self.prospect_id, db_path=self.db)
        self.assertEqual(p["status"], "booked")

    def test_mark_rejected_updates_status_and_redirects(self):
        self._login()
        resp = self.http.post(
            self._update_url(),
            data={"new_status": "rejected"},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)
        p = database.get_prospect_by_id(self.prospect_id, db_path=self.db)
        self.assertEqual(p["status"], "rejected")

    def test_requires_session(self):
        resp = self.http.post(
            self._update_url(),
            data={"new_status": "booked"},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/client/login", resp.headers["Location"])

    def test_cannot_update_other_clients_prospect(self):
        other_id = database.add_client(
            "Other", "other@example.com", db_path=self.db
        )
        other_pid = database.add_prospect(
            name="Bob", company="OtherCo", email="bob@other.com",
            client_id=other_id, db_path=self.db,
        )
        self._login()
        resp = self.http.post(
            self._update_url(other_pid),
            data={"new_status": "booked"},
            follow_redirects=False,
        )
        # Should redirect back to prospects list, not update
        self.assertEqual(resp.status_code, 302)
        p = database.get_prospect_by_id(other_pid, db_path=self.db)
        self.assertEqual(p["status"], "new")  # unchanged


class TestOutreachReviewMode(unittest.TestCase):
    """Tests for outreach approval queue and review mode toggle."""

    def setUp(self):
        self.db = _make_test_db()
        web_app.app.config["TESTING"] = True
        self._orig_db_path = database.DB_PATH
        database.DB_PATH = self.db
        self.http = web_app.app.test_client()
        self.client_id = database.add_client(
            name="Review Co", email="review@example.com", db_path=self.db
        )
        self.prospect_id = database.add_prospect(
            name="Carol", company="WidgetCo", email="carol@widget.com",
            client_id=self.client_id, db_path=self.db,
        )

    def tearDown(self):
        database.DB_PATH = self._orig_db_path
        if os.path.exists(self.db):
            os.unlink(self.db)

    def _login(self):
        with self.http.session_transaction() as sess:
            sess["client_id"] = self.client_id

    def _seed_pending(self):
        oid = database.save_outreach(
            prospect_id=self.prospect_id,
            subject="Hello Carol",
            body="Hi Carol, ...",
            client_id=self.client_id,
            db_path=self.db,
        )
        database.update_outreach_status(oid, "pending_review", db_path=self.db)
        return oid

    def test_enable_review_mode_sets_flag(self):
        self._login()
        resp = self.http.post(
            "/client/campaign/review-mode/enable", follow_redirects=False
        )
        self.assertEqual(resp.status_code, 302)
        client = database.get_client(self.client_id, db_path=self.db)
        self.assertEqual(client["outreach_review_mode"], 1)

    def test_disable_review_mode_clears_flag(self):
        self._login()
        database.update_client(self.client_id, outreach_review_mode=1, db_path=self.db)
        resp = self.http.post(
            "/client/campaign/review-mode/disable", follow_redirects=False
        )
        self.assertEqual(resp.status_code, 302)
        client = database.get_client(self.client_id, db_path=self.db)
        self.assertEqual(client["outreach_review_mode"], 0)

    def test_outreach_queue_page_returns_200(self):
        self._login()
        self._seed_pending()
        resp = self.http.get("/client/outreach-queue")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Hello Carol", resp.data)

    def test_outreach_queue_requires_session(self):
        resp = self.http.get("/client/outreach-queue", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/client/login", resp.headers["Location"])

    def test_reject_action_marks_draft_rejected(self):
        self._login()
        oid = self._seed_pending()
        resp = self.http.post(
            f"/client/outreach-queue/{oid}/action",
            json={"action": "reject"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["status"], "rejected_draft")
        records = database.get_all_outreach(client_id=self.client_id, db_path=self.db)
        record = next(r for r in records if r["id"] == oid)
        self.assertEqual(record["status"], "rejected_draft")

    def test_reject_action_unauthenticated_returns_401(self):
        oid = self._seed_pending()
        resp = self.http.post(
            f"/client/outreach-queue/{oid}/action",
            json={"action": "reject"},
        )
        self.assertEqual(resp.status_code, 401)

    def test_reject_of_other_clients_record_returns_404(self):
        other_id = database.add_client("Other", "x@y.com", db_path=self.db)
        other_pid = database.add_prospect(
            name="X", company="Y", email="x@y.com",
            client_id=other_id, db_path=self.db,
        )
        oid = database.save_outreach(
            prospect_id=other_pid, subject="S", body="B",
            client_id=other_id, db_path=self.db,
        )
        database.update_outreach_status(oid, "pending_review", db_path=self.db)
        self._login()
        resp = self.http.post(
            f"/client/outreach-queue/{oid}/action",
            json={"action": "reject"},
        )
        self.assertEqual(resp.status_code, 404)

    def test_pending_outreach_query_scoped_to_client(self):
        oid = self._seed_pending()
        other_id = database.add_client("Other2", "z@example.com", db_path=self.db)
        pending_mine  = database.get_pending_outreach_for_review(
            self.client_id, db_path=self.db
        )
        pending_other = database.get_pending_outreach_for_review(
            other_id, db_path=self.db
        )
        self.assertEqual(len(pending_mine), 1)
        self.assertEqual(pending_mine[0]["id"], oid)
        self.assertEqual(len(pending_other), 0)


class TestWeeklyReportHtml(unittest.TestCase):
    """Tests for generate_weekly_report_html() in reporter.py."""

    def test_html_report_contains_key_stats(self):
        import reporter
        summary = {
            "date": "2026-04-17",
            "prospects": {
                "total": 42,
                "with_email": 30,
                "with_linkedin": 10,
                "with_phone": 5,
                "scored": 20,
            },
            "funnel": {
                "counts": {
                    "new": 10, "qualified": 5, "contacted": 15,
                    "replied": 7, "booked": 3, "rejected": 2,
                },
                "active": 40,
                "conversion_rate": 7.1,
            },
            "score_bands": {"hot": 12, "warm": 20, "cold": 10},
            "top_prospects": [
                {"name": "Alice Jones", "company": "Acme", "lead_score": 95, "status": "replied"},
            ],
            "top_companies": [("Acme", 5)],
            "outreach": {"draft": 2, "approved": 1, "sent": 18},
        }
        html = reporter.generate_weekly_report_html(
            summary,
            client_name="Bob",
            week_label="14 Apr 2026",
            dashboard_url="http://localhost/client",
        )
        self.assertIn("Hi Bob,", html)
        self.assertIn("14 Apr 2026", html)
        self.assertIn("42", html)   # total prospects
        self.assertIn("18", html)   # sent
        self.assertIn("Alice Jones", html)
        self.assertIn("View your dashboard", html)
        self.assertIn("http://localhost/client", html)
        self.assertIn("7.1%", html)  # conversion rate

    def test_html_report_works_with_empty_pipeline(self):
        import reporter
        summary = {
            "date": "2026-04-17",
            "prospects": {
                "total": 0, "with_email": 0, "with_linkedin": 0,
                "with_phone": 0, "scored": 0,
            },
            "funnel": {
                "counts": {s: 0 for s in ["new","qualified","contacted","replied","booked","rejected"]},
                "active": 0,
                "conversion_rate": 0.0,
            },
            "score_bands": {"hot": 0, "warm": 0, "cold": 0},
            "top_prospects": [],
            "top_companies": [],
            "outreach": {"draft": 0, "approved": 0, "sent": 0},
        }
        html = reporter.generate_weekly_report_html(summary)
        self.assertIn("Antigravity", html)
        self.assertIn("0%", html)


class TestOpsActionRoutes(unittest.TestCase):
    """Tests for POST /api/ops/client/<id>/pause|resume|toggle-review-mode|resend-welcome."""

    def setUp(self):
        self.db = _make_test_db()
        web_app.app.config["TESTING"] = True
        self._orig_db_path = database.DB_PATH
        database.DB_PATH = self.db
        self.http = web_app.app.test_client()
        self.client_id = database.add_client(
            name="Ops Target", email="ops@example.com", db_path=self.db
        )

    def tearDown(self):
        database.DB_PATH = self._orig_db_path
        if os.path.exists(self.db):
            os.unlink(self.db)

    def test_pause_sets_campaign_paused(self):
        resp = self.http.post(f"/api/ops/client/{self.client_id}/pause", headers=_OPS_AUTH)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertTrue(data["campaign_paused"])
        client = database.get_client(self.client_id, db_path=self.db)
        self.assertEqual(client["campaign_paused"], 1)

    def test_resume_clears_campaign_paused(self):
        database.update_client(self.client_id, campaign_paused=1, db_path=self.db)
        resp = self.http.post(f"/api/ops/client/{self.client_id}/resume", headers=_OPS_AUTH)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertFalse(data["campaign_paused"])
        client = database.get_client(self.client_id, db_path=self.db)
        self.assertEqual(client["campaign_paused"], 0)

    def test_toggle_review_mode_on(self):
        resp = self.http.post(f"/api/ops/client/{self.client_id}/toggle-review-mode", headers=_OPS_AUTH)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertTrue(data["outreach_review_mode"])
        client = database.get_client(self.client_id, db_path=self.db)
        self.assertEqual(client["outreach_review_mode"], 1)

    def test_toggle_review_mode_off(self):
        database.update_client(self.client_id, outreach_review_mode=1, db_path=self.db)
        resp = self.http.post(f"/api/ops/client/{self.client_id}/toggle-review-mode", headers=_OPS_AUTH)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertFalse(data["outreach_review_mode"])
        client = database.get_client(self.client_id, db_path=self.db)
        self.assertEqual(client["outreach_review_mode"], 0)

    def test_unknown_client_returns_404(self):
        resp = self.http.post("/api/ops/client/99999/pause", headers=_OPS_AUTH)
        self.assertEqual(resp.status_code, 404)
        self.assertIn("error", resp.get_json())

    def test_ops_api_requires_basic_auth(self):
        resp = self.http.post(f"/api/ops/client/{self.client_id}/pause")
        self.assertEqual(resp.status_code, 401)

    def test_resend_welcome_returns_ok_when_email_sent(self):
        import unittest.mock as mock
        with mock.patch("web_app._route_send_email") as mock_send:
            mock_send.return_value = None
            resp = self.http.post(
                f"/api/ops/client/{self.client_id}/resend-welcome", headers=_OPS_AUTH
            )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["ok"])
        mock_send.assert_called_once()

    def test_resend_welcome_404_for_unknown_client(self):
        resp = self.http.post("/api/ops/client/99999/resend-welcome", headers=_OPS_AUTH)
        self.assertEqual(resp.status_code, 404)

    def test_resend_welcome_400_when_no_email(self):
        no_email_id = database.add_client(name="No Email Co", email="", db_path=self.db)
        resp = self.http.post(f"/api/ops/client/{no_email_id}/resend-welcome", headers=_OPS_AUTH)
        self.assertEqual(resp.status_code, 400)


class TestSenderVerification(unittest.TestCase):
    """End-to-end tests for the sender email verification flow."""

    def setUp(self):
        self.db = _make_test_db()
        web_app.app.config["TESTING"] = True
        self._orig_db_path = database.DB_PATH
        database.DB_PATH = self.db
        self.http = web_app.app.test_client()
        self.client_id = database.add_client(
            name="Sender Co",
            email="sender@example.com",
            sender_email="outreach@sender.co",
            db_path=self.db,
        )

    def tearDown(self):
        database.DB_PATH = self._orig_db_path
        if os.path.exists(self.db):
            os.unlink(self.db)

    def _login(self):
        with self.http.session_transaction() as sess:
            sess["client_id"] = self.client_id

    # ── POST /client/settings/verify-sender ───────────────────────────────

    def test_verify_sender_send_requires_session(self):
        resp = self.http.post("/client/settings/verify-sender", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/client/login", resp.headers["Location"])

    def test_verify_sender_send_no_email_redirects_with_error(self):
        no_email_id = database.add_client(
            name="No Sender", email="nosender@example.com", db_path=self.db
        )
        with self.http.session_transaction() as sess:
            sess["client_id"] = no_email_id
        resp = self.http.post("/client/settings/verify-sender", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("verify_error=no_email", resp.headers["Location"])

    def test_verify_sender_send_emails_token_and_redirects(self):
        import unittest.mock as mock
        self._login()
        with mock.patch("web_app._route_send_email") as mock_send:
            mock_send.return_value = None
            resp = self.http.post("/client/settings/verify-sender", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("verify_sent=1", resp.headers["Location"])
        # Token must be stored in DB
        client = database.get_client(self.client_id, db_path=self.db)
        self.assertIsNotNone(client.get("sender_verify_token"))
        self.assertIsNotNone(client.get("sender_verify_expires_at"))
        # Email was sent to the sender_email, not the account email
        call_kwargs = mock_send.call_args
        to_addr = call_kwargs[1].get("to_address") or call_kwargs[0][0]
        self.assertEqual(to_addr, "outreach@sender.co")

    # ── GET /client/verify-sender ─────────────────────────────────────────

    def test_verify_sender_confirm_invalid_token_shows_error(self):
        resp = self.http.get("/client/verify-sender?token=not-a-real-token")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Invalid or expired", resp.data)

    def test_verify_sender_confirm_missing_token_redirects(self):
        resp = self.http.get("/client/verify-sender", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/client/login", resp.headers["Location"])

    def test_verify_sender_confirm_expired_token_shows_error(self):
        import datetime as _dt
        expired = (_dt.datetime.utcnow() - _dt.timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        database.set_sender_verify_token(self.client_id, "expired-tok", expired, db_path=self.db)
        resp = self.http.get("/client/verify-sender?token=expired-tok")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"expired", resp.data.lower())

    def test_verify_sender_confirm_valid_token_marks_verified(self):
        import datetime as _dt
        import unittest.mock as mock
        self._login()
        with mock.patch("web_app._route_send_email"):
            self.http.post("/client/settings/verify-sender")
        client = database.get_client(self.client_id, db_path=self.db)
        token = client["sender_verify_token"]
        resp = self.http.get(f"/client/verify-sender?token={token}", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("verified=1", resp.headers["Location"])
        client = database.get_client(self.client_id, db_path=self.db)
        self.assertEqual(client["sender_email_verified"], 1)
        # Token must be cleared after use
        self.assertFalse(client.get("sender_verify_token"))

    def test_verify_sender_confirm_without_session_redirects_to_login(self):
        import unittest.mock as mock
        self._login()
        with mock.patch("web_app._route_send_email"):
            self.http.post("/client/settings/verify-sender")
        # Log out, then follow the verify link
        self.http.post("/client/logout")
        client = database.get_client(self.client_id, db_path=self.db)
        token = client["sender_verify_token"]
        resp = self.http.get(f"/client/verify-sender?token={token}", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/client/login", resp.headers["Location"])
        self.assertIn("verified=1", resp.headers["Location"])


if __name__ == "__main__":
    unittest.main()
