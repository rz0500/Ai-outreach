"""Bounce notices: detection, hard/soft classification, and the effects of a hard bounce."""

import email
import gc
import os
import unittest
from unittest.mock import patch

import bounce_handler as bh
import database as db
import inbox_monitor
from test_inbox_spam_rescue import FakeIMAP

TEST_DB = "test_bounce_handler.db"


def _dsn(recipient="sam@example.com", status="5.0.0", action="failed", line="550: No Such User Here"):
    """A Yahoo-style RFC 3464 delivery-status notification."""
    raw = (
        "From: MAILER-DAEMON@yahoo.com\r\n"
        "Subject: Failure Notice\r\n"
        "MIME-Version: 1.0\r\n"
        'Content-Type: multipart/report; report-type=delivery-status; boundary="B"\r\n\r\n'
        "--B\r\nContent-Type: text/plain\r\n\r\n"
        f"Sorry, we were unable to deliver your message to the following address.\r\n\r\n<{recipient}>:\r\n{line}\r\n\r\n"
        "--B\r\nContent-Type: message/delivery-status\r\n\r\n"
        "Reporting-MTA: dns; sonic-mta.mail.yahoo.com\r\n\r\n"
        f"Final-Recipient: rfc822; {recipient}\r\nAction: {action}\r\nStatus: {status}\r\n\r\n"
        "--B--\r\n"
    )
    return email.message_from_string(raw)


def _plain_bounce(recipient="x@example.com"):
    raw = (
        "From: Mail Delivery System <MAILER-DAEMON@mx.example.org>\r\n"
        "Subject: Undelivered Mail Returned to Sender\r\n"
        "Content-Type: text/plain\r\n\r\n"
        f"<{recipient}>: host mx.example.com said: 550 5.1.1 Recipient address rejected: User unknown\r\n"
    )
    return email.message_from_string(raw)


class TestDetection(unittest.TestCase):
    def test_dsn_is_a_bounce(self):
        msg = _dsn()
        self.assertTrue(bh.is_bounce(msg, "mailer-daemon@yahoo.com", "Failure Notice"))

    def test_plain_mta_bounce_is_a_bounce(self):
        msg = _plain_bounce()
        self.assertTrue(bh.is_bounce(msg, "mailer-daemon@mx.example.org", "Undelivered Mail Returned to Sender"))

    def test_normal_reply_is_not_a_bounce(self):
        msg = email.message_from_string("From: sam@example.com\r\nSubject: Re: Hello\r\n\r\nSounds good")
        self.assertFalse(bh.is_bounce(msg, "sam@example.com", "Re: Hello"))

    def test_person_writing_undeliverable_is_not_a_bounce(self):
        msg = email.message_from_string("From: sam@example.com\r\nSubject: undeliverable?\r\n\r\nhi")
        self.assertFalse(bh.is_bounce(msg, "sam@example.com", "undeliverable?"))

    def test_other_report_types_are_not_bounces(self):
        raw = (
            "From: abuse@isp.com\r\nSubject: spam report\r\n"
            'Content-Type: multipart/report; report-type=feedback-report; boundary="B"\r\n\r\n'
            "--B\r\nContent-Type: text/plain\r\n\r\nx\r\n--B--\r\n"
        )
        self.assertFalse(bh.is_bounce(email.message_from_string(raw), "abuse@isp.com", "spam report"))


class TestParsing(unittest.TestCase):
    def test_hard_bounce_from_status_5(self):
        info = bh.parse_bounce(_dsn("sam@example.com"))
        self.assertTrue(info["hard"])
        self.assertEqual(info["recipients"], ["sam@example.com"])
        self.assertIn("550", info["detail"])

    def test_mailbox_full_is_soft(self):
        info = bh.parse_bounce(_dsn(status="4.2.2", line="452: mailbox full"))
        self.assertFalse(info["hard"])
        self.assertEqual(info["recipients"], [])

    def test_delayed_is_soft(self):
        self.assertFalse(bh.parse_bounce(_dsn(action="delayed", status="4.4.1"))["hard"])

    def test_delivered_notice_is_not_a_failure(self):
        self.assertFalse(bh.parse_bounce(_dsn(action="delivered", status="2.0.0"))["hard"])

    def test_plain_text_bounce_uses_text_and_finds_recipient(self):
        info = bh.parse_bounce(_plain_bounce("x@example.com"))
        self.assertTrue(info["hard"])
        self.assertEqual(info["recipients"], ["x@example.com"])


class TestProcessBounce(unittest.TestCase):
    def setUp(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)
        db.initialize_outreach_table(TEST_DB)
        db.initialize_database(TEST_DB)

    def tearDown(self):
        gc.collect()
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)

    def _prospect(self, email_addr="sam@example.com", status="contacted"):
        pid = db.add_prospect(name="Sam", company="Acme", email=email_addr, status=status, db_path=TEST_DB)
        db.ensure_sequence_enrollment(pid, sequence_name="candidate_email", db_path=TEST_DB)
        oid = db.save_outreach(pid, "follow up", "body", db_path=TEST_DB)
        return pid, oid

    def test_hard_bounce_suppresses_pauses_and_cancels_queue(self):
        pid, oid = self._prospect()
        self.assertEqual(bh.process_bounce(_dsn("sam@example.com"), db_path=TEST_DB), 1)

        self.assertTrue(db.is_suppressed("sam@example.com", TEST_DB))
        self.assertEqual(db.get_prospect_by_id(pid, db_path=TEST_DB)["status"], "rejected")
        enrol = db.get_active_sequence_enrollments(TEST_DB, sequence_name="candidate_email")
        self.assertEqual(enrol, [])
        outreach = [o for o in db.get_all_outreach(db_path=TEST_DB) if o["id"] == oid][0]
        self.assertEqual(outreach["status"], "skipped")
        events = [e for e in db.get_communication_events(pid, TEST_DB) if e["event_type"] == "bounce"]
        self.assertEqual(len(events), 1)

    def test_repeat_notice_is_idempotent(self):
        self._prospect()
        self.assertEqual(bh.process_bounce(_dsn("sam@example.com"), db_path=TEST_DB), 1)
        self.assertEqual(bh.process_bounce(_dsn("sam@example.com"), db_path=TEST_DB), 0)

    def test_soft_bounce_changes_nothing(self):
        pid, _ = self._prospect()
        self.assertEqual(bh.process_bounce(_dsn(status="4.2.2"), db_path=TEST_DB), 0)
        self.assertFalse(db.is_suppressed("sam@example.com", TEST_DB))
        self.assertEqual(db.get_prospect_by_id(pid, db_path=TEST_DB)["status"], "contacted")

    def test_replied_prospect_is_never_suppressed(self):
        pid, _ = self._prospect(status="replied")
        self.assertEqual(bh.process_bounce(_dsn("sam@example.com"), db_path=TEST_DB), 0)
        self.assertFalse(db.is_suppressed("sam@example.com", TEST_DB))

    def test_unknown_address_is_ignored(self):
        self._prospect()
        self.assertEqual(bh.process_bounce(_dsn("nobody@example.com"), db_path=TEST_DB), 0)


class TestMonitorIntegration(unittest.TestCase):
    def _run(self, fake, mark_as_read=True):
        with patch("inbox_monitor.imaplib.IMAP4_SSL", return_value=fake), \
             patch("inbox_monitor.IMAP_HOST", "imap.test.com"), \
             patch("inbox_monitor.IMAP_USER", "me@test.com"), \
             patch("inbox_monitor.IMAP_PASSWORD", "pw"), \
             patch("inbox_monitor.database.get_prospect_by_email") as get_p, \
             patch("inbox_monitor.bounce_handler.process_bounce", return_value=1) as process:
            updated = inbox_monitor.check_for_replies(mark_as_read=mark_as_read)
        return updated, get_p, process

    def test_bounce_in_inbox_is_processed_marked_read_and_not_a_reply(self):
        fake = FakeIMAP({"INBOX": {b"1": _dsn().as_bytes()}, "Bulk": {}})
        updated, get_p, process = self._run(fake)
        self.assertEqual(updated, 0)
        process.assert_called_once()
        get_p.assert_not_called()                       # never treated as a prospect reply
        self.assertIn(("INBOX", b"1", "\\Seen"), fake.stored)

    def test_bounce_in_spam_folder_is_processed_and_marked_read_but_not_moved(self):
        fake = FakeIMAP({"INBOX": {}, "Bulk": {b"1": _dsn().as_bytes()}})
        _, _, process = self._run(fake)
        process.assert_called_once()
        self.assertIn(("Bulk", b"1", "\\Seen"), fake.stored)
        self.assertEqual(fake.copied, [])


if __name__ == "__main__":
    unittest.main()
