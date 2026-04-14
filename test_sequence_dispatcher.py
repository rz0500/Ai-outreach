"""
test_sequence_dispatcher.py - Dispatcher tests
==============================================
Verifies routing and logging for the new multi-channel dispatcher.
"""

import gc
import os
import unittest
from datetime import date, timedelta
from unittest.mock import patch

from database import (
    add_prospect,
    ensure_sequence_enrollment,
    get_communication_events,
    initialize_database,
    update_sequence_enrollment_status,
)
from sequence_dispatcher import run_multichannel_sequence

TEST_DB = "test_sequence_dispatcher.db"


class TestSequenceDispatcher(unittest.TestCase):

    def setUp(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)
        initialize_database(TEST_DB)

    def tearDown(self):
        gc.collect()
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)

    def test_dry_run_returns_due_touchpoint_without_logging_send(self):
        pid = add_prospect(
            name="Jane Doe",
            company="Acme Corp",
            email="jane@acme.com",
            status="in_sequence",
            db_path=TEST_DB,
        )
        ensure_sequence_enrollment(pid, db_path=TEST_DB)

        results = run_multichannel_sequence(dry_run=True, db_path=TEST_DB)

        self.assertEqual(len(results), 1)
        self.assertFalse(results[0]["sent"])
        self.assertEqual(results[0]["channel"], "email")
        self.assertEqual(get_communication_events(db_path=TEST_DB), [])

    @patch("sequence_dispatcher.send_email", return_value=(True, ""))
    def test_email_touchpoint_sends_and_logs_event(self, mock_send):
        pid = add_prospect(
            name="Jane Doe",
            company="Acme Corp",
            email="jane@acme.com",
            status="in_sequence",
            db_path=TEST_DB,
        )
        ensure_sequence_enrollment(pid, db_path=TEST_DB)

        results = run_multichannel_sequence(
            dry_run=False,
            db_path=TEST_DB,
            today=date.today() + timedelta(days=1),
        )

        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["sent"])
        mock_send.assert_called_once()
        events = get_communication_events(pid, TEST_DB)
        self.assertEqual(events[0]["status"], "sent")

    def test_paused_enrollment_is_not_dispatched(self):
        pid = add_prospect(
            name="Jane Doe",
            company="Acme Corp",
            email="jane@acme.com",
            status="in_sequence",
            db_path=TEST_DB,
        )
        ensure_sequence_enrollment(pid, db_path=TEST_DB)
        update_sequence_enrollment_status(pid, "paused", db_path=TEST_DB)

        self.assertEqual(run_multichannel_sequence(dry_run=False, db_path=TEST_DB), [])

    @patch("sequence_dispatcher.send_linkedin_connection", return_value=True)
    def test_linkedin_touchpoint_routes_to_social_agent(self, mock_linkedin):
        pid = add_prospect(
            name="Jane Doe",
            company="Acme Corp",
            email="jane@acme.com",
            linkedin_url="https://linkedin.com/in/janedoe",
            status="in_sequence",
            db_path=TEST_DB,
        )
        ensure_sequence_enrollment(pid, db_path=TEST_DB)
        from database import log_communication_event
        log_communication_event(
            pid, "email", "outbound", "sequence_step", "sent",
            metadata="sequence=default_multichannel;step=1",
            db_path=TEST_DB,
        )

        results = run_multichannel_sequence(
            dry_run=False,
            db_path=TEST_DB,
            today=date.today() + timedelta(days=1),
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["channel"], "linkedin")
        self.assertTrue(results[0]["sent"])
        mock_linkedin.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
