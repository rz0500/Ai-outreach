import os
import tempfile
import unittest
from unittest.mock import patch

import database
import web_app


class TestReplyDraftLookup(unittest.TestCase):
    def setUp(self):
        handle, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        database.initialize_database(self.db_path)
        self.prospect_id = database.add_prospect(
            name="Leah Carter",
            company="Harbor Studio",
            email="leah@harborstudio.co",
            website="https://harborstudio.co",
            status="qualified",
            db_path=self.db_path,
        )
        self.draft_id = database.save_reply_draft(
            prospect_id=self.prospect_id,
            inbound_from="leah@harborstudio.co",
            inbound_body="Sounds interesting. What does next week look like?",
            classification="interested",
            classification_reasoning="Prospect asked to continue the conversation.",
            drafted_reply="Leah,\n\nThursday at 2pm works on my side.\n\nBest,\nAlex",
            db_path=self.db_path,
        )

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_get_reply_draft_by_id_returns_joined_prospect_data(self):
        draft = database.get_reply_draft_by_id(self.draft_id, db_path=self.db_path)
        self.assertIsNotNone(draft)
        self.assertEqual(draft["prospect_name"], "Leah Carter")
        self.assertEqual(draft["prospect_company"], "Harbor Studio")
        self.assertEqual(draft["prospect_email"], "leah@harborstudio.co")
        self.assertEqual(draft["inbound_from"], "leah@harborstudio.co")


class TestReplyApproveSend(unittest.TestCase):
    def setUp(self):
        web_app.app.config["TESTING"] = True
        self.client = web_app.app.test_client()

    @patch("web_app.database.log_communication_event")
    @patch("web_app.database.update_status")
    @patch("web_app.database.update_reply_draft_status")
    @patch("web_app._route_send_email", return_value=(True, ""))
    @patch("web_app._validate_email_address", return_value=(True, ""))
    @patch("web_app.database.get_reply_draft_by_id")
    def test_approve_sends_reply_and_marks_sent(
        self,
        mock_get_draft,
        mock_validate,
        mock_send_email,
        mock_update_reply_status,
        mock_update_status,
        mock_log_event,
    ):
        mock_get_draft.return_value = {
            "id": 7,
            "prospect_id": 12,
            "prospect_company": "Harbor Studio",
            "prospect_email": "leah@harborstudio.co",
            "inbound_from": "leah@harborstudio.co",
            "inbound_subject": "Harbor Studio",
            "inbound_message_id": "<msg-123@test>",
            "drafted_reply": "Leah,\n\nThursday at 2pm works on my side.\n\nBest,\nAlex",
        }
        mock_update_reply_status.return_value = True
        mock_update_status.return_value = True
        mock_log_event.return_value = 99

        resp = self.client.post(
            "/api/reply-drafts/7/action",
            json={"action": "approve"},
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["status"], "sent")
        self.assertEqual(data["subject"], "Re: Harbor Studio")
        mock_send_email.assert_called_once_with(
            "leah@harborstudio.co",
            "Re: Harbor Studio",
            "Leah,\n\nThursday at 2pm works on my side.\n\nBest,\nAlex",
            in_reply_to="<msg-123@test>",
            references="<msg-123@test>",
        )
        mock_update_reply_status.assert_called_once_with(7, "sent")
        mock_update_status.assert_called_once_with(12, "replied")
        mock_log_event.assert_called_once()

    @patch("web_app._route_send_email", return_value=(False, "SMTP error"))
    @patch("web_app._validate_email_address", return_value=(True, ""))
    @patch("web_app.database.get_reply_draft_by_id")
    def test_approve_returns_error_when_send_fails(
        self,
        mock_get_draft,
        mock_validate,
        mock_send_email,
    ):
        mock_get_draft.return_value = {
            "id": 8,
            "prospect_id": 12,
            "prospect_company": "Harbor Studio",
            "prospect_email": "leah@harborstudio.co",
            "inbound_from": "leah@harborstudio.co",
            "inbound_subject": "Harbor Studio",
            "inbound_message_id": "<msg-456@test>",
            "drafted_reply": "Reply body",
        }

        resp = self.client.post(
            "/api/reply-drafts/8/action",
            json={"action": "approve"},
        )

        self.assertEqual(resp.status_code, 500)
        self.assertIn("Send failed", resp.get_json()["error"])
        mock_send_email.assert_called_once()

    @patch("web_app.database.update_reply_draft_status", return_value=True)
    @patch("web_app.database.get_reply_draft_by_id")
    def test_dismiss_marks_draft_dismissed(self, mock_get_draft, mock_update_reply_status):
        mock_get_draft.return_value = {
            "id": 9,
            "prospect_id": 12,
            "prospect_company": "Harbor Studio",
            "prospect_email": "leah@harborstudio.co",
            "inbound_from": "leah@harborstudio.co",
            "drafted_reply": "Reply body",
        }

        resp = self.client.post(
            "/api/reply-drafts/9/action",
            json={"action": "dismiss"},
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["status"], "dismissed")
        mock_update_reply_status.assert_called_once_with(9, "dismissed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
