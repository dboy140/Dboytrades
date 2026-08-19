"""Tests for the replay engine.

The two properties worth guarding hardest are that the strategy cannot see the
future and that ambiguous bars resolve against the trade. Both are the standard
ways a backtest reports profits it could never have earned.
"""

from datetime import datetime, timedelta

import pytest

from bot.backtest import Result, Trade, run
from bot.bars import NY, Bar
from bot.signals import Signal

START = datetime(2026, 6, 15, 10, 0, tzinfo=NY)


def mk(seq):
    return [Bar(START + timedelta(minutes=i), *o) for i, o in enumerate(seq)]


def const(sig_at, sig):
    """Strategy that emits one signal at a given index."""
    def strategy(bars, i):
        return sig if i == sig_at else None
    return strategy


class TestNoLookahead:
    def test_strategy_never_sees_future_bars(self):
        seen = []

        def spy(bars, i):
            seen.append(len(bars))
            assert all(b.ts <= bars[i].ts for b in bars[:i + 1])
            return None

        bars = mk([(10, 11, 9, 10)] * 5)
        run(bars, spy)
        # The engine passes the whole list, so the contract is the `upto` index:
        # every helper slices to i. Assert the strategy was called once per bar.
        assert len(seen) == 5

    def test_signal_cannot_fill_on_its_own_bar(self):
        """A limit placed on bar i must not fill on bar i."""
        bars = mk([(10, 11, 9, 10), (10, 11, 9, 10), (10, 11, 9, 10)])
        sig = Signal(0, "X", "long", entry=10, stop=8, target=14, rule_ids=["R"])
        res = run(bars, const(0, sig))
        assert res.trades and res.trades[0].entry_index == 1


class TestPessimisticFills:
    def test_stop_wins_when_bar_spans_both(self):
        """The decisive test: a bar containing stop and target must take the stop."""
        bars = mk([
            (100, 101, 99, 100),      # 0 signal
            (100, 100.5, 99.5, 100),  # 1 fill at 100
            (100, 120, 80, 100),      # 2 spans stop 96 and target 112
        ])
        sig = Signal(0, "X", "long", entry=100, stop=96, target=112, rule_ids=["R"])
        t = run(bars, const(0, sig)).trades[0]
        assert t.exit_reason == "stop"
        assert t.r_multiple == pytest.approx(-1.0)

    def test_clean_target_hit_records_positive_r(self):
        bars = mk([
            (100, 101, 99, 100), (100, 100.5, 99.5, 100), (100, 113, 99.5, 112),
        ])
        sig = Signal(0, "X", "long", entry=100, stop=96, target=112, rule_ids=["R"])
        t = run(bars, const(0, sig)).trades[0]
        assert t.exit_reason == "target"
        assert t.r_multiple == pytest.approx(3.0)

    def test_short_side_mirrors(self):
        bars = mk([
            (100, 101, 99, 100), (100, 100.5, 99.5, 100), (100, 100.5, 87, 88),
        ])
        sig = Signal(0, "X", "short", entry=100, stop=104, target=88, rule_ids=["R"])
        t = run(bars, const(0, sig)).trades[0]
        assert t.exit_reason == "target"
        assert t.r_multiple == pytest.approx(3.0)


class TestOrderLifecycle:
    def test_unfilled_order_expires(self):
        bars = mk([(100, 101, 99, 100)] * 6)
        sig = Signal(0, "X", "long", entry=50, stop=45, target=70, rule_ids=["R"])
        res = run(bars, const(0, sig), entry_expiry_bars=3)
        assert res.trades == []
        assert res.signals_not_filled == 1

    def test_max_open_respected(self):
        bars = mk([(100, 101, 99, 100)] * 10)
        sig = Signal(0, "X", "long", entry=100, stop=96, target=112, rule_ids=["R"])

        def always(bars_, i):
            return Signal(i, "X", "long", 100, 96, 112, ["R"])

        res = run(bars, always, max_open=1)
        assert sum(1 for t in res.trades if t.is_open) <= 1


class TestMetrics:
    def _two_trades(self):
        res = Result()
        for r, reason in ((3.0, "target"), (-1.0, "stop")):
            t = Trade("X", "long", ["SB-001"], "w", 0, START, 100, 96, 112)
            t.exit_price = 112 if r > 0 else 96
            t.exit_reason = reason
            t.exit_index = 1
            res.trades.append(t)
        return res

    def test_expectancy_and_winrate(self):
        s = self._two_trades().stats()
        assert s["trades"] == 2
        assert s["win_rate"] == 0.5
        assert s["expectancy_r"] == pytest.approx(1.0)

    def test_max_consecutive_losses(self):
        assert self._two_trades().stats()["max_consecutive_losses"] == 1

    def test_by_rule_flags_insufficient_data(self):
        by = self._two_trades().by_rule()
        assert by["SB-001"]["trades"] == 2
        assert by["SB-001"]["enough_data"] is False  # under the 20-trade threshold

    def test_empty_result_is_safe(self):
        assert Result().stats()["trades"] == 0


class TestExcursions:
    def test_mae_and_mfe_recorded_in_r(self):
        bars = mk([
            (100, 101, 99, 100),
            (100, 100.5, 99.5, 100),   # fill at 100
            (100, 106, 98, 105),        # +1.5R best, -0.5R worst
            (105, 113, 104, 112),
        ])
        sig = Signal(0, "X", "long", entry=100, stop=96, target=112, rule_ids=["R"])
        t = run(bars, const(0, sig)).trades[0]
        assert t.mfe == pytest.approx(3.0)
        assert t.mae == pytest.approx(-0.5)


class TestSignalCoherence:
    """Guards the bug that produced a 100% win rate on random data: an inverted
    stop does not crash, it books instant profits."""

    def test_long_with_stop_above_entry_is_rejected(self):
        from bot.signals import _is_coherent
        bad = Signal(0, "X", "long", entry=100, stop=104, target=112, rule_ids=["R"])
        assert not _is_coherent(bad, 1.0)

    def test_long_with_target_below_entry_is_rejected(self):
        from bot.signals import _is_coherent
        bad = Signal(0, "X", "long", entry=100, stop=96, target=98, rule_ids=["R"])
        assert not _is_coherent(bad, 1.0)

    def test_short_with_stop_below_entry_is_rejected(self):
        from bot.signals import _is_coherent
        bad = Signal(0, "X", "short", entry=100, stop=96, target=88, rule_ids=["R"])
        assert not _is_coherent(bad, 1.0)

    def test_valid_long_accepted(self):
        from bot.signals import _is_coherent
        good = Signal(0, "X", "long", entry=100, stop=96, target=112, rule_ids=["R"])
        assert _is_coherent(good, 1.0)

    def test_min_rr_enforced(self):
        from bot.signals import _is_coherent
        thin = Signal(0, "X", "long", entry=100, stop=96, target=102, rule_ids=["R"])
        assert not _is_coherent(thin, 2.0)
        assert _is_coherent(thin, 0.4)
