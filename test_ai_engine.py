"""
test_ai_engine.py - Module 9 Tests
=====================================
Tests ai_engine.py using unittest.mock — the Anthropic API is never called
and no tokens are spent.

Test groups:
  1. _prospect_to_text      — formats prospect dict into prompt text
  2. _extract_json          — parses JSON from a mock API response
  3. generate_hyper_personalized_email
       - happy path (valid JSON response)
       - missing keys in response
       - invalid JSON response
       - API auth error propagates
       - API rate-limit error propagates
  4. analyze_prospect_score
       - happy path (valid JSON response)
       - score clamped / out-of-range raises ValueError
       - missing keys raises ValueError
       - invalid JSON raises ValueError

Run with:
    python test_ai_engine.py
"""

import json
import unittest
from unittest.mock import MagicMock, patch

import anthropic

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_prospect(**overrides) -> dict:
    base = {
        "name":         "Jane Doe",
        "company":      "Acme Corp",
        "email":        "jane@acme.com",
        "linkedin_url": "https://linkedin.com/in/janedoe",
        "website":      "https://acme.com",
        "phone":        "+1-415-555-0100",
        "lead_score":   75,
        "status":       "qualified",
        "notes":        "VP of Sales. Company raised Series B. Hiring SDRs.",
    }
    base.update(overrides)
    return base


def _mock_response(payload: dict) -> MagicMock:
    """Build a mock anthropic.Message whose first content block returns payload as JSON."""
    block = MagicMock()
    block.type = "text"
    block.text = json.dumps(payload)
    msg = MagicMock()
    msg.content = [block]
    return msg


# ---------------------------------------------------------------------------
# 1. _prospect_to_text
# ---------------------------------------------------------------------------

class TestProspectToText(unittest.TestCase):

    def test_includes_all_present_fields(self):
        from ai_engine import _prospect_to_text
        text = _prospect_to_text(_make_prospect())
        self.assertIn("Jane Doe", text)
        self.assertIn("Acme Corp", text)
        self.assertIn("jane@acme.com", text)
        self.assertIn("Series B", text)

    def test_omits_none_fields(self):
        from ai_engine import _prospect_to_text
        prospect = _make_prospect(phone=None, linkedin_url=None)
        text = _prospect_to_text(prospect)
        self.assertNotIn("Phone", text)
        self.assertNotIn("LinkedIn", text)

    def test_minimal_prospect(self):
        from ai_engine import _prospect_to_text
        text = _prospect_to_text({"name": "Bob", "company": "Corp"})
        self.assertIn("Bob", text)
        self.assertIn("Corp", text)


# ---------------------------------------------------------------------------
# 2. _extract_json
# ---------------------------------------------------------------------------

class TestExtractJson(unittest.TestCase):

    def test_parses_valid_json(self):
        from ai_engine import _extract_json
        response = _mock_response({"score": 80, "reasoning": "Strong signals."})
        result = _extract_json(response)
        self.assertEqual(result["score"], 80)

    def test_raises_on_invalid_json(self):
        from ai_engine import _extract_json
        block = MagicMock()
        block.type = "text"
        block.text = "This is not JSON at all."
        msg = MagicMock()
        msg.content = [block]
        with self.assertRaises(ValueError):
            _extract_json(msg)

    def test_raises_when_no_text_block(self):
        from ai_engine import _extract_json
        block = MagicMock()
        block.type = "tool_use"   # not a text block
        msg = MagicMock()
        msg.content = [block]
        with self.assertRaises(ValueError):
            _extract_json(msg)


# ---------------------------------------------------------------------------
# 3. generate_hyper_personalized_email
# ---------------------------------------------------------------------------

class TestGenerateEmail(unittest.TestCase):

    @patch("ai_engine._client")
    def test_happy_path_returns_subject_and_body(self, mock_client):
        from ai_engine import generate_hyper_personalized_email
        mock_client.messages.create.return_value = _mock_response({
            "subject": "Quick thought for Acme",
            "body":    "Hi Jane,\n\nAcme Corp raised Series B, which changes the pressure on pipeline.\n\nBest,\n[Your name]",
        })

        result = generate_hyper_personalized_email(_make_prospect())

        self.assertEqual(result["subject"], "Quick thought for Acme")
        self.assertIn("Jane", result["body"])
        mock_client.messages.create.assert_called_once()

    @patch("ai_engine._client")
    def test_passes_prospect_data_to_api(self, mock_client):
        from ai_engine import generate_hyper_personalized_email
        mock_client.messages.create.return_value = _mock_response({
            "subject": "Hey",
            "body":    "Hi Jane,\n\nAcme Corp has a clear offer.\n\nBest,\n[Your name]",
        })

        generate_hyper_personalized_email(_make_prospect())

        call_kwargs = mock_client.messages.create.call_args.kwargs
        user_content = call_kwargs["messages"][0]["content"]
        self.assertIn("Jane Doe", user_content)
        self.assertIn("Acme Corp", user_content)

    @patch("ai_engine._client")
    def test_uses_cache_control_on_system_prompt(self, mock_client):
        from ai_engine import generate_hyper_personalized_email
        mock_client.messages.create.return_value = _mock_response({
            "subject": "Hey", "body": "Acme Corp has a clear offer.",
        })

        generate_hyper_personalized_email(_make_prospect())

        system = mock_client.messages.create.call_args.kwargs["system"]
        self.assertIsInstance(system, list)
        self.assertEqual(system[0]["cache_control"]["type"], "ephemeral")

    @patch("ai_engine._client")
    def test_raises_on_missing_subject_key(self, mock_client):
        from ai_engine import generate_hyper_personalized_email
        mock_client.messages.create.return_value = _mock_response({
            "body": "Hi Jane"  # missing "subject"
        })
        with self.assertRaises(ValueError):
            generate_hyper_personalized_email(_make_prospect())

    @patch("ai_engine._client")
    def test_raises_on_missing_body_key(self, mock_client):
        from ai_engine import generate_hyper_personalized_email
        mock_client.messages.create.return_value = _mock_response({
            "subject": "Hey"  # missing "body"
        })
        with self.assertRaises(ValueError):
            generate_hyper_personalized_email(_make_prospect())

    @patch("ai_engine._client")
    def test_raises_on_invalid_json_response(self, mock_client):
        from ai_engine import generate_hyper_personalized_email
        block = MagicMock()
        block.type = "text"
        block.text = "Sure, here is your email!"   # not JSON
        msg = MagicMock()
        msg.content = [block]
        mock_client.messages.create.return_value = msg
        with self.assertRaises(ValueError):
            generate_hyper_personalized_email(_make_prospect())

    @patch("ai_engine._client")
    def test_auth_error_propagates(self, mock_client):
        from ai_engine import generate_hyper_personalized_email
        mock_client.messages.create.side_effect = anthropic.AuthenticationError(
            message="Invalid key", response=MagicMock(), body={}
        )
        with self.assertRaises(anthropic.AuthenticationError):
            generate_hyper_personalized_email(_make_prospect())

    @patch("ai_engine._client")
    def test_rate_limit_error_propagates(self, mock_client):
        from ai_engine import generate_hyper_personalized_email
        mock_client.messages.create.side_effect = anthropic.RateLimitError(
            message="Too many requests", response=MagicMock(), body={}
        )
        with self.assertRaises(anthropic.RateLimitError):
            generate_hyper_personalized_email(_make_prospect())


# ---------------------------------------------------------------------------
# 4. analyze_prospect_score
# ---------------------------------------------------------------------------

class TestAnalyzeProspectScore(unittest.TestCase):

    @patch("ai_engine._client")
    def test_happy_path_returns_score_and_reasoning(self, mock_client):
        from ai_engine import analyze_prospect_score
        mock_client.messages.create.return_value = _mock_response({
            "score":     82,
            "reasoning": "VP-level decision-maker with full contact info and Series B signals.",
        })

        result = analyze_prospect_score(_make_prospect())

        self.assertEqual(result["score"], 82)
        self.assertIn("VP", result["reasoning"])
        mock_client.messages.create.assert_called_once()

    @patch("ai_engine._client")
    def test_score_boundaries_accepted(self, mock_client):
        from ai_engine import analyze_prospect_score
        for score in (1, 50, 100):
            mock_client.messages.create.return_value = _mock_response({
                "score": score, "reasoning": "OK."
            })
            result = analyze_prospect_score(_make_prospect())
            self.assertEqual(result["score"], score)

    @patch("ai_engine._client")
    def test_score_out_of_range_raises(self, mock_client):
        from ai_engine import analyze_prospect_score
        for bad_score in (0, 101, -5, 200):
            mock_client.messages.create.return_value = _mock_response({
                "score": bad_score, "reasoning": "Whatever."
            })
            with self.assertRaises(ValueError, msg=f"score={bad_score} should raise"):
                analyze_prospect_score(_make_prospect())

    @patch("ai_engine._client")
    def test_uses_cache_control_on_system_prompt(self, mock_client):
        from ai_engine import analyze_prospect_score
        mock_client.messages.create.return_value = _mock_response({
            "score": 70, "reasoning": "Warm lead."
        })

        analyze_prospect_score(_make_prospect())

        system = mock_client.messages.create.call_args.kwargs["system"]
        self.assertIsInstance(system, list)
        self.assertEqual(system[0]["cache_control"]["type"], "ephemeral")

    @patch("ai_engine._client")
    def test_passes_prospect_data_to_api(self, mock_client):
        from ai_engine import analyze_prospect_score
        mock_client.messages.create.return_value = _mock_response({
            "score": 65, "reasoning": "Warm."
        })

        analyze_prospect_score(_make_prospect())

        user_content = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
        self.assertIn("Jane Doe", user_content)
        self.assertIn("Series B", user_content)

    @patch("ai_engine._client")
    def test_raises_on_missing_score_key(self, mock_client):
        from ai_engine import analyze_prospect_score
        mock_client.messages.create.return_value = _mock_response({
            "reasoning": "Good lead."  # missing "score"
        })
        with self.assertRaises(ValueError):
            analyze_prospect_score(_make_prospect())

    @patch("ai_engine._client")
    def test_raises_on_missing_reasoning_key(self, mock_client):
        from ai_engine import analyze_prospect_score
        mock_client.messages.create.return_value = _mock_response({
            "score": 70  # missing "reasoning"
        })
        with self.assertRaises(ValueError):
            analyze_prospect_score(_make_prospect())

    @patch("ai_engine._client")
    def test_raises_on_invalid_json_response(self, mock_client):
        from ai_engine import analyze_prospect_score
        block = MagicMock()
        block.type = "text"
        block.text = "The score is 75 out of 100."   # natural language, not JSON
        msg = MagicMock()
        msg.content = [block]
        mock_client.messages.create.return_value = msg
        with self.assertRaises(ValueError):
            analyze_prospect_score(_make_prospect())

    @patch("ai_engine._client")
    def test_auth_error_propagates(self, mock_client):
        from ai_engine import analyze_prospect_score
        mock_client.messages.create.side_effect = anthropic.AuthenticationError(
            message="Invalid key", response=MagicMock(), body={}
        )
        with self.assertRaises(anthropic.AuthenticationError):
            analyze_prospect_score(_make_prospect())


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sep = "=" * 58
    print(f"\n{sep}")
    print("  AI ENGINE - MODULE 9 TESTS")
    print(sep + "\n")
    unittest.main(verbosity=2)
