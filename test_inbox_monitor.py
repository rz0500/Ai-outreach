import unittest
from unittest.mock import patch, MagicMock
import inbox_monitor

class TestInboxMonitor(unittest.TestCase):

    def test_extract_email_address(self):
        self.assertEqual(inbox_monitor.extract_email_address("John <john@doe.com>"), "john@doe.com")
        self.assertEqual(inbox_monitor.extract_email_address("jane@doe.com"), "jane@doe.com")
        self.assertEqual(inbox_monitor.extract_email_address("  TEST@test.com  "), "test@test.com")

    @patch('inbox_monitor.imaplib.IMAP4_SSL')
    @patch('inbox_monitor.database.get_prospect_by_email')
    @patch('inbox_monitor.database.update_status')
    @patch('inbox_monitor.IMAP_HOST', 'imap.test.com')
    @patch('inbox_monitor.IMAP_USER', 'test@test.com')
    @patch('inbox_monitor.IMAP_PASSWORD', 'testpass')
    def test_check_for_replies(self, mock_update, mock_get_prospect, mock_imap_ssl):
        
        # Mock IMAP connection and results
        mock_mail = MagicMock()
        mock_imap_ssl.return_value = mock_mail
        mock_mail.select.return_value = ("OK", [b'1'])
        mock_mail.search.return_value = ("OK", [b'1'])
        
        # Mock fetch result (A raw RFC822 Header)
        raw_header = b"From: Prospect Joe <prospect@test.com>\r\nSubject: Re: Hello\r\n\r\n"
        mock_mail.fetch.return_value = ("OK", [(b'1 (RFC822.HEADER)', raw_header)])
        
        # Mock database lookup finding a prospect
        mock_get_prospect.return_value = {"id": 1, "status": "contacted", "notes": ""}
        
        updated = inbox_monitor.check_for_replies(mark_as_read=True)
        
        # Assertions
        self.assertEqual(updated, 1)
        mock_get_prospect.assert_called_with("prospect@test.com")
        mock_update.assert_called_with(1, "replied")
        mock_mail.store.assert_called_with(b'1', "+FLAGS", "\\Seen")

    @patch('inbox_monitor.imaplib.IMAP4_SSL')
    @patch('inbox_monitor.database.get_prospect_by_email')
    @patch('inbox_monitor.database.update_status')
    @patch('inbox_monitor.IMAP_HOST', 'imap.test.com')
    @patch('inbox_monitor.IMAP_USER', 'test@test.com')
    @patch('inbox_monitor.IMAP_PASSWORD', 'testpass')
    def test_skips_already_replied(self, mock_update, mock_get_prospect, mock_imap_ssl):
        mock_mail = MagicMock()
        mock_imap_ssl.return_value = mock_mail
        mock_mail.select.return_value = ("OK", [b'1'])
        mock_mail.search.return_value = ("OK", [b'1'])
        raw_header = b"From: Prospect Joe <prospect@test.com>\r\nSubject: Re: Hello\r\n\r\n"
        mock_mail.fetch.return_value = ("OK", [(b'1 (RFC822.HEADER)', raw_header)])
        
        # Mock a prospect already 'replied'
        mock_get_prospect.return_value = {"id": 1, "status": "replied", "notes": ""}
        
        updated = inbox_monitor.check_for_replies(mark_as_read=True)
        
        # Should not update again
        self.assertEqual(updated, 0)
        mock_update.assert_not_called()

if __name__ == '__main__':
    unittest.main()
