"""ai_engine._humanise strips em/en dashes and bare greetings from model output."""

import unittest

import ai_engine


class TestHumanise(unittest.TestCase):
    def test_em_and_en_dashes_become_commas(self):
        self.assertEqual(ai_engine._humanise("data — and AI"), "data, and AI")
        self.assertEqual(ai_engine._humanise("a–b"), "a, b")
        self.assertNotIn("—", ai_engine._humanise("x—y"))

    def test_bare_greeting_gets_there(self):
        self.assertEqual(ai_engine._humanise("Hi,\n\nText"), "Hi there,\n\nText")

    def test_named_greeting_is_untouched(self):
        self.assertEqual(ai_engine._humanise("Hi Priya,\n\nText"), "Hi Priya,\n\nText")


if __name__ == "__main__":
    unittest.main()


class TestGreeting(unittest.TestCase):
    def test_named_contact_is_greeted_by_first_name(self):
        out = ai_engine._fix_greeting("Hello,\n\nBody", {"name": "Priya Shah", "company": "Ledgerly"})
        self.assertEqual(out, "Hi Priya,\n\nBody")

    def test_placeholder_name_gets_company_team(self):
        out = ai_engine._fix_greeting("Hi there,\n\nBody", {"name": "Owner/Manager", "company": "Monzo Bank Ltd"})
        self.assertTrue(out.startswith("Hi Monzo"), out)
        self.assertIn(" team,", out.split("\n")[0])

    def test_missing_greeting_is_added(self):
        out = ai_engine._fix_greeting("I saw the opening.", {"name": "Sam Lee", "company": "Acme"})
        self.assertEqual(out, "Hi Sam,\n\nI saw the opening.")
