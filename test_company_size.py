"""company_size: band classification and verified-evidence handling (Claude mocked)."""

import os
import unittest
from unittest.mock import patch

import company_size as cs

PAGE = "<html><body>" + "<p>We are a team of 45 people building data tools for retailers.</p>" * 6 + "</body></html>"


class TestClassify(unittest.TestCase):
    def test_stated_inside_and_outside_band(self):
        self.assertEqual(cs.classify(45, 45, "stated"), "in")
        self.assertEqual(cs.classify(500, None, "stated"), "out")
        self.assertEqual(cs.classify(5, 8, "stated"), "out")
        self.assertEqual(cs.classify(420000, 420000, "stated"), "out")

    def test_open_ended_or_straddling_stated_sizes_are_unknown(self):
        self.assertEqual(cs.classify(100, None, "stated"), "unknown")
        self.assertEqual(cs.classify(200, 400, "stated"), "unknown")

    def test_team_page_count_only_rules_out_large_companies(self):
        self.assertEqual(cs.classify(12, None, "counted"), "unknown")
        self.assertEqual(cs.classify(400, None, "counted"), "out")

    def test_estimates_decide_on_the_midpoint(self):
        self.assertEqual(cs.classify(50, 150, "estimated"), "in")
        self.assertEqual(cs.classify(200, 400, "estimated"), "out")    # midpoint 300
        self.assertEqual(cs.classify(1, 10, "estimated"), "out")
        self.assertEqual(cs.classify(None, None, "estimated"), "unknown")

    def test_custom_band(self):
        self.assertEqual(cs.classify(300, 300, "stated", minimum=100, maximum=500), "in")


class TestCheck(unittest.TestCase):
    def _run(self, data):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k"}), \
             patch.object(cs, "_fetch", return_value=PAGE), \
             patch.object(cs, "_extract", return_value=data):
            return cs.check_company_size("https://acme.io", "Acme")

    def test_stated_size_with_real_quote_is_trusted(self):
        out = self._run({"employees_low": 45, "employees_high": 45, "basis": "stated",
                         "evidence": "We are a team of 45 people building data tools"})
        self.assertEqual(out["verdict"], "in")

    def test_invented_quote_is_not_trusted(self):
        out = self._run({"employees_low": 45, "employees_high": 45, "basis": "stated",
                         "evidence": "Acme has exactly forty five staff worldwide"})
        self.assertEqual(out["verdict"], "unknown")

    def test_low_confidence_estimate_is_unknown(self):
        out = self._run({"employees_low": 50, "employees_high": 100, "basis": "estimated", "confidence": "low"})
        self.assertEqual(out["verdict"], "unknown")

    def test_confident_estimate_counts(self):
        out = self._run({"employees_low": 1000, "employees_high": 3000, "basis": "estimated", "confidence": "high"})
        self.assertEqual(out["verdict"], "out")

    def test_no_key_or_site_is_unknown_and_never_raises(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            self.assertEqual(cs.check_company_size("https://acme.io", "Acme")["verdict"], "unknown")
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k"}), patch.object(cs, "_fetch", side_effect=RuntimeError):
            self.assertEqual(cs.check_company_size("https://acme.io", "Acme")["verdict"], "unknown")


if __name__ == "__main__":
    unittest.main()
