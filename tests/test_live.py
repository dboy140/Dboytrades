"""Tests for the execution rails.

Each rail exists because of a specific way accounts get destroyed. The tests
name the failure they prevent.
"""

import json
from datetime import datetime, timedelta

import pytest

from bot.bars import NY
from bot.live import (
    Executor, PaperBroker, RiskLimits, SafetyViolation, position_size,
    validation_allows_live,
)
from bot.signals import Signal

WHEN = datetime(2026, 6, 15, 10, 30, tzinfo=NY)
VPP = {"NAS100": 1.0, "EURUSD": 10.0, "GBPUSD": 10.0}


def sig(entry=100.0, stop=96.0, target=112.0, direction="long"):
    return Signal(0, "Silver Bullet", direction, entry, stop, target, ["SB-001"])


def ex(**kw):
    kw.setdefault("value_per_point", VPP)
    return Executor(PaperBroker(25_000), **kw)


class TestSizing:
    def test_matches_the_documented_arithmetic(self):
        # 25,000 x 1% = 250 risk; 250 / (40 x 1) = 6.25
        assert position_size(25_000, 1.0, 40, 1.0) == 6.25

    def test_rounds_down_never_up(self):
        """Rounding up breaches the risk limit on every trade."""
        size = position_size(25_000, 1.0, 12, 10.0)   # 2.083...
        assert size == 2.08
        assert size * 12 * 10 <= 250

    def test_rejects_nonsense_inputs(self):
        with pytest.raises(ValueError):
            position_size(25_000, 1.0, 0, 1.0)


class TestLiveGate:
    def test_live_refused_without_a_report(self, tmp_path):
        with pytest.raises(SafetyViolation, match="no validation report"):
            ex(mode="live", validation_report=tmp_path / "missing.json")

    def test_live_refused_on_too_few_oos_trades(self, tmp_path):
        p = tmp_path / "v.json"
        p.write_text(json.dumps({"total_oos_trades": 8, "combined_oos_expectancy": 1.5}))
        ok, why = validation_allows_live(p)
        assert not ok and "conclusive below 30" in why

    def test_live_refused_when_the_interval_includes_zero(self, tmp_path):
        """The check that a pure random walk defeated.

        Noise cleared 'enough trades' and 'positive expectancy' and was
        declared SURVIVED, which opened this gate. A positive average over a
        modest sample is exactly what no edge looks like some of the time.
        """
        p = tmp_path / "v.json"
        p.write_text(json.dumps({
            "total_oos_trades": 45, "combined_oos_expectancy": 0.26,
            "oos_confidence": {"positive_with_95pct_confidence": False,
                               "ci95_low": -0.11, "ci95_high": 0.63},
            "folds_positive": 3, "folds_scored": 4,
        }))
        ok, why = validation_allows_live(p)
        assert not ok and "not distinguishable from luck" in why

    def test_live_refused_when_only_a_minority_of_windows_worked(self, tmp_path):
        p = tmp_path / "v.json"
        p.write_text(json.dumps({
            "total_oos_trades": 60, "combined_oos_expectancy": 0.4,
            "oos_confidence": {"positive_with_95pct_confidence": True,
                               "ci95_low": 0.08, "ci95_high": 0.71},
            "folds_positive": 2, "folds_scored": 5,
        }))
        ok, why = validation_allows_live(p)
        assert not ok and "2 of 5" in why

    def test_a_report_predating_the_confidence_check_is_refused(self, tmp_path):
        """Silence is not evidence. An older report simply has no interval in
        it, and treating a missing field as a pass would reopen the hole."""
        p = tmp_path / "v.json"
        p.write_text(json.dumps({"total_oos_trades": 60,
                                 "combined_oos_expectancy": 0.35}))
        ok, why = validation_allows_live(p)
        assert not ok and "re-run validation" in why

    def test_live_refused_when_edge_died_out_of_sample(self, tmp_path):
        p = tmp_path / "v.json"
        p.write_text(json.dumps({"total_oos_trades": 60, "combined_oos_expectancy": -0.2}))
        ok, why = validation_allows_live(p)
        assert not ok and "did not survive" in why

    def test_live_allowed_only_with_real_evidence(self, tmp_path):
        p = tmp_path / "v.json"
        p.write_text(json.dumps({
            "total_oos_trades": 60, "combined_oos_expectancy": 0.35,
            "oos_confidence": {"positive_with_95pct_confidence": True,
                               "ci95_low": 0.09, "ci95_high": 0.62},
            "folds_positive": 4, "folds_scored": 5,
        }))
        ok, why = validation_allows_live(p)
        assert ok and "validated" in why

    def test_paper_mode_needs_no_report(self):
        assert ex(mode="paper").mode == "paper"


class TestRails:
    def test_daily_loss_limit_halts_trading(self):
        e = ex()
        e.state.day = WHEN.date()
        e.state.realised_pct_today = -2.0
        with pytest.raises(SafetyViolation, match="daily loss limit"):
            e.submit(sig(), "NAS100", "A", WHEN)

    def test_consecutive_losses_halt_trading(self):
        e = ex()
        e.state.day = WHEN.date()
        e.state.consecutive_losses = 4
        with pytest.raises(SafetyViolation, match="consecutive losses"):
            e.submit(sig(), "NAS100", "A", WHEN)

    def test_max_concurrent_enforced(self):
        e = ex(limits=RiskLimits(max_concurrent=1))
        e.submit(sig(), "NAS100", "A", WHEN)
        with pytest.raises(SafetyViolation, match="max concurrent"):
            e.submit(sig(), "XAUUSD", "A", WHEN)

    def test_correlated_exposure_blocked(self):
        """Two correlated positions at 1% is a 2% trade wearing a disguise."""
        e = ex()
        e.submit(sig(), "EURUSD", "A", WHEN)
        with pytest.raises(SafetyViolation, match="correlated"):
            e.submit(sig(), "GBPUSD", "A", WHEN)

    def test_unknown_instrument_refuses_rather_than_guessing(self):
        e = ex()
        with pytest.raises(SafetyViolation, match="value-per-point"):
            e.submit(sig(), "SOMETHING_NEW", "A", WHEN)

    def test_tier_c_is_zero_size(self):
        e = ex()
        with pytest.raises(SafetyViolation, match="study-only"):
            e.submit(sig(), "NAS100", "C", WHEN)

    def test_new_day_resets_the_halt(self):
        e = ex()
        e.state.day = WHEN.date()
        e.state.realised_pct_today = -2.0
        e.state.halted = True
        e.state.halt_reason = "daily loss"
        out = e.submit(sig(), "NAS100", "A", WHEN + timedelta(days=1))
        assert out["order_id"]


class TestBookkeeping:
    def test_win_resets_the_loss_streak(self):
        e = ex()
        e.state.consecutive_losses = 3
        e.record_close("NAS100", 2.0, 1.0)
        assert e.state.consecutive_losses == 0

    def test_loss_increments_the_streak_and_the_daily_pct(self):
        e = ex()
        e.record_close("NAS100", -1.0, 1.0)
        assert e.state.consecutive_losses == 1
        assert e.state.realised_pct_today == -1.0

    def test_order_carries_its_rule_ids(self):
        out = ex().submit(sig(), "NAS100", "A", WHEN)
        assert out["rule_ids"] == ["SB-001"]
        assert out["mode"] == "paper"
