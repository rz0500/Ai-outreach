"""
test_email_reasoning.py - Data-driven email reasoning tests
===========================================================
Verifies company analysis, angle selection, weak-data mode,
and internal quality scoring.
"""

import unittest
from unittest.mock import patch

from email_validator import score_internal_quality, validate_email
from outreach import analyze_company, choose_primary_angle, debug_email_reasoning, generate_email
from settings import DEFAULT_CALENDAR_LINK


def _prospect(**overrides) -> dict:
    base = {
        "name": "Jane Doe",
        "company": "Acme Corp",
        "niche": "CRM implementation for mid-market healthcare teams",
        "icp": "Heads of Operations at 50-200 person healthcare companies",
        "website_headline": "CRM implementation for healthcare teams that need faster rollout",
        "product_feature": "migration playbooks for regulated healthcare workflows",
        "hiring_signal": "hiring SDRs in Austin",
        "linkedin_activity": "",
        "competitors": "Huble",
        "outbound_status": "no_outbound",
        "ad_status": "",
        "notes": "Recent signal: hiring SDRs in Austin.",
    }
    base.update(overrides)
    return base


class TestEmailReasoning(unittest.TestCase):

    def test_company_analysis_extracts_structured_fields(self):
        analysis = analyze_company(_prospect())
        self.assertIn("CRM implementation", analysis["company_positioning"])
        self.assertIn("Heads of Operations", analysis["target_customer"])
        self.assertIn("migration playbooks", analysis["key_offer_or_feature"])
        self.assertIn("hiring SDRs", analysis["recent_signal"])
        self.assertEqual(analysis["relevant_competitor"], "Huble")

    def test_choose_primary_angle_prefers_hiring_signal(self):
        analysis = analyze_company(_prospect())
        self.assertEqual(choose_primary_angle(analysis), "hiring signal")

    def test_generate_email_returns_grounded_scores(self):
        result = generate_email(_prospect())
        self.assertIn("Acme Corp", result["body"])
        self.assertGreaterEqual(result["specificity"], 6)
        self.assertGreaterEqual(result["credibility"], 7)
        self.assertLessEqual(result["generic_risk"], 3)
        self.assertLessEqual(len(result["body"].split()), 140)

    def test_weak_data_mode_flags_enrichment_need(self):
        prospect = {"name": "Bob", "company": "Northstar Labs"}
        debug = debug_email_reasoning(prospect)
        self.assertTrue(debug["analysis"]["weak_data_mode"])
        self.assertTrue(debug["analysis"]["needs_enrichment"])
        self.assertIn("Northstar Labs", debug["email"]["body"])
        self.assertNotIn("I only have a limited read", debug["email"]["body"])

    def test_competitor_angle_selected_when_outbound_gap_is_explicit(self):
        prospect = _prospect(
            hiring_signal="",
            competitors="6sense",
            outbound_status="no_outbound",
        )
        analysis = analyze_company(prospect)
        self.assertEqual(choose_primary_angle(analysis), "competitor")

    def test_internal_quality_rewrite_flag_stays_false_for_grounded_email(self):
        debug = debug_email_reasoning(_prospect())
        validation = validate_email(debug["email"]["subject"], debug["email"]["body"], _prospect())
        score = score_internal_quality(
            debug["email"]["subject"],
            debug["email"]["body"],
            _prospect(),
            debug["analysis"],
            validation,
        )
        self.assertFalse(score.rewrite_required)

    def test_operator_style_avoids_soft_phrasing(self):
        body = generate_email(_prospect())["body"].lower()
        self.assertNotIn("noticed that", body)
        self.assertNotIn("happy to share", body)
        self.assertNotIn("might be", body)
        self.assertNotIn("could be", body)

    def test_operator_style_uses_fast_multiline_structure(self):
        with patch("outreach.get_calendar_link", return_value=DEFAULT_CALENDAR_LINK):
            email = generate_email(_prospect())
        body = email["body"]
        lines = [line.strip() for line in body.splitlines() if line.strip()]

        self.assertEqual(lines[0], "Hi Jane,")
        self.assertTrue(lines[1].startswith("Most SaaS teams"))
        self.assertIn("Acme Corp", body)
        self.assertIn(DEFAULT_CALENDAR_LINK, body)
        self.assertGreaterEqual(len(lines), 7)
        self.assertLessEqual(len(body.split()), 140)

    def test_weak_data_email_still_stays_confident(self):
        with patch("outreach.get_calendar_link", return_value=DEFAULT_CALENDAR_LINK):
            debug = debug_email_reasoning({"name": "Leah Morris", "company": "Harbor Studio"})
        body = debug["email"]["body"].lower()

        self.assertIn("harbor studio", body)
        self.assertIn("most b2b teams grow the same way", body)
        self.assertIn("it works — until it doesn't", body)
        self.assertNotIn("i only have a limited read", body)
        self.assertNotIn("if there is", body)
        self.assertIn(DEFAULT_CALENDAR_LINK.lower(), body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
