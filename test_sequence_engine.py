"""
test_sequence_engine.py - Channel-aware sequence foundation tests
=================================================================
Verifies sequence enrollment persistence and due-touchpoint logic.
"""

import gc
import os
import unittest
from datetime import date, timedelta

from database import (
    add_prospect,
    ensure_sequence_enrollment,
    get_sequence_enrollment,
    initialize_database,
    log_communication_event,
    suppress_contact,
    update_sequence_enrollment_status,
)
from sequence_engine import DEFAULT_SEQUENCE_NAME, get_due_touchpoints, get_sequence_definition

TEST_DB = "test_sequence_engine.db"


class TestSequenceEngine(unittest.TestCase):

    def setUp(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)
        initialize_database(TEST_DB)

    def tearDown(self):
        gc.collect()
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)

    def test_ensure_sequence_enrollment_is_idempotent(self):
        pid = add_prospect(
            name="Jane Doe",
            company="Acme Corp",
            email="jane@acme.com",
            status="in_sequence",
            db_path=TEST_DB,
        )

        first_id = ensure_sequence_enrollment(pid, db_path=TEST_DB)
        second_id = ensure_sequence_enrollment(pid, db_path=TEST_DB)

        self.assertEqual(first_id, second_id)
        enrollment = get_sequence_enrollment(pid, TEST_DB)
        self.assertEqual(enrollment["sequence_name"], DEFAULT_SEQUENCE_NAME)

    def test_first_touchpoint_due_on_enrollment_day(self):
        pid = add_prospect(
            name="Jane Doe",
            company="Acme Corp",
            email="jane@acme.com",
            status="in_sequence",
            db_path=TEST_DB,
        )
        ensure_sequence_enrollment(pid, db_path=TEST_DB)

        due = get_due_touchpoints(TEST_DB, today=date.today())

        self.assertEqual(len(due), 1)
        self.assertEqual(due[0]["next_touchpoint"]["step"], 1)
        self.assertEqual(due[0]["next_touchpoint"]["channel"], "email")

    def test_second_touchpoint_due_after_step_one_sent(self):
        pid = add_prospect(
            name="Jane Doe",
            company="Acme Corp",
            email="jane@acme.com",
            status="in_sequence",
            db_path=TEST_DB,
        )
        ensure_sequence_enrollment(pid, db_path=TEST_DB)

        enrollment = get_sequence_enrollment(pid, TEST_DB)
        log_communication_event(
            pid, "email", "outbound", "sequence_step", "sent",
            metadata="sequence=default_multichannel;step=1",
            db_path=TEST_DB,
        )

        due = get_due_touchpoints(
            TEST_DB,
            today=date.today() + timedelta(days=1),
        )

        self.assertEqual(len(due), 1)
        self.assertEqual(due[0]["enrollment_id"], enrollment["id"])
        self.assertEqual(due[0]["next_touchpoint"]["step"], 2)
        self.assertEqual(due[0]["next_touchpoint"]["channel"], "linkedin")

    def test_paused_enrollment_is_not_due(self):
        pid = add_prospect(
            name="Jane Doe",
            company="Acme Corp",
            email="jane@acme.com",
            status="in_sequence",
            db_path=TEST_DB,
        )
        ensure_sequence_enrollment(pid, db_path=TEST_DB)
        update_sequence_enrollment_status(pid, "paused", paused_reason="manual hold", db_path=TEST_DB)

        self.assertEqual(get_due_touchpoints(TEST_DB), [])

    def test_suppressed_contact_is_not_due(self):
        pid = add_prospect(
            name="Jane Doe",
            company="Acme Corp",
            email="jane@acme.com",
            status="in_sequence",
            db_path=TEST_DB,
        )
        ensure_sequence_enrollment(pid, db_path=TEST_DB)
        suppress_contact("jane@acme.com", "opt out", db_path=TEST_DB)

        self.assertEqual(get_due_touchpoints(TEST_DB), [])

    def test_sequence_definition_matches_blueprint_length(self):
        definition = get_sequence_definition()
        self.assertEqual(len(definition), 8)
        self.assertEqual(definition[-1]["label"], "Breakup email")


if __name__ == "__main__":
    unittest.main(verbosity=2)
