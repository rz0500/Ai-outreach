"""job_leads: role/agency filtering, name matching, employer aggregation and discovery (all HTTP mocked)."""

import gc
import os
import unittest
from unittest.mock import MagicMock, patch

import database as db
import job_leads as jl

TEST_DB = "test_job_leads.db"


def _job(title, company, location="London", url="https://adzuna.example/1"):
    return {"title": title, "company": {"display_name": company},
            "location": {"display_name": location}, "redirect_url": url}


class TestFilters(unittest.TestCase):
    def test_relevant_titles(self):
        for title in ("Graduate Data Analyst", "Junior Business Analyst", "Product Analyst",
                      "Commercial Analyst", "Insights Analyst", "BI Analyst", "Revenue Operations Analyst",
                      "Financial Analyst", "Reporting Analyst"):
            self.assertTrue(jl.is_relevant_title(title), title)

    def test_irrelevant_titles(self):
        for title in ("Junior Cyber Security Analyst", "Technical Support Analyst", "Service Desk Analyst",
                      "ATM Test Analyst", "Data Engineer", "Head Chef", "Claims Analyst", "Payroll Analyst"):
            self.assertFalse(jl.is_relevant_title(title), title)

    def test_agencies_and_boards_are_dropped(self):
        for name in ("Hays Specialist Recruitment Limited", "Harnham - Data & Analytics Recruitment", "Reed",
                     "Hackajob Ltd", "Meraki Talent Limited", "Osborne Appointments", "eFinancialCareers",
                     "Robert Walters", "Adecco", "Oliver James", "Selby Jennings", "Spectrum IT",
                     "Harvey Nash"):
            self.assertTrue(jl.is_agency(name), name)

    def test_real_employers_are_kept(self):
        for name in ("Motability Operations", "Holcim UK", "COVEA INSURANCE SERVICES LIMITED", "Monzo Bank"):
            self.assertFalse(jl.is_agency(name), name)


class TestNames(unittest.TestCase):
    def test_matching_ignores_legal_words_and_case(self):
        self.assertTrue(jl.names_match("COVEA INSURANCE SERVICES LIMITED", "Covea Insurance"))
        self.assertTrue(jl.names_match("Motability Operations", "Motability Operations Group"))

    def test_different_companies_do_not_match(self):
        self.assertFalse(jl.names_match("Holcim UK", "Holcim Barbecue Supplies Ltd"))
        self.assertFalse(jl.names_match("Monzo Bank", "Barclays Bank"))
        self.assertFalse(jl.names_match("", "Acme"))

    def test_role_score_prefers_early_career_over_senior(self):
        self.assertGreater(jl.role_score("Graduate Data Analyst"), jl.role_score("Data Analyst"))
        self.assertGreater(jl.role_score("Data Analyst"), jl.role_score("Senior Data Analyst"))


class TestFindWebsite(unittest.TestCase):
    def _client(self, results, website="https://www.motability.co.uk"):
        client = MagicMock()
        client.places.return_value = {"results": results}
        client.place.return_value = {"result": {"name": "Motability Operations", "website": website}}
        return client

    def test_confident_match_returns_website(self):
        client = self._client([{"name": "Motability Operations", "place_id": "p1"}])
        self.assertEqual(jl.find_website(client, "Motability Operations Ltd", "London"),
                         ("Motability Operations", "https://www.motability.co.uk"))

    def test_wrong_business_is_rejected(self):
        client = self._client([{"name": "Bob's Motors", "place_id": "p1"}])
        self.assertEqual(jl.find_website(client, "Motability Operations", ""), ("", ""))
        client.place.assert_not_called()

    def test_job_board_website_is_rejected(self):
        client = self._client([{"name": "Motability Operations", "place_id": "p1"}], website="https://uk.linkedin.com/company/x")
        self.assertEqual(jl.find_website(client, "Motability Operations", ""), ("", ""))

    def test_business_google_files_as_an_employment_agency_is_rejected(self):
        client = self._client([{"name": "Motability Operations", "place_id": "p1",
                                "types": ["employment_agency", "establishment"]}])
        self.assertEqual(jl.find_website(client, "Motability Operations", ""), ("", ""))
        client.place.assert_not_called()

    def test_api_error_is_not_fatal(self):
        client = MagicMock()
        client.places.side_effect = RuntimeError("boom")
        self.assertEqual(jl.find_website(client, "Acme", ""), ("", ""))


class TestDiscover(unittest.TestCase):
    def setUp(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)
        self.state = os.path.splitext(os.path.abspath(TEST_DB))[0] + "_job_state.json"
        if os.path.exists(self.state):
            os.remove(self.state)
        db.initialize_database(TEST_DB)
        # No real network or model calls: the free lookups are stubbed to "found nothing".
        for target, value in (("job_leads.guess_website", ("", "")), ("company_size.screen_names", {})):
            patcher = patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self):
        gc.collect()
        for f in (TEST_DB, self.state):
            if os.path.exists(f):
                os.remove(f)

    def _maps(self, sites):
        """Fake Maps: company name -> website; a company with no entry has no match."""
        client = MagicMock()
        current = {}

        def places(query=None):
            for name, site in sites.items():
                if name.lower() in (query or "").lower():
                    current["site"] = site
                    return {"results": [{"name": name, "place_id": name}]}
            return {"results": []}

        client.places.side_effect = places
        client.place.side_effect = lambda pid, fields=None: {"result": {"name": pid, "website": sites[pid]}}
        return client

    def _run(self, jobs, sites, target=10, **kw):
        with patch.object(jl, "get_adzuna_credentials", return_value=("id", "key")), \
             patch.object(jl, "get_googlemaps_client", return_value=self._maps(sites)), \
             patch.object(jl, "_fetch_page", side_effect=lambda *a: jobs if a[3] == 1 else []):
            return jl.discover_job_leads(target, db_path=TEST_DB, **kw)

    def test_new_employers_are_inserted_with_a_hiring_signal(self):
        jobs = [_job("Graduate Data Analyst", "Acme Data"), _job("Senior Business Analyst", "Beta Analytics")]
        leads = self._run(jobs, {"Acme Data": "https://acmedata.io", "Beta Analytics": "https://beta.io"},
                          max_searches=1)
        self.assertEqual({l["company"] for l in leads}, {"Acme Data", "Beta Analytics"})
        acme = [l for l in leads if l["company"] == "Acme Data"][0]
        self.assertEqual(acme["status"], "qualified")
        stored = db.get_prospect_by_id(acme["id"], db_path=TEST_DB)
        self.assertEqual(stored["hiring_signal"], "Advertising: Graduate Data Analyst")
        self.assertIn("Graduate Data Analyst", stored["notes"])

    def test_agencies_irrelevant_titles_and_known_companies_are_skipped(self):
        db.add_prospect(name="Owner/Manager", company="Known Co", website="https://known.io", db_path=TEST_DB)
        jobs = [
            _job("Graduate Data Analyst", "Hays Specialist Recruitment Limited"),
            _job("Cyber Security Analyst", "Secure Co"),
            _job("Data Analyst", "Known Co"),
            _job("Data Analyst", "Fresh Co"),
        ]
        sites = {"Known Co": "https://known.io", "Secure Co": "https://secure.io", "Fresh Co": "https://fresh.io"}
        leads = self._run(jobs, sites, max_searches=1)
        self.assertEqual([l["company"] for l in leads], ["Fresh Co"])

    def test_one_role_per_employer_prefers_early_career(self):
        jobs = [_job("Senior Data Analyst", "Acme Data"), _job("Graduate Data Analyst", "Acme Data")]
        leads = self._run(jobs, {"Acme Data": "https://acmedata.io"}, max_searches=1)
        self.assertEqual(len(leads), 1)
        stored = db.get_prospect_by_id(leads[0]["id"], db_path=TEST_DB)
        self.assertEqual(stored["hiring_signal"], "Advertising: Graduate Data Analyst")

    def test_employer_without_a_findable_website_is_dropped(self):
        leads = self._run([_job("Data Analyst", "Mystery Ltd")], {}, max_searches=1)
        self.assertEqual(leads, [])

    def test_same_website_is_not_added_twice(self):
        db.add_prospect(name="x", company="Old Name", website="https://www.acmedata.io/about", db_path=TEST_DB)
        leads = self._run([_job("Data Analyst", "Acme Data")], {"Acme Data": "https://acmedata.io"}, max_searches=1)
        self.assertEqual(leads, [])

    def test_target_caps_the_result(self):
        jobs = [_job("Data Analyst", f"Company{i} Data") for i in range(6)]
        sites = {f"Company{i} Data": f"https://c{i}.io" for i in range(6)}
        self.assertEqual(len(self._run(jobs, sites, target=3, max_searches=1)), 3)

    def test_rotation_advances_and_pages_progress(self):
        with patch.object(jl, "get_adzuna_credentials", return_value=("id", "key")), \
             patch.object(jl, "get_googlemaps_client", return_value=self._maps({})), \
             patch.object(jl, "_fetch_page", return_value=[]) as fetch:
            jl.discover_job_leads(5, db_path=TEST_DB, max_searches=2)
        searches = [call.args[2] for call in fetch.call_args_list]
        self.assertEqual(searches, [jl.SEARCHES[0], jl.SEARCHES[1]])
        self.assertEqual(jl._load_state(TEST_DB)["search"], 2)

    def test_full_pages_advance_the_page_pointer(self):
        full_page = [_job("Data Analyst", f"Z{i} Data") for i in range(50)]
        with patch.object(jl, "get_adzuna_credentials", return_value=("id", "key")), \
             patch.object(jl, "get_googlemaps_client", return_value=self._maps({})), \
             patch.object(jl, "_fetch_page", return_value=full_page):
            jl.discover_job_leads(5, db_path=TEST_DB, max_searches=1)   # no website matches, so nothing is inserted
        self.assertEqual(jl._load_state(TEST_DB)["pages"]["0"], 1 + jl._PAGES_PER_SEARCH)

    def test_missing_credentials_or_maps_key_returns_nothing(self):
        with patch.object(jl, "get_adzuna_credentials", return_value=("", "")):
            self.assertEqual(jl.discover_job_leads(5, db_path=TEST_DB), [])
        with patch.object(jl, "get_adzuna_credentials", return_value=("id", "key")), \
             patch.object(jl, "get_googlemaps_client", return_value=None):
            self.assertEqual(jl.discover_job_leads(5, db_path=TEST_DB), [])


class TestFreeLookups(unittest.TestCase):
    def _resp(self, url, text, status=200):
        r = MagicMock()
        r.status_code, r.url, r.text = status, url, text
        return r

    def test_guess_website_accepts_a_domain_whose_title_matches(self):
        page = "<html><head><title>Vanrath | Technology recruitment</title></head></html>"
        with patch.object(jl.requests, "get", return_value=self._resp("https://vanrath.com/", page)):
            self.assertEqual(jl.guess_website("Vanrath Ltd"), ("Vanrath Ltd", "https://vanrath.com/"))

    def test_guess_website_rejects_a_page_for_a_different_company(self):
        page = "<html><head><title>Totally Different Co</title></head></html>"
        with patch.object(jl.requests, "get", return_value=self._resp("https://vanrath.com/", page)):
            self.assertEqual(jl.guess_website("Vanrath Ltd"), ("", ""))

    def test_short_one_word_names_are_not_guessed(self):
        page = "<html><head><title>CPS Systems</title></head></html>"
        with patch.object(jl.requests, "get", return_value=self._resp("https://cps.com/", page)):
            self.assertEqual(jl.guess_website("CPS Group Limited"), ("", ""))

    def test_guess_website_gives_up_when_nothing_loads(self):
        with patch.object(jl.requests, "get", side_effect=jl.requests.RequestException):
            self.assertEqual(jl.guess_website("Vanrath"), ("", ""))


class TestNameScreen(unittest.TestCase):
    def setUp(self):
        for f in (TEST_DB,):
            if os.path.exists(f):
                os.remove(f)
        self.state = os.path.splitext(os.path.abspath(TEST_DB))[0] + "_job_state.json"
        db.initialize_database(TEST_DB)

    def tearDown(self):
        gc.collect()
        for f in (TEST_DB, self.state):
            if os.path.exists(f):
                os.remove(f)

    def test_big_corporates_are_dropped_before_any_website_lookup(self):
        jobs = [_job("Data Analyst", "Capital One"), _job("Data Analyst", "Small Data Co")]
        maps = MagicMock()
        with patch.object(jl, "get_adzuna_credentials", return_value=("id", "key")),              patch.object(jl, "get_googlemaps_client", return_value=maps),              patch("company_size.screen_names", return_value={"Capital One": "out"}),              patch.object(jl, "guess_website", return_value=("Small Data Co", "https://smalldata.io")),              patch.object(jl, "_fetch_page", side_effect=lambda *a: jobs if a[3] == 1 else []):
            leads = jl.discover_job_leads(10, db_path=TEST_DB, max_searches=1)
        self.assertEqual([l["company"] for l in leads], ["Small Data Co"])
        maps.places.assert_not_called()


if __name__ == "__main__":
    unittest.main()
