import os
import tempfile
import unittest
import uuid
from unittest.mock import patch

import deck_generator


def _fake_pdf_export(filepath):
    """Stand-in for the real PDF export, which opens PowerPoint/LibreOffice on this machine."""
    pdf_path = os.path.splitext(filepath)[0] + ".pdf"
    with open(pdf_path, "wb") as fh:
        fh.write(b"%PDF-1.4 test stub\n")
    return pdf_path, "ok (stub)"


def _prospect(**overrides):
    base = {
        "name": "James Cole",
        "company": "Apex Digital",
        "niche": "B2B SaaS for construction project managers",
        "icp": "mid-sized UK construction firms, 5+ concurrent projects",
        "website_headline": "Stop losing projects to miscommunication",
        "product_feature": "real-time site-to-office sync with automated reporting",
        "competitors": "Buildertrend, CoConstruct",
        "ad_status": "running_ads",
        "outbound_status": "no_outbound",
        "notes": (
            "[Research Hook]\n"
            "Pain Point: miscommunication between site and office\n"
            "Growth Signal: Recently rebranded site with enterprise case studies added.\n"
            "Opener: Apex Digital's positioning is built around a problem every PM feels on a live project."
        ),
    }
    base.update(overrides)
    return base


class TestDeckGenerator(unittest.TestCase):

    def test_build_deck_system_prompt_fills_variables(self):
        variables = deck_generator._extract_variables(_prospect())
        prompt = deck_generator.build_deck_system_prompt(variables)

        self.assertIn("Apex Digital", prompt)
        self.assertIn("Buildertrend", prompt)
        self.assertIn("CoConstruct", prompt)
        self.assertIn("miscommunication between site and office", prompt)
        self.assertNotIn("{{company_name}}", prompt)

    def test_template_copy_matches_required_shape(self):
        variables = deck_generator._extract_variables(_prospect())
        copy = deck_generator._gen_copy_template(variables)

        self.assertEqual(copy["slide6"]["headline"], "No results. No charge.")
        self.assertEqual(copy["slide5"]["headline"], "The System")
        self.assertEqual(len(copy["slide5"]["outcomes"]), 3)
        self.assertIn("Apex Digital", " ".join(copy["slide3"]["terminal_lines"]))

    def test_run_deck_qa_passes_for_template_copy(self):
        variables = deck_generator._extract_variables(_prospect())
        copy = deck_generator._gen_copy_template(variables)
        report = deck_generator.run_deck_qa(copy, variables)

        self.assertEqual(report["copy_issues"], [])

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""})  # template copy: no live API call
    @patch.object(deck_generator, "_rasterize_pdf", return_value=([], "skipped: stubbed in test"))
    @patch.object(deck_generator, "_convert_deck_to_pdf", side_effect=_fake_pdf_export)
    def test_generate_deck_creates_pptx(self, _mock_convert, _mock_raster):
        original_output_dir = deck_generator.OUTPUT_DIR
        output_dir = os.path.join(os.getcwd(), f"deck_test_{uuid.uuid4().hex}")
        try:
            os.makedirs(output_dir, exist_ok=True)
            deck_generator.OUTPUT_DIR = output_dir
            path = deck_generator.generate_deck(_prospect())
            self.assertTrue(os.path.exists(path))
            self.assertTrue(path.endswith(".pdf"))
        finally:
            deck_generator.OUTPUT_DIR = original_output_dir
            if os.path.exists(output_dir):
                for name in os.listdir(output_dir):
                    os.remove(os.path.join(output_dir, name))
                os.rmdir(output_dir)


if __name__ == "__main__":
    unittest.main(verbosity=2)
