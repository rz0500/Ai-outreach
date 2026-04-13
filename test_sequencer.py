"""
test_sequencer.py - Module 8 Tests
=====================================
Tests sequencer.py using an isolated SQLite database and unittest.mock.
No emails are ever sent.

Test groups:
  1. Database helpers  — get_prospects_in_sequence, update_sequence_progress
  2. Due-date logic    — _next_step correctly identifies due / not-due prospects
  3. get_due_prospects — integration across DB + due-date logic
  4. run_sequence      — dry_run output, live send path (mocked), error paths

Run with:
    python test_sequencer.py
"""

import gc
import os
import unittest
from datetime import date, timedelta
from unittest.mock import patch, MagicMock

from database import (
    initialize_database,
    add_prospect,
    get_prospects_in_sequence,
    update_sequence_progress,
    update_status,
)
from sequencer import _next_step, get_due_prospects, run_sequence, SEQUENCE

TEST_DB = "test_sequencer.db"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_prospect(**overrides) -> dict:
    """Return a minimal prospect dict, with optional field overrides."""
    base = {
        "id": 1,
        "name": "Jane Doe",
        "company": "Acme Corp",
        "email": "jane@acme.com",
        "notes": "",
        "sequence_step": 0,
        "last_contacted_date": None,
        "status": "in_sequence",
        "lead_score": 75,
    }
    base.update(overrides)
    return base


def _seed(db_path: str, **kwargs) -> int:
    """Add a prospect with in_sequence status and return its ID."""
    defaults = dict(
        name="Jane Doe", company="Acme Corp",
        email="jane@acme.com", status="in_sequence",
    )
    defaults.update(kwargs)
    return add_prospect(**defaults, db_path=db_path)


# ---------------------------------------------------------------------------
# 1. Database helpers
# ---------------------------------------------------------------------------

class TestDatabaseHelpers(unittest.TestCase):

    def setUp(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)
        initialize_database(TEST_DB)

    def tearDown(self):
        gc.collect()
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)

    def test_get_prospects_in_sequence_returns_only_in_sequence(self):
        _seed(TEST_DB, name="Alice", email="alice@a.com", status="in_sequence")
        add_prospect(name="Bob", company="Corp", email="bob@b.com",
                     status="new", db_path=TEST_DB)

        results = get_prospects_in_sequence(TEST_DB)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["name"], "Alice")

    def test_get_prospects_in_sequence_empty(self):
        self.assertEqual(get_prospects_in_sequence(TEST_DB), [])

    def test_update_sequence_progress_writes_step_and_date(self):
        pid = _seed(TEST_DB)
        today = date.today().isoformat()

        ok = update_sequence_progress(pid, 1, today, TEST_DB)

        self.assertTrue(ok)
        prospects = get_prospects_in_sequence(TEST_DB)
        self.assertEqual(prospects[0]["sequence_step"], 1)
        self.assertEqual(prospects[0]["last_contacted_date"], today)

    def test_update_sequence_progress_returns_false_for_missing_id(self):
        ok = update_sequence_progress(9999, 1, date.today().isoformat(), TEST_DB)
        self.assertFalse(ok)


# ---------------------------------------------------------------------------
# 2. Due-date logic (_next_step)
# ---------------------------------------------------------------------------

class TestNextStep(unittest.TestCase):

    def test_step1_due_when_never_contacted(self):
        """A fresh enrolment (step=0, no last date) is due for step 1 immediately."""
        prospect = _make_prospect(sequence_step=0, last_contacted_date=None)
        result = _next_step(prospect)
        self.assertIsNotNone(result)
        self.assertEqual(result["step"], 1)

    def test_step2_due_after_3_days(self):
        three_days_ago = (date.today() - timedelta(days=3)).isoformat()
        prospect = _make_prospect(sequence_step=1, last_contacted_date=three_days_ago)
        result = _next_step(prospect)
        self.assertIsNotNone(result)
        self.assertEqual(result["step"], 2)

    def test_step2_not_due_after_2_days(self):
        two_days_ago = (date.today() - timedelta(days=2)).isoformat()
        prospect = _make_prospect(sequence_step=1, last_contacted_date=two_days_ago)
        result = _next_step(prospect)
        self.assertIsNone(result)

    def test_step3_due_after_7_days(self):
        seven_days_ago = (date.today() - timedelta(days=7)).isoformat()
        prospect = _make_prospect(sequence_step=2, last_contacted_date=seven_days_ago)
        result = _next_step(prospect)
        self.assertIsNotNone(result)
        self.assertEqual(result["step"], 3)

    def test_step3_not_due_after_6_days(self):
        six_days_ago = (date.today() - timedelta(days=6)).isoformat()
        prospect = _make_prospect(sequence_step=2, last_contacted_date=six_days_ago)
        result = _next_step(prospect)
        self.assertIsNone(result)

    def test_no_step_after_sequence_complete(self):
        """A prospect who has completed all steps has no next step."""
        seven_days_ago = (date.today() - timedelta(days=7)).isoformat()
        prospect = _make_prospect(
            sequence_step=len(SEQUENCE),
            last_contacted_date=seven_days_ago,
        )
        result = _next_step(prospect)
        self.assertIsNone(result)

    def test_step1_due_when_enrolled_today(self):
        """Day-0 step is always due, even if enrolled this moment."""
        prospect = _make_prospect(sequence_step=0, last_contacted_date=date.today().isoformat())
        result = _next_step(prospect)
        self.assertIsNotNone(result)
        self.assertEqual(result["step"], 1)


# ---------------------------------------------------------------------------
# 3. get_due_prospects
# ---------------------------------------------------------------------------

class TestGetDueProspects(unittest.TestCase):

    def setUp(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)
        initialize_database(TEST_DB)

    def tearDown(self):
        gc.collect()
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)

    def test_returns_prospect_due_for_step1(self):
        _seed(TEST_DB)
        due = get_due_prospects(TEST_DB)
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0]["next_step"]["step"], 1)

    def test_excludes_prospect_not_yet_due(self):
        pid = _seed(TEST_DB)
        update_sequence_progress(pid, 1, date.today().isoformat(), TEST_DB)
        # Step 2 requires 3 days — not due yet
        due = get_due_prospects(TEST_DB)
        self.assertEqual(due, [])

    def test_excludes_non_sequence_prospects(self):
        add_prospect(name="Bob", company="X", email="bob@x.com",
                     status="new", db_path=TEST_DB)
        due = get_due_prospects(TEST_DB)
        self.assertEqual(due, [])

    def test_returns_multiple_due_prospects(self):
        _seed(TEST_DB, name="Alice", email="alice@a.com")
        _seed(TEST_DB, name="Bob",   email="bob@b.com")
        due = get_due_prospects(TEST_DB)
        self.assertEqual(len(due), 2)


# ---------------------------------------------------------------------------
# 4. run_sequence
# ---------------------------------------------------------------------------

class TestRunSequence(unittest.TestCase):

    def setUp(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)
        initialize_database(TEST_DB)

    def tearDown(self):
        gc.collect()
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)

    def test_dry_run_returns_results_without_sending(self):
        _seed(TEST_DB)
        results = run_sequence(dry_run=True, db_path=TEST_DB)

        self.assertEqual(len(results), 1)
        self.assertFalse(results[0]["sent"])
        self.assertEqual(results[0]["step"], 1)

    def test_dry_run_does_not_update_database(self):
        pid = _seed(TEST_DB)
        run_sequence(dry_run=True, db_path=TEST_DB)

        prospects = get_prospects_in_sequence(TEST_DB)
        self.assertEqual(prospects[0]["sequence_step"], 0)  # unchanged

    def test_dry_run_returns_empty_when_nothing_due(self):
        results = run_sequence(dry_run=True, db_path=TEST_DB)
        self.assertEqual(results, [])

    @patch("sequencer.send_email", return_value=(True, ""))
    def test_live_run_sends_email_and_updates_db(self, mock_send):
        pid = _seed(TEST_DB)
        results = run_sequence(dry_run=False, db_path=TEST_DB)

        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["sent"])
        mock_send.assert_called_once()

        # DB should now show step=1 and today's date
        prospects = get_prospects_in_sequence(TEST_DB)
        self.assertEqual(prospects[0]["sequence_step"], 1)
        self.assertEqual(prospects[0]["last_contacted_date"], date.today().isoformat())

    @patch("sequencer.send_email", return_value=(False, "Auth failed"))
    def test_live_run_records_error_on_failed_send(self, mock_send):
        _seed(TEST_DB)
        results = run_sequence(dry_run=False, db_path=TEST_DB)

        self.assertFalse(results[0]["sent"])
        self.assertIn("Auth failed", results[0]["error"])

        # DB should NOT be updated on failure
        prospects = get_prospects_in_sequence(TEST_DB)
        self.assertEqual(prospects[0]["sequence_step"], 0)

    def test_live_run_skips_prospect_with_no_email(self):
        add_prospect(name="No Email", company="Corp",
                     email=None, status="in_sequence", db_path=TEST_DB)
        results = run_sequence(dry_run=False, db_path=TEST_DB)

        self.assertEqual(len(results), 1)
        self.assertFalse(results[0]["sent"])
        self.assertIn("No email", results[0]["error"])

    @patch("sequencer.send_email", return_value=(True, ""))
    def test_final_step_moves_status_to_contacted(self, mock_send):
        """After step 3 is sent, the prospect should exit the sequence."""
        seven_days_ago = (date.today() - timedelta(days=7)).isoformat()
        pid = _seed(TEST_DB)
        update_sequence_progress(pid, 2, seven_days_ago, TEST_DB)

        run_sequence(dry_run=False, db_path=TEST_DB)

        # Prospect should no longer appear in the sequence
        in_seq = get_prospects_in_sequence(TEST_DB)
        self.assertEqual(in_seq, [])


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sep = "=" * 58
    print(f"\n{sep}")
    print("  SEQUENCER - MODULE 8 TESTS")
    print(sep + "\n")
    unittest.main(verbosity=2)
