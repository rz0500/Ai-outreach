"""Outreach goes out on weekdays only: scheduling rolls to Monday and the send loop rests at weekends."""

import datetime
import unittest
from unittest.mock import patch

import web_app

UTC = datetime.timezone.utc


def _utc(y, m, d, h=0, mi=0):
    return datetime.datetime(y, m, d, h, mi, tzinfo=UTC)


class TestNextSendTime(unittest.TestCase):
    """London: BST (UTC+1) until 25 Oct 2026, GMT after."""

    def _next(self, now, tz="Europe/London"):
        with patch.dict("os.environ", {"SEND_WEEKENDS": ""}):
            return web_app._next_8am_utc(tz, now=now)

    def test_midweek_goes_to_next_morning(self):
        # Wed 30 Sep 10:00 BST -> Thu 1 Oct 08:00 BST = 07:00 UTC
        self.assertEqual(self._next(_utc(2026, 9, 30, 9)), datetime.datetime(2026, 10, 1, 7, 0))

    def test_friday_after_eight_rolls_to_monday(self):
        # Fri 2 Oct 11:00 BST -> Mon 5 Oct 08:00 BST = 07:00 UTC
        self.assertEqual(self._next(_utc(2026, 10, 2, 10)), datetime.datetime(2026, 10, 5, 7, 0))

    def test_saturday_and_sunday_roll_to_monday(self):
        monday = datetime.datetime(2026, 10, 5, 7, 0)
        self.assertEqual(self._next(_utc(2026, 10, 3, 12)), monday)   # Saturday
        self.assertEqual(self._next(_utc(2026, 10, 4, 12)), monday)   # Sunday

    def test_early_monday_morning_is_still_today(self):
        # Mon 5 Oct 06:00 BST is before 08:00: send today
        self.assertEqual(self._next(_utc(2026, 10, 5, 5)), datetime.datetime(2026, 10, 5, 7, 0))

    def test_early_saturday_morning_still_waits_for_monday(self):
        self.assertEqual(self._next(_utc(2026, 10, 3, 5)), datetime.datetime(2026, 10, 5, 7, 0))

    def test_clock_change_is_handled(self):
        # Fri 23 Oct (BST) -> Mon 26 Oct: clocks went back on 25 Oct, so 08:00 is now 08:00 UTC
        self.assertEqual(self._next(_utc(2026, 10, 23, 10)), datetime.datetime(2026, 10, 26, 8, 0))
        # deep winter
        self.assertEqual(self._next(_utc(2026, 12, 4, 10)), datetime.datetime(2026, 12, 7, 8, 0))

    def test_other_timezones_use_their_own_weekend(self):
        # Fri 2 Oct 20:00 UTC is already Saturday 06:00 in Sydney (UTC+10) -> Monday 08:00 Sydney = Sun 22:00 UTC
        self.assertEqual(self._next(_utc(2026, 10, 2, 20), tz="Australia/Sydney"),
                         datetime.datetime(2026, 10, 4, 21, 0))

    def test_weekends_allowed_when_switched_on(self):
        with patch.dict("os.environ", {"SEND_WEEKENDS": "true"}):
            self.assertEqual(web_app._next_8am_utc("Europe/London", now=_utc(2026, 10, 3, 12)),
                             datetime.datetime(2026, 10, 4, 7, 0))   # Sunday 08:00 BST


class TestWeekendGuard(unittest.TestCase):
    def test_weekend_detection_in_uk_time(self):
        with patch.dict("os.environ", {"SEND_WEEKENDS": ""}):
            self.assertFalse(web_app._is_weekend(_utc(2026, 10, 2, 22)))   # Fri 23:00 BST
            self.assertTrue(web_app._is_weekend(_utc(2026, 10, 2, 23, 30)))   # Sat 00:30 BST
            self.assertTrue(web_app._is_weekend(_utc(2026, 10, 4, 12)))    # Sunday
            self.assertFalse(web_app._is_weekend(_utc(2026, 10, 4, 23, 30)))  # Mon 00:30 BST

    def test_switch_turns_the_guard_off(self):
        with patch.dict("os.environ", {"SEND_WEEKENDS": "yes"}):
            self.assertFalse(web_app._is_weekend(_utc(2026, 10, 3, 12)))

    def test_send_loop_does_nothing_at_the_weekend(self):
        with patch.object(web_app, "_is_weekend", return_value=True), \
             patch.object(web_app.database, "get_pending_sends") as pending, \
             patch.object(web_app, "_route_send_email") as send:
            web_app._send_scheduled_outreach()
        pending.assert_not_called()
        send.assert_not_called()

    def test_send_loop_runs_on_weekdays(self):
        with patch.object(web_app, "_is_weekend", return_value=False), \
             patch.object(web_app.database, "get_pending_sends", return_value=[]) as pending:
            web_app._send_scheduled_outreach()
        pending.assert_called_once()


if __name__ == "__main__":
    unittest.main()
