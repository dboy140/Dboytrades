"""Tests for the execution layer.

Detection correctness is where a backtest silently becomes fiction, so these
tests use hand-built bars with known answers rather than sampled market data.
"""

from datetime import datetime, timedelta

import pytest

from bot.bars import NY, Bar, confirmed_swings, swing_points
from bot.patterns import (
    FVG, average_body, detect_mss, find_fvgs, is_displacement, is_inverted,
    ote_levels, premium_discount,
)
from bot.sessions import active_windows, in_window, uk_offset_hours

START = datetime(2026, 6, 15, 9, 0, tzinfo=NY)


def mk(seq):
    """Build bars from (o,h,l,c) tuples, one minute apart."""
    return [Bar(START + timedelta(minutes=i), *ohlc) for i, ohlc in enumerate(seq)]


class TestBar:
    def test_rejects_naive_datetime(self):
        with pytest.raises(ValueError, match="timezone-aware"):
            Bar(datetime(2026, 1, 1, 10, 0), 1, 2, 0.5, 1.5)

    def test_rejects_inverted_high_low(self):
        with pytest.raises(ValueError):
            Bar(START, 1, 0.5, 2, 1)

    def test_rejects_close_outside_range(self):
        with pytest.raises(ValueError):
            Bar(START, 1, 2, 0.5, 5)

    def test_body_and_direction(self):
        b = Bar(START, 10, 12, 9, 11)
        assert b.body == 1 and b.range == 3 and b.bullish


class TestFVG:
    def test_bullish_gap_detected(self):
        bars = mk([(9, 10, 9, 9.8), (9.8, 12.5, 9.8, 12.3), (12.3, 13, 12, 12.8)])
        g = find_fvgs(bars)[0]
        assert g.direction == "bullish"
        assert (g.bottom, g.top) == (10, 12)

    def test_bearish_gap_detected(self):
        bars = mk([(13, 13, 12, 12.2), (12.2, 12.2, 9.5, 9.7), (9.7, 10, 9, 9.2)])
        g = find_fvgs(bars)[0]
        assert g.direction == "bearish"
        assert (g.bottom, g.top) == (10, 12)

    def test_indexed_by_third_bar_not_first(self):
        """Indexing by the first bar would let a backtest act two bars early."""
        bars = mk([(9, 10, 9, 9.8), (9.8, 12.5, 9.8, 12.3), (12.3, 13, 12, 12.8)])
        assert find_fvgs(bars)[0].index == 2

    def test_no_gap_when_ranges_overlap(self):
        bars = mk([(9, 11, 9, 10), (10, 12, 9.5, 11), (11, 12, 10.5, 11.5)])
        assert find_fvgs(bars) == []

    def test_consequent_encroachment_is_midpoint(self):
        assert FVG(2, "bullish", top=12, bottom=10).consequent_encroachment == 11

    def test_min_size_filters_noise(self):
        bars = mk([(9, 10, 9, 9.8), (9.8, 10.5, 9.8, 10.4), (10.4, 11, 10.05, 10.8)])
        assert find_fvgs(bars, min_size=0.5) == []
        assert find_fvgs(bars, min_size=0.0)


class TestInversion:
    def _bull_gap_then(self, extra):
        base = [(9, 10, 9, 9.8), (9.8, 12.5, 9.8, 12.3), (12.3, 13, 12, 12.8)]
        return mk(base + extra)

    def test_close_below_gap_inverts(self):
        bars = self._bull_gap_then([(12.8, 12.8, 9.0, 9.5)])
        assert is_inverted(find_fvgs(bars)[0], bars, upto=3)

    def test_wick_through_does_not_invert(self):
        """IFVG-005 is explicit that bodies matter, not wicks."""
        bars = self._bull_gap_then([(12.0, 12.2, 9.0, 11.0)])
        assert not is_inverted(find_fvgs(bars)[0], bars, upto=3)


class TestDisplacement:
    def test_large_body_is_displacement(self):
        seq = [(10, 10.2, 9.9, 10.05)] * 20 + [(10, 12, 10, 11.9)]
        bars = mk(seq)
        assert is_displacement(bars, len(bars) - 1, multiple=1.5)

    def test_ordinary_body_is_not(self):
        bars = mk([(10, 10.2, 9.9, 10.05)] * 21)
        assert not is_displacement(bars, len(bars) - 1, multiple=1.5)

    def test_uses_only_prior_bars(self):
        """The displacement bar must not inflate its own baseline."""
        seq = [(10, 10.2, 9.9, 10.05)] * 20 + [(10, 12, 10, 11.9)]
        bars = mk(seq)
        assert average_body(bars, len(bars) - 2) < 0.2


class TestSwings:
    def test_finds_obvious_swing_high(self):
        bars = mk([(1, 2, 1, 1.5), (1.5, 3, 1.5, 2.5), (2.5, 9, 2.5, 8),
                   (8, 8.5, 7, 7.2), (7.2, 7.5, 6, 6.1)])
        highs = [s for s in swing_points(bars) if s.kind == "high"]
        assert highs and highs[0].index == 2 and highs[0].price == 9

    def test_confirmed_swings_have_no_lookahead(self):
        bars = mk([(1, 2, 1, 1.5), (1.5, 3, 1.5, 2.5), (2.5, 9, 2.5, 8),
                   (8, 8.5, 7, 7.2), (7.2, 7.5, 6, 6.1)])
        # The swing at index 2 needs 2 bars after it, so it is not knowable at bar 3.
        assert confirmed_swings(bars, upto=3) == []
        assert any(s.index == 2 for s in confirmed_swings(bars, upto=4))


class TestMSS:
    # Structure: swing high at 2 (12.0), swing low at 5 (9.0), lower swing low
    # at 9 (8.5) sweeping it, then price reclaims the preceding high.
    SEQ = [
        (10, 10.5, 9.8, 10.4),      # 0
        (10.4, 11.0, 10.3, 10.9),   # 1
        (10.9, 12.0, 10.8, 11.8),   # 2  swing high 12.0
        (11.8, 11.9, 10.5, 10.6),   # 3
        (10.6, 10.7, 9.5, 9.6),     # 4
        (9.6, 9.8, 9.0, 9.5),       # 5  swing low 9.0
        (9.5, 10.2, 9.4, 10.1),     # 6
        (10.1, 10.6, 10.0, 10.5),   # 7  swing high 10.6
        (10.5, 10.6, 9.3, 9.4),     # 8
        (9.4, 9.5, 8.5, 8.7),       # 9  swing low 8.5 -- sweeps the 9.0
        (8.7, 9.6, 8.6, 9.5),       # 10
        (9.5, 10.8, 9.4, 10.7),     # 11 reclaims the 10.6 -> shift
        (10.7, 12.3, 10.6, 12.2),   # 12 closes above every remaining high
    ]

    def test_bullish_shift_detected(self):
        """SMC-001: sweep the lows, then take the high that preceded them."""
        mss = detect_mss(mk(self.SEQ), upto=11)
        assert mss is not None
        assert mss.direction == "bullish"
        assert mss.swept_price == 8.5
        assert mss.reclaimed_price == 10.6

    def test_targets_are_the_highs_still_to_the_left(self):
        mss = detect_mss(mk(self.SEQ), upto=11)
        assert mss.targets == [12.0]
        assert mss.tradeable

    def test_shift_with_no_remaining_target_is_not_tradeable(self):
        """Price closed above every available high: the shift is real but there
        is nothing to aim at, and MM-006 forbids entering without an objective."""
        mss = detect_mss(mk(self.SEQ), upto=12)
        assert mss is not None
        assert mss.targets == []
        assert not mss.tradeable

    def test_no_shift_before_the_reclaim(self):
        assert detect_mss(mk(self.SEQ), upto=10) is None

    def test_returns_none_on_insufficient_data(self):
        assert detect_mss(mk([(1, 2, 1, 1.5)] * 3), upto=2) is None


class TestOTE:
    def test_bullish_levels(self):
        lv = ote_levels(100, 80, "bullish")
        assert lv["level_62"] == pytest.approx(87.6)
        assert lv["equilibrium"] == 90
        assert lv["level_79"] < lv["level_705"] < lv["level_62"]

    def test_bearish_levels_mirror(self):
        lv = ote_levels(100, 80, "bearish")
        assert lv["level_62"] == pytest.approx(92.4)
        assert lv["level_79"] > lv["level_705"] > lv["level_62"]


class TestPremiumDiscount:
    def test_classification(self):
        assert premium_discount(95, 100, 80) == "premium"
        assert premium_discount(85, 100, 80) == "discount"
        assert premium_discount(90, 100, 80) == "equilibrium"

    def test_invalid_range_rejected(self):
        with pytest.raises(ValueError):
            premium_discount(90, 80, 100)


class TestSessions:
    def _at(self, h, m=0, month=6, day=15):
        return datetime(2026, month, day, h, m, tzinfo=NY)

    def test_silver_bullet_am_window(self):
        assert in_window(self._at(10, 30), "silver_bullet_am")
        assert not in_window(self._at(11, 0), "silver_bullet_am")  # end exclusive
        assert not in_window(self._at(9, 59), "silver_bullet_am")

    def test_instrument_filtering(self):
        assert any(w.key == "silver_bullet_am"
                   for w in active_windows(self._at(10, 30), "NAS100"))
        assert not any(w.key == "silver_bullet_am"
                       for w in active_windows(self._at(10, 30), "EURUSD"))

    def test_news_day_widens_am_window(self):
        at_1130 = self._at(11, 30)
        assert not active_windows(at_1130, "NAS100", news_day=False) or \
            not any(w.key.startswith("silver_bullet_am")
                    for w in active_windows(at_1130, "NAS100", news_day=False))
        assert any(w.key == "silver_bullet_am_news"
                   for w in active_windows(at_1130, "NAS100", news_day=True))

    def test_windows_carry_their_rule_ids(self):
        w = next(w for w in active_windows(self._at(10, 30), "NAS100")
                 if w.key == "silver_bullet_am")
        assert "SB-001" in w.rule_ids

    def test_dst_offset_changes(self):
        assert uk_offset_hours(self._at(10)) == 5
        assert uk_offset_hours(self._at(10, month=3, day=15)) == 4

    def test_window_is_the_same_ny_hour_across_dst(self):
        """The window is defined in NY time, so it must not move when UK DST does."""
        assert in_window(self._at(10, 30, month=3, day=15), "silver_bullet_am")
        assert in_window(self._at(10, 30, month=6, day=15), "silver_bullet_am")
