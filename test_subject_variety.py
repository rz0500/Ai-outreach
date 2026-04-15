import unittest

from outreach import analyze_company, choose_primary_angle, generate_email


def _prospect(**overrides):
    base = {
        "name": "Jane Doe",
        "company": "Acme Corp",
        "niche": "CRM implementation for mid-market healthcare teams",
        "icp": "Heads of Operations at 50-200 person healthcare companies",
        "website_headline": "CRM implementation for healthcare teams that need faster rollout",
        "product_feature": "migration playbooks for regulated healthcare workflows",
        "hiring_signal": "",
        "linkedin_activity": "",
        "competitors": "",
        "outbound_status": "no_outbound",
        "ad_status": "",
        "notes": "",
    }
    base.update(overrides)
    return base


class TestSubjectVariety(unittest.TestCase):
    def test_hiring_signal_subject(self):
        email = generate_email(_prospect(hiring_signal="hiring SDRs in Austin"))
        self.assertEqual(email["subject"], "Acme Corp hiring")

    def test_competitor_subject(self):
        email = generate_email(_prospect(competitors="Huble"))
        self.assertEqual(email["subject"], "Acme Corp and Huble")

    def test_product_feature_subject(self):
        email = generate_email(
            _prospect(
                outbound_status="active_outbound",
                competitors="",
                product_feature="migration playbooks",
            )
        )
        self.assertEqual(email["subject"], "Acme Corp migration playbooks")

    def test_outbound_gap_subject(self):
        email = generate_email(
            _prospect(
                product_feature="",
                competitors="",
                icp="",
                website_headline="",
                niche="",
                outbound_status="no_outbound",
            )
        )
        self.assertEqual(email["subject"], "Acme Corp pipeline")

    def test_angle_selection_still_matches_subject_logic(self):
        analysis = analyze_company(_prospect(hiring_signal="hiring SDRs in Austin"))
        self.assertEqual(choose_primary_angle(analysis), "hiring signal")


if __name__ == "__main__":
    unittest.main(verbosity=2)
