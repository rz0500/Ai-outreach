"""Tests for lead_discovery using a fake Google Maps client and a temp DB."""

import gc
import os
import unittest
from unittest.mock import patch

import database as db
import lead_discovery as ld

TEST_DB = "test_lead_discovery.db"


class FakeMaps:
    """Minimal googlemaps.Client stand-in: paged search + place details."""

    def __init__(self, pages, sites):
        self.pages = pages            # list of result lists, one per page
        self.sites = sites            # place_id -> website
        self.queries = []
        self.detail_calls = []

    def places(self, query=None, page_token=None):
        if query is not None:
            self.queries.append(query)
            page = 0
        else:
            page = int(page_token)
        results = self.pages[page] if page < len(self.pages) else []
        nxt = str(page + 1) if page + 1 < len(self.pages) else None
        out = {"results": results}
        if nxt:
            out["next_page_token"] = nxt
        return out

    def place(self, place_id, fields=None):
        self.detail_calls.append(place_id)
        return {"result": {"name": place_id.upper(), "website": self.sites.get(place_id, "")}}


def _p(pid, name=None, **extra):
    return {"place_id": pid, "name": name or pid.upper(), **extra}


class TestDiscovery(unittest.TestCase):
    def setUp(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)
        self.state = os.path.splitext(os.path.abspath(TEST_DB))[0] + "_discovery_state.json"
        if os.path.exists(self.state):
            os.remove(self.state)
        db.initialize_database(TEST_DB)
        p = patch("lead_discovery.time.sleep")
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        gc.collect()
        for f in (TEST_DB, self.state):
            if os.path.exists(f):
                os.remove(f)

    def _run(self, fake, **kw):
        with patch("lead_discovery.get_googlemaps_client", return_value=fake):
            return ld.discover_new_leads(db_path=TEST_DB, **kw)

    def test_returns_only_new_companies_and_stores_them(self):
        db.add_prospect(name="Owner/Manager", company="Old Co", website="https://oldco.com",
                        db_path=TEST_DB)
        fake = FakeMaps(
            [[_p("a"), _p("b"), _p("old", "Old Co")]],
            {"a": "https://a.com", "b": "https://www.b.io/about", "old": "https://oldco.com"},
        )
        leads = self._run(fake, target=10, max_searches=1)
        self.assertEqual({l["company"] for l in leads}, {"A", "B"})
        self.assertNotIn("old", fake.detail_calls)   # known by name: no paid details call
        self.assertTrue(all(l["status"] == "qualified" for l in leads))

    def test_same_domain_is_not_added_twice(self):
        fake = FakeMaps([[_p("a"), _p("b")]], {"a": "https://same.com", "b": "https://www.same.com/x"})
        leads = self._run(fake, target=10, max_searches=1)
        self.assertEqual(len(leads), 1)

    def test_skips_irrelevant_and_closed_and_no_website(self):
        fake = FakeMaps(
            [[
                _p("uni", "City University", types=["university"]),
                _p("cafe", types=["cafe"]),
                _p("shut", business_status="CLOSED_PERMANENTLY"),
                _p("nosite"),
                _p("good"),
            ]],
            {"uni": "https://u.ac.uk", "cafe": "https://c.com", "shut": "https://s.com", "good": "https://good.com"},
        )
        leads = self._run(fake, target=10, max_searches=1)
        self.assertEqual([l["company"] for l in leads], ["GOOD"])

    def test_reads_multiple_pages_and_stops_at_target(self):
        fake = FakeMaps(
            [[_p("a"), _p("b")], [_p("c"), _p("d")], [_p("e")]],
            {k: f"https://{k}.com" for k in "abcde"},
        )
        leads = self._run(fake, target=3, pages=3, max_searches=1)
        self.assertEqual(len(leads), 3)

    def test_rotation_moves_on_between_runs(self):
        fake = FakeMaps([[]], {})
        self._run(fake, target=5, max_searches=2)
        first = list(fake.queries)
        fake2 = FakeMaps([[]], {})
        self._run(fake2, target=5, max_searches=2)
        self.assertEqual(len(first), 2)
        self.assertEqual(len(fake2.queries), 2)
        self.assertNotEqual(first, fake2.queries)

    def test_no_api_key_returns_empty(self):
        with patch("lead_discovery.get_googlemaps_client", return_value=None):
            self.assertEqual(ld.discover_new_leads(5, db_path=TEST_DB), [])

    def test_next_page_token_not_ready_yet_is_retried(self):
        class SlowToken(FakeMaps):
            failures = 2

            def places(self, query=None, page_token=None):
                if page_token is not None and self.failures > 0:
                    self.failures -= 1
                    raise RuntimeError("INVALID_REQUEST")
                return super().places(query=query, page_token=page_token)

        fake = SlowToken([[_p("a")], [_p("b")]], {"a": "https://a.com", "b": "https://b.com"})
        leads = self._run(fake, target=10, pages=2, max_searches=1)
        self.assertEqual({l["company"] for l in leads}, {"A", "B"})

    def test_page_two_failure_keeps_page_one_results(self):
        class NeverReady(FakeMaps):
            def places(self, query=None, page_token=None):
                if page_token is not None:
                    raise RuntimeError("INVALID_REQUEST")
                return super().places(query=query, page_token=page_token)

        fake = NeverReady([[_p("a"), _p("b")], [_p("c")]], {k: f"https://{k}.com" for k in "abc"})
        leads = self._run(fake, target=10, pages=2, max_searches=1)
        self.assertEqual({l["company"] for l in leads}, {"A", "B"})

    def test_domain_of(self):
        self.assertEqual(ld.domain_of("https://www.Acme.com/a?b=1"), "acme.com")
        self.assertEqual(ld.domain_of("acme.co.uk"), "acme.co.uk")
        self.assertEqual(ld.domain_of(""), "")


if __name__ == "__main__":
    unittest.main()
