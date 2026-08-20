"""Tests for the no-trade filters, position sizing and journal export."""

from datetime import datetime, timedelta

import pytest

from bot.bars import NY, Bar
from bot.filters import (
    agrees_with_order_flow, asian_range, asian_range_ok, low_resistance,
    weekday_preferred, within_htf_range,
)
from bot.risk import correlated, daily_budget_left, position_size

START = datetime(2026, 6, 15, 10, 0, tzinfo=NY)


def mk(seq, start=START, step_minutes=1):
    return [Bar(start + timedelta(minutes=i * step_minutes), *o)
            for i, o in enumerate(seq)]


SWINGY = [
    (99, 100, 98, 99.5), (99.5, 101, 99, 100.5), (100.5, 105, 100, 104),
    (104, 104.5, 102, 102.5), (102.5, 103, 101, 101.5),
    (101.5, 102, 100, 100.5), (100.5, 101, 99.5, 100),
]


class TestLowResistance:
    """MM-006 is the system's strongest claim, so it gets the most scrutiny."""

    def test_intermediate_high_blocks_a_long(self):
        r = low_resistance(100, 110, "long", mk(SWINGY), 6, htf_minutes=0)
        assert not r.passed
        assert r.rule_id == "MM-006"
        assert "105" in r.reason

    def test_clean_path_passes(self):
        assert low_resistance(100, 104.9, "long", mk(SWINGY), 6, htf_minutes=0).passed

    def test_target_itself_is_not_a_blocker(self):
        """The nearest pool IS the target; it must not veto its own trade."""
        assert low_resistance(100, 105.0, "long", mk(SWINGY), 6, htf_minutes=0).passed

    def test_short_side_mirrors(self):
        seq = [(101, 102, 100, 101.5), (101.5, 102, 100.5, 101),
               (101, 101.5, 95, 95.5), (95.5, 98, 95.2, 97.5),
               (97.5, 99, 97, 98.5), (98.5, 100, 98, 99.5), (99.5, 101, 99, 100.5)]
        r = low_resistance(100, 90, "short", mk(seq), 6, htf_minutes=0)
        assert not r.passed and "95" in r.reason


class TestHTFRange:
    def test_inside_range_is_internal_liquidity(self):
        assert within_htf_range(100, 110, htf_high=120, htf_low=90).passed

    def test_target_outside_range_fails(self):
        assert not within_htf_range(100, 130, htf_high=120, htf_low=90).passed


class TestAsianRange:
    # Must span midnight: the Asian session is the PREVIOUS New York day, so a
    # fixture confined to one date computes nothing and the filter falls
    # through to "not applied" -- passing for the wrong reason.
    def _overnight(self, asian_ohlc):
        start = datetime(2026, 6, 14, 20, 0, tzinfo=NY)   # 20:00 NY
        asian = mk([asian_ohlc] * 240, start=start)        # 20:00 -> 00:00
        london = mk([(1.1005, 1.1008, 1.1000, 1.1003)] * 180,
                    start=datetime(2026, 6, 15, 2, 0, tzinfo=NY))
        return asian + london

    def test_fixture_actually_spans_two_days(self):
        """Guards the trap this test previously fell into."""
        bars = self._overnight((1.1000, 1.1010, 1.0995, 1.1005))
        assert asian_range(bars, len(bars) - 1) is not None

    def test_tight_range_passes(self):
        bars = self._overnight((1.1000, 1.1010, 1.0995, 1.1005))
        r = asian_range_ok(bars, len(bars) - 1, pip_size=0.0001, max_pips=30)
        assert r.passed
        assert "not applied" not in r.reason      # computed, not skipped
        assert "15 pips" in r.reason

    def test_wide_range_blocks_london(self):
        bars = self._overnight((1.1000, 1.1080, 1.0940, 1.1005))
        r = asian_range_ok(bars, len(bars) - 1, pip_size=0.0001, max_pips=30)
        assert not r.passed
        assert "exceeds" in r.reason

    def test_missing_session_does_not_block(self):
        """Absent data must not silently veto every trade."""
        r = asian_range_ok(mk([(1.1, 1.1, 1.1, 1.1)] * 5), 4)
        assert r.passed and "not applied" in r.reason


class TestOrderFlow:
    def test_agreement_passes(self):
        assert agrees_with_order_flow("long", "long").passed

    def test_opposition_blocks(self):
        r = agrees_with_order_flow("long", "short")
        assert not r.passed and r.rule_id == "SMC-005"

    def test_no_bias_stands_aside(self):
        """HTF-003 permits having no bias; that means no trade, not a free pass."""
        assert not agrees_with_order_flow("long", None).passed


class TestWeekday:
    def test_monday_preferred(self):
        mon = mk([(1, 2, 0.5, 1.5)], start=datetime(2026, 6, 15, 10, tzinfo=NY))
        assert weekday_preferred(mon, 0).passed

    def test_friday_flagged_but_advisory(self):
        fri = mk([(1, 2, 0.5, 1.5)], start=datetime(2026, 6, 19, 10, tzinfo=NY))
        assert not weekday_preferred(fri, 0).passed


class TestPositionSizing:
    def test_matches_the_documented_nas100_example(self):
        """00-SYSTEM.md section 8 worked example: 6 contracts, GBP240, 0.96%."""
        p = position_size(25000, 1.0, 40, 1.0)
        assert p.size == 6
        assert p.risk_currency == 240.0
        assert p.risk_pct_actual == pytest.approx(0.96)

    def test_matches_the_documented_eurusd_example(self):
        p = position_size(25000, 1.0, 12, 10.0, lot_step=0.1)
        assert p.size == pytest.approx(2.0)
        assert p.risk_currency == 240.0

    def test_always_rounds_down(self):
        """Rounding up breaches the risk limit on every trade."""
        p = position_size(10000, 1.0, 33, 1.0)
        assert p.size == 3           # 100/33 = 3.03
        assert p.risk_currency <= 100

    def test_rejects_zero_stop(self):
        with pytest.raises(ValueError):
            position_size(25000, 1.0, 0, 1.0)

    def test_correlation_detection(self):
        assert correlated("NAS100", "ES")
        assert correlated("EURUSD", "GBPUSD")
        assert not correlated("NAS100", "EURUSD")

    def test_daily_budget(self):
        assert daily_budget_left(1.0) == pytest.approx(1.0)
        assert daily_budget_left(2.5) == 0.0


class TestJournal:
    def test_row_has_every_template_column(self, tmp_path):
        import csv as _csv
        from bot import journal
        from bot.backtest import Trade

        t = Trade("Silver Bullet", "long", ["SB-001", "SB-003", "MM-006"],
                  "silver_bullet_am", 0, START, 100, 96, 112)
        t.exit_price, t.exit_reason, t.exit_index = 112, "target", 1
        out = tmp_path / "j.csv"
        journal.write(out, [t], "NAS100", account=25000.0)

        rows = list(_csv.DictReader(open(out)))
        template = list(_csv.reader(open("strategy/backtest-template.csv")))[0]
        assert list(rows[0].keys()) == template
        assert rows[0]["rule_ids"] == "SB-001,SB-003,MM-006"
        assert rows[0]["resistance_class"] == "low"
        assert rows[0]["tier"] == "A"
        assert rows[0]["r_multiple"] == "3.0"

    def test_resistance_unchecked_when_filter_absent(self, tmp_path):
        from bot import journal
        from bot.backtest import Trade
        t = Trade("Silver Bullet", "long", ["SB-001"], "w", 0, START, 100, 96, 112)
        t.exit_price, t.exit_reason = 112, "target"
        out = tmp_path / "j.csv"
        journal.write(out, [t], "NAS100")
        import csv as _csv
        assert list(_csv.DictReader(open(out)))[0]["resistance_class"] == "unchecked"


class TestResistanceTimeframe:
    """MM-007: lower-timeframe apparent resistance is not resistance. Evaluated
    on 1m bars this filter rejected 100% of signals on real-shaped data."""

    def _choppy_range(self):
        """Sawtooth between roughly 100 and 102.5, ending near the low.

        Many micro highs sit between the close and a 103 target on 1m, but the
        15m aggregation smooths them into a handful of levels.
        """
        seq, price = [], 100.0
        up = True
        for i in range(240):
            step = 0.06 if up else -0.06
            o = price
            c = o + step
            seq.append((o, max(o, c) + 0.01, min(o, c) - 0.01, c))
            price = c
            if price > 102.4:
                up = False
            elif price < 100.2:
                up = True
        return mk(seq)

    def test_execution_timeframe_sees_resistance_everywhere(self):
        bars = self._choppy_range()
        r = low_resistance(bars[-1].close, 103.0, "long",
                           bars, len(bars) - 1, htf_minutes=0)
        assert not r.passed          # dozens of micro-swings in the way
        assert "opposing level" in r.reason

    def test_higher_timeframe_sees_far_fewer_obstacles(self):
        bars = self._choppy_range()
        lo = low_resistance(bars[-1].close, 103.0, "long", bars,
                            len(bars) - 1, htf_minutes=0)
        hi = low_resistance(bars[-1].close, 103.0, "long", bars,
                            len(bars) - 1, htf_minutes=15)
        n_lo = int(lo.reason.split()[2]) if not lo.passed else 0
        n_hi = int(hi.reason.split()[2]) if not hi.passed else 0
        assert n_hi < n_lo, (lo.reason, hi.reason)

    def test_genuine_htf_level_still_blocks(self):
        """The fix must not make the filter toothless."""
        seq, price = [], 100.0
        for i in range(120):
            o = price; c = o + 0.05
            seq.append((o, max(o, c) + 0.02, min(o, c) - 0.02, c)); price = c
        seq.append((price, price + 5.0, price - 0.1, price + 0.1))   # spike high
        for i in range(120):
            o = price; c = o - 0.02
            seq.append((o, max(o, c) + 0.02, min(o, c) - 0.02, c)); price = c
        bars = mk(seq)
        spike = max(b.high for b in bars)
        r = low_resistance(bars[-1].close, spike + 2.0, "long",
                           bars, len(bars) - 1, htf_minutes=15)
        assert not r.passed


class TestResample:
    def test_aggregates_ohlc_correctly(self):
        from bot.bars import resample
        bars = mk([(10, 12, 9, 11), (11, 15, 10, 14), (14, 14.5, 13, 13.5)])
        agg = resample(bars, 15)
        assert len(agg) == 1
        assert (agg[0].open, agg[0].high, agg[0].low, agg[0].close) == (10, 15, 9, 13.5)

    def test_splits_on_bucket_boundary(self):
        from bot.bars import resample
        bars = mk([(10, 11, 9, 10)] * 20)     # 20 one-minute bars from 10:00
        assert len(resample(bars, 15)) == 2   # 10:00-10:14, 10:15-10:19

    def test_rejects_zero_minutes(self):
        from bot.bars import resample
        with pytest.raises(ValueError):
            resample(mk([(10, 11, 9, 10)]), 0)
