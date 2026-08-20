"""Turn facts into trade candidates.

Only the setups the corpus defines mechanically are implemented: Silver Bullet
(SB-001..004) and OTE (OTE-001..003). MMBM and MMSM are deliberately absent --
"original consolidation" and "smart money reversal" are demonstrated on charts
and never defined numerically, so any threshold here would be invented and
falsely attributed. See bot/README.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .bars import Bar, confirmed_swings, resample
from .filters import low_resistance
from .patterns import MSS, FVG, detect_mss, find_fvgs, is_displacement, ote_levels
from .sessions import active_windows


@dataclass
class Signal:
    index: int
    setup: str
    direction: str          # "long" | "short"
    entry: float
    stop: float
    target: float
    rule_ids: list[str]
    window: str = ""
    notes: str = ""

    @property
    def risk(self) -> float:
        return abs(self.entry - self.stop)

    @property
    def reward(self) -> float:
        return abs(self.target - self.entry)

    @property
    def rr(self) -> float:
        return self.reward / self.risk if self.risk > 0 else 0.0


def _is_coherent(sig: Signal, min_rr: float) -> bool:
    """Reject a signal whose stop or target sits on the wrong side of entry.

    Exists because an inverted stop does not fail loudly -- it books instant
    wins and produced a 100% win rate on random-walk data during development.
    Any geometry error here flatters the backtest instead of crashing it.
    """
    if sig.direction == "long":
        if not (sig.stop < sig.entry < sig.target):
            return False
    else:
        if not (sig.target < sig.entry < sig.stop):
            return False
    return sig.risk > 0 and sig.rr >= min_rr


def _nearest_target(mss: MSS | None, bars: list[Bar], upto: int,
                    direction: str, htf_minutes: int = 15) -> float | None:
    """Nearest opposing liquidity. SB-004: take the nearest pool, not extension.

    Uses the same timeframe as the MM-006 resistance check. If the target were
    drawn from 1m wiggles while resistance was judged on 15m structure, the two
    would be answering different questions and the filter would look stricter
    than it is.
    """
    if mss and mss.targets:
        return mss.targets[0]
    if htf_minutes and htf_minutes > 1:
        htf = resample(bars[:upto + 1], htf_minutes)
        swings = confirmed_swings(htf, len(htf) - 1)
    else:
        swings = confirmed_swings(bars, upto)
    close = bars[upto].close
    if direction == "long":
        highs = sorted(s.price for s in swings if s.kind == "high" and s.price > close)
        return highs[0] if highs else None
    lows = sorted((s.price for s in swings if s.kind == "low" and s.price < close),
                  reverse=True)
    return lows[0] if lows else None


def silver_bullet(bars: list[Bar], upto: int, instrument: str, bias: str,
                  *, displacement_multiple: float = 1.5,
                  news_day: bool = False, min_rr: float = 1.0,
                  rejections: list[str] | None = None) -> Signal | None:
    """SB-001/002 window, SB-003 entry and stop, SB-004 target.

    `bias` must be supplied by the caller: HTF bias is not automatable
    (GAPS G-07), so the engine refuses to guess it.
    """
    if bias not in ("long", "short"):
        return None
    bar = bars[upto]
    windows = [w for w in active_windows(bar.ts, instrument, news_day)
               if w.key.startswith("silver_bullet")]
    if not windows:
        return None
    if not is_displacement(bars, upto, displacement_multiple):
        return None

    gaps = [g for g in find_fvgs(bars[:upto + 1]) if g.index == upto]
    want = "bullish" if bias == "long" else "bearish"
    gap = next((g for g in gaps if g.direction == want), None)
    if gap is None:
        return None

    mss = detect_mss(bars, upto)
    target = _nearest_target(mss, bars, upto, bias)
    if target is None:
        return None  # MM-006: no defined objective, no trade

    entry = gap.consequent_encroachment
    # SB-003: "beyond the extreme of the candle that produced the displacement".
    # That is the MIDDLE bar of the three, not the third: for a bullish gap the
    # third bar's low IS the gap's top, so using it would place a long's stop
    # above its entry.
    displacement_bar = bars[upto - 1]
    stop = displacement_bar.low if bias == "long" else displacement_bar.high

    sig = Signal(upto, "Silver Bullet", bias, entry, stop, target,
                 ["SB-001" if "am" in windows[0].key else "SB-002", "SB-003", "SB-004"],
                 window=windows[0].key)
    if not _is_coherent(sig, min_rr):
        return None

    # MM-006 is the system's strongest claim; enforcing it here means the
    # backtest tests the system the corpus describes rather than a looser one.
    lr = low_resistance(sig.entry, sig.target, sig.direction, bars, upto)
    if not lr.passed:
        if rejections is not None:
            rejections.append(f"{lr.rule_id}: {lr.reason}")
        return None
    sig.rule_ids.append("MM-006")
    return sig


def ote(bars: list[Bar], upto: int, instrument: str,
        *, stop_buffer: float = 0.0, min_rr: float = 1.0,
        rejections: list[str] | None = None) -> Signal | None:
    """OTE-003 sequence, OTE-002 entry at 62% and stop beyond the fib origin.

    Unlike Silver Bullet this does not need an external bias: OTE-003 derives
    direction from the market structure shift itself.
    """
    bar = bars[upto]
    windows = [w for w in active_windows(bar.ts, instrument)
               if w.key in ("london_killzone", "ny_killzone", "nbb_london_sb", "nbb_ny_sb")]
    if not windows:
        return None

    mss = detect_mss(bars, upto)
    if mss is None or not mss.tradeable:
        return None

    swings = confirmed_swings(bars, upto)
    if mss.direction == "bullish":
        low = mss.swept_price
        highs = [s.price for s in swings if s.kind == "high" and s.price > low]
        if not highs:
            return None
        lv = ote_levels(max(highs), low, "bullish")
        entry, stop = lv["level_62"], low - stop_buffer
        direction = "long"
    else:
        high = mss.swept_price
        lows = [s.price for s in swings if s.kind == "low" and s.price < high]
        if not lows:
            return None
        lv = ote_levels(high, min(lows), "bearish")
        entry, stop = lv["level_62"], high + stop_buffer
        direction = "short"

    sig = Signal(upto, "LDN to New York OTE", direction, entry, stop,
                 mss.targets[0], ["OTE-001", "OTE-002", "OTE-003"],
                 window=windows[0].key,
                 notes="entry at 62% per OTE-002; 70.5/79 deliberately not used")
    if not _is_coherent(sig, min_rr):
        return None
    lr = low_resistance(sig.entry, sig.target, sig.direction, bars, upto)
    if not lr.passed:
        if rejections is not None:
            rejections.append(f"{lr.rule_id}: {lr.reason}")
        return None
    sig.rule_ids.append("MM-006")
    return sig
