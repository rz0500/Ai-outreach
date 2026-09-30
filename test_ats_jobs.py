"""ATS job-board reader: board detection, per-provider parsing, filtering and crawl integration."""

import unittest
from unittest.mock import patch

import ats_jobs
import contact_finder as cf


class TestFindBoards(unittest.TestCase):
    def test_detects_each_provider(self):
        html = """
        <a href="https://boards.greenhouse.io/acme">Jobs</a>
        <a href="https://jobs.lever.co/acme-lever/">Jobs</a>
        <a href="https://jobs.ashbyhq.com/acme-ashby">Jobs</a>
        <a href="https://apply.workable.com/acme-workable/">Jobs</a>
        <a href="https://jobs.smartrecruiters.com/AcmeSR">Jobs</a>
        """
        self.assertEqual(
            ats_jobs.find_boards(html),
            [("greenhouse", "acme"), ("lever", "acme-lever"), ("ashby", "acme-ashby"),
             ("workable", "acme-workable"), ("smartrecruiters", "AcmeSR")],
        )

    def test_greenhouse_embed_and_new_domain(self):
        html = '<iframe src="https://boards.greenhouse.io/embed/job_board?for=acme"></iframe> https://job-boards.greenhouse.io/other'
        self.assertEqual(ats_jobs.find_boards(html), [("greenhouse", "acme"), ("greenhouse", "other")])

    def test_no_boards_and_no_false_slugs(self):
        self.assertEqual(ats_jobs.find_boards("<p>No jobs here</p>"), [])
        self.assertEqual(ats_jobs.find_boards("https://boards.greenhouse.io/embed/"), [])

    def test_duplicates_are_collapsed(self):
        html = "https://jobs.lever.co/acme https://jobs.lever.co/acme"
        self.assertEqual(ats_jobs.find_boards(html), [("lever", "acme")])


class TestBoardTitles(unittest.TestCase):
    def _titles(self, provider, payload):
        with patch.object(ats_jobs, "_get_json", return_value=payload):
            return ats_jobs.board_titles(provider, "x")

    def test_each_provider_shape(self):
        self.assertEqual(self._titles("greenhouse", {"jobs": [{"title": "Data Analyst"}]}), ["Data Analyst"])
        self.assertEqual(self._titles("lever", [{"text": "BI Analyst"}]), ["BI Analyst"])
        self.assertEqual(self._titles("ashby", {"jobs": [{"title": "Analytics Lead"}]}), ["Analytics Lead"])
        self.assertEqual(self._titles("workable", {"jobs": [{"title": "Graduate Analyst"}]}), ["Graduate Analyst"])
        self.assertEqual(self._titles("smartrecruiters", {"content": [{"name": "Insights Analyst"}]}), ["Insights Analyst"])

    def test_bad_or_missing_payloads_give_empty_lists(self):
        for provider in ("greenhouse", "lever", "ashby", "workable", "smartrecruiters", "unknown"):
            self.assertEqual(self._titles(provider, None), [])
        self.assertEqual(self._titles("greenhouse", ["not", "a", "dict"]), [])
        self.assertEqual(self._titles("lever", {"not": "a list"}), [])


class TestAnalystJobs(unittest.TestCase):
    def test_keeps_only_analyst_type_titles_deduped_and_capped(self):
        titles = ["Senior Data Analyst", "Head Chef", "senior data analyst", "Graduate Programme 2027",
                  "Business Intelligence Developer", "Sales Executive", "Analytics Engineer", "Insights Analyst"]
        with patch.object(ats_jobs, "board_titles", return_value=titles):
            found = ats_jobs.analyst_jobs(["https://jobs.lever.co/acme"], limit=4)
        self.assertEqual(found, ["Senior Data Analyst", "Graduate Programme 2027",
                                 "Business Intelligence Developer", "Analytics Engineer"])

    def test_only_first_two_boards_are_read(self):
        html = " ".join(f"https://jobs.lever.co/co{i}" for i in range(5))
        with patch.object(ats_jobs, "board_titles", return_value=[]) as titles:
            ats_jobs.analyst_jobs([html])
        self.assertEqual(titles.call_count, 2)

    def test_no_boards_means_no_requests(self):
        with patch.object(ats_jobs, "_get_json") as get:
            self.assertEqual(ats_jobs.analyst_jobs(["<p>hello</p>"]), [])
        get.assert_not_called()


class TestCrawlIntegration(unittest.TestCase):
    def test_board_roles_appear_first_in_site_intel(self):
        pages = {
            "https://acme.com": '<a href="/careers">Careers</a> info@acme.com',
            "https://acme.com/careers": '<a href="https://boards.greenhouse.io/acme">Open roles</a> <p>Junior Data Analyst</p>',
        }
        with patch.object(cf, "_fetch", side_effect=lambda u: pages.get(u, "")), \
             patch.object(ats_jobs, "board_titles", return_value=["Analytics Manager", "Chef"]):
            intel = cf.find_site_intel("acme.com")
        self.assertEqual(intel["hiring_roles"], ["Analytics Manager", "Junior Data Analyst"])
        self.assertEqual(cf.describe_hiring(intel), "Careers page lists: Analytics Manager, Junior Data Analyst")


if __name__ == "__main__":
    unittest.main()
