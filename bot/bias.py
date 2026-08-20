"""Automated daily bias from HTF-001.

READ THIS BEFORE TRUSTING THE OUTPUT.

HTF-001 says: map where buy stops sit above old highs and sell stops below old
lows, and the side holding the LARGER pool is the side the market is reaching
for. It never says what makes one pool larger than another. Nothing in the
corpus does -- that is GAPS G-07, and the closest ICT comes to a procedure is
an argument against forcing a daily bias at all (HTF-003).

So the scoring below is MINE. It is a heuristic consistent with the cited
rules, not a rule either source stated, and it must never be described as ICT's
method. Every parameter is exposed and marked UNSOURCED so the arbitrariness is
visible rather than buried in a constant.

Two ideas it encodes, each traceable to something that IS cited:

  * Clustered swings are a bigger pool than a lone one. Equal highs and equal
    lows appear throughout the corpus as liquidity markers, so treating a
    cluster as a deeper pool follows from the material even though the
    threshold does not.
  * Nearer pools matter more than distant ones. ICT criticises liquidity tools
    for drawing attention to "levels of liquidity that are not so pertinent to
    right now" (SMC-008 source), which supports weighting by proximity.

It returns None readily. A bias that is not clear is not a bias, and HTF-003
explicitly permits having none.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .bars import Bar, SwingIndex, confirmed_swings
from .patterns import premium_discount

# --- UNSOURCED parameters. Tune per instrument; record what you chose. -------
SWING_LOOKBACK = 2          # fractal width for daily swings
CLUSTER_TOLERANCE = 0.0015  # swings within 0.15% count as one pool ("equal highs")
DECISION_MARGIN = 1.30      # one side must outscore the other by this factor
MIN_POOLS = 2               # below this there is not enough structure to read
# ----------------------------------------------------------------------------


@dataclass
class Pool:
    price: float
    side: str            # "buyside" | "sellside"
    swings: int          # how many swings cluster here
    distance_ratio: float  # distance from price, in average daily ranges
    score: float           # == swings / (1 + distance_ratio); kept exact, not
                           # rounded, so the stored fields reproduce each other


@dataclass
class BiasResult:
    direction: str | None        # "long" | "short" | None
    buyside_score: float
    sellside_score: float
    pools: list[Pool] = field(default_factory=list)
    premium_discount: str = ""
    reason: str = ""
    unsourced: bool = True       # always. This is a heuristic, not a cited rule.

    @property
    def ratio(self) -> float:
        lo = min(self.buyside_score, self.sellside_score)
        hi = max(self.buyside_score, self.sellside_score)
        return hi / lo if lo > 0 else float("inf") if hi > 0 else 1.0


def _unswept(bars: list[Bar], upto: int, lookback: int,
             index: SwingIndex | None = None) -> tuple[list[float], list[float]]:
    """Swing highs never traded through since, and swing lows likewise.

    A pool that has already been taken is spent -- it is no longer a draw.
    """
    swings = confirmed_swings(bars, upto, lookback, index=index)
    highs, lows = [], []
    for s in swings:
        after = bars[s.index + 1:upto + 1]
        if s.kind == "high" and not any(b.high > s.price for b in after):
            highs.append(s.price)
        elif s.kind == "low" and not any(b.low < s.price for b in after):
            lows.append(s.price)
    return highs, lows


def _cluster(prices: list[float], tolerance: float) -> list[tuple[float, int]]:
    """Group near-equal levels. Equal highs are one deep pool, not several."""
    if not prices:
        return []
    out: list[tuple[float, int]] = []
    for p in sorted(prices):
        if out and abs(p - out[-1][0]) / max(abs(out[-1][0]), 1e-9) <= tolerance:
            level, n = out[-1]
            out[-1] = ((level * n + p) / (n + 1), n + 1)
        else:
            out.append((p, 1))
    return out


def daily_bias(bars: list[Bar], upto: int, *,
               lookback: int = SWING_LOOKBACK,
               tolerance: float = CLUSTER_TOLERANCE,
               margin: float = DECISION_MARGIN,
               min_pools: int = MIN_POOLS,
               index: SwingIndex | None = None) -> BiasResult:
    """Score unswept pools either side and return a bias, or None.

    Uses only bars up to `upto`, so it is safe inside a replay.
    """
    price = bars[upto].close
    highs, lows = _unswept(bars, upto, lookback, index=index)

    ranges = [b.range for b in bars[max(0, upto - 20):upto + 1]]
    avg_range = (sum(ranges) / len(ranges)) if ranges else 1.0
    avg_range = max(avg_range, 1e-9)

    pools: list[Pool] = []
    for level, n in _cluster(highs, tolerance):
        if level <= price:
            continue  # buy stops sit ABOVE price
        d = (level - price) / avg_range
        pools.append(Pool(level, "buyside", n, d, n / (1.0 + d)))
    for level, n in _cluster(lows, tolerance):
        if level >= price:
            continue
        d = (price - level) / avg_range
        pools.append(Pool(level, "sellside", n, d, n / (1.0 + d)))

    buy = sum(p.score for p in pools if p.side == "buyside")
    sell = sum(p.score for p in pools if p.side == "sellside")

    rng_hi = max((b.high for b in bars[max(0, upto - 20):upto + 1]), default=price)
    rng_lo = min((b.low for b in bars[max(0, upto - 20):upto + 1]), default=price)
    pd = premium_discount(price, rng_hi, rng_lo) if rng_hi > rng_lo else "equilibrium"

    res = BiasResult(None, round(buy, 4), round(sell, 4), pools, pd)

    if len(pools) < min_pools:
        res.reason = f"only {len(pools)} unswept pools; not enough structure to read"
        return res
    if buy <= 0 or sell <= 0:
        # Liquidity on one side only is a genuine read, not an absence of one.
        res.direction = "long" if buy > 0 else "short"
        res.reason = f"unswept liquidity on the {'buy' if buy > 0 else 'sell'} side only"
        return res
    if buy >= sell * margin:
        res.direction = "long"
        res.reason = f"buyside outscores sellside {buy:.2f} vs {sell:.2f}"
    elif sell >= buy * margin:
        res.direction = "short"
        res.reason = f"sellside outscores buyside {sell:.2f} vs {buy:.2f}"
    else:
        res.reason = (f"neither side clears the {margin}x margin "
                      f"({buy:.2f} vs {sell:.2f}) - no bias, which HTF-003 permits")
    return res
