"""Hiring-signal detection on careers pages, and companies with a signal being sent first."""

import gc
import os
import unittest
from unittest.mock import patch

import contact_finder as cf
import database as db

TEST_DB = "test_site_intel.db"


def _crawl(pages):
    with patch.object(cf, "_fetch", side_effect=lambda u: pages.get(u, "")):
        return cf.find_site_intel("acme.com")


class TestHiringSignal(unittest.TestCase):
    def test_analyst_roles_on_careers_page_are_found(self):
        intel = _crawl({
            "https://acme.com": '<a href="/careers">Careers</a> info@acme.com',
            "https://acme.com/careers": "<h2>Junior Data Analyst</h2><h2>Graduate Business Analyst</h2><h2>Head Chef</h2>",
        })
        self.assertEqual(intel["hiring_roles"], ["Junior Data Analyst", "Graduate Business Analyst"])
        self.assertEqual(intel["contacts"][0]["email"], "info@acme.com")

    def test_graduate_programme_wording_is_flagged(self):
        intel = _crawl({
            "https://acme.com": '<a href="/careers">Careers</a>',
            "https://acme.com/careers": "Our graduate scheme opens each September.",
        })
        self.assertTrue(intel["graduate_friendly"])
        self.assertEqual(cf.describe_hiring(intel), "Careers page mentions a graduate / early-careers programme")

    def test_analyst_talk_on_non_careers_pages_is_not_a_vacancy(self):
        intel = _crawl({
            "https://acme.com": "We employ a data analyst and publish an analyst report",
            "https://acme.com/about": "Our business analyst team is great",
        })
        self.assertEqual(intel["hiring_roles"], [])
        self.assertFalse(intel["graduate_friendly"])
        self.assertEqual(cf.describe_hiring(intel), "")

    def test_roles_are_deduped_and_capped(self):
        titles = "".join(f"<p>{t} Data Analyst</p>" for t in ("Junior", "Junior", "Senior", "Lead", "Associate", "Graduate"))
        intel = _crawl({
            "https://acme.com": '<a href="/jobs">Jobs</a>',
            "https://acme.com/jobs": titles,
        })
        self.assertEqual(len(intel["hiring_roles"]), 4)
        self.assertEqual(len({r.lower() for r in intel["hiring_roles"]}), 4)

    def test_describe_hiring_lists_roles(self):
        text = cf.describe_hiring({"hiring_roles": ["Data Analyst", "Business Analyst"], "graduate_friendly": True})
        self.assertEqual(text, "Careers page lists: Data Analyst, Business Analyst")

    def test_old_helpers_still_work(self):
        with patch.object(cf, "_fetch", side_effect=lambda u: {"https://acme.com": "jobs@acme.com"}.get(u, "")):
            self.assertEqual(cf.find_best_contact("acme.com")["email"], "jobs@acme.com")


class TestSendPriority(unittest.TestCase):
    def setUp(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)
        db.initialize_outreach_table(TEST_DB)
        db.initialize_database(TEST_DB)

    def tearDown(self):
        gc.collect()
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)

    def _queue(self, company, send_after, hiring=""):
        pid = db.add_prospect(name="X", company=company, email=f"a@{company.lower()}.example.com",
                              status="qualified", db_path=TEST_DB)
        if hiring:
            db.update_enrichment_fields(pid, {"hiring_signal": hiring}, db_path=TEST_DB)
        oid = db.save_outreach(pid, "s", "b", db_path=TEST_DB)
        import sqlite3
        with sqlite3.connect(TEST_DB) as conn:
            conn.execute("UPDATE outreach SET send_after=? WHERE id=?", (send_after, oid))
        return oid

    def test_companies_with_a_hiring_signal_are_sent_first(self):
        early_no_signal = self._queue("Early", "2020-01-01 08:00:00")
        late_with_signal = self._queue("Late", "2020-01-02 08:00:00", hiring="Careers page lists: Data Analyst")
        due = [row["id"] for row in db.get_pending_sends(db_path=TEST_DB)]
        self.assertEqual(due, [late_with_signal, early_no_signal])

    def test_early_career_openings_go_before_other_signals(self):
        none_ = self._queue("None", "2020-01-01 08:00:00")
        senior = self._queue("Senior", "2020-01-02 08:00:00", hiring="Advertising: Senior Data Analyst")
        grad = self._queue("Grad", "2020-01-03 08:00:00", hiring="Advertising: Graduate Data Analyst")
        due = [row["id"] for row in db.get_pending_sends(db_path=TEST_DB)]
        self.assertEqual(due, [grad, senior, none_])

    def test_send_time_still_orders_within_each_group(self):
        a = self._queue("A", "2020-01-02 08:00:00")
        b = self._queue("B", "2020-01-01 08:00:00")
        due = [row["id"] for row in db.get_pending_sends(db_path=TEST_DB)]
        self.assertEqual(due, [b, a])


if __name__ == "__main__":
    unittest.main()
