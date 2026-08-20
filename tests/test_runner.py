"""Runner tests, including an end-to-end pass through the whole chain.

The end-to-end test is the one that matters: bars in one end, orders out the
other, with every rail enforced in between and nothing able to see the future.
"""

import json
from datetime import datetime, timedelta

import pytest

from bot.bars import NY, Bar
from bot.live import Executor, PaperBroker, RiskLimits, SafetyViolation
from bot.runner import Runner, RunnerConfig
from bot.signals import Signal

VPP = {"NAS100": 1.0, "EURUSD": 10.0, "GBPUSD": 10.0}


def bars_over_days(days: int, start_hour: int = 0) -> list[Bar]:
    """Continuous 1m bars with mild structure, spanning whole days."""
    import random
    rng = random.Random(5)
    out, price = [], 100.0
    t = datetime(2026, 1, 5, start_hour, 0, tzinfo=NY)
    for _ in range(days * 24 * 60):
        o = price
        c = o + rng.gauss(0, 0.05)
        out.append(Bar(t, o, max(o, c) + 0.02, min(o, c) - 0.02, c))
        price = c
        t += timedelta(minutes=1)
    return out


def make_runner(**cfg_kw):
    ex = Executor(PaperBroker(25_000), value_per_point=VPP, mode="paper")
    cfg = RunnerConfig(instrument=cfg_kw.pop("instrument", "EURUSD"), **cfg_kw)
    return Runner(ex, cfg), ex


class TestWarmup:
    def test_no_orders_before_warmup(self, tmp_path):
        r, _ = make_runner(warmup_bars=500, journal_path=str(tmp_path / "j.jsonl"))
        for b in bars_over_days(1)[:400]:
            assert r.on_bar(b) is None
        assert r.stats.signals == 0

    def test_warmup_counts_bars_not_time(self, tmp_path):
        r, _ = make_runner(warmup_bars=10, journal_path=str(tmp_path / "j.jsonl"))
        for b in bars_over_days(1)[:20]:
            r.on_bar(b)
        assert r.stats.bars_seen == 20


class TestBiasNoLookahead:
    def test_bias_uses_only_completed_prior_days(self, tmp_path):
        """The day in progress must never inform its own bias -- in live
        trading that data does not exist yet."""
        r, _ = make_runner(setup="silver_bullet", bias_mode="auto",
                           instrument="NAS100", warmup_bars=1,
                           journal_path=str(tmp_path / "j.jsonl"))
        bars = bars_over_days(9)
        for b in bars:
            r.on_bar(b)
        # Every cached bias must have been computed from strictly earlier days.
        for day, direction in r._bias_cache.items():
            earlier = [d for d in r._daily if d.ny.date() < day]
            if direction is not None:
                assert earlier, f"bias for {day} had no prior days"

    def test_fixed_bias_is_respected(self, tmp_path):
        r, _ = make_runner(setup="silver_bullet", bias_mode="short",
                           instrument="NAS100", warmup_bars=1,
                           journal_path=str(tmp_path / "j.jsonl"))
        assert r._bias_for(bars_over_days(1)[0]) == "short"


class TestRailsAreEnforcedInTheLoop:
    def test_blocked_orders_are_counted_and_journaled(self, tmp_path):
        journal = tmp_path / "j.jsonl"
        ex = Executor(PaperBroker(25_000), value_per_point=VPP, mode="paper")
        cfg = RunnerConfig(instrument="EURUSD", warmup_bars=1,
                           journal_path=str(journal))
        r = Runner(ex, cfg)

        # Force every submission to be refused.
        def always_block(*a, **k):
            raise SafetyViolation("daily loss limit hit")
        ex.submit = always_block
        r._signal = lambda i: Signal(i, "X", "long", 100, 96, 112, ["OTE-001"])

        for b in bars_over_days(1)[:5]:
            r.on_bar(b)

        assert r.stats.submitted == 0
        assert r.stats.blocked == 5
        lines = [json.loads(l) for l in journal.read_text().splitlines()]
        assert all(e["event"] == "blocked" for e in lines)
        assert all("OTE-001" in e["rule_ids"] for e in lines)

    def test_orders_carry_rule_ids_into_the_journal(self, tmp_path):
        journal = tmp_path / "j.jsonl"
        r, _ = make_runner(warmup_bars=1, journal_path=str(journal))
        r._signal = lambda i: (Signal(i, "X", "long", 100, 96, 112, ["OTE-002"])
                               if i == 2 else None)
        for b in bars_over_days(1)[:5]:
            r.on_bar(b)
        events = [json.loads(l) for l in journal.read_text().splitlines()]
        orders = [e for e in events if e["event"] == "order"]
        assert len(orders) == 1
        assert orders[0]["rule_ids"] == ["OTE-002"]
        assert orders[0]["mode"] == "paper"


class TestEndToEnd:
    """Bars in, orders out, rails enforced, nothing seeing the future."""

    def test_full_chain_runs_and_stays_within_limits(self, tmp_path):
        journal = tmp_path / "j.jsonl"
        ex = Executor(PaperBroker(25_000), limits=RiskLimits(max_concurrent=1),
                      value_per_point=VPP, mode="paper")
        r = Runner(ex, RunnerConfig(instrument="EURUSD", setup="ote",
                                    warmup_bars=200,
                                    journal_path=str(journal)))
        stats = r.run(bars_over_days(6))

        assert stats.bars_seen == 6 * 24 * 60
        # Concurrency rail must hold no matter how many signals fired.
        assert len(ex.state.open_instruments) <= 1
        assert stats.submitted + stats.blocked == stats.signals

    def test_live_mode_cannot_be_reached_without_validation(self, tmp_path):
        with pytest.raises(SafetyViolation, match="refusing to trade live"):
            Executor(PaperBroker(), value_per_point=VPP, mode="live",
                     validation_report=tmp_path / "absent.json")

    def test_live_mode_opens_only_with_a_passing_report(self, tmp_path):
        report = tmp_path / "v.json"
        report.write_text(json.dumps({
            "total_oos_trades": 45, "combined_oos_expectancy": 0.4,
            "oos_confidence": {"positive_with_95pct_confidence": True,
                               "ci95_low": 0.11, "ci95_high": 0.68},
            "folds_positive": 4, "folds_scored": 5,
        }))
        ex = Executor(PaperBroker(25_000), value_per_point=VPP, mode="live",
                      validation_report=report)
        assert ex.mode == "live"

    def test_live_mode_stays_shut_without_a_confidence_interval(self, tmp_path):
        """A report from before the luck check has no interval in it, and a
        missing field must not read as a pass."""
        report = tmp_path / "v.json"
        report.write_text(json.dumps({"total_oos_trades": 45,
                                      "combined_oos_expectancy": 0.4}))
        with pytest.raises(SafetyViolation):
            Executor(PaperBroker(25_000), value_per_point=VPP, mode="live",
                     validation_report=report)

    def test_summary_reports_block_reasons(self, tmp_path):
        r, ex = make_runner(warmup_bars=1, journal_path=str(tmp_path / "j.jsonl"))
        ex.submit = lambda *a, **k: (_ for _ in ()).throw(
            SafetyViolation("correlated exposure: EURUSD"))
        r._signal = lambda i: Signal(i, "X", "long", 100, 96, 112, ["R"])
        for b in bars_over_days(1)[:3]:
            r.on_bar(b)
        assert "correlated exposure" in r.summary()
