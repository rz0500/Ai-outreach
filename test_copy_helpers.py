"""Greeting, company-name display and company-mention checks used by outbound copy."""

import unittest

import outreach
import sequence_engine
from email_validator import _company_mentioned


class TestGreeting(unittest.TestCase):
    def test_placeholder_names_become_there(self):
        for name in ("Owner/Manager", "owner", "", "  ", "Team"):
            self.assertEqual(outreach._first_name(name), "there")
            self.assertEqual(sequence_engine._first_name(name), "there")

    def test_real_names_use_first_word(self):
        self.assertEqual(outreach._first_name("Supriya Dixit"), "Supriya")
        self.assertEqual(sequence_engine._first_name("Tom"), "Tom")


class TestCompanyDisplay(unittest.TestCase):
    def test_maps_noise_is_removed_from_email_and_subject(self):
        draft = outreach.generate_email({"name": "Owner/Manager", "company": "FintechOS HQ - London, UK"})
        self.assertIn("Hi there,", draft["body"])
        self.assertNotIn("London, UK", draft["body"])
        self.assertNotIn("London, UK", draft["subject"])
        self.assertIn("FintechOS", draft["body"])

    def test_follow_ups_use_clean_name(self):
        msg = sequence_engine.build_touchpoint_message(
            {"name": "Owner/Manager", "company": "London Data Consulting (LDC)"},
            {"message_type": "email_followup_1"},
        )
        self.assertNotIn("(LDC)", msg["subject"] + msg["body"])
        self.assertIn("London Data Consulting", msg["subject"])


class TestCompanyMention(unittest.TestCase):
    def test_shortened_brand_counts(self):
        self.assertTrue(_company_mentioned("traction fintech", "saw that traction is growing"))

    def test_generic_words_alone_do_not_count(self):
        self.assertFalse(_company_mentioned("fintech global", "the fintech space is growing"))

    def test_full_name_counts(self):
        self.assertTrue(_company_mentioned("fintech global", "fintech global is growing"))

    def test_unrelated_body_fails(self):
        self.assertFalse(_company_mentioned("acme corp", "a generic email"))


if __name__ == "__main__":
    unittest.main()
