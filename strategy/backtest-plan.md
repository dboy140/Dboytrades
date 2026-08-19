# Backtest Plan

Nothing in this system has been tested against price. This plan is how it earns
the right to be traded.

---

## Sample and period

| | |
| --- | --- |
| **Instruments** | NAS100, EURUSD, GBPUSD, XAUUSD |
| **Period** | 2 years, most recent complete |
| **Minimum sample** | **20 trades per rule**, not per system |
| **Expected total** | 250–400 trades across four instruments |

Twenty per rule is the threshold the review loop uses for demotion, so anything
less cannot answer the question the journal is built to ask.

**Test each instrument separately.** The corpus states Silver Bullet windows for
index futures and NBB's windows for FX. Pooling instruments would hide exactly
the distinction `CONFLICTS.md` C-02 leaves open — and XAUUSD is covered by
neither source, so it is genuinely untested territory.

## Data

| | |
| --- | --- |
| Timeframes | 1m execution, 5m/15m structure, 1h/4h/daily bias |
| Timezone | Store UTC, **display New York** |
| Source | Any provider with clean 1m futures and FX history |

⚠️ **Use a real timezone database (`America/New_York`), never a fixed offset.**
US and UK DST dates differ by about four weeks a year, and a fixed offset
silently shifts every window by an hour during those weeks — which would corrupt
the single most testable claim in the system.

## Method

1. **Forward-walk only.** Bar by bar. No looking right. Discretionary systems
   backtest beautifully and trade badly, almost entirely because of hindsight in
   bias-setting.
2. **Score the checklist before the outcome is visible.**
3. **Log `rule_ids` on every trade.** Without it you can measure the system but
   not fix it.
4. **Record no-trade days and why.** If the no-trade filters never fire, they are
   not filters.
5. **Take the stated target.** Do not improvise exits — you are testing the rules,
   not your judgement.

## Metrics

### Per system
Win rate · Average R · **Expectancy** (`(win% × avgWin) − (loss% × avgLoss)`) ·
Max consecutive losses · Max drawdown (%R and currency) · Profit factor ·
Trades per week

### Per rule — this is the point
| Metric | Why |
| --- | --- |
| Win rate and average R | Demote below breakeven at 20+ trades |
| Frequency | A rule firing twice a year cannot be validated |
| Contribution | Expectancy with the rule vs without |

### Per setup
Broken out for `Silver Bullet`, `MMBM`, `MMSM`, `LDN to New York OTE`, so tiers
are set by data rather than by my reading of the corpus.

### Diagnostics
- **MAE on winners** — if consistently small, stops are too wide
- **MFE on losers** — if consistently large, exits are too late
- **Score vs outcome** — if 9–10 doesn't beat 7–8, the checklist is mis-weighted
- **Window discipline** — in-window vs out-of-window performance directly tests
  `SB-001`, `LDN-001`, `NY-002`

## Questions this must answer

1. Does the 02:00 vs 01:00 London start matter? (`CONFLICTS.md` C-01) — if
   setups cluster in 01:00–02:00, the conservative read is wrong.
2. Do NBB's FX windows outperform ICT's on EURUSD/GBPUSD? (C-02)
3. What stop distance replaces the 5-pip OTE rule on NAS100 and XAUUSD?
4. Does the low-resistance filter (`MM-006`) actually separate winners from losers?
   It is the system's strongest claim and the easiest to falsify.
5. Are the **[UNSOURCED]** risk numbers survivable at the observed max
   consecutive losses?

## Pass criteria

Before live money, per instrument:

- [ ] Expectancy > 0 over 20+ trades per rule
- [ ] Max drawdown within tolerance at the chosen risk %
- [ ] Max consecutive losses survivable at 1% (e.g. 8 losers ≈ −8%)
- [ ] Tier A outperforms Tier B — if not, the tiering is wrong
- [ ] The no-trade filters demonstrably avoided losing trades

**Any rule failing at 20+ trades is demoted to Tier C and its citation
re-watched before it is deleted.** The video may say something the extraction
missed.
