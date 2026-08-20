"""CLI: run a backtest over a CSV of bars.

    python -m bot.run_backtest data/bars/NAS100_1m.csv --instrument NAS100 \
        --setup silver_bullet --bias long

CSV columns: timestamp,open,high,low,close[,volume]
Timestamps must carry a timezone or be UTC-marked (e.g. 2026-06-15T14:00:00Z).
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .backtest import run
from .bars import NY, UTC, Bar
from .bias import daily_bias
from . import journal
from .signals import ote, silver_bullet


def to_daily(bars: list[Bar]) -> list[Bar]:
    """Aggregate to daily bars on New York calendar days.

    The bias rules are daily-chart rules, and the sessions they gate are New
    York sessions, so the day boundary must be New York's rather than UTC's.
    """
    out: list[Bar] = []
    cur: list[Bar] = []
    day = None
    for b in bars:
        d = b.ny.date()
        if day is None:
            day = d
        if d != day:
            out.append(Bar(cur[0].ts, cur[0].open, max(x.high for x in cur),
                           min(x.low for x in cur), cur[-1].close,
                           sum(x.volume for x in cur)))
            cur, day = [], d
        cur.append(b)
    if cur:
        out.append(Bar(cur[0].ts, cur[0].open, max(x.high for x in cur),
                       min(x.low for x in cur), cur[-1].close,
                       sum(x.volume for x in cur)))
    return out


def build_daily_bias_lookup(bars: list[Bar], **kw) -> dict:
    """date -> bias for that day, computed from the PREVIOUS day's close.

    Using the same day's completed bar would be lookahead: the bias must be
    knowable before the session it gates.
    """
    daily = to_daily(bars)
    lookup: dict = {}
    for i in range(len(daily) - 1):
        res = daily_bias(daily, i, **kw)
        lookup[daily[i + 1].ny.date()] = res
    return lookup


def load_csv(path: str) -> list[Bar]:
    bars: list[Bar] = []
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            raw = row.get("timestamp") or row.get("time") or row.get("date")
            ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                raise SystemExit(
                    f"{path}: timestamp {raw!r} has no timezone. Session rules are the "
                    "most testable part of this system and a guessed timezone would "
                    "silently invalidate all of them. Export with an offset or a Z."
                )
            bars.append(Bar(ts.astimezone(UTC), float(row["open"]), float(row["high"]),
                            float(row["low"]), float(row["close"]),
                            float(row.get("volume") or 0)))
    bars.sort(key=lambda b: b.ts)
    return bars


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Backtest the automatable setups")
    ap.add_argument("csv")
    ap.add_argument("--instrument", required=True,
                    choices=["NAS100", "EURUSD", "GBPUSD", "XAUUSD"])
    ap.add_argument("--setup", default="silver_bullet",
                    choices=["silver_bullet", "ote"])
    ap.add_argument("--bias", choices=["long", "short", "auto"],
                    help="required for silver_bullet. 'auto' uses the HTF-001 "
                         "heuristic in bot/bias.py, which is UNSOURCED - see its "
                         "module docstring before trusting it (GAPS G-07)")
    ap.add_argument("--displacement-multiple", type=float, default=1.5)
    ap.add_argument("--min-rr", type=float, default=1.0)
    ap.add_argument("--journal", help="write trades to this CSV (journal format)")
    ap.add_argument("--account", type=float, help="account size, to size positions")
    ap.add_argument("--value-per-point", type=float, default=1.0)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    rejections: list[str] = []
    bars = load_csv(args.csv)
    if len(bars) < 50:
        raise SystemExit(f"only {len(bars)} bars; need a meaningful sample")

    if args.setup == "silver_bullet":
        if not args.bias:
            raise SystemExit(
                "--bias is required for silver_bullet.\n"
                "Higher timeframe bias is not mechanically derivable from this corpus "
                "(GAPS G-07), so the engine refuses to guess it rather than inventing "
                "a rule and attributing it to the source."
            )
        if args.bias == "auto":
            lookup = build_daily_bias_lookup(bars)
            decided = sum(1 for r in lookup.values() if r.direction)
            print(f"\nAutomated bias (UNSOURCED heuristic, see bot/bias.py):")
            print(f"  {decided} of {len(lookup)} days got a bias; "
                  f"{len(lookup) - decided} were left flat")

            def strategy(bs, i):
                res = lookup.get(bs[i].ny.date())
                if res is None or res.direction is None:
                    return None      # HTF-003: no bias is a valid outcome
                return silver_bullet(bs, i, args.instrument, res.direction,
                                     displacement_multiple=args.displacement_multiple,
                                     min_rr=args.min_rr, rejections=rejections)
        else:
            def strategy(bs, i):
                return silver_bullet(bs, i, args.instrument, args.bias,
                                     displacement_multiple=args.displacement_multiple,
                                     min_rr=args.min_rr, rejections=rejections)
    else:
        def strategy(bs, i):
            return ote(bs, i, args.instrument, min_rr=args.min_rr,
                       rejections=rejections)

    res = run(bars, strategy)
    stats, by_rule = res.stats(), res.by_rule()

    if args.json:
        print(json.dumps({"stats": stats, "by_rule": by_rule}, indent=2, default=str))
        return 0

    print(f"\n{args.setup} on {args.instrument} -- {len(bars):,} bars "
          f"({bars[0].ts.date()} to {bars[-1].ts.date()})\n")
    for k, v in stats.items():
        print(f"  {k:<24} {v}")
    if by_rule:
        print("\n  per rule:")
        for rid, s in by_rule.items():
            flag = "" if s["enough_data"] else "   (under 20 trades - not conclusive)"
            print(f"    {rid:<10} {s['trades']:>4} trades  avg {s['avg_r']:+.2f}R  "
                  f"win {s['win_rate']:.0%}{flag}")
    # The backtest plan is explicit: a filter that never fires is not a filter.
    print(f"\n  MM-006 rejections (high resistance): {len(rejections)}")
    for r in rejections[:3]:
        print(f"    {r}")
    if not rejections:
        print("    none fired - either every setup was clean, or the filter is "
              "not reaching the cases it should")

    if args.journal:
        n = journal.write(args.journal, res.trades, args.instrument,
                          account=args.account,
                          value_per_point=args.value_per_point)
        print(f"\n  wrote {n} trades to {args.journal}")

    if stats.get("trades", 0) < 20:
        print("\n  NOTE: fewer than 20 closed trades. Per GAPS.md and the review loop, "
              "no rule should be judged on this.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
