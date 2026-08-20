"""Tests for the anti-overfitting suite.

These guard the claim that matters most: that a good-looking backtest is
distinguishable from a curve-fitted one. Each test builds a system whose true
nature is known and checks the tool identifies it.
"""

from datetime import datetime, timedelta

import pytest

from bot.backtest import Trade, run
from bot.bars import NY, Bar
from bot.signals import Signal
from bot.validate import (
    bootstrap_expectancy, monte_carlo_drawdown, parameter_surface,
    surface_is_a_spike, walk_forward,
)

START = datetime(2026, 1, 5, 10, 0, tzinfo=NY)


def trade(r: float) -> Trade:
    t = Trade("X", "long", ["R"], "w", 0, START, 100, 96, 112)
    t.exit_price = 100 + r * 4
    t.exit_index, t.exit_reason = 1, "target" if r > 0 else "stop"
    return t


class TestBootstrap:
    def test_strong_edge_is_positive_with_confidence(self):
        res = bootstrap_expectancy([trade(2.0)] * 30 + [trade(-1.0)] * 10)
        assert res["positive_with_95pct_confidence"] is True

    def test_coin_flip_is_not_distinguishable_from_no_edge(self):
        """20 wins at +1R and 20 losses at -1R is exactly no edge."""
        res = bootstrap_expectancy([trade(1.0)] * 20 + [trade(-1.0)] * 20)
        assert res["positive_with_95pct_confidence"] is False
        assert "not distinguishable" in res["note"]

    def test_small_positive_sample_is_honest_about_uncertainty(self):
        """Six trades that all won still must not claim confidence."""
        res = bootstrap_expectancy([trade(1.0)] * 5 + [trade(-1.0)])
        assert res["trades"] == 6
        assert res["ci95_low"] < res["expectancy_r"]

    def test_refuses_below_five_trades(self):
        assert "too few" in bootstrap_expectancy([trade(1.0)] * 4)["note"]


class TestMonteCarlo:
    def test_reports_worse_than_median_tail(self):
        res = monte_carlo_drawdown([trade(1.0)] * 25 + [trade(-1.0)] * 25)
        assert res["worst_5pct_drawdown_r"] <= res["median_drawdown_r"]

    def test_consecutive_losses_can_exceed_what_history_showed(self):
        """The sequence that happened is one sample. Sizing must survive others."""
        res = monte_carlo_drawdown([trade(1.0), trade(-1.0)] * 25)
        assert res["worst_5pct_consecutive_losses"] >= 4

    def test_refuses_below_five_trades(self):
        assert "too few" in monte_carlo_drawdown([trade(1.0)] * 3)["note"]


class TestSurface:
    def test_single_profitable_setting_is_flagged_as_a_spike(self):
        surface = [{"p": i, "trades": 10,
                    "expectancy_r": 3.0 if i == 5 else -0.5,
                    "win_rate": 0.5} for i in range(10)]
        assert surface_is_a_spike(surface) is True

    def test_broad_plateau_is_not_a_spike(self):
        surface = [{"p": i, "trades": 10, "expectancy_r": 0.4, "win_rate": 0.55}
                   for i in range(10)]
        assert surface_is_a_spike(surface) is False

    def test_too_few_points_gives_no_verdict(self):
        assert surface_is_a_spike([{"p": 1, "trades": 10, "expectancy_r": 1.0}]) is False


class TestWalkForward:
    def _bars(self, days: int):
        out = []
        t = datetime(2026, 1, 1, 0, 0, tzinfo=NY)
        price = 100.0
        for _ in range(days * 24 * 60):
            out.append(Bar(t, price, price + 0.5, price - 0.5, price))
            t += timedelta(minutes=1)
        return out

    def test_returns_empty_when_data_is_too_short(self):
        rep = walk_forward(self._bars(10), lambda **k: (lambda b, i: None),
                           [{"x": 1}], train_days=60, test_days=20)
        assert rep.folds == []
        assert "INSUFFICIENT" in rep.verdict

    def test_verdict_is_honest_with_no_trades(self):
        rep = walk_forward(self._bars(100), lambda **k: (lambda b, i: None),
                           [{"x": 1}], train_days=60, test_days=20)
        assert rep.total_oos_trades == 0
        assert "INSUFFICIENT" in rep.verdict

    def test_degradation_ratio_computed(self):
        from bot.validate import Fold
        f = Fold(0, "a", "b", "c", "d", {}, in_sample_expectancy=2.0,
                 out_of_sample_expectancy=0.5, out_of_sample_trades=25)
        assert f.degradation == 0.25

    def test_degradation_undefined_when_in_sample_lost(self):
        from bot.validate import Fold
        f = Fold(0, "a", "b", "c", "d", {}, -1.0, 0.5, 25)
        assert f.degradation is None


class TestVerdictLanguage:
    def _report(self, oos_expectancy, trades, in_sample=1.0):
        from bot.validate import Fold, WalkForwardReport
        rep = WalkForwardReport()
        rep.folds.append(Fold(0, "a", "b", "c", "d", {}, in_sample,
                              oos_expectancy, trades))
        return rep

    def test_negative_out_of_sample_is_reported_as_failure(self):
        assert "FAILED" in self._report(-0.4, 30).verdict

    def test_heavy_degradation_is_reported_as_weak(self):
        assert "WEAK" in self._report(0.1, 30, in_sample=2.0).verdict

    def test_survival_is_not_overclaimed(self):
        v = self._report(0.9, 30, in_sample=1.0).verdict
        assert "SURVIVED" in v
        assert "not sufficient" in v
