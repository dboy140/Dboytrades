"""Tests for data validation.

The timezone check is the important one. MT4/MT5 exports carry broker server
time (usually UTC+2/+3); label those as UTC and every session window is wrong
by hours, while the backtest runs happily and reports confident numbers.
"""

import csv
import random
from datetime import datetime, timedelta, timezone

import pytest

from bot.bars import NY, Bar
from bot.inspect_data import (
    duplicates, find_gaps, hourly_range_profile, infer_ny_offset, restamp,
    session_coverage,
)

UTC = timezone.utc


def spiky_bars(shift_hours: int = 0, days: int = 8, seed: int = 1) -> list[Bar]:
    """Bars with a realistic volatility spike at the 09:30 New York open."""
    rng = random.Random(seed)
    out, t, price = [], datetime(2026, 6, 1, tzinfo=UTC), 20000.0
    for _ in range(60 * 24 * days):
        ny_hour = (t + timedelta(hours=-4)).hour        # June: NY is UTC-4
        vol = 12.0 if ny_hour == 9 else 2.0
        o = price
        c = o + rng.gauss(0, vol)
        out.append(Bar(t + timedelta(hours=shift_hours), o,
                       max(o, c) + abs(rng.gauss(0, vol / 3)),
                       min(o, c) - abs(rng.gauss(0, vol / 3)), c))
        price = c
        t += timedelta(minutes=1)
    return out


class TestTimezoneInference:
    def test_correctly_stamped_data_reports_no_drift(self):
        offset, _ = infer_ny_offset(spiky_bars(0))
        assert offset == 0

    @pytest.mark.parametrize("shift", [2, 3, -5])
    def test_shifted_data_is_detected(self, shift):
        """UTC+2 and UTC+3 are the common broker server times."""
        offset, _ = infer_ny_offset(spiky_bars(shift))
        assert offset == shift

    def test_diagnostics_show_a_real_spike(self):
        _, diag = infer_ny_offset(spiky_bars(0))
        assert diag["spike_ratio"] > 2.0

    def test_flat_data_gives_no_confident_answer(self):
        """Without a volatility spike there is nothing to infer from; the
        detector must not invent a shift."""
        flat = [Bar(datetime(2026, 6, 1, tzinfo=UTC) + timedelta(minutes=i),
                    100, 100.5, 99.5, 100) for i in range(60 * 24 * 3)]
        _, diag = infer_ny_offset(flat)
        assert diag["spike_ratio"] == pytest.approx(1.0, abs=0.15)


class TestRestamp:
    def test_round_trip_corrects_the_drift(self, tmp_path):
        src = tmp_path / "broker.csv"
        with open(src, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["timestamp", "open", "high", "low", "close", "volume"])
            for b in spiky_bars(3, days=4):
                w.writerow([b.ts.isoformat().replace("+00:00", "Z"),
                            b.open, b.high, b.low, b.close, 0])

        assert infer_ny_offset(spiky_bars(3, days=4))[0] == 3
        out = restamp(str(src), -3)

        from bot.run_backtest import load_csv
        assert infer_ny_offset(load_csv(out))[0] == 0

    def test_original_file_is_left_untouched(self, tmp_path):
        src = tmp_path / "x.csv"
        src.write_text("timestamp,open,high,low,close\n"
                       "2026-06-01T00:00:00Z,1,2,0.5,1.5\n")
        before = src.read_text()
        restamp(str(src), 3)
        assert src.read_text() == before


class TestIntegrity:
    def test_duplicates_counted(self):
        b = spiky_bars(0, days=1)
        assert duplicates(b) == 0
        assert duplicates(b + b[:5]) == 5

    def test_gaps_detected(self):
        b = spiky_bars(0, days=1)
        spliced = b[:100] + b[400:]
        gaps = find_gaps(spliced)
        # bar[99] to bar[400] is 301 minutes apart, not 300.
        assert gaps and gaps[0][2] == 301

    def test_continuous_data_has_no_gaps(self):
        assert find_gaps(spiky_bars(0, days=1)) == []


class TestSessionCoverage:
    def test_reports_bars_per_window(self):
        cov = session_coverage(spiky_bars(0, days=8))
        assert cov["silver_bullet_am"] > 0
        assert cov["silver_bullet_pm"] > 0

    def test_empty_window_is_visible(self):
        """A file with no bars in a window cannot test the rules that use it."""
        start = datetime(2026, 6, 15, 10, 0, tzinfo=NY)
        only_am = [Bar(start + timedelta(minutes=i), 100, 101, 99, 100)
                   for i in range(30)]
        cov = session_coverage(only_am)
        assert cov["silver_bullet_am"] > 0
        assert cov["london_killzone"] == 0


class TestProfile:
    def test_hourly_profile_peaks_at_the_open(self):
        prof = hourly_range_profile(spiky_bars(0))
        assert max(prof, key=prof.get) == 13   # 09:30 NY in June == 13:30 UTC
