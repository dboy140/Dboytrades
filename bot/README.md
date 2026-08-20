# Execution layer

Turns the cited rules into computable facts. Every function names the rule it
implements, so a signal traces back to `extraction/rules.json` and from there to
a video and timestamp.

## What is automatable — and what is not

Assessed against the 63 extracted rules:

| Setup | Automatable | Blocker |
| --- | --- | --- |
| **Silver Bullet** | **6/6** | none |
| **LDN to New York OTE** | **4/4** | none |
| MMBM | 0/4 | "original consolidation" and "smart money reversal" are never defined numerically |
| MMSM | 0/2 | "second stage of distribution" likewise |

**41 of 63 rules are mechanically computable. 22 need judgement.**

This is a finding about the corpus, not a limitation of the code. ICT
demonstrates the market maker models on charts rather than defining their
components, so there is no threshold to implement. Writing one would mean
inventing a rule and attributing it to him — which is the thing this whole
project exists to avoid.

**Consequence:** a bot can trade Silver Bullet and OTE unaided. MMBM/MMSM stay
manual until *you* define the missing terms from your own backtest, at which
point they become your parameters, honestly labelled as such.

## Modules

| Module | Implements |
| --- | --- |
| `bars.py` | `Bar`, fractal swings, `confirmed_swings` (no-lookahead) |
| `patterns.py` | FVG, inversion, displacement, MSS, OTE levels, premium/discount |
| `sessions.py` | All session windows, DST-aware via IANA |

## Two guarantees worth knowing

**No lookahead.** `confirmed_swings(bars, upto)` returns only swings knowable at
that bar. A fractal swing at index *i* is not confirmed until *i + lookback*.
Using `swing_points` over a whole series in a backtest would let the strategy
see structure that had not formed — the most common way a discretionary
backtest flatters itself.

**FVGs are indexed by their third bar**, the first moment the gap exists.
Indexing by the first bar would let a backtest act two bars early.

## Unsourced parameters

These are exposed, not buried, because the corpus does not quantify them:

| Parameter | Default | Note |
| --- | --- | --- |
| `is_displacement(multiple=)` | 1.5× average body | ICT shows displacement on charts, never defines it |
| `swing_points(lookback=)` | 2 | no fractal width is stated anywhere |
| `find_fvgs(min_size=)` | 0.0 | no minimum gap size is stated |

Tune per instrument in the backtest and record what you chose.

## Automated bias — read this before using it

`bot/bias.py` implements a daily bias from `HTF-001`, wired in as `--bias auto`.

**It is not ICT's method.** `HTF-001` says the side holding the *larger* pool is
the draw. It never says what makes a pool larger, and nothing in the corpus
does — that is `GAPS` G-07. The scoring is mine:

```
score(pool) = clustered_swings / (1 + distance_in_average_ranges)
bias        = the side that outscores the other by >= 1.30x
```

Two parts of that do follow from cited material: equal highs and equal lows are
treated throughout the corpus as liquidity markers, so a cluster is scored as a
deeper pool; and ICT criticises liquidity tools for surfacing levels "not so
pertinent to right now", which supports weighting by proximity. **The numbers
themselves — 1.30x, the 0.15% cluster tolerance, the fractal width — are
arbitrary and exposed as parameters so they stay visible.**

Every `BiasResult` carries `unsourced=True` so it cannot be mistaken for a
cited rule.

**It refuses often, and that is deliberate.** `HTF-003` argues against forcing a
daily bias at all, so the heuristic returns `None` when neither side clears the
margin or there is too little structure. On a 25-day synthetic sample it gave a
bias on 5 days and stayed flat on 20. If that feels too quiet, lower `margin` —
but lower it in a backtest, not in live trading.

Bias is computed from the **previous** day's completed bar. Using the same day's
would be lookahead: the bias has to be knowable before the session it gates.

## No-trade filters

`bot/filters.py` enforces the rules that say when NOT to trade. Without them
the backtest measures a looser system than the corpus describes.

| Filter | Rule | Behaviour |
| --- | --- | --- |
| `low_resistance` | MM-006 | blocks: opposing level between entry and target |
| `within_htf_range` | MM-007 | internal range liquidity is low resistance |
| `asian_range_ok` | LDN-005 | blocks London if the Asian range exceeded ~30 pips |
| `agrees_with_order_flow` | SMC-005 | blocks trades against HTF order flow |
| `weekday_preferred` | SMC-005 | advisory only: Mon-Wed preferred |

### Resistance is judged on 15m, not the execution timeframe

Evaluated on 1m bars, MM-006 **rejected 100% of signals**, reporting things like
"27 opposing levels between entry and target". Those were three-bar wiggles, not
liquidity pools.

MM-007 says exactly this: a move inside the higher timeframe range is low
resistance "even where a lower timeframe shows apparent resistance". So the
check resamples to 15m first. The target is drawn from the same timeframe —
otherwise target and filter answer different questions and the filter looks
stricter than it is.

### It will reject a lot, and that is not a bug to tune away

On random-walk data it still rejects ~24 of 25 signals. That is the correct
response to structureless data: a random walk has no clean runs to a target.
**Do not loosen the filter until random data produces trades** — that would
destroy the system's strongest claim in order to make noise look tradeable.
Judge it on real data with real structure.

## Position sizing

`bot/risk.py`. **Entirely unsourced** (GAPS G-01) — the corpus contains no
sizing, no risk per trade, no daily limits. The arithmetic reproduces the worked
examples in `00-SYSTEM.md` section 8 exactly, and there are tests pinning that,
but the numbers are convention, not distillation. Sizes always round DOWN;
rounding up breaches the stated limit on every trade.

## Journal export

`--journal out.csv` writes trades in the exact column order of
`strategy/backtest-template.csv`, so backtest output and hand-logged live trades
share one sheet. `checklist_score` is left blank deliberately: it is scored
before entry by a human and cannot be reconstructed afterwards.
