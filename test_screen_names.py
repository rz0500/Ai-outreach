"""company_size.screen_names: only confident 'out of band' answers remove a company."""

import os
import unittest
from unittest.mock import MagicMock, patch

import company_size as cs


def _reply(text):
    client = MagicMock()
    client.messages.create.return_value = MagicMock(content=[MagicMock(text=text)])
    return patch("anthropic.Anthropic", return_value=client)


class TestScreenNames(unittest.TestCase):
    COS = [("Capital One", "London"), ("Small Data Co", ""), ("Mid Firm", "")]

    def test_confident_large_company_is_removed_and_others_kept(self):
        reply = ('{"results": [{"n": 1, "low": 10000, "high": 50000, "confidence": "high"},'
                 ' {"n": 3, "low": 50, "high": 150, "confidence": "medium"}]}')
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k"}), _reply(reply):
            self.assertEqual(cs.screen_names(self.COS), {"Capital One": "out"})

    def test_low_confidence_is_ignored(self):
        reply = '{"results": [{"n": 1, "low": 10000, "high": 50000, "confidence": "low"}]}'
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k"}), _reply(reply):
            self.assertEqual(cs.screen_names(self.COS), {})

    def test_failure_or_no_key_removes_nothing(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            self.assertEqual(cs.screen_names(self.COS), {})
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k"}), _reply("not json"):
            self.assertEqual(cs.screen_names(self.COS), {})


if __name__ == "__main__":
    unittest.main()
