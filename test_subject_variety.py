import unittest

from outreach import analyze_company, choose_primary_angle, generate_email

STALE_AGENCY_WORDS = ("pipeline", "outbound", "demand", "buyers")


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
        email = generate_email(_prospect(hiring_signal="hiring analysts in Austin"))
        self.assertEqual(email["subject"], "Acme Corp analytics team")

    def test_subject_names_the_company_and_has_no_agency_wording(self):
        cases = [
            _prospect(competitors="Huble"),
            _prospect(outbound_status="active_outbound", product_feature="migration playbooks"),
            _prospect(product_feature="", competitors="", icp="", website_headline="", niche=""),
        ]
        for prospect in cases:
            subject = generate_email(prospect)["subject"]
            self.assertIn("Acme Corp", subject)
            for word in STALE_AGENCY_WORDS:
                self.assertNotIn(word, subject.lower())

    def test_subject_is_stable_for_a_company_but_varies_across_companies(self):
        first = generate_email(_prospect())["subject"]
        again = generate_email(_prospect())["subject"]
        self.assertEqual(first, again)

        companies = ["Acme Corp", "Monzo", "Harbor Studio", "Vidi Corp", "Datatonic", "Finbourne"]
        subjects = {
            generate_email(_prospect(company=c))["subject"].replace(c, "X") for c in companies
        }
        self.assertGreater(len(subjects), 1)

    def test_angle_selection_still_matches_subject_logic(self):
        analysis = analyze_company(_prospect(hiring_signal="hiring SDRs in Austin"))
        self.assertEqual(choose_primary_angle(analysis), "hiring signal")


if __name__ == "__main__":
    unittest.main()
