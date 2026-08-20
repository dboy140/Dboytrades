"""Position sizing.  Rule: none.

ALL OF THIS IS UNSOURCED. Neither ICT nor NBBTRADER states position sizing,
risk per trade, daily limits or exposure caps anywhere in the 734,784-word
corpus -- that is GAPS G-01, the largest unsourced area in the project and the
one most likely to cost real money.

The arithmetic below is conventional practice. It is here so the backtest can
report currency drawdown rather than only R multiples, not because the corpus
justifies any particular number.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- UNSOURCED. Replace with your own backtested figures. -------------------
RISK_PCT = {"A": 1.0, "B": 0.5, "C": 0.0}
MAX_DAILY_PCT = 2.0
MAX_WEEKLY_PCT = 5.0
MAX_CONCURRENT = 2
CORRELATED = (("NAS100", "ES"), ("EURUSD", "GBPUSD"))
# ----------------------------------------------------------------------------


@dataclass
class Position:
    size: float
    risk_currency: float
    risk_pct_actual: float
    capped_by: str = ""


def position_size(account: float, risk_pct: float, stop_distance: float,
                  value_per_point: float, *, lot_step: float = 1.0) -> Position:
    """size = (account * risk%) / (stop_distance * value_per_point), rounded DOWN.

    Rounding down is not a detail: rounding up breaches the stated risk limit on
    every single trade, and the breach compounds with position count.
    """
    if stop_distance <= 0 or value_per_point <= 0:
        raise ValueError("stop_distance and value_per_point must be positive")
    budget = account * (risk_pct / 100.0)
    raw = budget / (stop_distance * value_per_point)
    size = (int(raw / lot_step)) * lot_step
    actual = size * stop_distance * value_per_point
    return Position(size, round(actual, 2),
                    round(actual / account * 100, 4) if account else 0.0)


def correlated(a: str, b: str) -> bool:
    """Two correlated positions at 1% each is a 2% trade wearing a disguise."""
    for group in CORRELATED:
        if a in group and b in group:
            return True
    return False


def daily_budget_left(risk_taken_today_pct: float,
                      max_daily_pct: float = MAX_DAILY_PCT) -> float:
    return max(0.0, max_daily_pct - risk_taken_today_pct)
