"""
test_mailer.py - Module 7 Tests
=================================
Tests send_email() using unittest.mock — no real SMTP connection is made
and no emails are sent.

Covers:
  1. Successful send via SMTP_SSL (port 465)
  2. Successful send via STARTTLS (port 587)
  3. Authentication failure
  4. Recipient refused
  5. Generic SMTP error
  6. Connection / OS error
  7. Missing .env credentials

Run with:
    python test_mailer.py
"""

import smtplib
import unittest
from unittest.mock import MagicMock, patch

TO      = "prospect@example.com"
SUBJECT = "Quick idea for Acme"
BODY    = "Hi Jane,\n\nJust wanted to reach out...\n\nBest,\nAlex"


# ---------------------------------------------------------------------------
# Port 465 — SMTP_SSL
# ---------------------------------------------------------------------------

class TestSendEmailSSL(unittest.TestCase):

    @patch("mailer.SMTP_PORT", 465)
    @patch("mailer.SMTP_PASSWORD", "app-password-123")
    @patch("mailer.SMTP_USER", "sender@example.com")
    @patch("mailer.SMTP_HOST", "smtp.gmail.com")
    @patch("smtplib.SMTP_SSL")
    def test_successful_send(self, mock_ssl):
        from mailer import send_email
        mock_server = MagicMock()
        mock_ssl.return_value.__enter__.return_value = mock_server

        ok, err = send_email(TO, SUBJECT, BODY)

        self.assertTrue(ok)
        self.assertEqual(err, "")
        mock_server.login.assert_called_once()
        mock_server.sendmail.assert_called_once()

    @patch("mailer.SMTP_PORT", 465)
    @patch("mailer.SMTP_PASSWORD", "app-password-123")
    @patch("mailer.SMTP_USER", "sender@example.com")
    @patch("mailer.SMTP_HOST", "smtp.gmail.com")
    @patch("smtplib.SMTP_SSL")
    def test_auth_failure(self, mock_ssl):
        from mailer import send_email
        mock_server = MagicMock()
        mock_ssl.return_value.__enter__.return_value = mock_server
        mock_server.login.side_effect = smtplib.SMTPAuthenticationError(535, b"Bad credentials")

        ok, err = send_email(TO, SUBJECT, BODY)

        self.assertFalse(ok)
        self.assertIn("Authentication failed", err)

    @patch("mailer.SMTP_PORT", 465)
    @patch("mailer.SMTP_PASSWORD", "app-password-123")
    @patch("mailer.SMTP_USER", "sender@example.com")
    @patch("mailer.SMTP_HOST", "smtp.gmail.com")
    @patch("smtplib.SMTP_SSL")
    def test_recipient_refused(self, mock_ssl):
        from mailer import send_email
        mock_server = MagicMock()
        mock_ssl.return_value.__enter__.return_value = mock_server
        mock_server.sendmail.side_effect = smtplib.SMTPRecipientsRefused(
            {TO: (550, b"User unknown")}
        )

        ok, err = send_email(TO, SUBJECT, BODY)

        self.assertFalse(ok)
        self.assertIn("Recipient refused", err)

    @patch("mailer.SMTP_PORT", 465)
    @patch("mailer.SMTP_PASSWORD", "app-password-123")
    @patch("mailer.SMTP_USER", "sender@example.com")
    @patch("mailer.SMTP_HOST", "smtp.gmail.com")
    @patch("smtplib.SMTP_SSL")
    def test_generic_smtp_error(self, mock_ssl):
        from mailer import send_email
        mock_server = MagicMock()
        mock_ssl.return_value.__enter__.return_value = mock_server
        mock_server.sendmail.side_effect = smtplib.SMTPException("Something went wrong")

        ok, err = send_email(TO, SUBJECT, BODY)

        self.assertFalse(ok)
        self.assertIn("SMTP error", err)

    @patch("mailer.SMTP_PORT", 465)
    @patch("mailer.SMTP_PASSWORD", "app-password-123")
    @patch("mailer.SMTP_USER", "sender@example.com")
    @patch("mailer.SMTP_HOST", "smtp.gmail.com")
    @patch("smtplib.SMTP_SSL")
    def test_connection_error(self, mock_ssl):
        from mailer import send_email
        mock_ssl.side_effect = OSError("Connection refused")

        ok, err = send_email(TO, SUBJECT, BODY)

        self.assertFalse(ok)
        self.assertIn("Connection error", err)


# ---------------------------------------------------------------------------
# Port 587 — STARTTLS
# ---------------------------------------------------------------------------

class TestSendEmailSTARTTLS(unittest.TestCase):

    @patch("mailer.SMTP_PORT", 587)
    @patch("mailer.SMTP_PASSWORD", "app-password-123")
    @patch("mailer.SMTP_USER", "sender@example.com")
    @patch("mailer.SMTP_HOST", "smtp.gmail.com")
    @patch("smtplib.SMTP")
    def test_successful_send_starttls(self, mock_smtp):
        from mailer import send_email
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_server

        ok, err = send_email(TO, SUBJECT, BODY)

        self.assertTrue(ok)
        self.assertEqual(err, "")
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once()
        mock_server.sendmail.assert_called_once()


# ---------------------------------------------------------------------------
# Missing credentials
# ---------------------------------------------------------------------------

class TestMissingCredentials(unittest.TestCase):

    @patch("mailer.SMTP_HOST", "")
    @patch("mailer.SMTP_USER", "")
    @patch("mailer.SMTP_PASSWORD", "")
    def test_missing_all_credentials(self):
        from mailer import send_email
        ok, err = send_email(TO, SUBJECT, BODY)
        self.assertFalse(ok)
        self.assertIn("Missing .env keys", err)

    @patch("mailer.SMTP_HOST", "smtp.gmail.com")
    @patch("mailer.SMTP_USER", "sender@example.com")
    @patch("mailer.SMTP_PASSWORD", "")
    def test_missing_password(self):
        from mailer import send_email
        ok, err = send_email(TO, SUBJECT, BODY)
        self.assertFalse(ok)
        self.assertIn("SMTP_PASSWORD", err)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sep = "=" * 58
    print(f"\n{sep}")
    print("  MAILER - MODULE 7 TESTS")
    print(sep + "\n")
    unittest.main(verbosity=2)
