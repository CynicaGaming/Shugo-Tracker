import datetime as dt
import unittest

from shugotracker.clock import clock_text, eastern_offset, server_now

U = dt.timezone.utc


class ClockTests(unittest.TestCase):
    def test_daylight_saving_edges(self):
        self.assertEqual(eastern_offset(dt.datetime(2026, 3, 8, 6, 59, tzinfo=U)), dt.timedelta(hours=-5))
        self.assertEqual(eastern_offset(dt.datetime(2026, 3, 8, 7, 0, tzinfo=U)), dt.timedelta(hours=-4))
        self.assertEqual(eastern_offset(dt.datetime(2026, 11, 1, 5, 59, tzinfo=U)), dt.timedelta(hours=-4))
        self.assertEqual(eastern_offset(dt.datetime(2026, 11, 1, 6, 0, tzinfo=U)), dt.timedelta(hours=-5))

    def test_server_time(self):
        ts = dt.datetime(2026, 10, 31, 8, 2, tzinfo=U).timestamp()      # 04:02 EDT
        self.assertEqual(server_now(ts).strftime("%H:%M"), "04:02")
        self.assertEqual(clock_text("ST", ts), "10/31/2026 04:02")
        ts = dt.datetime(2026, 12, 1, 17, 30, tzinfo=U).timestamp()     # 12:30 EST
        self.assertEqual(clock_text("ST", ts), "12/01/2026 12:30")
        ts = dt.datetime(2026, 11, 1, 2, 30, tzinfo=U).timestamp()      # still Oct 31 in the East
        self.assertEqual(clock_text("ST", ts), "10/31/2026 22:30")
