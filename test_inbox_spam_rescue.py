"""Reply monitor must also read the spam folder and rescue real prospect replies."""

import unittest
from unittest.mock import MagicMock, patch

import inbox_monitor

REPLY = (
    b"From: Sam Lee <sam@example.com>\r\nSubject: Re: Datatonic\r\n"
    b"Message-ID: <abc@example.com>\r\n\r\nSure, happy to chat."
)
SPAM = b"From: Deals <deals@spammy.biz>\r\nSubject: WIN NOW\r\n\r\nclick here"


class FakeIMAP:
    """Just enough of imaplib.IMAP4_SSL for check_for_replies."""

    def __init__(self, folders):
        self.folders = folders
        self.selected = None
        self.stored = []
        self.copied = []
        self.expunged = False

    def login(self, *a):
        return ("OK", [])

    def list(self):
        return ("OK", [b'(\\HasNoChildren) "/" "Inbox"', b'(\\Junk \\HasNoChildren) "/" "Bulk"'])

    def select(self, name):
        self.selected = name.strip('"')
        return ("OK", [b"1"])

    def search(self, *a):
        return ("OK", [b" ".join(self.folders[self.selected].keys())])

    def fetch(self, msg_id, spec):
        return ("OK", [(b"1 (RFC822)", self.folders[self.selected][msg_id])])

    def store(self, msg_id, op, flag):
        self.stored.append((self.selected, msg_id, flag))
        return ("OK", [])

    def copy(self, msg_id, dest):
        self.copied.append((self.selected, msg_id, dest))
        return ("OK", [b"copied"])

    def expunge(self):
        self.expunged = True
        return ("OK", [])

    def close(self):
        return ("OK", [])

    def logout(self):
        return ("BYE", [])


def _run(fake, prospect):
    with patch("inbox_monitor.imaplib.IMAP4_SSL", return_value=fake), \
         patch("inbox_monitor.IMAP_HOST", "imap.test.com"), \
         patch("inbox_monitor.IMAP_USER", "me@test.com"), \
         patch("inbox_monitor.IMAP_PASSWORD", "pw"), \
         patch("inbox_monitor.database.get_prospect_by_email", return_value=prospect) as get_p, \
         patch("inbox_monitor.database.get_prospects_by_email_domain", return_value=[]), \
         patch("inbox_monitor.database.update_status") as update, \
         patch("inbox_monitor.classify_reply", return_value={
             "classification": "interested", "reasoning": "wants a chat", "drafted_reply": "Great!"}), \
         patch("inbox_monitor._handle_classified_reply") as handle:
        updated = inbox_monitor.check_for_replies(mark_as_read=False)
    return updated, get_p, update, handle


class TestSpamFolderRescue(unittest.TestCase):
    def test_reply_filed_as_spam_is_processed_and_moved_to_inbox(self):
        fake = FakeIMAP({"INBOX": {}, "Bulk": {b"1": REPLY}})
        prospect = {"id": 7, "status": "contacted", "notes": ""}
        updated, _, update, handle = _run(fake, prospect)

        self.assertEqual(updated, 1)
        update.assert_called_once_with(7, "replied")
        handle.assert_called_once()
        self.assertEqual(fake.copied, [("Bulk", b"1", "INBOX")])
        self.assertIn(("Bulk", b"1", "\\Deleted"), fake.stored)
        self.assertTrue(fake.expunged)

    def test_ordinary_spam_is_left_alone(self):
        fake = FakeIMAP({"INBOX": {}, "Bulk": {b"1": SPAM}})
        updated, _, update, handle = _run(fake, None)

        self.assertEqual(updated, 0)
        update.assert_not_called()
        handle.assert_not_called()
        self.assertEqual(fake.copied, [])
        self.assertEqual(fake.stored, [])
        self.assertFalse(fake.expunged)

    def test_inbox_reply_still_works_and_nothing_is_moved(self):
        fake = FakeIMAP({"INBOX": {b"1": REPLY}, "Bulk": {}})
        prospect = {"id": 7, "status": "contacted", "notes": ""}
        updated, _, update, _ = _run(fake, prospect)

        self.assertEqual(updated, 1)
        update.assert_called_once_with(7, "replied")
        self.assertEqual(fake.copied, [])


class TestProspectForSender(unittest.TestCase):
    """A colleague replying from a different address at the same company still counts."""

    def _match(self, sender, exact=None, domain_rows=()):
        with patch("inbox_monitor.database.get_prospect_by_email", return_value=exact), \
             patch("inbox_monitor.database.get_prospects_by_email_domain",
                   return_value=list(domain_rows)) as by_domain:
            return inbox_monitor._prospect_for_sender(sender), by_domain

    def test_exact_address_wins(self):
        prospect = {"id": 1}
        found, by_domain = self._match("info@acme.com", exact=prospect)
        self.assertEqual(found, prospect)
        by_domain.assert_not_called()

    def test_colleague_at_same_company_matches_when_unambiguous(self):
        found, _ = self._match("sarah@acme.com", domain_rows=[{"id": 2}])
        self.assertEqual(found, {"id": 2})

    def test_ambiguous_company_does_not_match(self):
        found, _ = self._match("sarah@acme.com", domain_rows=[{"id": 2}, {"id": 3}])
        self.assertIsNone(found)

    def test_freemail_senders_never_match_by_domain(self):
        found, by_domain = self._match("someone@gmail.com", domain_rows=[{"id": 2}])
        self.assertIsNone(found)
        by_domain.assert_not_called()

    def test_system_senders_never_match_by_domain(self):
        for sender in ("mailer-daemon@acme.com", "postmaster@acme.com", "noreply@acme.com"):
            found, _ = self._match(sender, domain_rows=[{"id": 2}])
            self.assertIsNone(found)


class TestFindJunkFolder(unittest.TestCase):
    def _mail(self, lines, status="OK"):
        mail = MagicMock()
        mail.list.return_value = (status, lines)
        return mail

    def test_yahoo_bulk(self):
        mail = self._mail([b'(\\HasNoChildren) "/" "Inbox"', b'(\\Junk \\HasNoChildren) "/" "Bulk"'])
        self.assertEqual(inbox_monitor._find_junk_folder(mail), "Bulk")

    def test_gmail_spam_with_nested_name(self):
        mail = self._mail([b'(\\HasNoChildren \\Junk) "/" "[Gmail]/Spam"'])
        self.assertEqual(inbox_monitor._find_junk_folder(mail), "[Gmail]/Spam")

    def test_no_junk_folder(self):
        mail = self._mail([b'(\\HasNoChildren) "/" "Inbox"'])
        self.assertIsNone(inbox_monitor._find_junk_folder(mail))

    def test_failures_never_raise(self):
        self.assertIsNone(inbox_monitor._find_junk_folder(self._mail([], status="NO")))
        broken = MagicMock()
        broken.list.side_effect = RuntimeError("boom")
        self.assertIsNone(inbox_monitor._find_junk_folder(broken))


if __name__ == "__main__":
    unittest.main()
