"""Bar-by-bar replay. No lookahead, pessimistic fills.

Two decisions here matter more than the rest of the engine put together:

  * The strategy sees `bars[:i+1]` and nothing else. Every helper it calls
    takes an `upto` index for the same reason.
  * When a bar's range spans both stop and target, the STOP is taken. Without
    that rule a backtest quietly awards itself the winner every time, and the
    error compounds hardest on exactly the volatile bars that matter.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime

from .bars import Bar
from .signals import Signal


@dataclass
class Trade:
    setup: str
    direction: str
    rule_ids: list[str]
    window: str
    entry_index: int
    entry_ts: datetime
    entry: float
    stop: float
    target: float
    exit_index: int | None = None
    exit_ts: datetime | None = None
    exit_price: float | None = None
    exit_reason: str = ""
    mae: float = 0.0   # worst excursion against, in R
    mfe: float = 0.0   # best excursion for, in R

    @property
    def risk(self) -> float:
        return abs(self.entry - self.stop)

    @property
    def r_multiple(self) -> float:
        if self.exit_price is None or self.risk == 0:
            return 0.0
        move = (self.exit_price - self.entry) if self.direction == "long" \
            else (self.entry - self.exit_price)
        return move / self.risk

    @property
    def is_open(self) -> bool:
        return self.exit_price is None


@dataclass
class Result:
    trades: list[Trade] = field(default_factory=list)
    signals_generated: int = 0
    signals_not_filled: int = 0

    @property
    def closed(self) -> list[Trade]:
        return [t for t in self.trades if not t.is_open]

    def stats(self) -> dict:
        closed = self.closed
        if not closed:
            return {"trades": 0, "note": "no closed trades"}
        rs = [t.r_multiple for t in closed]
        wins = [r for r in rs if r > 0]
        losses = [r for r in rs if r <= 0]
        streak = worst = 0
        for r in rs:
            streak = streak + 1 if r <= 0 else 0
            worst = max(worst, streak)
        equity, peak, dd = 0.0, 0.0, 0.0
        for r in rs:
            equity += r
            peak = max(peak, equity)
            dd = min(dd, equity - peak)
        return {
            "trades": len(closed),
            "win_rate": round(len(wins) / len(closed), 3),
            "avg_r": round(statistics.mean(rs), 3),
            "expectancy_r": round(statistics.mean(rs), 3),
            "total_r": round(sum(rs), 2),
            "profit_factor": round(sum(wins) / abs(sum(losses)), 2) if losses and sum(losses) else None,
            "max_consecutive_losses": worst,
            "max_drawdown_r": round(dd, 2),
            "avg_mae_r": round(statistics.mean(t.mae for t in closed), 3),
            "avg_mfe_r": round(statistics.mean(t.mfe for t in closed), 3),
            "signals_generated": self.signals_generated,
            "signals_not_filled": self.signals_not_filled,
        }

    def by_rule(self) -> dict[str, dict]:
        """Per-rule performance -- the number the weekly review loop needs."""
        out: dict[str, list[float]] = {}
        for t in self.closed:
            for rid in t.rule_ids:
                out.setdefault(rid, []).append(t.r_multiple)
        return {
            rid: {"trades": len(rs), "avg_r": round(statistics.mean(rs), 3),
                  "win_rate": round(sum(1 for r in rs if r > 0) / len(rs), 3),
                  "enough_data": len(rs) >= 20}
            for rid, rs in sorted(out.items())
        }


def _touched(bar: Bar, price: float) -> bool:
    return bar.low <= price <= bar.high


def run(bars: list[Bar], strategy, *, max_open: int = 1,
        entry_expiry_bars: int = 10) -> Result:
    """Replay `bars`, calling `strategy(bars, i) -> Signal | None`.

    A signal becomes a pending limit order at its entry price, valid for
    `entry_expiry_bars`. Filling at the signal bar's close instead would be a
    market order, which is not what any of the entry rules describe.
    """
    res = Result()
    pending: list[tuple[Signal, int]] = []
    open_trades: list[Trade] = []

    for i, bar in enumerate(bars):
        # 1. Manage open trades first: a position on the books takes priority
        #    over looking for new ones.
        for t in list(open_trades):
            risk = t.risk or 1e-9
            if t.direction == "long":
                t.mae = min(t.mae, (bar.low - t.entry) / risk)
                t.mfe = max(t.mfe, (bar.high - t.entry) / risk)
                hit_stop, hit_target = bar.low <= t.stop, bar.high >= t.target
            else:
                t.mae = min(t.mae, (t.entry - bar.high) / risk)
                t.mfe = max(t.mfe, (t.entry - bar.low) / risk)
                hit_stop, hit_target = bar.high >= t.stop, bar.low <= t.target
            if hit_stop or hit_target:
                # Pessimistic: when both are inside the bar, assume the stop.
                t.exit_index, t.exit_ts = i, bar.ts
                if hit_stop:
                    t.exit_price, t.exit_reason = t.stop, "stop"
                else:
                    t.exit_price, t.exit_reason = t.target, "target"
                    # A limit exit cannot fill better than the target, so cap
                    # MFE there. Leaving the bar's overshoot in would report
                    # profit that was never takeable and would make targets
                    # look better placed than they are.
                    t.mfe = min(t.mfe, abs(t.target - t.entry) / risk)
                open_trades.remove(t)

        # 2. Fill pending orders.
        for sig, placed in list(pending):
            if i - placed > entry_expiry_bars:
                pending.remove((sig, placed))
                res.signals_not_filled += 1
                continue
            if i > placed and _touched(bar, sig.entry) and len(open_trades) < max_open:
                t = Trade(sig.setup, sig.direction, list(sig.rule_ids), sig.window,
                          i, bar.ts, sig.entry, sig.stop, sig.target)
                res.trades.append(t)
                open_trades.append(t)
                pending.remove((sig, placed))

        # 3. Look for a new signal, with no visibility beyond bar i.
        if len(open_trades) + len(pending) < max_open:
            sig = strategy(bars, i)
            if sig is not None:
                res.signals_generated += 1
                pending.append((sig, i))

    return res
