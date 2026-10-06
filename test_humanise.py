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
