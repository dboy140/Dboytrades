"""Bar data and swing-point detection.

Everything downstream is built on these two primitives, so both are kept
deliberately dumb and fully tested. A subtle error here would produce a
backtest that looks plausible and is meaningless.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


@dataclass(frozen=True)
class Bar:
    """One OHLC bar. `ts` is the bar's OPEN time and must be timezone-aware.

    Naive datetimes are rejected rather than assumed to be UTC: the session
    rules are the most testable part of this system and a silent timezone
    assumption would corrupt every one of them.
    """

    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    def __post_init__(self) -> None:
        if self.ts.tzinfo is None:
            raise ValueError("Bar.ts must be timezone-aware")
        if self.high < self.low:
            raise ValueError(f"high {self.high} below low {self.low}")
        if not (self.low <= self.open <= self.high):
            raise ValueError("open outside high/low")
        if not (self.low <= self.close <= self.high):
            raise ValueError("close outside high/low")

    @property
    def ny(self) -> datetime:
        return self.ts.astimezone(NY)

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def bullish(self) -> bool:
        return self.close > self.open


@dataclass(frozen=True)
class Swing:
    index: int
    ts: datetime
    price: float
    kind: str  # "high" | "low"


def swing_points(bars: list[Bar], lookback: int = 2) -> list[Swing]:
    """Fractal swings: a high with `lookback` lower highs either side, and vice versa.

    `lookback` bars at each end can never qualify, which is correct rather than a
    limitation: a swing is only knowable once the bars after it exist. Callers
    doing bar-by-bar replay must respect that a swing at index i is not
    confirmed until index i + lookback.
    """
    out: list[Swing] = []
    n = len(bars)
    for i in range(lookback, n - lookback):
        window = bars[i - lookback:i + lookback + 1]
        centre = bars[i]
        if all(centre.high >= b.high for b in window) and any(
            centre.high > b.high for b in window if b is not centre
        ):
            out.append(Swing(i, centre.ts, centre.high, "high"))
        if all(centre.low <= b.low for b in window) and any(
            centre.low < b.low for b in window if b is not centre
        ):
            out.append(Swing(i, centre.ts, centre.low, "low"))
    return out


def confirmed_swings(bars: list[Bar], upto: int, lookback: int = 2) -> list[Swing]:
    """Swings knowable at bar `upto` with no lookahead.

    This is the function a backtest must use. `swing_points` over the whole
    series would let the strategy see swings that had not yet formed, which is
    the single most common way a discretionary backtest flatters itself.
    """
    return [s for s in swing_points(bars[:upto + 1], lookback) if s.index + lookback <= upto]


def resample(bars: list[Bar], minutes: int) -> list[Bar]:
    """Aggregate to a higher timeframe, bucketing on New York wall-clock time.

    Needed because structure has to be judged on a timeframe where a swing
    means something. On 1m bars every three-bar wiggle is a fractal swing, and
    treating those as liquidity pools makes every path look obstructed.
    """
    if minutes <= 0:
        raise ValueError("minutes must be positive")
    out: list[Bar] = []
    bucket: list[Bar] = []
    key = None
    for bar in bars:
        ny = bar.ny
        k = (ny.date(), ny.hour, ny.minute // minutes)
        if key is None:
            key = k
        if k != key:
            out.append(Bar(bucket[0].ts, bucket[0].open,
                           max(x.high for x in bucket), min(x.low for x in bucket),
                           bucket[-1].close, sum(x.volume for x in bucket)))
            bucket, key = [], k
        bucket.append(bar)
    if bucket:
        out.append(Bar(bucket[0].ts, bucket[0].open,
                       max(x.high for x in bucket), min(x.low for x in bucket),
                       bucket[-1].close, sum(x.volume for x in bucket)))
    return out
