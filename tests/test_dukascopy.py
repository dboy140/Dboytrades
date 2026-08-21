"""Tests for the Dukascopy feed decoder.

The download itself is not tested -- it needs the network, and the build
environment has no egress. What is tested is everything that can go wrong
*quietly*: a zero-indexed month fetching the wrong data, a point factor
scaling every price by 100, a tick landing in the wrong minute. None of those
raise. They produce a well-formed file that is simply wrong, which a backtest
will happily consume and report confident numbers from.
"""

from __future__ import annotations

import lzma
import struct
from datetime import datetime, timedelta, timezone

import pytest

from bot.dukascopy import (
    CSV_HEADER, TICK, Tick, decode_bi5, hour_url, hours_between, point_factor,
    rows_to_csv, ticks_to_minutes,
)

UTC = timezone.utc
HOUR = datetime(2024, 3, 5, 14, 0, tzinfo=UTC)


def bi5(ticks: list[tuple]) -> bytes:
    """Build a .bi5 payload the way Dukascopy does: LZMA-alone, 20-byte records."""
    raw = b"".join(TICK.pack(*t) for t in ticks)
    c = lzma.LZMACompressor(format=lzma.FORMAT_ALONE)
    return c.compress(raw) + c.flush()


class TestHourUrl:
    def test_month_is_zero_indexed(self):
        """January is 00. A 1-indexed month downloads the wrong month
        successfully, which is the worst kind of bug."""
        u = hour_url("EURUSD", datetime(2024, 1, 2, 3, tzinfo=UTC))
        assert "/2024/00/02/03h_ticks.bi5" in u

    def test_december_is_eleven(self):
        u = hour_url("EURUSD", datetime(2024, 12, 31, 23, tzinfo=UTC))
        assert "/2024/11/31/23h_ticks.bi5" in u

    def test_symbol_is_upper_cased(self):
        assert "/EURUSD/" in hour_url("eurusd", HOUR)


class TestPointFactor:
    def test_five_decimal_pairs(self):
        assert point_factor("EURUSD") == 1e5

    def test_jpy_pairs_are_three_decimal(self):
        assert point_factor("USDJPY") == 1e3

    def test_unknown_symbol_raises_rather_than_defaulting(self):
        """A default would scale prices silently. Better to stop."""
        with pytest.raises(KeyError, match="no point factor"):
            point_factor("EURNOK")


class TestDecode:
    def test_decodes_prices_and_times(self):
        payload = bi5([(0, 109_500, 109_480, 1.5, 2.5),
                       (1500, 109_510, 109_490, 1.0, 1.0)])
        ticks = decode_bi5(payload, "EURUSD", HOUR)
        assert len(ticks) == 2
        assert ticks[0].bid == pytest.approx(1.0948)
        assert ticks[0].ask == pytest.approx(1.0950)
        assert ticks[0].ts == HOUR
        assert ticks[1].ts == HOUR + timedelta(milliseconds=1500)

    def test_bid_and_ask_are_not_swapped(self):
        """The record is (ask, bid), not (bid, ask). Swapped, every spread
        inverts and every fill is on the wrong side."""
        ticks = decode_bi5(bi5([(0, 109_500, 109_480, 1.0, 1.0)]), "EURUSD", HOUR)
        assert ticks[0].ask > ticks[0].bid

    def test_jpy_scaling_differs(self):
        ticks = decode_bi5(bi5([(0, 151_234, 151_230, 1.0, 1.0)]), "USDJPY", HOUR)
        assert ticks[0].bid == pytest.approx(151.230)

    def test_empty_hour_is_normal_not_an_error(self):
        """Weekends come back empty. Raising here would abort a whole run."""
        assert decode_bi5(b"", "EURUSD", HOUR) == []

    def test_truncated_file_raises(self):
        c = lzma.LZMACompressor(format=lzma.FORMAT_ALONE)
        payload = c.compress(b"\x00" * 13) + c.flush()
        with pytest.raises(ValueError, match="whole number"):
            decode_bi5(payload, "EURUSD", HOUR)

    def test_undecompressable_payload_raises(self):
        with pytest.raises(ValueError, match="could not decompress"):
            decode_bi5(b"not lzma at all", "EURUSD", HOUR)


class TestAggregation:
    def _ticks(self, spec):
        return [Tick(HOUR + timedelta(seconds=s), bid, bid + 0.0002, v, v)
                for s, bid, v in spec]

    def test_ohlc_within_a_minute(self):
        rows = ticks_to_minutes(self._ticks([
            (0, 1.1000, 1.0), (10, 1.1020, 2.0),
            (20, 1.0990, 1.0), (30, 1.1005, 1.0)]))
        assert len(rows) == 1
        ts, o, h, l, c, v = rows[0]
        assert (o, h, l, c) == (1.1000, 1.1020, 1.0990, 1.1005)
        assert v == pytest.approx(5.0)

    def test_ticks_split_across_minutes(self):
        rows = ticks_to_minutes(self._ticks([
            (0, 1.1000, 1.0), (59, 1.1010, 1.0), (60, 1.1020, 1.0)]))
        assert len(rows) == 2
        assert rows[0][0] == HOUR
        assert rows[1][0] == HOUR + timedelta(minutes=1)
        assert rows[0][4] == 1.1010     # close of the first minute
        assert rows[1][1] == 1.1020     # open of the second

    def test_a_minute_with_no_ticks_produces_no_bar(self):
        """Never carried forward. An invented bar is indistinguishable from a
        real one once it is in the CSV."""
        rows = ticks_to_minutes(self._ticks([(0, 1.1, 1.0), (180, 1.2, 1.0)]))
        assert len(rows) == 2
        assert (rows[1][0] - rows[0][0]).total_seconds() == 180

    def test_rows_are_sorted_even_if_ticks_are_not(self):
        rows = ticks_to_minutes(self._ticks([(120, 1.2, 1.0), (0, 1.1, 1.0)]))
        assert [r[0] for r in rows] == sorted(r[0] for r in rows)

    def test_ask_side_gives_different_prices(self):
        ticks = self._ticks([(0, 1.1000, 1.0)])
        assert ticks_to_minutes(ticks, "bid")[0][1] == pytest.approx(1.1000)
        assert ticks_to_minutes(ticks, "ask")[0][1] == pytest.approx(1.1002)

    def test_rejects_a_nonsense_side(self):
        with pytest.raises(ValueError, match="bid.*ask"):
            ticks_to_minutes([], "mid")


class TestHoursBetween:
    def test_covers_the_range_exclusive_of_the_end(self):
        hrs = list(hours_between(datetime(2024, 1, 1, tzinfo=UTC),
                                 datetime(2024, 1, 1, 3, tzinfo=UTC)))
        assert len(hrs) == 3
        assert hrs[0].hour == 0 and hrs[-1].hour == 2

    def test_two_years_is_the_expected_count(self):
        hrs = list(hours_between(datetime(2024, 1, 1, tzinfo=UTC),
                                 datetime(2026, 1, 1, tzinfo=UTC)))
        assert len(hrs) == (365 + 366) * 24      # 2024 is a leap year

    def test_naive_datetimes_are_refused(self):
        with pytest.raises(ValueError, match="timezone-aware"):
            list(hours_between(datetime(2024, 1, 1), datetime(2024, 1, 2)))


class TestCsvOutput:
    def test_round_trips_through_the_loader(self):
        """The real contract: what this writes, bot.run_backtest must read."""
        from bot.run_backtest import load_csv
        rows = ticks_to_minutes([
            Tick(HOUR + timedelta(seconds=s), b, b + 0.0002, 1.0, 1.0)
            for s, b in [(0, 1.1000), (30, 1.1020), (60, 1.1010)]])
        text = rows_to_csv(rows)
        assert text.startswith(CSV_HEADER)

        import tempfile, pathlib
        p = pathlib.Path(tempfile.mkdtemp()) / "d.csv"
        p.write_text(text)
        bars = load_csv(str(p))
        assert len(bars) == 2
        assert bars[0].ts == HOUR
        assert bars[0].ts.tzinfo is not None
        assert bars[0].high == pytest.approx(1.1020)

    def test_timestamps_carry_an_offset(self):
        rows = ticks_to_minutes([Tick(HOUR, 1.1, 1.1002, 1.0, 1.0)])
        line = rows_to_csv(rows).splitlines()[1]
        assert "+00:00" in line
