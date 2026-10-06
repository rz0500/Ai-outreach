"""
End-to-end lifecycle of the email-only follow-up sequence on a temp DB:
initial email -> follow-up 1 (day 5) -> follow-up 2 (day 12), with no
duplicate rows, no follow-ups after a reply, and step tracking on send.
"""

import gc
import os
import sqlite3
import unittest
from datetime import date, timedelta
from unittest.mock import patch

import database as db
from sequence_dispatcher import record_email_step_sent, run_multichannel_sequence
from sequence_engine import CANDIDATE_EMAIL_SEQUENCE_NAME as SEQ

TEST_DB = "test_followup_lifecycle.db"


def _rows(pid):
    with sqlite3.connect(TEST_DB) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(
            "SELECT * FROM outreach WHERE prospect_id=? ORDER BY id", (pid,))]


class TestFollowupLifecycle(unittest.TestCase):
    def setUp(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)
        # Outreach table first, so initialize_database can add its send_after column.
        db.initialize_outreach_table(TEST_DB)
        db.initialize_database(TEST_DB)
        # Nothing in this test may ever send a real email.
        no_send = patch(
            "sequence_dispatcher.deliver_prospect_email",
            side_effect=AssertionError("real send attempted"),
        )
        no_send.start()
        self.addCleanup(no_send.stop)
        # Follow-ups are off by default; the chain tests below opt in.
        flag = patch.dict(os.environ, {"FOLLOWUPS_ENABLED": "true"})
        flag.start()
        self.addCleanup(flag.stop)
        self.pid = db.add_prospect(
            name="Sam Lee", company="Acme Data", email="sam@example.com",
            status="qualified", db_path=TEST_DB,
        )
        # Pipeline output: the AI draft is step 1 and the prospect is enrolled.
        oid = db.save_outreach(self.pid, "Acme Data analytics team", "hello", db_path=TEST_DB)
        db.tag_outreach_sequence_step(oid, SEQ, 1, db_path=TEST_DB)
        db.ensure_sequence_enrollment(self.pid, sequence_name=SEQ, db_path=TEST_DB)
        self.enrolled = date.today()

    def tearDown(self):
        gc.collect()
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)

    def _run(self, days_later):
        with patch("web_app._infer_timezone", return_value="UTC"):
            return run_multichannel_sequence(
                dry_run=False, db_path=TEST_DB, sequence_name=SEQ,
                today=self.enrolled + timedelta(days=days_later),
            )

    def _send_row(self, row):
        """What web_app._send_scheduled_outreach does after a successful send."""
        with sqlite3.connect(TEST_DB) as conn:
            conn.execute("UPDATE outreach SET status='sent', sent_at=datetime('now') WHERE id=?", (row["id"],))
        db.update_status(self.pid, "contacted", db_path=TEST_DB)
        record_email_step_sent(row, db_path=TEST_DB)

    def test_nothing_is_queued_before_the_first_email_is_sent(self):
        self.assertEqual(self._run(0), [])          # prospect not active yet
        db.update_status(self.pid, "in_sequence", db_path=TEST_DB)
        self._run(0)
        self.assertEqual(len(_rows(self.pid)), 1)   # step 1 already exists: no duplicate

    def test_full_chain_and_no_duplicates(self):
        first = _rows(self.pid)[0]
        self._send_row(first)

        self._run(2)                                # too early for follow-up 1
        self.assertEqual(len(_rows(self.pid)), 1)

        self._run(5)                                # follow-up 1 due
        rows = _rows(self.pid)
        self.assertEqual(len(rows), 2)
        self.assertEqual((rows[1]["sequence_step"], rows[1]["sequence_name"]), (2, SEQ))
        self.assertTrue(rows[1]["send_after"])

        self._run(6)                                # daily run repeats: still one row
        self.assertEqual(len(_rows(self.pid)), 2)

        self._send_row(_rows(self.pid)[1])
        self._run(12)                               # follow-up 2 due
        rows = _rows(self.pid)
        self.assertEqual([r["sequence_step"] for r in rows], [1, 2, 3])

        self._send_row(rows[2])
        self._run(40)                               # sequence finished
        self.assertEqual(len(_rows(self.pid)), 3)

    def test_no_follow_ups_by_default(self):
        with patch.dict(os.environ, {"FOLLOWUPS_ENABLED": "false"}):
            self._send_row(_rows(self.pid)[0])
            for day in (5, 12, 40):
                self._run(day)
            self.assertEqual(len(_rows(self.pid)), 1)

    def test_reply_stops_follow_ups(self):
        self._send_row(_rows(self.pid)[0])
        db.update_status(self.pid, "replied", db_path=TEST_DB)
        self._run(5)
        self.assertEqual(len(_rows(self.pid)), 1)

    def test_step_event_only_written_for_tagged_rows(self):
        untagged = {"prospect_id": self.pid, "subject": "x"}
        self.assertFalse(record_email_step_sent(untagged, db_path=TEST_DB))


if __name__ == "__main__":
    unittest.main()
