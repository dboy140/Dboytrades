"""Tests for the automated bias heuristic.

This is the one component in the repo that is NOT derived from a cited rule --
HTF-001 says "the larger pool" and never defines larger. The tests therefore
pin down the behaviour I chose, including its refusals, so the arbitrariness
stays visible.
"""

from datetime import datetime, timedelta

import pytest

from bot.bars import NY, Bar
from bot.bias import _cluster, _unswept, daily_bias

START = datetime(2026, 1, 5, 0, 0, tzinfo=NY)


def mk(seq):
    return [Bar(START + timedelta(days=i), *o) for i, o in enumerate(seq)]


class TestClustering:
    def test_near_equal_levels_become_one_deep_pool(self):
        """Equal highs are one pool, not three -- the corpus treats them as a
        single liquidity marker."""
        assert _cluster([100.0, 100.1, 100.05], 0.0015) == [(pytest.approx(100.05), 3)]

    def test_distant_levels_stay_separate(self):
        out = _cluster([100.0, 120.0], 0.0015)
        assert len(out) == 2

    def test_empty(self):
        assert _cluster([], 0.0015) == []


class TestUnswept:
    def test_swept_high_is_excluded(self):
        """A pool already taken is spent and is no longer a draw."""
        bars = mk([
            (10, 11, 10, 10.5), (10.5, 12, 10.4, 11.8), (11.8, 15, 11.7, 14.8),
            (14.8, 15.1, 13, 13.2), (13.2, 13.5, 12, 12.2),
            (12.2, 16, 12.1, 15.8),   # trades above the 15 swing high -> swept
            (15.8, 16.1, 15, 15.2), (15.2, 15.4, 14, 14.2),
        ])
        highs, _ = _unswept(bars, upto=7, lookback=2)
        assert not any(abs(h - 15.0) < 0.01 for h in highs)

    def test_untouched_high_is_kept(self):
        bars = mk([
            (10, 11, 10, 10.5), (10.5, 12, 10.4, 11.8), (11.8, 15, 11.7, 14.8),
            (14.8, 14.9, 13, 13.2), (13.2, 13.5, 12, 12.2),
            (12.2, 12.6, 11.5, 11.8), (11.8, 12.0, 11, 11.2), (11.2, 11.5, 10.5, 10.8),
        ])
        highs, _ = _unswept(bars, upto=7, lookback=2)
        assert any(abs(h - 15.0) < 0.01 for h in highs)


class TestBias:
    def test_returns_none_without_enough_structure(self):
        res = daily_bias(mk([(10, 10.5, 9.5, 10)] * 6), upto=5)
        assert res.direction is None
        assert "not enough structure" in res.reason

    # An unswept high at 13.0 and an unswept low at 7.0, with price closing at
    # 10.0 -- equidistant, so neither side can clear the margin.
    BALANCED = [
        (10, 10.5, 9.5, 10.2),
        (10.2, 11.0, 10.0, 10.8),
        (10.8, 13.0, 10.7, 12.5),   # swing high 13.0
        (12.5, 12.6, 11.0, 11.2),
        (11.2, 11.4, 10.0, 10.2),
        (10.2, 10.4, 7.0, 7.5),     # swing low 7.0
        (7.5, 9.0, 7.4, 8.8),
        (8.8, 10.2, 8.6, 10.0),
        (10.0, 10.3, 9.5, 10.0),    # price midway between the two pools
    ]

    def test_no_bias_when_sides_are_balanced(self):
        """HTF-003 explicitly permits having no bias; the engine must use that."""
        res = daily_bias(mk(self.BALANCED), upto=8)
        assert res.direction is None
        assert "no bias" in res.reason
        assert res.ratio == pytest.approx(1.0, abs=0.05)

    def test_balanced_fixture_really_has_two_pools(self):
        """Guards against the test passing for the wrong reason."""
        res = daily_bias(mk(self.BALANCED), upto=8)
        assert len(res.pools) == 2
        assert {p.side for p in res.pools} == {"buyside", "sellside"}

    def test_margin_is_what_decides(self):
        """Same data, lower margin -> still no bias, because it is a true tie."""
        res = daily_bias(mk(self.BALANCED), upto=8, margin=1.01)
        assert res.direction is None

    def test_one_sided_liquidity_gives_a_direction(self):
        bars = mk([
            (10, 10.2, 9.9, 10.1), (10.1, 10.3, 10.0, 10.2),
            (10.2, 14.0, 10.1, 13.5),  # swing high 14
            (13.5, 13.6, 12.0, 12.2), (12.2, 12.4, 11.8, 12.0),
            (12.0, 13.0, 11.9, 12.8), (12.8, 13.1, 12.5, 12.9),
        ])
        res = daily_bias(bars, upto=6)
        assert res.direction in ("long", None)
        if res.direction == "long":
            assert res.buyside_score > 0

    def test_nearer_pool_scores_higher_than_distant_one(self):
        near = mk([(10, 10.2, 9.9, 10.1)] * 3 + [(10.1, 11.0, 10.0, 10.9)] +
                  [(10.9, 11.1, 10.5, 10.7)] * 3)
        res = daily_bias(near, upto=6)
        for p in res.pools:
            assert p.score == pytest.approx(p.swings / (1 + p.distance_ratio))

    def test_result_is_always_marked_unsourced(self):
        """Nobody should be able to mistake this for a cited rule."""
        res = daily_bias(mk([(10, 10.5, 9.5, 10)] * 6), upto=5)
        assert res.unsourced is True

    def test_no_lookahead(self):
        """The bias at bar i must not change when later bars are appended."""
        seq = [
            (10, 11, 9, 10), (10, 12, 9.5, 11.5), (11.5, 13, 11, 12),
            (12, 12.5, 10, 10.5), (10.5, 11, 8, 8.5), (8.5, 9.5, 8.2, 9.2),
            (9.2, 10.0, 9.0, 9.8), (9.8, 10.2, 9.5, 10.0),
        ]
        short = daily_bias(mk(seq[:7]), upto=6)
        long_ = daily_bias(mk(seq), upto=6)
        assert short.direction == long_.direction
        assert short.buyside_score == long_.buyside_score
        assert short.sellside_score == long_.sellside_score

    def test_premium_discount_is_reported(self):
        bars = mk([
            (10, 11, 9, 10), (10, 12, 9.5, 11.5), (11.5, 13, 11, 12),
            (12, 12.5, 10, 10.5), (10.5, 11, 8, 8.5), (8.5, 9.5, 8.2, 9.2),
        ])
        assert daily_bias(bars, upto=5).premium_discount in \
            ("premium", "discount", "equilibrium")
