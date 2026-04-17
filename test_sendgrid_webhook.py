import os
import tempfile
import unittest
import json
import base64
import hashlib

os.environ.setdefault("SECRET_KEY", "test-secret-key")

import database
import web_app
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils


def _make_test_db():
    db = tempfile.mktemp(suffix=".db")
    database.initialize_database(db)
    database.initialize_outreach_table(db)
    return db


class TestSendGridWebhook(unittest.TestCase):
    def setUp(self):
        self.db = _make_test_db()
        web_app.app.config["TESTING"] = True
        self._orig_db_path = database.DB_PATH
        self._orig_sendgrid_public_key = os.environ.get("SENDGRID_WEBHOOK_PUBLIC_KEY")
        database.DB_PATH = self.db
        self.client = web_app.app.test_client()

        self.client_two_id = database.add_client("Client Two", "two@test.com", db_path=self.db)
        self.house_prospect_id = database.add_prospect(
            name="House Lead",
            company="House Co",
            email="bounce@test.com",
            client_id=1,
            db_path=self.db,
        )
        self.client_two_prospect_id = database.add_prospect(
            name="Client Two Lead",
            company="Client Two Co",
            email="unsubscribe@test.com",
            client_id=self.client_two_id,
            db_path=self.db,
        )

    def tearDown(self):
        database.DB_PATH = self._orig_db_path
        if self._orig_sendgrid_public_key is None:
            os.environ.pop("SENDGRID_WEBHOOK_PUBLIC_KEY", None)
        else:
            os.environ["SENDGRID_WEBHOOK_PUBLIC_KEY"] = self._orig_sendgrid_public_key
        try:
            os.unlink(self.db)
        except OSError:
            pass

    def _signed_headers(self, payload_bytes: bytes, timestamp: str = "1713312000") -> dict:
        private_key = ec.generate_private_key(ec.SECP256R1())
        os.environ["SENDGRID_WEBHOOK_PUBLIC_KEY"] = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")

        digest = hashlib.sha256(timestamp.encode("utf-8") + payload_bytes).digest()
        signature = private_key.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
        return {
            "X-Twilio-Email-Event-Webhook-Timestamp": timestamp,
            "X-Twilio-Email-Event-Webhook-Signature": base64.b64encode(signature).decode("ascii"),
            "Content-Type": "application/json",
        }

    def test_sendgrid_bounce_suppresses_all_matching_workspaces(self):
        resp = self.client.post("/webhook/sendgrid", json=[
            {
                "event": "bounce",
                "email": "bounce@test.com",
                "reason": "550 invalid recipient",
            }
        ])
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertEqual(payload["processed"], 1)
        self.assertEqual(payload["matched_prospects"], 1)

        self.assertTrue(database.is_suppressed("bounce@test.com", db_path=self.db, client_id=1))
        self.assertEqual(database.get_prospect_by_id(self.house_prospect_id, db_path=self.db)["status"], "rejected")
        self.assertNotEqual(database.get_prospect_by_id(self.client_two_prospect_id, db_path=self.db)["status"], "rejected")

        house_events = database.get_communication_events(self.house_prospect_id, db_path=self.db)
        self.assertTrue(any(evt["event_type"] == "sendgrid_bounce" for evt in house_events))

    def test_sendgrid_unsubscribe_marks_as_skipped_style_event(self):
        resp = self.client.post("/webhook/sendgrid", json=[
            {
                "event": "unsubscribe",
                "email": "unsubscribe@test.com",
                "reason": "user opted out",
            }
        ])
        self.assertEqual(resp.status_code, 200)

        self.assertTrue(database.is_suppressed("unsubscribe@test.com", db_path=self.db, client_id=self.client_two_id))
        self.assertEqual(database.get_prospect_by_id(self.client_two_prospect_id, db_path=self.db)["status"], "rejected")

        events = database.get_communication_events(self.client_two_prospect_id, db_path=self.db)
        unsubscribe_events = [evt for evt in events if evt["event_type"] == "sendgrid_unsubscribe"]
        self.assertTrue(unsubscribe_events)
        self.assertEqual(unsubscribe_events[0]["status"], "skipped")

    def test_sendgrid_webhook_rejects_non_array_payload(self):
        resp = self.client.post("/webhook/sendgrid", json={"event": "bounce"})
        self.assertEqual(resp.status_code, 400)

    def test_sendgrid_webhook_accepts_valid_signature_when_configured(self):
        payload = json.dumps([
            {
                "event": "bounce",
                "email": "bounce@test.com",
                "reason": "550 invalid recipient",
            }
        ]).encode("utf-8")
        headers = self._signed_headers(payload)

        resp = self.client.post("/webhook/sendgrid", data=payload, headers=headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["processed"], 1)

    def test_sendgrid_webhook_rejects_invalid_signature_when_configured(self):
        payload = json.dumps([
            {
                "event": "unsubscribe",
                "email": "unsubscribe@test.com",
                "reason": "user opted out",
            }
        ]).encode("utf-8")
        headers = self._signed_headers(payload)
        headers["X-Twilio-Email-Event-Webhook-Signature"] = base64.b64encode(b"bad-signature").decode("ascii")

        resp = self.client.post("/webhook/sendgrid", data=payload, headers=headers)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("signature", resp.get_json()["error"].lower())


if __name__ == "__main__":
    unittest.main()
