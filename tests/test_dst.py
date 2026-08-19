"""Tests for the NY/UK conversion.

The DST mismatch is the most operationally dangerous detail in the system: for
about four weeks a year every session window lands an hour earlier in UK time,
and a fixed +5 offset would put the operator in the market at the wrong hour.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from scripts.dst_table import convert, mismatch_windows, offset_hours

NY = ZoneInfo("America/New_York")


class TestOffset:
    @pytest.mark.parametrize("month,day,expected", [
        (1, 15, 5),    # both standard
        (6, 15, 5),    # both DST
        (3, 15, 4),    # US on DST, UK not
        (10, 28, 4),   # US on DST, UK not
        (11, 15, 5),   # both standard again
    ])
    def test_known_offsets_2026(self, month, day, expected):
        assert offset_hours(datetime(2026, month, day, 12, tzinfo=NY)) == expected


class TestMismatchWindows:
    def test_two_windows_per_year(self):
        assert len(mismatch_windows(2026)) == 2
        assert len(mismatch_windows(2027)) == 2

    def test_2026_windows_match_the_published_table(self):
        """The system doc publishes these dates; they must not drift."""
        spring, autumn = mismatch_windows(2026)
        assert spring[0] == "2026-03-08"
        assert autumn[0] == "2026-10-25"

    def test_spring_window_is_about_three_weeks(self):
        a, b = mismatch_windows(2026)[0]
        days = (datetime.fromisoformat(b) - datetime.fromisoformat(a)).days
        assert 18 <= days <= 24, days

    def test_autumn_window_is_about_one_week(self):
        a, b = mismatch_windows(2026)[1]
        days = (datetime.fromisoformat(b) - datetime.fromisoformat(a)).days
        assert 5 <= days <= 9, days


class TestConversion:
    def test_silver_bullet_am_normally_1500_uk(self):
        assert convert("10:00", datetime(2026, 6, 15, tzinfo=NY)) == "15:00"

    def test_silver_bullet_am_is_1400_uk_in_the_window(self):
        assert convert("10:00", datetime(2026, 3, 15, tzinfo=NY)) == "14:00"

    def test_london_killzone_shifts_too(self):
        assert convert("02:00", datetime(2026, 6, 15, tzinfo=NY)) == "07:00"
        assert convert("02:00", datetime(2026, 3, 15, tzinfo=NY)) == "06:00"

    def test_pm_silver_bullet(self):
        assert convert("14:00", datetime(2026, 6, 15, tzinfo=NY)) == "19:00"
        assert convert("14:00", datetime(2026, 3, 15, tzinfo=NY)) == "18:00"
