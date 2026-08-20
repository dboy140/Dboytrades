"""No-trade filters.  Rules: MM-006, MM-007, LDN-005, SMC-005.

MM-006 is the system's strongest claim and the easiest to falsify, which is
exactly why it must be enforced by the engine rather than assumed: without it
the backtest tests a different system from the one the corpus describes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time

from .bars import Bar, SwingIndex, confirmed_swings, resample_tail
from .sessions import NY


@dataclass
class FilterResult:
    passed: bool
    reason: str = ""
    rule_id: str = ""


def low_resistance(entry: float, target: float, direction: str,
                   bars: list[Bar], upto: int, lookback: int = 2,
                   htf_minutes: int = 15,
                   index: SwingIndex | None = None) -> FilterResult:
    """MM-006: no opposing liquidity between entry and objective.

    For a long, an intermediate swing HIGH between entry and target is
    liquidity price must fight through -- npL3ZXJ5zOU: "if we're trading
    against a high", that is the high-resistance case.

    Structure is judged on `htf_minutes` bars, not the execution timeframe.
    MM-007 is explicit that lower-timeframe "resistance" should be ignored when
    the higher timeframe wants the level, and the practical consequence is
    stark: evaluated on 1m bars this filter rejected 100% of signals, reporting
    dozens of "opposing levels" that were three-bar wiggles. Set
    `htf_minutes=0` to check on the execution timeframe instead.
    """
    if htf_minutes and htf_minutes > 1:
        # The index carries the resample too, so finished higher-timeframe
        # bars are aggregated once per run rather than once per signal.
        htf = (index.htf(htf_minutes, upto) if index is not None
               else resample_tail(bars, htf_minutes, upto))
        swings = confirmed_swings(htf, len(htf) - 1, lookback)
    else:
        swings = confirmed_swings(bars, upto, lookback, index=index)
    if direction == "long":
        blockers = [s.price for s in swings
                    if s.kind == "high" and entry < s.price < target]
    else:
        blockers = [s.price for s in swings
                    if s.kind == "low" and target < s.price < entry]
    if blockers:
        return FilterResult(
            False,
            f"high resistance: {len(blockers)} opposing level(s) between entry "
            f"{entry:.2f} and target {target:.2f}, nearest {blockers[0]:.2f}",
            "MM-006")
    return FilterResult(True, "low resistance run", "MM-006")


def within_htf_range(price: float, target: float,
                     htf_high: float, htf_low: float) -> FilterResult:
    """MM-007: a move staying inside the higher timeframe range is internal
    range liquidity and therefore low resistance, whatever a lower timeframe
    shows."""
    inside = htf_low <= target <= htf_high and htf_low <= price <= htf_high
    return FilterResult(
        inside,
        "internal range liquidity" if inside
        else "target sits outside the higher timeframe range",
        "MM-007")


ASIAN_START, ASIAN_END = time(20, 0), time(0, 0)


def asian_range(bars: list[Bar], upto: int) -> float | None:
    """High-low of the most recent Asian session (20:00-00:00 New York)."""
    day = bars[upto].ny.date()
    session = [b for b in bars[:upto + 1]
               if b.ny.time() >= ASIAN_START and b.ny.date() < day]
    if not session:
        return None
    last_day = max(b.ny.date() for b in session)
    session = [b for b in session if b.ny.date() == last_day]
    return max(b.high for b in session) - min(b.low for b in session)


def asian_range_ok(bars: list[Bar], upto: int, *, pip_size: float = 0.0001,
                   max_pips: float = 30.0) -> FilterResult:
    """LDN-005: skip London if the Asian range did not settle into 20-30 pips.

    `max_pips` is the top of the stated 20-30 band. The band is quoted for FX
    majors; it has no meaning on indices, so callers should not apply this
    filter to NAS100.
    """
    rng = asian_range(bars, upto)
    if rng is None:
        return FilterResult(True, "no Asian session data; filter not applied", "LDN-005")
    pips = rng / pip_size
    if pips > max_pips:
        return FilterResult(
            False,
            f"Asian range {pips:.0f} pips exceeds {max_pips:.0f}; float was not "
            "allowed to build, so skip London",
            "LDN-005")
    return FilterResult(True, f"Asian range {pips:.0f} pips", "LDN-005")


def agrees_with_order_flow(direction: str, htf_bias: str | None) -> FilterResult:
    """SMC-005: take trades only in the direction of higher timeframe order flow."""
    if htf_bias is None:
        return FilterResult(False, "no higher timeframe bias; HTF-003 permits standing aside",
                            "SMC-005")
    ok = direction == htf_bias
    return FilterResult(ok,
                        "agrees with higher timeframe order flow" if ok
                        else f"opposes higher timeframe order flow ({htf_bias})",
                        "SMC-005")


def weekday_preferred(bars: list[Bar], upto: int) -> FilterResult:
    """SMC-005 also concentrates day trades Monday to Wednesday.

    Advisory rather than blocking: it is a preference in the source, not a
    prohibition, so it is reported and left to the caller.
    """
    wd = bars[upto].ny.weekday()  # 0 = Monday
    return FilterResult(wd <= 2, "Mon-Wed" if wd <= 2 else "Thu/Fri", "SMC-005")
