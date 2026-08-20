"""Bar data and swing-point detection.

Everything downstream is built on these two primitives, so both are kept
deliberately dumb and fully tested. A subtle error here would produce a
backtest that looks plausible and is meaningless.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
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
        """New York wall clock, computed once per bar.

        Every session rule, every resample bucket and every weekday check goes
        through here, so on a long file this property is called tens of
        millions of times -- 5.3 of 28.7 seconds in one profile, all of it
        recomputing the same conversion. Cached in `__dict__`, which the frozen
        dataclass still has; the name is not a field, so equality and hashing
        are untouched.
        """
        got = self.__dict__.get("_ny")
        if got is None:
            got = self.ts.astimezone(NY)
            object.__setattr__(self, "_ny", got)
        return got

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


# Structure is local. Rescanning all history on every bar is quadratic, which
# on a two-year 1-minute file works out at roughly 140 hours -- a backtest that
# cannot be run is worth nothing. 1500 one-minute bars is about 25 hours, more
# than a full session cycle, and far more than any rule here reaches back for.
DEFAULT_SWING_WINDOW = 1500


def confirmed_swings(bars: list[Bar], upto: int, lookback: int = 2,
                     window: int | None = DEFAULT_SWING_WINDOW,
                     index: "SwingIndex | None" = None) -> list[Swing]:
    """Swings knowable at bar `upto` with no lookahead.

    This is the function a backtest must use. `swing_points` over the whole
    series would let the strategy see swings that had not yet formed, which is
    the single most common way a discretionary backtest flatters itself.

    `window` bounds how far back to scan, making each call O(window) rather
    than O(upto). Pass None to scan everything -- correct but quadratic, and
    only sensible on short series such as daily bars.

    Pass `index` (a `SwingIndex` over the same series and lookback) to answer
    from a single precomputed scan instead. That is what a backtest should do:
    it turns the per-bar cost from O(window) into two bisects.
    """
    if index is not None:
        if index.lookback != lookback:
            raise ValueError(
                f"index built for lookback {index.lookback}, called with {lookback}")
        return index.confirmed(upto, window)
    lo = 0 if window is None else max(0, upto - window + 1)
    segment = bars[lo:upto + 1]
    out: list[Swing] = []
    for s in swing_points(segment, lookback):
        absolute = s.index + lo
        if absolute + lookback <= upto:
            out.append(Swing(absolute, s.ts, s.price, s.kind))
    return out


class SwingIndex:
    """Every swing in one series, computed once, answered by bisect.

    `confirmed_swings` is correct but is re-run per bar, and even bounded to a
    window it is the dominant cost of a backtest: profiling the signal path put
    9.9 of 12.1 seconds inside it. Scanning once up front and answering each
    query with two bisects removes that entirely.

    Works for both drivers. A backtest hands the whole series to the
    constructor; the live runner starts empty and calls `push` per bar, which
    costs O(lookback) because a bar can only ever confirm the swing sitting
    `lookback` bars behind it.

    The index owns its own list of bars rather than aliasing the caller's. That
    is deliberate: an index silently describing a series that has since grown
    would return stale structure and flatter the backtest instead of failing.
    """

    def __init__(self, bars: list[Bar] | None = None, lookback: int = 2):
        self.lookback = lookback
        self._bars: list[Bar] = list(bars) if bars else []
        self._swings: list[Swing] = swing_points(self._bars, lookback)
        self._at: list[int] = [s.index for s in self._swings]
        self._htf: dict[int, dict] = {}

    def __len__(self) -> int:
        return len(self._bars)

    def push(self, bar: Bar) -> None:
        """Append one bar and record whatever swing it confirms."""
        self._bars.append(bar)
        lb = self.lookback
        centre = len(self._bars) - 1 - lb
        if centre < lb:
            return
        window = self._bars[centre - lb:centre + lb + 1]
        c = self._bars[centre]
        if (all(c.high >= b.high for b in window)
                and any(c.high > b.high for b in window if b is not c)):
            self._swings.append(Swing(centre, c.ts, c.high, "high"))
            self._at.append(centre)
        if (all(c.low <= b.low for b in window)
                and any(c.low < b.low for b in window if b is not c)):
            self._swings.append(Swing(centre, c.ts, c.low, "low"))
            self._at.append(centre)

    # ---- higher timeframe -------------------------------------------------
    #
    # Kept here rather than in a separate object because it is the same
    # question about the same series: what structure was knowable at bar N.

    def htf(self, minutes: int, upto: int,
            max_htf_bars: int | None = DEFAULT_SWING_WINDOW) -> list[Bar]:
        """Same result as `resample_tail`, without redoing the finished buckets.

        Resampling per signal was the second quadratic: 25.4 of 28.7 seconds in
        one profile. Queries arrive with a non-decreasing `upto`, so a closed
        bucket never changes and is aggregated exactly once. Only the bucket
        currently forming is rebuilt, which costs `minutes` bars.
        """
        if minutes <= 0:
            raise ValueError("minutes must be positive")
        st = self._htf.get(minutes)
        if st is None or upto < st["pos"]:
            # A query that moves backwards means a different replay; the
            # carried-forward buckets describe the old one, so start again.
            st = {"complete": [], "start": 0, "pos": -1, "key": None}
            self._htf[minutes] = st

        bars = self._bars
        for i in range(st["pos"] + 1, upto + 1):
            k = _bucket_key(bars[i], minutes)
            if st["key"] is None:
                st["key"], st["start"] = k, i
            elif k != st["key"]:
                st["complete"].append(_aggregate(bars, st["start"], i - 1))
                st["key"], st["start"] = k, i
        st["pos"] = upto

        forming = _aggregate(bars, st["start"], upto)
        if max_htf_bars is None:
            return [*st["complete"], forming]
        keep = max(0, max_htf_bars - 1)
        if not keep:
            return [forming]
        # max(0, ...) matters: a negative start index would slice from the end
        # and silently return a few bars instead of every one there is.
        lo = max(0, len(st["complete"]) - keep)
        return [*st["complete"][lo:], forming]

    def confirmed(self, upto: int, window: int | None = None) -> list[Swing]:
        """Swings knowable at `upto`, oldest first, with no lookahead.

        Equivalent to `confirmed_swings(bars, upto, lookback, window=None)`
        restricted to `window`. Note this is *not* identical to
        `confirmed_swings(..., window=N)`: that rescans a slice, so the first
        `lookback` bars of the slice can never qualify and real swings are
        dropped at the window's left edge. Scanning once over the whole series
        has no such edge, so the index is the more complete answer.
        """
        hi = bisect_right(self._at, upto - self.lookback)
        lo = 0 if window is None else bisect_left(self._at, upto - window + 1)
        return self._swings[lo:hi]


class SwingIndexCache:
    """One `SwingIndex` per bar series, for strategy callables reused across
    several series -- walk-forward folds, per-instrument runs, parameter sweeps.

    Keyed on object identity, and the series themselves are held rather than
    their `id()`s. An id released by garbage collection can be reissued to a
    different list, at which point an id-keyed cache would answer from another
    instrument's structure while looking perfectly healthy. Length is rechecked
    too, so a series that grew gets reindexed instead of going stale.
    """

    def __init__(self, lookback: int = 2, max_series: int = 4):
        self.lookback = lookback
        self.max_series = max_series
        self._entries: list[tuple[list[Bar], SwingIndex]] = []

    def get(self, bars: list[Bar]) -> SwingIndex:
        for pos, (held, idx) in enumerate(self._entries):
            if held is bars:
                if len(idx) == len(bars):
                    return idx
                break
        else:
            pos = None
        if pos is not None:
            self._entries.pop(pos)
        idx = SwingIndex(bars, self.lookback)
        self._entries.append((bars, idx))
        if len(self._entries) > self.max_series:
            self._entries.pop(0)
        return idx


def _aggregate(bars: list[Bar], lo: int, hi: int) -> Bar:
    """One higher-timeframe bar from `bars[lo:hi + 1]`."""
    first, last = bars[lo], bars[hi]
    high, low, vol = first.high, first.low, 0.0
    for i in range(lo, hi + 1):
        b = bars[i]
        if b.high > high:
            high = b.high
        if b.low < low:
            low = b.low
        vol += b.volume
    return Bar(first.ts, first.open, high, low, last.close, vol)


def _bucket_key(bar: Bar, minutes: int):
    ny = bar.ny
    return (ny.date(), ny.hour, ny.minute // minutes)


def resample_tail(bars: list[Bar], minutes: int, upto: int,
                  max_htf_bars: int | None = DEFAULT_SWING_WINDOW) -> list[Bar]:
    """The tail of `resample(bars[:upto + 1], minutes)`, in bounded time.

    Resampling all history on every signal is the other half of the quadratic:
    at 750,000 bars each call walks the whole file to build higher-timeframe
    bars that only the last few hundred of which are ever read.

    The result is bit-identical to the last `max_htf_bars` entries of the full
    resample because the scan start is snapped back to a bucket boundary. A
    partial first bucket would give that one bar a different open, high and low
    -- a difference small enough to look like nothing and large enough to move
    a swing.
    """
    if minutes <= 0:
        raise ValueError("minutes must be positive")
    if max_htf_bars is None:
        return resample(bars[:upto + 1], minutes)
    lo = upto
    seen = 1
    key = _bucket_key(bars[upto], minutes)
    i = upto - 1
    while i >= 0:
        k = _bucket_key(bars[i], minutes)
        if k != key:
            if seen >= max_htf_bars:
                break
            seen += 1
            key = k
        lo = i
        i -= 1
    return resample(bars[lo:upto + 1], minutes)


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
