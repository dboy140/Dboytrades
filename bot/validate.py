"""Guards against the failure this project is most exposed to: a backtest that
looks excellent and loses money live.

A high backtest win rate is trivially easy to manufacture. Nudge the
displacement multiple, the swing lookback and the minimum R until the equity
curve looks good, and a number like 85% appears. That number is not evidence --
it is a description of how hard the parameters were pushed against one
particular slice of history. A system tuned that way is MORE dangerous than an
untuned one, because it inspires confidence it has not earned.

The four tools here exist to make that failure visible:

  walk_forward        -- optimise on old data, measure on data never seen
  parameter_surface   -- a sharp peak means curve-fitting; a plateau means edge
  bootstrap_expectancy-- is expectancy distinguishable from zero, or is it luck?
  monte_carlo_drawdown-- what drawdown should be expected from this trade
                         distribution, regardless of the order history gave

None of them will make a strategy profitable. They tell you whether to believe
a result, which is the only thing standing between a backtest and losing money.
"""

from __future__ import annotations

import random
import statistics
from dataclasses import dataclass, field
from typing import Callable, Iterable

from .backtest import Result, Trade, run
from .bars import Bar

Strategy = Callable[[list[Bar], int], object]
StrategyFactory = Callable[..., Strategy]


# 20 was the old floor and it was too low: with four folds it means five
# trades a window, which is noise. This is still a floor rather than a
# sufficiency test -- the confidence interval does the real work.
MIN_OOS_TRADES = 30


@dataclass
class Fold:
    index: int
    train_from: str
    train_to: str
    test_from: str
    test_to: str
    best_params: dict
    in_sample_expectancy: float
    out_of_sample_expectancy: float
    out_of_sample_trades: int
    # The R-multiples themselves, not just their mean. Pooling these is what
    # lets the verdict put a confidence interval on the out-of-sample result
    # rather than trusting a single average.
    out_of_sample_r: list[float] = field(default_factory=list)

    @property
    def degradation(self) -> float | None:
        """How much of the in-sample edge survived. Below ~0.5 is a warning."""
        if self.in_sample_expectancy <= 0:
            return None
        return self.out_of_sample_expectancy / self.in_sample_expectancy


@dataclass
class WalkForwardReport:
    folds: list[Fold] = field(default_factory=list)

    @property
    def combined_oos_expectancy(self) -> float:
        """Weighted by trades, not a flat mean over folds.

        A flat mean lets a fold with two trades count as much as one with
        eleven, and on a random walk that is enough to turn a losing system
        into a passing one. Observed: four folds of 5/2/11/9 trades averaged
        +0.26R unweighted on pure noise.
        """
        den = self.total_oos_trades
        if not den:
            return 0.0
        num = sum(f.out_of_sample_expectancy * f.out_of_sample_trades
                  for f in self.folds)
        return round(num / den, 4)

    @property
    def oos_r_multiples(self) -> list[float]:
        """Every out-of-sample trade from every fold, pooled."""
        return [r for f in self.folds for r in f.out_of_sample_r]

    @property
    def folds_positive(self) -> int:
        return sum(1 for f in self.folds
                   if f.out_of_sample_trades and f.out_of_sample_expectancy > 0)

    @property
    def folds_scored(self) -> int:
        return sum(1 for f in self.folds if f.out_of_sample_trades)

    @property
    def oos_confidence(self) -> dict:
        """Bootstrap interval on the pooled out-of-sample trades.

        This is the check that separates an edge from a lucky run, and it is
        applied to the walk-forward result itself rather than to a whole-sample
        backtest at some arbitrary parameter setting.
        """
        return bootstrap_r(self.oos_r_multiples)

    @property
    def total_oos_trades(self) -> int:
        return sum(f.out_of_sample_trades for f in self.folds)

    @property
    def verdict(self) -> str:
        """Deliberately hard to pass.

        An earlier version asked only for 20 pooled out-of-sample trades and a
        positive flat mean across folds. A pure random walk cleared it: four
        folds of 5/2/11/9 trades, +0.26R, "SURVIVED". Since `bot/live.py` gates
        real orders on this, noise was enough to authorise live trading -- the
        worst failure this file can have, because it fails towards risking
        money rather than away from it.

        Three things now have to hold at once, and each closes a different way
        of passing by luck:

        1. Enough out-of-sample trades to say anything at all.
        2. A trade-weighted expectancy above zero, so a tiny fold cannot carry
           the result.
        3. A bootstrap interval on the pooled out-of-sample trades that
           excludes zero, and agreement across the majority of folds.

        (3) is the one that matters. A positive average over a small sample is
        exactly what a system with no edge produces some of the time.
        """
        if self.total_oos_trades < MIN_OOS_TRADES:
            return (f"INSUFFICIENT DATA -- {self.total_oos_trades} out-of-sample "
                    f"trades, fewer than {MIN_OOS_TRADES}. No conclusion is "
                    "available. This is not a failure, it is a shortage of data.")
        if self.combined_oos_expectancy <= 0:
            return ("FAILED -- the edge did not survive out of sample. This is "
                    "the expected result for a curve-fitted system.")

        ci = self.oos_confidence
        if not ci.get("positive_with_95pct_confidence"):
            return ("NOT DISTINGUISHABLE FROM LUCK -- out-of-sample expectancy "
                    f"is {self.combined_oos_expectancy:+.3f}R, but the 95% "
                    f"interval is [{ci.get('ci95_low')}, {ci.get('ci95_high')}] "
                    "and includes zero. A system with no edge produces results "
                    "like this routinely.")

        if self.folds_scored and self.folds_positive * 2 <= self.folds_scored:
            return (f"INCONSISTENT -- profitable in only {self.folds_positive} of "
                    f"{self.folds_scored} out-of-sample windows. An edge that "
                    "appears in a minority of periods is more likely a property "
                    "of those periods than of the rules.")

        degradations = [f.degradation for f in self.folds if f.degradation is not None]
        if degradations and statistics.mean(degradations) < 0.5:
            return ("WEAK -- positive out of sample, but most of the in-sample "
                    "edge was lost. Treat the in-sample figures as fiction.")
        return "SURVIVED out of sample. Necessary, not sufficient."


def _by_day(bars: list[Bar]) -> list[list[Bar]]:
    days: dict = {}
    for b in bars:
        days.setdefault(b.ny.date(), []).append(b)
    return [days[k] for k in sorted(days)]


def walk_forward(bars: list[Bar], factory: StrategyFactory,
                 param_grid: list[dict], *, train_days: int = 60,
                 test_days: int = 20) -> WalkForwardReport:
    """Optimise on a training window, measure on the window that follows.

    This is the only backtest number worth anything. Every parameter choice is
    made using data that precedes the data it is scored on, so the score cannot
    be contaminated by hindsight.
    """
    days = _by_day(bars)
    report = WalkForwardReport()
    if len(days) < train_days + test_days:
        return report

    fold_i = 0
    start = 0
    while start + train_days + test_days <= len(days):
        train = [b for d in days[start:start + train_days] for b in d]
        test = [b for d in days[start + train_days:start + train_days + test_days] for b in d]

        best, best_e = None, float("-inf")
        for params in param_grid:
            res = run(train, factory(**params))
            e = res.stats().get("expectancy_r", 0.0) or 0.0
            if res.stats().get("trades", 0) >= 3 and e > best_e:
                best, best_e = params, e

        if best is not None:
            oos = run(test, factory(**best))
            s = oos.stats()
            report.folds.append(Fold(
                fold_i, str(train[0].ny.date()), str(train[-1].ny.date()),
                str(test[0].ny.date()), str(test[-1].ny.date()),
                best, round(best_e, 4),
                round(s.get("expectancy_r", 0.0) or 0.0, 4), s.get("trades", 0),
                [t.r_multiple for t in oos.closed]))
        fold_i += 1
        start += test_days

    return report


def parameter_surface(bars: list[Bar], factory: StrategyFactory,
                      param_grid: list[dict]) -> list[dict]:
    """Score every parameter combination on the same data.

    Read the SHAPE, not the maximum. A single tall spike surrounded by losses
    is curve-fitting: it means the result depends on an exact setting that
    nothing justifies. A broad plateau suggests the effect is real and the
    exact value does not matter much.
    """
    out = []
    for params in param_grid:
        s = run(bars, factory(**params)).stats()
        out.append({**params,
                    "trades": s.get("trades", 0),
                    "expectancy_r": s.get("expectancy_r"),
                    "win_rate": s.get("win_rate")})
    return out


def surface_is_a_spike(surface: list[dict], top_fraction: float = 0.25) -> bool:
    """True when only a small minority of settings are profitable.

    A real effect tends to survive small parameter changes. If it only works at
    one setting, the setting was chosen to fit the past.
    """
    scored = [r for r in surface if r.get("expectancy_r") is not None and r["trades"] >= 3]
    if len(scored) < 4:
        return False
    profitable = sum(1 for r in scored if r["expectancy_r"] > 0)
    return (profitable / len(scored)) < top_fraction


def bootstrap_expectancy(trades: Iterable[Trade], n: int = 5000,
                         seed: int = 7) -> dict:
    """Confidence interval on expectancy by resampling closed trades."""
    return bootstrap_r([t.r_multiple for t in trades if not t.is_open], n, seed)


def bootstrap_r(rs: list[float], n: int = 5000, seed: int = 7) -> dict:
    """Confidence interval on expectancy by resampling R-multiples.

    Answers the question a single expectancy figure cannot: could this result
    have come from a system with no edge at all?

    Takes raw R-multiples so it can be applied to the pooled out-of-sample
    trades of a walk-forward run, which is the sample the verdict should
    actually be judging.
    """
    rs = list(rs)
    if len(rs) < 5:
        return {"trades": len(rs), "note": "too few trades to bootstrap"}
    rng = random.Random(seed)
    means = []
    for _ in range(n):
        sample = [rs[rng.randrange(len(rs))] for _ in range(len(rs))]
        means.append(statistics.mean(sample))
    means.sort()
    lo = means[int(0.025 * n)]
    hi = means[int(0.975 * n)]
    return {
        "trades": len(rs),
        "expectancy_r": round(statistics.mean(rs), 4),
        "ci95_low": round(lo, 4),
        "ci95_high": round(hi, 4),
        "positive_with_95pct_confidence": lo > 0,
        "note": ("The interval includes zero, so this result is not "
                 "distinguishable from no edge." if lo <= 0 else
                 "Expectancy is positive at 95% confidence on this sample."),
    }


def monte_carlo_drawdown(trades: Iterable[Trade], n: int = 5000,
                         seed: int = 11) -> dict:
    """Drawdown distribution from reshuffling the order of the same trades.

    History dealt one particular sequence. A different ordering of the same
    trades can produce a far deeper drawdown, and position sizing has to
    survive that, not just the sequence that happened.
    """
    rs = [t.r_multiple for t in trades if not t.is_open]
    if len(rs) < 5:
        return {"trades": len(rs), "note": "too few trades"}
    rng = random.Random(seed)
    worst = []
    streaks = []
    for _ in range(n):
        order = rs[:]
        rng.shuffle(order)
        equity = peak = dd = 0.0
        streak = longest = 0
        for r in order:
            equity += r
            peak = max(peak, equity)
            dd = min(dd, equity - peak)
            streak = streak + 1 if r <= 0 else 0
            longest = max(longest, streak)
        worst.append(dd)
        streaks.append(longest)
    worst.sort()
    streaks.sort()
    return {
        "trades": len(rs),
        "median_drawdown_r": round(worst[n // 2], 2),
        "worst_5pct_drawdown_r": round(worst[int(0.05 * n)], 2),
        "median_max_consecutive_losses": streaks[n // 2],
        "worst_5pct_consecutive_losses": streaks[int(0.95 * n)],
    }
