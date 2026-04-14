"""
test_compliance.py - Compliance and sequencing guardrails
=========================================================
Verifies suppression-list behavior, communication event logging,
and opt-out language in outbound emails.
"""

import gc
import os
import unittest
from datetime import date

from database import (
    add_prospect,
    get_communication_events,
    get_prospects_in_sequence,
    get_suppressed_contacts,
    initialize_database,
    is_suppressed,
    log_communication_event,
    suppress_contact,
    suppress_prospect,
)
from outreach import OPT_OUT_LINE, generate_email
from sequencer import run_sequence

TEST_DB = "test_compliance.db"


class TestCompliance(unittest.TestCase):

    def setUp(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)
        initialize_database(TEST_DB)

    def tearDown(self):
        gc.collect()
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)

    def test_suppress_contact_adds_email_once(self):
        created = suppress_contact("Test@Example.com", "opt out", db_path=TEST_DB)
        duplicate = suppress_contact("test@example.com", "duplicate", db_path=TEST_DB)

        self.assertTrue(created)
        self.assertFalse(duplicate)
        self.assertTrue(is_suppressed("test@example.com", TEST_DB))
        self.assertEqual(len(get_suppressed_contacts(TEST_DB)), 1)

    def test_suppressed_prospect_is_excluded_from_sequence(self):
        pid = add_prospect(
            name="Jane Doe",
            company="Acme Corp",
            email="jane@acme.com",
            status="in_sequence",
            db_path=TEST_DB,
        )

        self.assertEqual(len(get_prospects_in_sequence(TEST_DB)), 1)
        suppress_prospect(pid, "unsubscribe", db_path=TEST_DB)
        self.assertEqual(get_prospects_in_sequence(TEST_DB), [])

    def test_generate_email_includes_opt_out_line(self):
        draft = generate_email({"name": "Jane Doe", "company": "Acme Corp"})
        self.assertIn(OPT_OUT_LINE, draft["body"])

    def test_log_communication_event_records_event(self):
        pid = add_prospect(
            name="Jane Doe",
            company="Acme Corp",
            email="jane@acme.com",
            db_path=TEST_DB,
        )
        event_id = log_communication_event(
            pid, "email", "outbound", "sequence_step", "sent",
            content_excerpt="Quick idea for Acme", metadata="step=1", db_path=TEST_DB
        )

        events = get_communication_events(pid, TEST_DB)
        self.assertGreater(event_id, 0)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["status"], "sent")

    def test_sequencer_logs_skipped_event_for_missing_email(self):
        add_prospect(
            name="No Email",
            company="Corp",
            email=None,
            status="in_sequence",
            db_path=TEST_DB,
        )

        run_sequence(dry_run=False, db_path=TEST_DB)

        events = get_communication_events(db_path=TEST_DB)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["status"], "skipped")
        self.assertIn("No email", events[0]["metadata"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
