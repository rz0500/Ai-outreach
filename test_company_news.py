"""company_news: only facts whose quote really appears on the company's pages are kept."""

import os
import unittest
from datetime import date
from unittest.mock import MagicMock, patch

import ai_engine
import company_news as cn

PAGE = "<html><body><h1>News</h1><p>In March 2026 Acme Data launched its Insight Hub product for retailers.</p>" + "<p>filler text</p>" * 30 + "</body></html>"


def _claude(text):
    client = MagicMock()
    client.messages.create.return_value = MagicMock(content=[MagicMock(text=text)])
    return patch("anthropic.Anthropic", return_value=client)


class TestExtract(unittest.TestCase):
    SOURCE = "In March 2026 Acme Data launched its Insight Hub product for retailers. More text."

    def test_fact_with_verbatim_quote_is_kept(self):
        reply = '{"facts": [{"fact": "Acme launched Insight Hub.", "evidence": "Acme Data launched its Insight Hub product for retailers"}]}'
        with _claude(reply):
            self.assertEqual(cn._extract("Acme", self.SOURCE, date(2026, 6, 1)), ["Acme launched Insight Hub."])

    def test_invented_quote_is_dropped(self):
        reply = '{"facts": [{"fact": "Acme raised 50m.", "evidence": "Acme Data raised fifty million pounds in a Series B"}]}'
        with _claude(reply):
            self.assertEqual(cn._extract("Acme", self.SOURCE, date(2026, 6, 1)), [])

    def test_garbage_reply_gives_nothing(self):
        with _claude("sorry, no"):
            self.assertEqual(cn._extract("Acme", self.SOURCE, date(2026, 6, 1)), [])


class TestFindRecentFacts(unittest.TestCase):
    def test_no_api_key_means_no_facts(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            self.assertEqual(cn.find_recent_facts("https://acme.io", "Acme"), "")

    def test_facts_are_joined_and_failures_never_raise(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k"}), \
             patch.object(cn, "_fetch", return_value=PAGE), \
             patch.object(cn, "_extract", return_value=["Fact one.", "Fact two."]):
            self.assertEqual(cn.find_recent_facts("https://acme.io", "Acme"), "Fact one. | Fact two.")
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k"}), \
             patch.object(cn, "_fetch", return_value=PAGE), \
             patch.object(cn, "_extract", side_effect=RuntimeError("boom")):
            self.assertEqual(cn.find_recent_facts("https://acme.io", "Acme"), "")

    def test_unreachable_site_gives_nothing(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k"}), patch.object(cn, "_fetch", return_value=""):
            self.assertEqual(cn.find_recent_facts("https://acme.io", "Acme"), "")

    def test_news_links_on_the_same_site_are_found_first(self):
        html = '<a href="/our-news">Latest news</a><a href="https://other.com/blog">x</a><a href="/careers">Jobs</a>'
        pages = cn._news_pages("https://acme.io", html)
        self.assertEqual(pages[0], "https://acme.io/our-news")
        self.assertNotIn("https://other.com/blog", pages)


class TestEmailPieces(unittest.TestCase):
    def test_recent_facts_reach_the_prompt(self):
        block = ai_engine._build_enrichment_block({"company": "Acme", "recent_facts": "Acme launched Insight Hub."})
        self.assertIn("Acme launched Insight Hub.", block)

    def test_missing_signoff_is_added_and_present_one_is_kept(self):
        fixed = ai_engine._ensure_signoff("Hi there,\n\nWould you be up for a coffee?")
        self.assertIn("University of Westminster", fixed)
        self.assertEqual(ai_engine._ensure_signoff(fixed), fixed)


if __name__ == "__main__":
    unittest.main()
