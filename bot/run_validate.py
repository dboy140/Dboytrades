"""Walk-forward validation CLI. Produces the report live mode requires.

    python -m bot.run_validate data/bars/EURUSD_1m.csv --instrument EURUSD
"""

from __future__ import annotations

import argparse
import json
from itertools import product
from pathlib import Path

from .run_backtest import load_csv
from .signals import ote, silver_bullet
from .validate import (
    MIN_OOS_TRADES, bootstrap_expectancy, monte_carlo_drawdown,
    parameter_surface, surface_is_a_spike, walk_forward,
)
from .backtest import run
from .bars import SwingIndexCache


def build_grid(setup: str) -> list[dict]:
    """Deliberately coarse. A fine grid finds a better peak and means less."""
    if setup == "silver_bullet":
        return [{"displacement_multiple": d, "min_rr": r}
                for d, r in product((1.2, 1.5, 2.0), (1.0, 1.5, 2.0))]
    return [{"min_rr": r} for r in (1.0, 1.5, 2.0, 2.5)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Walk-forward validation")
    ap.add_argument("csv")
    ap.add_argument("--instrument", required=True,
                    choices=["NAS100", "EURUSD", "GBPUSD", "XAUUSD"])
    ap.add_argument("--setup", default="ote", choices=["silver_bullet", "ote"])
    ap.add_argument("--bias", default="long", choices=["long", "short"])
    ap.add_argument("--train-days", type=int, default=60)
    ap.add_argument("--test-days", type=int, default=20)
    ap.add_argument("--out", default="logs/validation.json")
    args = ap.parse_args(argv)

    bars = load_csv(args.csv)
    inst, setup = args.instrument, args.setup

    # Shared across the whole grid on purpose. walk_forward iterates folds
    # outermost, so each fold's series is indexed once and then reused by every
    # parameter combination tried on it.
    swings = SwingIndexCache()

    if setup == "silver_bullet":
        def factory(displacement_multiple=1.5, min_rr=1.0):
            return lambda bs, i: silver_bullet(
                bs, i, inst, args.bias,
                displacement_multiple=displacement_multiple, min_rr=min_rr,
                index=swings.get(bs))
    else:
        def factory(min_rr=1.0):
            return lambda bs, i: ote(bs, i, inst, min_rr=min_rr,
                                     index=swings.get(bs))

    grid = build_grid(setup)
    line = "=" * 70

    print(f"\n{line}\nWALK-FORWARD VALIDATION\n{line}")
    print(f"{setup} on {inst} -- {len(bars):,} bars")
    print(f"train {args.train_days}d / test {args.test_days}d, "
          f"{len(grid)} parameter combinations\n")

    report = walk_forward(bars, factory, grid,
                          train_days=args.train_days, test_days=args.test_days)

    if not report.folds:
        print("Not enough data to form a single fold.")
        print(f"Need at least {args.train_days + args.test_days} trading days.")
        return 1

    print(f"{'fold':<5} {'test period':<26} {'IS exp':>8} {'OOS exp':>9} {'trades':>7} {'kept':>7}")
    for f in report.folds:
        kept = f"{f.degradation:.0%}" if f.degradation is not None else "-"
        print(f"{f.index:<5} {f.test_from} to {f.test_to:<10} "
              f"{f.in_sample_expectancy:>8.3f} {f.out_of_sample_expectancy:>9.3f} "
              f"{f.out_of_sample_trades:>7} {kept:>7}")

    print(f"\nCombined out-of-sample expectancy: {report.combined_oos_expectancy:+.4f}R")
    print(f"Out-of-sample trades:              {report.total_oos_trades}")
    print(f"\nVERDICT: {report.verdict}")

    # The confidence interval belongs on the pooled OUT-OF-SAMPLE trades --
    # the sample the verdict is about. An earlier version ran it on a
    # whole-sample backtest at grid[len(grid)//2], an arbitrary setting which
    # on one run generated zero trades, so the single most important check
    # printed "too few trades" and the verdict sailed past unchallenged.
    ci = report.oos_confidence

    print(f"\n{line}\nIS THE OUT-OF-SAMPLE RESULT DISTINGUISHABLE FROM LUCK?\n{line}")
    for k, v in ci.items():
        print(f"  {k:<32} {v}")
    print(f"  {'profitable windows':<32} "
          f"{report.folds_positive}/{report.folds_scored}")

    # Drawdown is a question about the trades you would have taken, so it is
    # asked of the setting walk-forward actually chose most often.
    chosen = _most_chosen(report) or grid[0]
    res = run(bars, factory(**chosen))
    boot = bootstrap_expectancy(res.closed)
    mc = monte_carlo_drawdown(res.closed)
    print(f"\n  whole-sample check at the most-chosen setting {chosen}:")
    for k, v in boot.items():
        print(f"  {k:<32} {v}")

    print(f"\n{line}\nWHAT DRAWDOWN SHOULD BE EXPECTED?\n{line}")
    print("  (reshuffling the same trades -- history dealt one order of many)")
    for k, v in mc.items():
        print(f"  {k:<32} {v}")

    surface = parameter_surface(bars, factory, grid)
    spike = surface_is_a_spike(surface)
    print(f"\n{line}\nPARAMETER SENSITIVITY\n{line}")
    for row in surface:
        print(f"  {row}")
    print(f"\n  curve-fitting suspected: {spike}")
    if spike:
        print("  Only a small minority of settings are profitable. That usually")
        print("  means the winning setting was chosen to fit this history.")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "setup": setup, "instrument": inst,
        "combined_oos_expectancy": report.combined_oos_expectancy,
        "total_oos_trades": report.total_oos_trades,
        "verdict": report.verdict,
        # The live gate reads these three. Without them it cannot tell a real
        # edge from a lucky sample, so an older report missing them is
        # refused rather than waved through.
        "oos_confidence": ci,
        "folds_positive": report.folds_positive,
        "folds_scored": report.folds_scored,
        "folds": [f.__dict__ for f in report.folds],
        "bootstrap": boot, "monte_carlo": mc,
        "parameter_surface": surface, "curve_fitting_suspected": spike,
    }, indent=2, default=str))
    print(f"\nwrote {out}")
    print(f"Live mode reads this file. It refuses unless out-of-sample "
          f"expectancy is positive over {MIN_OOS_TRADES}+ trades, the 95% "
          "interval excludes zero, and most windows are profitable.")
    return 0


def _most_chosen(report) -> dict | None:
    """The parameter set walk-forward picked in the most folds."""
    counts: dict[str, tuple[int, dict]] = {}
    for f in report.folds:
        k = json.dumps(f.best_params, sort_keys=True)
        n, params = counts.get(k, (0, f.best_params))
        counts[k] = (n + 1, params)
    if not counts:
        return None
    return max(counts.values(), key=lambda t: t[0])[1]


if __name__ == "__main__":
    raise SystemExit(main())
