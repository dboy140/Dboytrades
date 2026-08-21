"""Fetch 1-minute bars from Dukascopy's public data feed.

The web export form at dukascopy.com/swiss/english/marketwatch/historical/
downloads one day at a time, which makes two years of history 730 manual
downloads. The same data sits behind a plain HTTP feed, one file per hour, and
this module reads that instead.

Nothing here needs an account, a key or a desktop install -- which matters,
because JForex and MetaTrader are both desktop-only and a Chromebook can run
neither.

The network half of this cannot be tested in the build environment (egress is
blocked), so it is deliberately kept thin: a URL builder and a fetch loop. All
the logic that can be wrong in a quiet, data-corrupting way -- decoding the
binary records, scaling prices, bucketing into minutes -- is pure and tested.
"""

from __future__ import annotations

import lzma
import struct
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

FEED = "https://datafeed.dukascopy.com/datafeed"

# One tick is 20 bytes, big-endian: ms offset into the hour, ask, bid, then
# ask and bid volume as floats. Prices are integers in "points" and must be
# divided by an instrument-specific factor.
TICK = struct.Struct(">IIIff")
TICK_SIZE = TICK.size

# Number of points per unit of price. Five-decimal FX pairs use 1e5; anything
# quoted in JPY, and gold, use 1e3. Getting this wrong does not raise -- it
# silently scales every price by 100, so it is a table rather than a guess.
POINT_FACTOR = {
    "EURUSD": 1e5, "GBPUSD": 1e5, "AUDUSD": 1e5, "NZDUSD": 1e5,
    "USDCAD": 1e5, "USDCHF": 1e5, "EURGBP": 1e5, "EURCHF": 1e5,
    "USDJPY": 1e3, "EURJPY": 1e3, "GBPJPY": 1e3, "AUDJPY": 1e3,
    "XAUUSD": 1e3, "XAGUSD": 1e3,
}


def point_factor(symbol: str) -> float:
    try:
        return POINT_FACTOR[symbol.upper()]
    except KeyError:
        raise KeyError(
            f"no point factor known for {symbol!r}. Add it to POINT_FACTOR "
            "rather than guessing: a wrong factor does not fail, it scales "
            "every price silently."
        ) from None


def hour_url(symbol: str, when: datetime) -> str:
    """Feed URL for one hour of ticks.

    The month is ZERO-indexed in these paths -- January is 00. That is the
    single easiest thing to get wrong here, and the failure mode is a
    successful download of the wrong month.
    """
    return (f"{FEED}/{symbol.upper()}/{when.year:04d}/{when.month - 1:02d}/"
            f"{when.day:02d}/{when.hour:02d}h_ticks.bi5")


@dataclass(frozen=True)
class Tick:
    ts: datetime
    bid: float
    ask: float
    bid_volume: float
    ask_volume: float


def decode_bi5(payload: bytes, symbol: str, hour_start: datetime) -> list[Tick]:
    """Decode one .bi5 hour file into ticks.

    Empty files are normal, not an error: the market is shut at weekends and
    Dukascopy serves a zero-length body for those hours.
    """
    if not payload:
        return []
    raw = _decompress(payload)
    if len(raw) % TICK_SIZE:
        raise ValueError(
            f"{len(raw)} bytes is not a whole number of {TICK_SIZE}-byte ticks; "
            "the file is truncated or is not a .bi5")
    factor = point_factor(symbol)
    out: list[Tick] = []
    for off in range(0, len(raw), TICK_SIZE):
        ms, ask, bid, ask_v, bid_v = TICK.unpack_from(raw, off)
        out.append(Tick(hour_start + timedelta(milliseconds=ms),
                        bid / factor, ask / factor, bid_v, ask_v))
    return out


def _decompress(payload: bytes) -> bytes:
    """Dukascopy writes the old LZMA-alone container, not .xz.

    Tried in order rather than assumed, because which one comes back has
    changed before and an exception here is much better than silence.
    """
    for fmt in (lzma.FORMAT_ALONE, lzma.FORMAT_AUTO, lzma.FORMAT_XZ):
        try:
            return lzma.LZMADecompressor(format=fmt).decompress(payload)
        except lzma.LZMAError:
            continue
    raise ValueError("could not decompress .bi5 payload with any LZMA format")


def ticks_to_minutes(ticks: list[Tick], side: str = "bid") -> list[tuple]:
    """Aggregate ticks into 1-minute OHLC rows, oldest first.

    Returns plain tuples rather than Bars so this module stays importable
    without the rest of the engine -- the Colab notebook writes CSV directly.

    A minute with no ticks produces no row. It is not carried forward from the
    previous minute: an invented bar would be indistinguishable from a real one
    downstream, and the loader would happily backtest on it.
    """
    if side not in ("bid", "ask"):
        raise ValueError("side must be 'bid' or 'ask'")
    buckets: dict[datetime, list] = {}
    for t in ticks:
        minute = t.ts.replace(second=0, microsecond=0)
        price = t.bid if side == "bid" else t.ask
        vol = t.bid_volume if side == "bid" else t.ask_volume
        b = buckets.get(minute)
        if b is None:
            buckets[minute] = [price, price, price, price, vol]
        else:
            if price > b[1]:
                b[1] = price
            if price < b[2]:
                b[2] = price
            b[3] = price
            b[4] += vol
    return [(m, *buckets[m]) for m in sorted(buckets)]


def hours_between(start: datetime, end: datetime):
    """Every UTC hour in [start, end), weekends included.

    Weekend hours are requested rather than skipped. The feed answers them with
    an empty body, and that is a cheaper way to be right about session
    boundaries and holidays than encoding a calendar here.
    """
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start and end must be timezone-aware")
    cur = start.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    end = end.astimezone(timezone.utc)
    while cur < end:
        yield cur
        cur += timedelta(hours=1)


CSV_HEADER = "timestamp,open,high,low,close,volume"


def rows_to_csv(rows: list[tuple]) -> str:
    """Render as the CSV the loader expects, timestamps carrying an offset.

    The offset is not decoration. `load_csv` rejects naive timestamps, because
    a file stamped in broker local time and read as UTC puts every session
    window hours out while the backtest runs on regardless.
    """
    out = [CSV_HEADER]
    for ts, o, h, l, c, v in rows:
        out.append(f"{ts.isoformat()},{o:.5f},{h:.5f},{l:.5f},{c:.5f},{v:.2f}")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------- network ----
#
# Thin on purpose. Everything above this line is pure and tested; none of this
# can be exercised in the build environment, so it is kept to fetching bytes
# and handing them to code that is.

def fetch_hour(symbol: str, when: datetime, *, timeout: float = 30.0,
               attempts: int = 3) -> bytes:
    """One hour of raw .bi5 bytes. A 404 means "no data", not a failure."""
    import time
    import urllib.error
    import urllib.request

    url = hour_url(symbol, when)
    last: Exception | None = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return b""      # market shut, or before this symbol's history
            last = exc
        except Exception as exc:                      # noqa: BLE001
            last = exc
        if i < attempts - 1:
            time.sleep(2 ** i)
    raise RuntimeError(f"failed to fetch {url} after {attempts} attempts: {last}")


def fetch_range(symbol: str, start: datetime, end: datetime, *,
                side: str = "bid", workers: int = 16,
                progress=None) -> list[tuple]:
    """Every 1-minute bar in [start, end), fetched concurrently.

    Hours are fetched in parallel but reassembled in chronological order, so
    the result does not depend on which requests happen to finish first.
    """
    from concurrent.futures import ThreadPoolExecutor

    hours = list(hours_between(start, end))
    payloads: list[bytes | None] = [None] * len(hours)

    def one(i: int) -> None:
        payloads[i] = fetch_hour(symbol, hours[i])

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for _ in pool.map(one, range(len(hours))):
            done += 1
            if progress and done % 200 == 0:
                progress(done, len(hours))
    if progress:
        progress(len(hours), len(hours))

    ticks: list[Tick] = []
    for hour, payload in zip(hours, payloads):
        ticks.extend(decode_bi5(payload or b"", symbol, hour))
    return ticks_to_minutes(ticks, side)
