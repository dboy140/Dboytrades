"""The bot loop: bars in, orders out, with every rail enforced.

Deliberately agnostic about where bars come from. `BarFeed` is a protocol, so
the same loop drives a CSV replay (paper), a broker's live feed, or a recorded
session for debugging -- and the paper and live paths are literally the same
code, which is the only way paper results mean anything about live behaviour.

Nothing here decides whether the strategy is any good. `Executor` refuses live
mode without a validation report; this module just runs the loop.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator, Protocol

from .bars import Bar, SwingIndex
from .bias import daily_bias
from .live import Executor, SafetyViolation
from .signals import Signal, ote, silver_bullet

log = logging.getLogger(__name__)


class BarFeed(Protocol):
    def __iter__(self) -> Iterator[Bar]: ...


@dataclass
class RunnerConfig:
    instrument: str
    setup: str = "ote"                  # "ote" | "silver_bullet"
    tier: str = "B"                     # OTE is Tier B, Silver Bullet Tier A
    bias_mode: str = "auto"             # "auto" | "long" | "short"
    displacement_multiple: float = 1.5
    min_rr: float = 1.0
    warmup_bars: int = 500              # structure needs history before signals
    journal_path: str = "logs/journal.jsonl"


@dataclass
class RunnerStats:
    bars_seen: int = 0
    signals: int = 0
    submitted: int = 0
    blocked: int = 0
    block_reasons: dict[str, int] = field(default_factory=dict)

    def note_block(self, reason: str) -> None:
        self.blocked += 1
        key = reason.split(".")[0][:60]
        self.block_reasons[key] = self.block_reasons.get(key, 0) + 1


class Runner:
    def __init__(self, executor: Executor, config: RunnerConfig):
        self.executor = executor
        self.config = config
        self.stats = RunnerStats()
        self._bars: list[Bar] = []
        # Structure is maintained incrementally: each bar can only confirm the
        # swing sitting `lookback` bars behind it, so this is O(1) per bar
        # where rescanning history per bar was quadratic.
        self._index = SwingIndex(lookback=2)
        self._daily: list[Bar] = []
        self._bias_cache: dict = {}
        self._journal = Path(config.journal_path)
        self._journal.parent.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------- internals ----

    def _roll_daily(self, bar: Bar) -> None:
        """Maintain a daily series for the bias, closing each day as it ends."""
        d = bar.ny.date()
        if not self._daily or self._daily[-1].ny.date() != d:
            self._daily.append(bar)
            return
        prev = self._daily[-1]
        self._daily[-1] = Bar(prev.ts, prev.open, max(prev.high, bar.high),
                              min(prev.low, bar.low), bar.close,
                              prev.volume + bar.volume)

    def _bias_for(self, bar: Bar) -> str | None:
        """Bias from COMPLETED prior days only.

        Using the day in progress would be lookahead, and in live trading it
        would simply be unavailable.
        """
        if self.config.bias_mode in ("long", "short"):
            return self.config.bias_mode
        d = bar.ny.date()
        if d in self._bias_cache:
            return self._bias_cache[d]
        completed = [b for b in self._daily if b.ny.date() < d]
        result = None
        if len(completed) >= 6:
            res = daily_bias(completed, len(completed) - 1)
            result = res.direction
        self._bias_cache[d] = result
        return result

    def _signal(self, index: int) -> Signal | None:
        cfg = self.config
        if cfg.setup == "silver_bullet":
            bias = self._bias_for(self._bars[index])
            if bias is None:
                return None
            return silver_bullet(self._bars, index, cfg.instrument, bias,
                                 displacement_multiple=cfg.displacement_multiple,
                                 min_rr=cfg.min_rr, index=self._index)
        return ote(self._bars, index, cfg.instrument, min_rr=cfg.min_rr,
                   index=self._index)

    def _record(self, event: dict) -> None:
        with self._journal.open("a") as fh:
            fh.write(json.dumps(event, default=str) + "\n")

    # --------------------------------------------------------------- loop ----

    def on_bar(self, bar: Bar) -> dict | None:
        """Process one bar. Returns the order dict if one was placed."""
        self._bars.append(bar)
        self._index.push(bar)
        self._roll_daily(bar)
        self.stats.bars_seen += 1

        if len(self._bars) < self.config.warmup_bars:
            return None

        sig = self._signal(len(self._bars) - 1)
        if sig is None:
            return None
        self.stats.signals += 1

        try:
            order = self.executor.submit(sig, self.config.instrument,
                                         self.config.tier, bar.ts)
        except SafetyViolation as exc:
            self.stats.note_block(str(exc))
            self._record({"ts": bar.ts, "event": "blocked", "reason": str(exc)[:200],
                          "rule_ids": sig.rule_ids})
            return None

        self.stats.submitted += 1
        self._record({"ts": bar.ts, "event": "order", **order,
                      "entry": sig.entry, "stop": sig.stop, "target": sig.target,
                      "rr": round(sig.rr, 2)})
        return order

    def run(self, feed: BarFeed) -> RunnerStats:
        for bar in feed:
            self.on_bar(bar)
        return self.stats

    def summary(self) -> str:
        s = self.stats
        lines = [
            f"bars seen   {s.bars_seen:,}",
            f"signals     {s.signals}",
            f"submitted   {s.submitted}",
            f"blocked     {s.blocked}",
        ]
        for reason, n in sorted(s.block_reasons.items(), key=lambda kv: -kv[1]):
            lines.append(f"   {n:>4}x {reason}")
        return "\n".join(lines)
