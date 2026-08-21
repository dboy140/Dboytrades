# Price data

Not committed — large, often licensed, and yours to supply.

## Format

```csv
timestamp,open,high,low,close,volume
2026-06-15T14:00:00Z,20014.5,20021.0,20012.75,20019.25,0
```

**Timestamps must carry a timezone** (offset or `Z`). The loader rejects naive
timestamps rather than assuming UTC: session windows are the most testable part
of this system, and a guessed timezone would silently invalidate every one of
them.

1-minute bars. Sorted or unsorted — the loader sorts.

## Where to get it

| Source | Cost | Notes |
| --- | --- | --- |
| **Your MT4/MT5 broker** | free | Best match to what you would actually have traded. Tools -> History Center, or `File -> Open Data Folder` for the raw `.hst`. **Exports in broker server time — see below.** |
| **Dukascopy — via `notebooks/get_data_colab.ipynb`** | free | **Start here.** Their web export form downloads one day at a time, which makes two years 730 manual downloads; the notebook pulls the whole range from the same feed underneath it. Runs in Colab, so no local install — which matters on a Chromebook, where JForex and MetaTrader will not run at all. Already UTC, already timezone-stamped. |
| Dukascopy — JForex desktop | free | Same data with a range picker, but Windows/macOS/Linux only. |
| **TradingView** | paid tiers | Chart -> Export chart data. The free plan caps how many bars you get, which usually is not enough at 1m. |
| **FirstRate Data / Databento** | paid | Actual NQ futures rather than the CFD. |

### NQ futures vs the NAS100 CFD

ICT teaches the Silver Bullet windows on **index futures**, not CFDs. NQ and
NAS100 track each other closely, but NQ is the instrument the rules were stated
for and it has a real exchange calendar and volume. If you are choosing and cost
is not the deciding factor, NQ is the more faithful test; NAS100 is the more
faithful test of what *you* will actually trade. Both are defensible — just
record which you used.

## ⚠️ Validate before you trust it

```bash
python -m bot.inspect_data data/bars/NAS100_1m.csv
```

**MT4/MT5 exports are stamped in broker server time, typically UTC+2 or UTC+3 —
not UTC.** Label those as UTC and every session window in this system is wrong
by two or three hours, and the backtest will run anyway and report
confident-looking numbers.

`inspect_data` does not trust the label. Index instruments have a large,
reliable volatility spike at the 09:30 New York equities open; it finds that
spike and derives the real offset. If it reports a drift:

```bash
python -m bot.inspect_data data/bars/NAS100_1m.csv --restamp -3
```

That writes `NAS100_1m.fixed.csv` and leaves the original alone. Re-run inspect
on the fixed file to confirm the drift is 0.

It also reports duplicate timestamps, weekday gaps, and how many bars fall
inside each session window — a file with zero bars in the Silver Bullet window
cannot test `SB-001` however many rows it has.

The timezone check **refuses on short files**. It works by locating the daily
volatility cycle, so it needs at least 20 distinct hours across 2+ days before
it will make any claim. On less it reports INCONCLUSIVE rather than guessing.

## How much data is enough

| Purpose | Minimum | Why |
| --- | --- | --- |
| Timezone validation | 2+ days | needs a full daily cycle |
| Smoke test the pipeline | ~2 weeks | a handful of signals |
| **Judge a rule** | **2 years** | 20+ trades per rule (see `backtest-plan.md`) |

The windows are one hour a day at most. A month of data yields only about 20
in-window hours per session, and a Silver Bullet setup does not appear every
day. Small samples do not produce a cautious answer here — they produce a
confident wrong one.

Match the instrument to the rules: NAS100 for Silver Bullet windows, EURUSD and
GBPUSD for the NBB windows. XAUUSD is covered by neither source (GAPS G-04) — if
you test it, treat every result as exploratory.

## Running

```bash
python -m bot.run_backtest data/bars/NAS100_1m.csv \
    --instrument NAS100 --setup silver_bullet --bias long

python -m bot.run_backtest data/bars/EURUSD_1m.csv \
    --instrument EURUSD --setup ote
```

`--bias` is required for Silver Bullet and deliberately not inferred: higher
timeframe bias is not mechanically derivable from this corpus (GAPS G-07), so
the engine refuses to guess rather than inventing a rule and attributing it to
the source. Run each bias separately, or supply bias per-day from your own
analysis.
