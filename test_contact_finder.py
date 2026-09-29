"""Tests for contact_finder: ranking, filtering, obfuscation decoding, crawl."""

import unittest
from unittest.mock import patch

import contact_finder as cf


def _cf_encode(addr: str, key: int = 0x5A) -> str:
    return f"{key:02x}" + "".join(f"{ord(c) ^ key:02x}" for c in addr)


class TestRanking(unittest.TestCase):
    def test_careers_beats_personal_beats_generic(self):
        ranked = cf.rank_emails(
            ["info@acme.com", "sarah.jones@acme.com", "careers@acme.com"], "acme.com"
        )
        self.assertEqual(
            [r["email"] for r in ranked],
            ["careers@acme.com", "sarah.jones@acme.com", "info@acme.com"],
        )

    def test_junk_addresses_are_dropped(self):
        ranked = cf.rank_emails(
            ["press@acme.com", "marketing@acme.com", "editor@acme.com", "noreply@acme.com"],
            "acme.com",
        )
        self.assertEqual(ranked, [])

    def test_sales_and_support_are_last_resort(self):
        ranked = cf.rank_emails(["sales@acme.com", "hello@acme.com"], "acme.com")
        self.assertEqual(ranked[0]["email"], "hello@acme.com")
        self.assertEqual(ranked[1]["kind"], "low")

    def test_third_party_addresses_are_ignored(self):
        ranked = cf.rank_emails(["u@sentry.io", "info@acme.com"], "acme.com")
        self.assertEqual([r["email"] for r in ranked], ["info@acme.com"])

    def test_freemail_only_used_when_nothing_on_domain(self):
        ranked = cf.rank_emails(["acmeltd@gmail.com", "info@acme.com"], "acme.com")
        self.assertEqual(ranked[0]["email"], "info@acme.com")
        only_free = cf.rank_emails(["acmeltd@gmail.com"], "acme.com")
        self.assertEqual(only_free[0]["email"], "acmeltd@gmail.com")

    def test_file_names_are_not_emails(self):
        ranked = cf.rank_emails(["logo@2x.png", "info@acme.com"], "acme.com")
        self.assertEqual([r["email"] for r in ranked], ["info@acme.com"])

    def test_person_name_derived_from_local_part(self):
        ranked = cf.rank_emails(["supriya.dixit@acme.com"], "acme.com")
        self.assertEqual(ranked[0]["kind"], "personal")
        self.assertEqual(ranked[0]["name"], "Supriya Dixit")

    def test_careers_words_inside_local_part_count_as_careers(self):
        ranked = cf.rank_emails(["yourfuturecareer@acme.com"], "acme.com")
        self.assertEqual(ranked[0]["kind"], "careers")

    def test_partners_inbox_is_not_a_person(self):
        ranked = cf.rank_emails(["partners@acme.com"], "acme.com")
        self.assertEqual(ranked[0]["kind"], "generic")
        self.assertEqual(ranked[0]["name"], "")

    def test_generic_inbox_has_no_name(self):
        ranked = cf.rank_emails(["hello@acme.com"], "acme.com")
        self.assertEqual(ranked[0]["name"], "")


class TestExtraction(unittest.TestCase):
    def test_cloudflare_protected_email_is_decoded(self):
        html = f'<a class="__cf_email__" data-cfemail="{_cf_encode("careers@acme.com")}">[email protected]</a>'
        self.assertIn("careers@acme.com", cf._emails_from_html(html))

    def test_obfuscated_at_dot_is_decoded(self):
        html = "<p>Write to jobs [at] acme [dot] com today</p>"
        self.assertIn("jobs@acme.com", cf._emails_from_html(html))

    def test_mailto_and_plain_text_found(self):
        html = '<a href="mailto:Hello@Acme.com?subject=x">x</a><p>or info@acme.com</p>'
        found = cf._emails_from_html(html)
        self.assertIn("hello@acme.com", found)
        self.assertIn("info@acme.com", found)


class TestCrawl(unittest.TestCase):
    def test_finds_careers_address_on_subpage(self):
        pages = {
            "https://acme.com": '<a href="/careers">Careers</a><p>info@acme.com</p>',
            "https://acme.com/careers": "<p>Apply: jobs@acme.com</p>",
        }
        with patch.object(cf, "_fetch", side_effect=lambda u: pages.get(u, "")):
            best = cf.find_best_contact("acme.com")
        self.assertEqual(best["email"], "jobs@acme.com")
        self.assertEqual(best["kind"], "careers")

    def test_returns_empty_when_nothing_found(self):
        with patch.object(cf, "_fetch", return_value=""):
            self.assertEqual(cf.find_best_contact("acme.com"), {})

    def test_empty_url(self):
        self.assertEqual(cf.find_contacts(""), [])


if __name__ == "__main__":
    unittest.main()
