# DboyTrades — Distilled Trading System

Built from 139 transcripts (734,784 words) of ICT and NBBTRADER content.
**63 rules, 102 citations, every one verified against real audio at the
timestamp it cites.**

Rule IDs like `SB-001` resolve in `extraction/rules.json`, where each carries
its sources. Anything marked **[UNSOURCED]** is an engineering default, not
something either source said.

---

## 1. Operating premise

Price is delivered algorithmically toward pools of resting orders. Buy stops
accumulate above old highs, sell stops below old lows, and price seeks whichever
pool the higher timeframe is reaching for (`HTF-001`).

Moves away from that objective are engineered, not random. A session typically
opens with a false move — the Judas swing — that runs the near-side stops before
delivering toward the real draw (`LDN-004`, `SMC-006`). Institutions must find
counterparty: to sell high they need buyers willing to buy higher, so highs get
run before distribution begins (`MM-009`).

The market maker models describe this as a curve. In a buy model price is driven
lower specifically in order to go higher: accumulation, a decline that
distributes, a smart money reversal, then an advance back to the original
consolidation where the buy stops sit (`MM-001`, `MM-003`).

Every level worth trading is a place where inefficiency was left behind or
liquidity is resting. Everything else is noise.

*(198 words)*

---

## 2. Higher timeframe bias

**Read this section's limits first.** The corpus does not contain a fully
decidable daily-bias procedure. The strongest statement is an argument against
forcing one:

> *"I'm not trying to get a daily bias every single day. I'm trying to determine
> the likely weekly expansion."* — `HTF-003`

So the checklist below is the closest decidable procedure the corpus supports,
and step 1 legitimately outputs "no bias, don't trade".

| # | Step | Decidable? | Rule |
| --- | --- | --- | --- |
| 1 | Mark the weekly range. Is expansion likely, or is the week's extreme already in? | Yes | `HTF-003`, `HTF-006` |
| 2 | On the daily, mark unswept buy stops above old highs and sell stops below old lows. | Yes | `HTF-001` |
| 3 | Which pool is larger and unswept? That is the draw. | Mostly — "larger" is judgement | `HTF-001` |
| 4 | Is price in premium or discount of the daily dealing range? | Yes — 50% of range | `HTF-002`, `SMC-003` |
| 5 | Transpose weekly/monthly arrays onto the daily. Keep only unmitigated ones. | Yes | `HTF-004` |
| 6 | Bias = direction from current price toward the draw, if steps 3–5 agree. | Yes | `HTF-002` |
| 7 | Commit for the session. Do not flip mid-day. | Yes | `HTF-005` |

If steps 3–5 disagree, there is no bias and no trade. That is a valid outcome.

**Wednesday note:** once the week's high or low forms — often Wednesday — stop
referencing Sunday's open and work from the weekly profile (`HTF-006`).

---

## 3. Draw on liquidity

Establish *where price is going* before any entry.

1. **Old highs and lows** — unswept, on daily and 4h, are the primary draws (`HTF-001`).
2. **Equilibrium** — from premium or discount, price first seeks the 50% of the
   recent range. Equilibrium alone is a sufficient target (`SMC-003`).
3. **The original consolidation** — in a market maker model, price advances until
   it takes the buy stops above the original consolidation's relative equal high
   (`MM-004`).
4. **Session-specific** — the lunch macro reaches for the first prominent
   liquidity pool formed after 10:00 NY. Walk forward from 10:00 and mark the
   first obvious swing (`SMC-007`).

### The filter that matters most

Classify every candidate as a **low- or high-resistance liquidity run**. Only
take low resistance (`MM-006`):

> Low resistance = **no opposing liquidity pool sits between entry and objective.**
> High resistance = an opposing high or low sits in the way.

He is explicit that high-resistance runs are what *not* to trade. A move staying
inside the monthly/weekly range is internal range liquidity and therefore low
resistance even where a lower timeframe shows apparent resistance (`MM-007`).

---

## 4. Session framework — UK time

All source times are **New York local**. UK is normally **+5h**, but US and UK
daylight-saving dates differ, and for about four weeks a year it is **+4h**.

### ⚠️ The DST trap

| Period | New York | London | Offset |
| --- | --- | --- | --- |
| Early Nov → 2nd Sun Mar | EST (UTC−5) | GMT (UTC+0) | **+5** |
| 2nd Sun Mar → last Sun Mar | EDT (UTC−4) | GMT (UTC+0) | **+4** ⚠️ |
| Last Sun Mar → last Sun Oct | EDT (UTC−4) | BST (UTC+1) | **+5** |
| Last Sun Oct → 1st Sun Nov | EDT (UTC−4) | GMT (UTC+0) | **+4** ⚠️ |

**Roughly three weeks in March and one week in late October, every window below
happens an hour earlier in UK time.** Set your platform to New York time and
avoid the conversion entirely.

### Windows

| Window | NY | UK (+5) | UK (+4) ⚠️ | Rule |
| --- | --- | --- | --- | --- |
| London killzone | 02:00–05:00 | 07:00–10:00 | 06:00–09:00 | `LDN-001` |
| NBB London SB (FX) | 03:00–04:00 | 08:00–09:00 | 07:00–08:00 | `SB-010` |
| NY killzone (FX) | 07:00–09:00 | 12:00–14:00 | 11:00–13:00 | `NY-001` |
| NBB NY SB (FX) | 08:00–09:00 | 13:00–14:00 | 12:00–13:00 | `SB-010` |
| CME open | 08:20 | 13:20 | 12:20 | `NY-004` |
| NY AM session | 08:30–11:00 | 13:30–16:00 | 12:30–15:00 | `NY-002` |
| **AM Silver Bullet** | **10:00–11:00** | **15:00–16:00** | **14:00–15:00** | `SB-001` |
| London close | 10:00–12:00 | 15:00–17:00 | 14:00–16:00 | `LDN-003` |
| Lunch macro | 12:00–13:30 | 17:00–18:30 | 16:00–17:30 | `SMC-007` |
| PM session | 13:00–16:00 | 18:00–21:00 | 17:00–20:00 | `NY-005` |
| **PM Silver Bullet** | **14:00–15:00** | **19:00–20:00** | **18:00–19:00** | `SB-002` |
| True day high/low forms | 15:00–16:00 | 20:00–21:00 | 19:00–20:00 | `NY-005` |

**Conflict:** one source gives the London killzone as 01:00–05:00. Resolved to
02:00 — see `CONFLICTS.md` C-01.

### Reference prices

- **Midnight NY open** — the day's reference (`NY-003`).
- **08:30 NY open** — a *distinct* reference. For a long, require price to run
  above it. Explicitly warned not to confuse the two (`NY-003`).

### Daily profile

London runs stops and expands → 05:00–08:00 consolidates → 08:00–08:30 retraces
→ New York reverses or expands (`NY-007`).

---

## 5. PD array layer — FVG and IFVG

### Fair value gap

Three-candle inefficiency. Its midpoint is **consequent encroachment** — the
reference level inside it (`FVG-001`).

**Which part is traded:** not necessarily deep. An *institutional order flow
entry drill* is a shallow entry that does **not** reach the midpoint, followed
by aggressive movement away (`FVG-002`). Entries that look missed on the chart
often filled this way.

A gap usually offers several attempts as price cycles through it — a missed
first touch is not a missed trade (`FVG-005`).

**Rebalanced vs repriced:** a gap is only balanced once price trades back
through the *originating range low*. Trading back up into the area is repricing,
not rebalancing (`FVG-004`).

### Inversion fair value gap

A gap price trades decisively through **inverts**: a failed bullish gap becomes
resistance, a failed bearish gap becomes support (`IFVG-001`). Also called a
*reclaimed* fair value gap.

- **Stop** goes just beyond the inverted gap itself, not at a wider structural
  level (`IFVG-002`).
- It acts as **dynamic** support/resistance — you can add on successive respects
  rather than treating it as one touch (`IFVG-003`).
- Its **consequent encroachment** is the sensitive level. Watch *bodies*, not
  wicks (`IFVG-005`).

### Which to prefer

Use a **plain FVG** when price is delivering with the bias and leaving fresh
inefficiency. Use an **IFVG** when a gap has already failed — the failure itself
is the signal that order flow changed.

**Honest limit:** how to know in advance which gap will invert is answered only
as a framework — time, price, institutional market structure, premium/discount —
not a checklist (`IFVG-004`). See `GAPS.md`.

---

## 6. Setup tiers

### Tier A — full size

Requires **all four**: HTF bias + draw on liquidity + session window + PD array.

#### `Silver Bullet`
| | |
| --- | --- |
| **Preconditions** | HTF bias set; low-resistance run to target |
| **Window** | AM 10:00–11:00 or PM 14:00–15:00 NY (`SB-001`, `SB-002`) |
| **Trigger** | Displacement inside the window leaving a fair value gap |
| **Entry** | Into that gap (`SB-003`) |
| **Stop** | Beyond the displacement candle's extreme (`SB-003`) |
| **Target** | Nearest opposing liquidity — relative equal highs/lows (`SB-004`) |
| **Invalidation** | Window closes with no qualifying displacement; or price closes through the gap |
| **Expected R** | 2–3R **[UNSOURCED]** — not stated; derive from backtest |
| **Frequency** | Up to 2/day (AM + PM), realistically 3–5/week |

Strengthened by SMT divergence plus a structure shift (`SB-008`). On news days
the AM window widens to 10:00–12:00 (`SB-006`). The 13:30 lunch macro sets the
tone for the PM window — read it first (`SB-007`).

#### `MMBM` — Market Maker Buy Model
| | |
| --- | --- |
| **Preconditions** | Daily bias bullish; original consolidation identifiable |
| **Sequence** | Original consolidation → decline → return → distribution → redistribution → **smart money reversal** → low-risk buy → reaccumulation → advance (`MM-001`) |
| **Trigger** | Smart money reversal, which forms on *brief* consolidation, not extended (`MM-008`) |
| **Entry** | Low-risk buy at the reversal; add at each reaccumulation |
| **Stop** | Below the smart money reversal low |
| **Target** | Buy stops above the original consolidation's relative equal high (`MM-004`) |
| **Invalidation** | Price loses the reversal low; **or** price returns to the original consolidation and lingers instead of rejecting sharply (`MM-005`) |
| **Expected R** | 3–5R **[UNSOURCED]** |
| **Frequency** | 1–2/week per instrument |

#### `MMSM` — Market Maker Sell Model
Mirror of MMBM: accumulation → reaccumulation → reversal → low-risk sell →
distribution → redistribution → **second-stage distribution** → sell-off into
sell-side liquidity (`MM-002`).

The second stage of distribution is the tell that separates a genuine sell model
from a pullback that will reaccumulate and go long again (`MM-010`, NBB).

### Tier B — reduced size

#### `LDN to New York OTE`
| | |
| --- | --- |
| **Preconditions** | Inside a killzone; bias established |
| **Trigger** | Sweep a short-term low → market structure shift (`OTE-003`) |
| **Entry** | Retracement to the **62%** level. Do not wait for 70.5% or 79% (`OTE-002`, `OTE-004`) |
| **Stop** | Five pips beyond the swing extreme the fib was drawn from (`OTE-002`) — FX figure; see below |
| **Target** | Opposing end of the dealing range / liquidity beyond |
| **Invalidation** | No structure shift, or outside killzone hours |
| **Expected R** | 2–3R **[UNSOURCED]** |
| **Frequency** | 2–4/week |

Both sources independently land on 62% (`OTE-004`). **The five-pip stop is an FX
figure and does not transfer to NAS100 or XAUUSD** — see `GAPS.md`.

### Tier C — study only

`IFVG-006` ICT Reaper (needs a retail pattern present as the liquidity source);
`FVG-006` classic buy day; `NY-004` CME-open bond timing. Sound but single-sourced
or instrument-specific. Journal them; don't size them.

---

## 7. Entry mechanics

**Which part of the FVG.** Not a fixed depth. The shallow entry drill — partial
fill that never reaches consequent encroachment, then aggressive movement away —
is a real and common fill (`FVG-002`). Working an order at consequent
encroachment risks never being filled on the strongest moves.

**Confirming an IFVG flip.** Price must close *through* the gap, then return to
it. Bodies respecting consequent encroachment from the new side confirms
(`IFVG-005`). Wicks through are not confirmation.

**Where the stop sits.**

| Setup | Stop | Rule |
| --- | --- | --- |
| Silver Bullet | Beyond the displacement candle's extreme | `SB-003` |
| IFVG entry | Immediately beyond the inverted gap | `IFVG-002` |
| OTE | 5 pips beyond the fib origin swing (FX) | `OTE-002` |
| MMBM/MMSM | Beyond the smart money reversal extreme | `MM-001` |

The pattern: **stop at the structure that created the entry, not a round number
or a wider swing.**

**Market structure shift** (NBB's mechanical definition, `SMC-001`):
1. Price sweeps a series of lows
2. Price takes out the high that formed *before* that low ← the shift
3. Look left for the highs still available as targets

---

## 8. Risk model

### ⚠️ Almost entirely unsourced

Neither source states position sizing, risk per trade, daily limits or exposure
caps anywhere in this corpus. Extensive search returned trade *management*
(`SMC-003` and NBB on trailing stops) but no sizing arithmetic.

**Everything in this section is [UNSOURCED]** — conventional practice, not
distilled teaching. Treat it as a starting frame to replace with your own
backtested numbers.

| Parameter | Value | Status |
| --- | --- | --- |
| Risk per trade, Tier A | 1.0% | **[UNSOURCED]** |
| Risk per trade, Tier B | 0.5% | **[UNSOURCED]** |
| Tier C | 0% — study only | **[UNSOURCED]** |
| Max daily risk | 2.0% (stop after 2 losers) | **[UNSOURCED]** |
| Max weekly risk | 5.0% | **[UNSOURCED]** |
| Max concurrent positions | 2, and never 2 correlated | **[UNSOURCED]** |

### The arithmetic

```
Position size = (Account × Risk%) ÷ (Stop distance × Value per point)
```

**NAS100, £25,000 account, 1% risk, 40-point stop, £1/point:**
```
Risk       = 25,000 × 0.01        = £250
Size       = 250 ÷ (40 × 1)       = 6.25  →  6 contracts (round DOWN)
Actual risk= 6 × 40 × 1           = £240   (0.96%)
```

**EURUSD, £25,000 account, 1% risk, 12-pip stop (OTE + 5 pips):**
```
Risk       = £250
Pip value  = £10 per pip per standard lot
Size       = 250 ÷ (12 × 10)      = 2.08 lots  →  2.0 lots
Actual risk= 2.0 × 12 × 10        = £240   (0.96%)
```

**Always round down.** Rounding up breaches the limit on every trade.

**Correlation:** NAS100 and ES move together; EURUSD and GBPUSD move together.
Two correlated positions at 1% is a 2% trade wearing a disguise.

---

## 9. Trade management

**What the corpus supports:**

- **Take the target.** Silver Bullet targets the nearest opposing liquidity and
  comes off there — *"buying here and getting out there just at that high, that's
  enough for a trade"* (`SB-004`). Explicitly not held for extension.
- **Equilibrium is enough.** From a deep discount, getting back to 50% of the
  range is a complete trade (`SMC-003`).
- **Add on respects.** An IFVG acting as dynamic support can be added into on
  successive respects (`IFVG-003`).
- **Trailing cuts both ways.** NBB gives the balanced case: trailing protects
  against reversal, but trailing too tight stops you out of trades that then run
  to target without you (`qKbVXGXWGVE`, Trade Management).

**What it does not:** no breakeven rule, no partial-taking percentages, no runner
policy. **[UNSOURCED]** defaults, replace after backtesting:

| | |
| --- | --- |
| Breakeven | At +1R **[UNSOURCED]** |
| Partial | 50% at first target, remainder to the draw **[UNSOURCED]** |
| Runners | None until backtest justifies them **[UNSOURCED]** |

---

## 10. No-trade conditions

| Condition | Rule |
| --- | --- |
| Asian range failed to settle into a 20–30 pip consolidation → skip London | `LDN-005` |
| Setup opposes higher timeframe institutional order flow | `SMC-005` |
| An opposing liquidity pool sits between entry and objective (high resistance) | `MM-006` |
| No bias — steps 3–5 of §2 disagree | `HTF-002` |
| Outside killzone hours | `OTE-003` |
| Week's expansion already delivered | `HTF-003` |
| Price returned to the original consolidation and lingered | `MM-005` |
| Thu/Fri when the weekly move is done | `SMC-005` (implied — he concentrates Mon–Wed) |

**[UNSOURCED]** additions: high-impact news within 15 minutes unless the setup
*is* the news reaction (`SB-006` implies caution but no blackout); public
holidays and half-days; the first session back after a break.

---

## 11. Journal fields

Log every trade with these columns so the system can be measured. Matches
`backtest-template.csv`.

| Field | Notes |
| --- | --- |
| `date`, `time_ny`, `time_uk` | Both — the DST gap makes UK-only ambiguous |
| `instrument` | XAUUSD / EURUSD / GBPUSD / NAS100 |
| `setup` | `Silver Bullet` / `MMBM` / `MMSM` / `LDN to New York OTE` |
| `tier` | A / B / C |
| `rule_ids` | Which rules fired, e.g. `SB-001,SB-003` ← **the key column** |
| `htf_bias`, `draw_on_liquidity` | Direction; where price was reaching |
| `resistance_class` | low / high — should always be `low` |
| `session`, `window_hit` | Which killzone; was it inside it |
| `pd_array` | FVG / IFVG / OB / OTE |
| `entry`, `stop`, `target`, `size`, `risk_pct` | |
| `checklist_score` | Out of 10 (§ below) |
| `outcome`, `r_multiple`, `mae`, `mfe` | MAE/MFE tell you if stops are too tight |
| `exit_reason` | target / stop / manual / time |
| `notes` | |

`rule_ids` is what makes the journal feed back into the system: if a rule's
trades lose consistently, that rule is wrong for you and the citation tells you
exactly which video to re-watch.

---

## 12. Weekly review loop

**Every Sunday:**

1. **Score by `rule_ids`.** Win rate and average R per rule. A rule below
   breakeven over 20+ trades is a demotion candidate.
2. **Check window discipline.** Trades taken outside `window_hit` — did they
   perform worse? If they performed the same, the window may matter less than
   claimed. Log it, don't act on one week.
3. **Check the resistance filter.** Any `resistance_class = high` trades should
   not exist. If they do and they lost, that is `MM-006` confirming itself.
4. **Check checklist score vs outcome.** If 9–10 scores don't beat 7–8, the
   checklist is weighted wrong.
5. **Review MAE.** Winners with deep MAE mean stops are near-optimal. Losers with
   shallow MFE mean entries are late.

**Triggers for changing a rule:**

| Trigger | Action |
| --- | --- |
| Rule below breakeven, 20+ trades | Demote a tier |
| Rule above 2R average, 20+ trades | Consider promoting |
| A conflict in `CONFLICTS.md` resolved by data | Update the rule, note the evidence |
| A `GAPS.md` question answered by data | Promote the **[UNSOURCED]** default to sourced-by-testing |

**Never** change a rule on fewer than 20 trades. **Never** add a rule that isn't
in `rules.json` without a citation — that is how a distilled system quietly
becomes an improvised one.

---

## Limitations

**This is a synthesis of what two educators say, not evidence that any of it
works.** No rule here has been tested against price data. Both sources sell
education, which is a reason for care rather than an accusation. 112 of 139
transcripts are auto-generated captions that mangle jargon — every rule was read
in context, but the risk of a mis-transcribed term surviving into a rule is real
and non-zero. 48 of 139 videos produced rules; the other 91 were indexed and
searched but contributed nothing that survived review, so coverage is partial.
The risk model is essentially unsourced. **Backtest before risking money.**
