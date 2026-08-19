# A+ Pre-Trade Scorecard

Binary only. Tick or don't — no "sort of".

Score **before** entry. Scoring after the fact is how a checklist becomes a
justification.

---

## Gate — all four required

Fail any one and there is no trade regardless of the score below.

- [ ] **G1** — HTF bias established and this trade agrees with it (`HTF-002`, `SMC-005`)
- [ ] **G2** — A specific draw on liquidity is identified and written down (`HTF-001`)
- [ ] **G3** — **Low** resistance: no opposing pool between entry and target (`MM-006`)
- [ ] **G4** — Inside a defined session window for this instrument (`LDN-001`, `NY-001`, `SB-001`, `SB-002`)

---

## Score — 10 points

| # | Check | Rule |
| --- | --- | --- |
| 1 | Weekly expansion still has room | `HTF-003` |
| 2 | Price is in the correct half — discount to buy, premium to sell | `SMC-003` |
| 3 | Setup is one of the four named journal setups | §6 |
| 4 | A session Judas swing has already run the near-side stops | `LDN-004`, `SMC-006` |
| 5 | Market structure shift confirmed by the three-step definition | `SMC-001` |
| 6 | A PD array is present at entry (FVG / IFVG / OB / OTE 62%) | `FVG-001`, `IFVG-001`, `OTE-002` |
| 7 | Stop sits at the structure that created the entry, not a round number | `SB-003`, `IFVG-002`, `OTE-002` |
| 8 | Target is a named liquidity pool, not a round number or an R multiple | `SB-004`, `MM-004` |
| 9 | SMT divergence agrees (indices only — score 1 free on FX/XAUUSD) | `SB-008`, `NY-006` |
| 10 | Monday–Wednesday | `SMC-005` |

---

## Thresholds

| Score | Action |
| --- | --- |
| **9–10** | Tier A, full size |
| **7–8** | Tier B, half size |
| **≤ 6** | **No trade.** Journal it as an observation |

**Minimum for Tier A is 9/10 with all four gates passed.**

The threshold is **[UNSOURCED]** — no source states one. It is deliberately
strict so early data shows whether high scores actually outperform. If 9–10
trades do not beat 7–8 over 20+ trades, the weighting is wrong, not the market
(see §12 of the system doc).

---

## After the trade

Record `checklist_score` in the journal alongside `rule_ids`. The score is only
worth keeping if it is later correlated against outcome — otherwise it is
ceremony.
