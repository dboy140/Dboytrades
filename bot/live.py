"""Live/paper execution with hard safety rails.

The rails are the point. This module will not place a live order for a strategy
that has not produced a positive out-of-sample result, because the most likely
way to lose money here is not a coding bug -- it is trading a curve-fitted
system with confidence borrowed from its backtest.

Defaults are chosen so that every mistake fails toward doing nothing:

  * paper mode unless live is passed explicitly
  * live mode refuses without a validation report showing positive OOS
  * daily loss limit, consecutive-loss kill switch, max concurrent positions
  * position size rounds DOWN, always
  * a broker adapter is required; there is no built-in default that could
    silently connect to a real account
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Protocol

from .bars import Bar
from .signals import Signal

log = logging.getLogger(__name__)


class Broker(Protocol):
    """Minimal broker interface. Implement this for your platform."""

    def account_balance(self) -> float: ...
    def place_order(self, instrument: str, direction: str, size: float,
                    entry: float, stop: float, target: float) -> str: ...
    def open_positions(self) -> list[dict]: ...
    def cancel(self, order_id: str) -> None: ...


class PaperBroker:
    """Records intent without sending anything anywhere."""

    def __init__(self, balance: float = 25_000.0):
        self._balance = balance
        self.orders: list[dict] = []

    def account_balance(self) -> float:
        return self._balance

    def place_order(self, instrument, direction, size, entry, stop, target) -> str:
        oid = f"paper-{len(self.orders) + 1}"
        self.orders.append({"id": oid, "instrument": instrument,
                            "direction": direction, "size": size, "entry": entry,
                            "stop": stop, "target": target,
                            "placed_at": datetime.utcnow().isoformat()})
        return oid

    def open_positions(self) -> list[dict]:
        return []

    def cancel(self, order_id: str) -> None:
        self.orders = [o for o in self.orders if o["id"] != order_id]


class SafetyViolation(RuntimeError):
    """A rail was hit. Never caught and retried -- it means stop."""


@dataclass
class RiskLimits:
    """All UNSOURCED. The corpus contains no position sizing whatsoever
    (GAPS G-01). Replace these with numbers your own backtest justifies."""

    risk_pct_tier_a: float = 1.0
    risk_pct_tier_b: float = 0.5
    max_daily_loss_pct: float = 2.0
    max_weekly_loss_pct: float = 5.0
    max_concurrent: int = 2
    max_consecutive_losses: int = 4
    correlated: tuple[tuple[str, ...], ...] = (("NAS100", "US100", "ES"),
                                               ("EURUSD", "GBPUSD"))


@dataclass
class SessionState:
    day: date | None = None
    realised_r_today: float = 0.0
    realised_pct_today: float = 0.0
    consecutive_losses: int = 0
    open_instruments: list[str] = field(default_factory=list)
    halted: bool = False
    halt_reason: str = ""


def position_size(balance: float, risk_pct: float, stop_distance: float,
                  value_per_point: float) -> float:
    """size = (balance * risk%) / (stop distance * value per point), rounded DOWN.

    Rounding up would breach the risk limit on every single trade.
    """
    if stop_distance <= 0 or value_per_point <= 0:
        raise ValueError("stop distance and value per point must be positive")
    raw = (balance * risk_pct / 100.0) / (stop_distance * value_per_point)
    import math
    return math.floor(raw * 100) / 100.0


def validation_allows_live(report_path: str | Path) -> tuple[bool, str]:
    """Live trading requires evidence, not intent.

    Reads a walk-forward report and permits live mode only when the
    out-of-sample result is positive over a real sample.
    """
    p = Path(report_path)
    if not p.exists():
        return False, (f"no validation report at {p}. Run walk-forward analysis "
                       "before trading this live.")
    try:
        data = json.loads(p.read_text())
    except Exception as exc:
        return False, f"validation report unreadable: {exc}"

    trades = data.get("total_oos_trades", 0)
    expectancy = data.get("combined_oos_expectancy", 0)
    if trades < 20:
        return False, (f"only {trades} out-of-sample trades. Nothing is "
                       "conclusive below 20.")
    if expectancy <= 0:
        return False, (f"out-of-sample expectancy is {expectancy}. The edge did "
                       "not survive validation.")
    return True, f"validated: {expectancy:+.3f}R over {trades} out-of-sample trades"


class Executor:
    def __init__(self, broker: Broker, limits: RiskLimits | None = None, *,
                 mode: str = "paper", validation_report: str | Path | None = None,
                 value_per_point: dict[str, float] | None = None):
        if mode not in ("paper", "live"):
            raise ValueError("mode must be 'paper' or 'live'")
        if mode == "live":
            ok, why = validation_allows_live(validation_report or "")
            if not ok:
                raise SafetyViolation(
                    f"refusing to trade live: {why}\n"
                    "Run in paper mode until the strategy has earned it."
                )
            log.warning("LIVE MODE -- %s", why)
        self.broker = broker
        self.limits = limits or RiskLimits()
        self.mode = mode
        self.state = SessionState()
        self.value_per_point = value_per_point or {}

    # ------------------------------------------------------------ rails ----

    def _roll_day(self, when: datetime) -> None:
        d = when.date()
        if self.state.day != d:
            self.state = SessionState(day=d)

    def _check(self, signal: Signal, instrument: str) -> None:
        s, lim = self.state, self.limits
        if s.halted:
            raise SafetyViolation(f"halted: {s.halt_reason}")
        if s.realised_pct_today <= -lim.max_daily_loss_pct:
            s.halted, s.halt_reason = True, (
                f"daily loss limit hit ({s.realised_pct_today:.2f}%)")
            raise SafetyViolation(s.halt_reason)
        if s.consecutive_losses >= lim.max_consecutive_losses:
            s.halted, s.halt_reason = True, (
                f"{s.consecutive_losses} consecutive losses")
            raise SafetyViolation(s.halt_reason)
        if len(s.open_instruments) >= lim.max_concurrent:
            raise SafetyViolation(
                f"already at max concurrent positions ({lim.max_concurrent})")
        for group in lim.correlated:
            if instrument in group and any(o in group for o in s.open_instruments):
                raise SafetyViolation(
                    f"correlated exposure: {instrument} against "
                    f"{s.open_instruments}. Two correlated positions at 1% is a "
                    "2% trade in disguise.")

    # ---------------------------------------------------------- ordering ----

    def submit(self, signal: Signal, instrument: str, tier: str,
               when: datetime) -> dict:
        self._roll_day(when)
        self._check(signal, instrument)

        vpp = self.value_per_point.get(instrument)
        if vpp is None:
            raise SafetyViolation(
                f"no value-per-point configured for {instrument}. Refusing to "
                "size a position on a guess.")

        risk_pct = (self.limits.risk_pct_tier_a if tier == "A"
                    else self.limits.risk_pct_tier_b if tier == "B" else 0.0)
        if risk_pct <= 0:
            raise SafetyViolation(f"tier {tier} is study-only; size is zero")

        size = position_size(self.broker.account_balance(), risk_pct,
                             signal.risk, vpp)
        if size <= 0:
            raise SafetyViolation(
                f"computed size {size}; stop distance {signal.risk} is too wide "
                "for this balance at {risk_pct}% risk")

        oid = self.broker.place_order(instrument, signal.direction, size,
                                      signal.entry, signal.stop, signal.target)
        self.state.open_instruments.append(instrument)
        return {"order_id": oid, "instrument": instrument, "size": size,
                "risk_pct": risk_pct, "mode": self.mode,
                "rule_ids": list(signal.rule_ids)}

    def record_close(self, instrument: str, r_multiple: float,
                     risk_pct: float) -> None:
        s = self.state
        if instrument in s.open_instruments:
            s.open_instruments.remove(instrument)
        s.realised_r_today += r_multiple
        s.realised_pct_today += r_multiple * risk_pct
        s.consecutive_losses = 0 if r_multiple > 0 else s.consecutive_losses + 1
