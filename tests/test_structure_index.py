"""Tests for the precomputed structure index.

`SwingIndex` exists purely for speed: rescanning history on every bar made a
backtest quadratic, and a two-year 1-minute file extrapolated to roughly 140
hours. A speed-up that quietly changes the answer is worse than the slow
version, so almost every test here is an equivalence test against the original
unbounded rescan rather than a test of the index in isolation.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta

import pytest

from bot.backtest import run
from bot.bars import (
    NY, UTC, Bar, SwingIndex, SwingIndexCache, confirmed_swings, resample,
    resample_tail, swing_points,
)
from bot.signals import ote


def noise(n: int, seed: int = 0) -> list[Bar]:
    """A random walk. Deliberately not market data: the point is to exercise
    every branch of the structure code, not to look realistic."""
    r = random.Random(seed)
    t = datetime(2024, 1, 2, 0, 0, tzinfo=UTC)
    px, out = 1.1000, []
    for i in range(n):
        o = px
        px += r.gauss(0, 0.0004)
        c = px
        h = max(o, c) + abs(r.gauss(0, 0.0002))
        l = min(o, c) - abs(r.gauss(0, 0.0002))
        out.append(Bar(t + timedelta(minutes=i), o, h, l, c, 100.0))
    return out


def unbounded(bars, upto, lookback=2):
    """The original behaviour: rescan everything, no window, no index."""
    return confirmed_swings(bars, upto, lookback, window=None)


class TestSwingIndexEquivalence:
    @pytest.mark.parametrize("lookback", [1, 2, 3])
    def test_matches_the_unbounded_rescan_at_every_bar(self, lookback):
        bars = noise(400, seed=1)
        idx = SwingIndex(bars, lookback)
        for upto in range(len(bars)):
            assert idx.confirmed(upto, None) == unbounded(bars, upto, lookback)

    def test_pushing_bars_gives_the_same_index_as_building_in_one_go(self):
        bars = noise(400, seed=2)
        batch = SwingIndex(bars, 2)
        live = SwingIndex(lookback=2)
        for bar in bars:
            live.push(bar)
        for upto in range(len(bars)):
            assert live.confirmed(upto, 100) == batch.confirmed(upto, 100)

    def test_index_finds_swings_the_windowed_rescan_misses_at_its_edge(self):
        """Not a discrepancy to fix -- the windowed rescan is the wrong one.

        `confirmed_swings(..., window=N)` slices the series and rescans, so the
        first `lookback` bars of the slice can never qualify however much real
        history sits behind them. Scanning once has no such edge.
        """
        bars = noise(400, seed=3)
        idx = SwingIndex(bars, 2)
        extra = 0
        for upto in range(len(bars)):
            windowed = confirmed_swings(bars, upto, 2, window=50)
            indexed = idx.confirmed(upto, 50)
            assert set(windowed) <= set(indexed)
            extra += len(indexed) - len(windowed)
        assert extra > 0

    def test_never_returns_an_unconfirmed_swing(self):
        bars = noise(200, seed=4)
        idx = SwingIndex(bars, 2)
        for upto in range(len(bars)):
            for s in idx.confirmed(upto, None):
                assert s.index + idx.lookback <= upto

    def test_owns_its_bars_so_a_later_append_cannot_corrupt_it(self):
        bars = noise(200, seed=5)
        idx = SwingIndex(bars, 2)
        before = idx.confirmed(150, None)
        bars.append(Bar(bars[-1].ts + timedelta(minutes=1), 9, 9, 9, 9))
        assert idx.confirmed(150, None) == before

    def test_lookback_mismatch_raises_rather_than_answering_wrongly(self):
        bars = noise(100, seed=6)
        idx = SwingIndex(bars, 2)
        with pytest.raises(ValueError, match="lookback"):
            confirmed_swings(bars, 50, 3, index=idx)

    def test_empty_index_answers_nothing(self):
        assert SwingIndex().confirmed(0, None) == []
        assert SwingIndex([]).confirmed(10, None) == []


class TestResampleTail:
    @pytest.mark.parametrize("minutes", [5, 15, 30, 60])
    @pytest.mark.parametrize("cap", [1, 3, 40, None])
    def test_is_the_tail_of_a_full_resample(self, minutes, cap):
        bars = noise(600, seed=7)
        for upto in range(120, 600, 29):
            tail = resample_tail(bars, minutes, upto, cap)
            full = resample(bars[:upto + 1], minutes)
            assert tail == full[len(full) - len(tail):]
            if cap is not None:
                assert len(tail) <= cap

    def test_snapping_to_a_bucket_boundary_is_what_makes_it_exact(self):
        """A partial first bucket would give that bar a different open, high
        and low -- small enough to look like rounding, large enough to move a
        swing and with it a trade."""
        bars = noise(400, seed=8)
        upto = 399
        tail = resample_tail(bars, 15, upto, 5)
        full = resample(bars[:upto + 1], 15)
        assert tail[0] == full[-5]

    def test_rejects_a_nonsense_timeframe(self):
        bars = noise(10, seed=9)
        with pytest.raises(ValueError, match="positive"):
            resample_tail(bars, 0, 5)


class TestHigherTimeframeIndex:
    @pytest.mark.parametrize("minutes", [5, 15, 60])
    @pytest.mark.parametrize("cap", [1, 4, 40])
    def test_matches_resample_tail_bar_for_bar(self, minutes, cap):
        bars = noise(500, seed=10)
        idx = SwingIndex(bars, 2)
        for upto in range(len(bars)):
            assert idx.htf(minutes, upto, cap) == \
                resample_tail(bars, minutes, upto, cap)

    def test_uncapped_equals_a_full_resample_of_the_prefix(self):
        bars = noise(300, seed=11)
        idx = SwingIndex(bars, 2)
        for upto in range(len(bars)):
            assert idx.htf(15, upto, None) == resample(bars[:upto + 1], 15)

    def test_short_history_returns_every_bucket_there_is(self):
        """Regression: the cap slice used a negative start index, which sliced
        from the end and returned two bars where four existed."""
        bars = noise(16, seed=12)
        idx = SwingIndex(bars, 2)
        assert idx.htf(5, 15, 5) == resample_tail(bars, 5, 15, 5)
        assert len(idx.htf(5, 15, 5)) == 4

    def test_a_query_that_moves_backwards_rebuilds_instead_of_going_stale(self):
        bars = noise(400, seed=13)
        idx = SwingIndex(bars, 2)
        for upto in range(len(bars)):
            idx.htf(15, upto, 20)
        for upto in (50, 200, 399, 10):
            assert idx.htf(15, upto, 20) == resample_tail(bars, 15, upto, 20)

    def test_streaming_and_batch_agree(self):
        bars = noise(300, seed=14)
        live = SwingIndex(lookback=2)
        for i, bar in enumerate(bars):
            live.push(bar)
            assert live.htf(15, i, 20) == resample_tail(bars, 15, i, 20)

    def test_rejects_a_nonsense_timeframe(self):
        idx = SwingIndex(noise(10, seed=15), 2)
        with pytest.raises(ValueError, match="positive"):
            idx.htf(0, 5)


class TestSwingIndexCache:
    def test_each_series_gets_its_own_index(self):
        a, b = noise(100, seed=16), noise(100, seed=17)
        cache = SwingIndexCache()
        assert cache.get(a) is not cache.get(b)

    def test_the_same_series_is_not_reindexed(self):
        a = noise(100, seed=18)
        cache = SwingIndexCache()
        assert cache.get(a) is cache.get(a)

    def test_a_series_that_grew_is_reindexed_rather_than_answered_stale(self):
        a = noise(100, seed=19)
        cache = SwingIndexCache()
        first = cache.get(a)
        a.append(Bar(a[-1].ts + timedelta(minutes=1), 1.1, 1.2, 1.0, 1.15))
        assert cache.get(a) is not first
        assert len(cache.get(a)) == len(a)

    def test_holds_a_bounded_number_of_series(self):
        cache = SwingIndexCache(max_series=2)
        kept = [noise(50, seed=s) for s in range(4)]
        for series in kept:
            cache.get(series)
        assert len(cache._entries) == 2


class TestBarNyCaching:
    def test_caching_does_not_disturb_equality_or_hashing(self):
        a = Bar(datetime(2024, 3, 1, 12, 0, tzinfo=UTC), 1, 2, 0.5, 1.5)
        b = Bar(datetime(2024, 3, 1, 12, 0, tzinfo=UTC), 1, 2, 0.5, 1.5)
        _ = a.ny                       # populate the cache on one of them only
        assert a == b
        assert hash(a) == hash(b)

    def test_still_returns_new_york_wall_clock(self):
        bar = Bar(datetime(2024, 3, 1, 12, 0, tzinfo=UTC), 1, 2, 0.5, 1.5)
        assert bar.ny == datetime(2024, 3, 1, 12, 0, tzinfo=UTC).astimezone(NY)
        assert bar.ny is bar.ny


class TestBacktestIsUnchanged:
    def test_indexed_run_produces_the_same_trades_as_the_full_rescan(self):
        """The whole justification for the index in one test.

        The unbounded arm patches `__defaults__` because the window default is
        bound at definition time -- setting the module global does nothing, a
        mistake that made an earlier version of this comparison silently
        compare the fast path against itself.
        """
        bars = noise(3000, seed=20)

        cache = SwingIndexCache()
        fast = run(bars, lambda bs, i: ote(bs, i, "EURUSD", index=cache.get(bs)))

        original = confirmed_swings.__defaults__
        confirmed_swings.__defaults__ = (2, None, None)
        try:
            slow = run(bars, lambda bs, i: ote(bs, i, "EURUSD"))
        finally:
            confirmed_swings.__defaults__ = original

        def shape(t):
            return (t.setup, t.direction, t.entry_index, t.entry, t.stop,
                    t.target, t.exit_reason, t.exit_index)

        assert [shape(t) for t in fast.trades] == [shape(t) for t in slow.trades]
        assert fast.signals_generated == slow.signals_generated

    def test_history_is_scanned_once_per_series_not_once_per_bar(self):
        """A timing assertion would be flaky; counting the full scans is not.

        If someone drops the index and the per-bar rescan returns, this fails
        immediately even on a machine fast enough to hide it.
        """
        import bot.bars as bars_mod

        bars = noise(1200, seed=21)
        calls = []
        real = bars_mod.swing_points

        def counted(*a, **kw):
            calls.append(len(a[0]))
            return real(*a, **kw)

        bars_mod.swing_points = counted
        try:
            cache = SwingIndexCache()
            run(bars, lambda bs, i: ote(bs, i, "EURUSD", index=cache.get(bs)))
        finally:
            bars_mod.swing_points = real

        # One scan for the execution series. Anything per-bar would be
        # hundreds, and the higher-timeframe swings are scanned over a bounded
        # resampled tail rather than the raw file.
        full_scans = [n for n in calls if n > len(bars) // 2]
        assert len(full_scans) == 1
