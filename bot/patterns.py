"""ICT pattern detection: fair value gaps, displacement, market structure shift.

Each function implements one cited rule and names it, so a signal can always be
traced back to the video that justifies it.
"""

from __future__ import annotations

from dataclasses import dataclass

from .bars import Bar, Swing, confirmed_swings


@dataclass(frozen=True)
class FVG:
    """A three-candle inefficiency.  Rules: FVG-001 (consequent encroachment)."""

    index: int          # index of the THIRD bar, i.e. when it becomes knowable
    direction: str      # "bullish" | "bearish"
    top: float
    bottom: float

    @property
    def consequent_encroachment(self) -> float:
        """Midpoint. FVG-001."""
        return (self.top + self.bottom) / 2.0

    @property
    def size(self) -> float:
        return self.top - self.bottom

    def contains(self, price: float) -> bool:
        return self.bottom <= price <= self.top


def find_fvgs(bars: list[Bar], min_size: float = 0.0) -> list[FVG]:
    """Bullish gap when bar[i+2].low > bar[i].high; bearish when bar[i+2].high < bar[i].low.

    Indexed by the third bar because that is the first moment the gap exists.
    Indexing by the first bar would let a backtest act on it two bars early.
    """
    out: list[FVG] = []
    for i in range(len(bars) - 2):
        a, c = bars[i], bars[i + 2]
        if c.low > a.high and (c.low - a.high) > min_size:
            out.append(FVG(i + 2, "bullish", top=c.low, bottom=a.high))
        elif c.high < a.low and (a.low - c.high) > min_size:
            out.append(FVG(i + 2, "bearish", top=a.low, bottom=c.high))
    return out


def is_inverted(fvg: FVG, bars: list[Bar], upto: int) -> bool:
    """Has price closed through the gap, inverting it?  Rule: IFVG-001.

    Requires a CLOSE beyond the far side, not a wick. IFVG-005 is explicit that
    bodies are what matter.
    """
    for bar in bars[fvg.index + 1:upto + 1]:
        if fvg.direction == "bullish" and bar.close < fvg.bottom:
            return True
        if fvg.direction == "bearish" and bar.close > fvg.top:
            return True
    return False


def average_body(bars: list[Bar], upto: int, window: int = 20) -> float:
    sample = bars[max(0, upto - window + 1):upto + 1]
    return sum(b.body for b in sample) / len(sample) if sample else 0.0


def is_displacement(bars: list[Bar], index: int, multiple: float = 1.5,
                    window: int = 20) -> bool:
    """A displacement candle: body large relative to recent bodies.

    The corpus never quantifies "displacement" -- it is shown on charts, not
    defined. `multiple` is therefore an UNSOURCED parameter and must be tuned
    per instrument in the backtest. It is exposed rather than buried so the
    tuning is visible.
    """
    if index <= 0 or index >= len(bars):
        return False
    avg = average_body(bars, index - 1, window)
    return avg > 0 and bars[index].body >= multiple * avg


@dataclass(frozen=True)
class MSS:
    """Market structure shift.  Rule: SMC-001 (NBB's mechanical definition)."""

    index: int
    direction: str        # "bullish" | "bearish"
    swept_price: float    # the low (bullish) or high (bearish) that was taken
    reclaimed_price: float  # the opposing swing that confirmed the shift
    targets: list[float]  # swings still available to the left

    @property
    def tradeable(self) -> bool:
        """A shift with nothing left to aim at is not a trade.

        SMC-001 ends with "look left for what highs are there to get taken
        out". When price has already closed beyond every one of them there is
        no objective, and MM-006 forbids entering without a defined low-
        resistance run to a target. Callers must gate on this.
        """
        return bool(self.targets)


def detect_mss(bars: list[Bar], upto: int, lookback: int = 2) -> MSS | None:
    """SMC-001, applied literally:

      1. price sweeps a series of lows
      2. price then takes out the high that formed BEFORE that low
      3. look left for the highs still available as targets

    Uses only swings confirmed at `upto`, so it is safe for bar-by-bar replay.
    """
    swings = confirmed_swings(bars, upto, lookback)
    if len(swings) < 3:
        return None

    lows = [s for s in swings if s.kind == "low"]
    highs = [s for s in swings if s.kind == "high"]
    if not lows or not highs:
        return None

    close = bars[upto].close

    # Bullish: a recent low took out an earlier low, then price reclaims the
    # high that preceded that sweeping low.
    for i in range(len(lows) - 1, 0, -1):
        swept, prior = lows[i], lows[i - 1]
        if swept.price >= prior.price:
            continue  # not a sweep
        preceding = [h for h in highs if h.index < swept.index]
        if not preceding:
            continue
        ref = preceding[-1]
        if close > ref.price:
            targets = sorted({h.price for h in highs if h.price > close})
            return MSS(upto, "bullish", swept.price, ref.price, targets)

    # Bearish mirror.
    for i in range(len(highs) - 1, 0, -1):
        swept, prior = highs[i], highs[i - 1]
        if swept.price <= prior.price:
            continue
        preceding = [l for l in lows if l.index < swept.index]
        if not preceding:
            continue
        ref = preceding[-1]
        if close < ref.price:
            targets = sorted({l.price for l in lows if l.price < close}, reverse=True)
            return MSS(upto, "bearish", swept.price, ref.price, targets)

    return None


def ote_levels(swing_high: float, swing_low: float, direction: str) -> dict[str, float]:
    """Optimal trade entry band.  Rules: OTE-001, OTE-002.

    62 / 70.5 / 79 percent retracement. OTE-002 says enter at 62 specifically.
    """
    rng = swing_high - swing_low
    if direction == "bullish":   # retracing down into discount
        return {
            "level_62": swing_high - 0.62 * rng,
            "level_705": swing_high - 0.705 * rng,
            "level_79": swing_high - 0.79 * rng,
            "equilibrium": swing_high - 0.5 * rng,
            "origin": swing_low,
        }
    return {
        "level_62": swing_low + 0.62 * rng,
        "level_705": swing_low + 0.705 * rng,
        "level_79": swing_low + 0.79 * rng,
        "equilibrium": swing_low + 0.5 * rng,
        "origin": swing_high,
    }


def premium_discount(price: float, range_high: float, range_low: float) -> str:
    """SMC-003 / SMC-004: position relative to the 50% of the dealing range."""
    if range_high <= range_low:
        raise ValueError("range_high must exceed range_low")
    eq = (range_high + range_low) / 2.0
    if price > eq:
        return "premium"
    if price < eq:
        return "discount"
    return "equilibrium"
