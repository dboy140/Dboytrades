"""Export backtest trades to the journal CSV.

Columns match strategy/backtest-template.csv so backtest output and hand-logged
live trades land in the same sheet and can be reviewed together. The column
that makes the weekly loop work is `rule_ids`: without it you can measure the
system but not fix it.
"""

from __future__ import annotations

import csv
from pathlib import Path

from .backtest import Trade
from .bars import NY
from .risk import position_size
from .sessions import uk_offset_hours

COLUMNS = [
    "date", "time_ny", "time_uk", "instrument", "setup", "tier", "rule_ids",
    "htf_bias", "draw_on_liquidity", "resistance_class", "session", "window_hit",
    "pd_array", "entry", "stop", "target", "size", "risk_pct", "checklist_score",
    "outcome", "r_multiple", "mae", "mfe", "exit_reason", "notes",
]

TIER = {"Silver Bullet": "A", "MMBM": "A", "MMSM": "A", "LDN to New York OTE": "B"}


def to_row(t: Trade, instrument: str, *, account: float | None = None,
           value_per_point: float = 1.0, lot_step: float = 1.0) -> dict:
    ny = t.entry_ts.astimezone(NY)
    uk = t.entry_ts.astimezone(__import__("zoneinfo").ZoneInfo("Europe/London"))
    tier = TIER.get(t.setup, "C")

    size = risk_pct = ""
    if account:
        from .risk import RISK_PCT
        pos = position_size(account, RISK_PCT.get(tier, 0.0), t.risk,
                            value_per_point, lot_step=lot_step)
        size, risk_pct = pos.size, pos.risk_pct_actual

    return {
        "date": ny.date().isoformat(),
        "time_ny": ny.strftime("%H:%M"),
        "time_uk": uk.strftime("%H:%M"),
        "instrument": instrument,
        "setup": t.setup,
        "tier": tier,
        "rule_ids": ",".join(t.rule_ids),
        "htf_bias": t.direction,
        "draw_on_liquidity": f"{t.target:g}",
        # MM-006 is enforced before a signal is emitted, so any trade that
        # exists passed it. Recorded explicitly so the column is auditable
        # rather than assumed.
        "resistance_class": "low" if "MM-006" in t.rule_ids else "unchecked",
        "session": t.window,
        "window_hit": "yes" if t.window else "no",
        "pd_array": "FVG" if t.setup == "Silver Bullet" else "OTE",
        "entry": f"{t.entry:g}", "stop": f"{t.stop:g}", "target": f"{t.target:g}",
        "size": size, "risk_pct": risk_pct,
        "checklist_score": "",   # scored by hand before entry; not inferable after
        "outcome": "win" if t.r_multiple > 0 else "loss" if not t.is_open else "open",
        "r_multiple": round(t.r_multiple, 3),
        "mae": round(t.mae, 3), "mfe": round(t.mfe, 3),
        "exit_reason": t.exit_reason,
        "notes": f"UK offset +{uk_offset_hours(t.entry_ts)}h",
    }


def write(path: str | Path, trades: list[Trade], instrument: str, **kw) -> int:
    rows = [to_row(t, instrument, **kw) for t in trades if not t.is_open]
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return len(rows)
