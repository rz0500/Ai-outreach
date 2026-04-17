"""
test_deliverability.py
======================
Focused tests for shared outbound deliverability behavior.
"""

import gc
import os
import unittest

from unittest.mock import patch

import database
from deliverability import classify_delivery_failure, deliver_prospect_email

TEST_DB = "test_deliverability.db"


class TestDeliverability(unittest.TestCase):

    def setUp(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)
        database.initialize_database(TEST_DB)

    def tearDown(self):
        gc.collect()
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)

    def test_classify_delivery_failure_maps_known_errors(self):
        self.assertEqual(
            classify_delivery_failure("Recipient refused by server: x@example.com"),
            "invalid_recipient",
        )
        self.assertEqual(
            classify_delivery_failure("Authentication failed - check SMTP settings"),
            "auth_or_config_error",
        )
        self.assertEqual(
            classify_delivery_failure("Connection error (smtp.gmail.com:465): timeout"),
            "transient_send_error",
        )

    def test_suppressed_email_is_skipped_and_logged(self):
        pid = database.add_prospect(
            name="Jane Doe",
            company="Acme Corp",
            email="jane@acme.com",
            status="in_sequence",
            db_path=TEST_DB,
        )
        database.suppress_contact("jane@acme.com", "opt out", db_path=TEST_DB)

        result = deliver_prospect_email(
            to_address="jane@acme.com",
            subject="Quick idea",
            body="Hello",
            prospect_id=pid,
            event_type="sequence_step",
            db_path=TEST_DB,
        )

        self.assertFalse(result["sent"])
        self.assertEqual(result["outcome"], "suppressed_skip")
        self.assertEqual(result["event_status"], "skipped")
        events = database.get_communication_events(pid, TEST_DB)
        self.assertEqual(events[0]["status"], "skipped")

    def test_recipient_refused_suppresses_and_rejects_prospect(self):
        pid = database.add_prospect(
            name="Jane Doe",
            company="Acme Corp",
            email="jane@acme.com",
            status="in_sequence",
            db_path=TEST_DB,
        )

        def refused(*args, **kwargs):
            return False, "Recipient refused by server: jane@acme.com"

        result = deliver_prospect_email(
            to_address="jane@acme.com",
            subject="Quick idea",
            body="Hello",
            prospect_id=pid,
            event_type="sequence_step",
            db_path=TEST_DB,
            send_callable=refused,
        )

        self.assertFalse(result["sent"])
        self.assertEqual(result["outcome"], "invalid_recipient")
        self.assertTrue(database.is_suppressed("jane@acme.com", TEST_DB))
        prospect = database.get_prospect_by_email("jane@acme.com", TEST_DB)
        self.assertEqual(prospect["status"], "rejected")
        events = database.get_communication_events(pid, TEST_DB)
        self.assertEqual(events[0]["status"], "failed")

    def test_auth_failure_logs_failed_without_suppression(self):
        pid = database.add_prospect(
            name="Jane Doe",
            company="Acme Corp",
            email="jane@acme.com",
            status="in_sequence",
            db_path=TEST_DB,
        )

        result = deliver_prospect_email(
            to_address="jane@acme.com",
            subject="Quick idea",
            body="Hello",
            prospect_id=pid,
            event_type="sequence_step",
            db_path=TEST_DB,
            send_callable=lambda *args, **kwargs: (False, "Authentication failed - bad credentials"),
        )

        self.assertFalse(result["sent"])
        self.assertEqual(result["outcome"], "auth_or_config_error")
        self.assertFalse(database.is_suppressed("jane@acme.com", TEST_DB))
        events = database.get_communication_events(pid, TEST_DB)
        self.assertEqual(events[0]["status"], "failed")

    def test_transient_failure_logs_failed_without_suppression(self):
        pid = database.add_prospect(
            name="Jane Doe",
            company="Acme Corp",
            email="jane@acme.com",
            status="in_sequence",
            db_path=TEST_DB,
        )

        result = deliver_prospect_email(
            to_address="jane@acme.com",
            subject="Quick idea",
            body="Hello",
            prospect_id=pid,
            event_type="sequence_step",
            db_path=TEST_DB,
            send_callable=lambda *args, **kwargs: (False, "SMTP error: timed out"),
        )

        self.assertFalse(result["sent"])
        self.assertEqual(result["outcome"], "transient_send_error")
        self.assertFalse(database.is_suppressed("jane@acme.com", TEST_DB))
        events = database.get_communication_events(pid, TEST_DB)
        self.assertEqual(events[0]["status"], "failed")

    def test_client_sender_identity_is_passed_to_send_callable(self):
        client_id = database.add_client(
            "Sender Co",
            "owner@senderco.com",
            sender_name="Taylor Sender",
            sender_email="taylor@senderco.com",
            db_path=TEST_DB,
        )
        pid = database.add_prospect(
            name="Jane Doe",
            company="Acme Corp",
            email="jane@acme.com",
            client_id=client_id,
            db_path=TEST_DB,
        )
        captured = {}

        def fake_sender(*args, **kwargs):
            captured["from_address"] = kwargs.get("from_address")
            captured["from_name"] = kwargs.get("from_name")
            return True, ""

        result = deliver_prospect_email(
            to_address="jane@acme.com",
            subject="Quick idea",
            body="Hello",
            prospect_id=pid,
            event_type="sequence_step",
            client_id=client_id,
            db_path=TEST_DB,
            send_callable=fake_sender,
        )

        self.assertTrue(result["sent"])
        self.assertEqual(captured["from_address"], "taylor@senderco.com")
        self.assertEqual(captured["from_name"], "Taylor Sender")

    def test_deliverability_summary_uses_existing_events(self):
        pid = database.add_prospect(
            name="Jane Doe",
            company="Acme Corp",
            email="jane@acme.com",
            db_path=TEST_DB,
        )
        database.suppress_contact("skip@example.com", "manual", db_path=TEST_DB)
        database.log_communication_event(
            pid, "email", "outbound", "sequence_step", "failed",
            metadata="delivery_outcome=transient_send_error", db_path=TEST_DB,
        )
        database.log_communication_event(
            pid, "email", "outbound", "sequence_step", "skipped",
            metadata="delivery_outcome=suppressed_skip", db_path=TEST_DB,
        )

        summary = database.get_deliverability_summary(db_path=TEST_DB)
        self.assertEqual(summary["suppressed_total"], 1)
        self.assertEqual(summary["failed_count"], 1)
        self.assertEqual(summary["skipped_count"], 1)
        self.assertEqual(len(summary["recent_failed"]), 1)
        self.assertEqual(len(summary["recent_skipped"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
