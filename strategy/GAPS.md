# Gaps

Questions this corpus does not answer. Ordered by how much they matter.

---

## Critical — the system is incomplete without these

### G-01 · Position sizing and risk limits
**Nothing.** Neither source states risk per trade, daily loss limits, exposure
caps or sizing arithmetic anywhere in 734,784 words. Searched repeatedly.

Every number in §8 of the system doc is an engineering default. This is the
largest unsourced area and the one most likely to cause real loss.

**To close:** your own risk tolerance plus backtested max-consecutive-losses.
Not recoverable from more scraping.

### G-02 · Which fair value gap will invert
`IFVG-004` answers this with a framework — time, price, institutional market
structure, premium/discount — not a procedure. The question is asked directly in
the video and the answer stays at the level of "I'm employing a lot of different
things".

Since IFVG entries are a core mechanic, this leaves a judgement call at the heart
of the system.

**To close:** backtest which candidate gaps actually inverted, and look for the
common features. This may be genuinely discretionary.

### G-03 · Stop distance outside FX
`OTE-002` gives "five pips beyond the swing" — an FX figure. There is no
equivalent for NAS100 (points) or XAUUSD (dollars). The other stop rules are
structural ("beyond the displacement candle") and do transfer.

**To close:** derive from backtested MAE per instrument.

---

## Significant

### G-04 · XAUUSD is not covered
You trade it; neither source addresses it in this corpus. Every gold rule here is
inference from FX or index teaching. Gold's volatility profile and session
behaviour differ enough that this should not be assumed.

**To close:** test separately and expect different windows.

### G-05 · Expected R and frequency per setup
The R multiples and trade frequencies in §6 are **[UNSOURCED]** estimates. No
source states expected R for any setup.

**To close:** backtest output, directly.

### G-06 · Breakeven, partials, runners
`SB-004` says take the target; NBB discusses trailing trade-offs without
resolving them. There is no stated breakeven trigger, partial percentage or
runner policy.

**To close:** MFE analysis will show whether partials cost or earn.

### G-07 · A decidable daily bias
§2 is the closest procedure the corpus supports, and step 3 ("which pool is
larger") remains judgement. `HTF-003` suggests this is deliberate — he argues
against forcing a daily bias at all.

**To close:** possibly not closeable. It may be genuinely discretionary, which is
worth accepting rather than papering over.

---

## Minor

### G-08 · London killzone start
02:00 or 01:00. See `CONFLICTS.md` C-01. Resolved conservatively to 02:00; the
backtest can settle it.

### G-09 · News handling
`SB-006` widens the AM window on news days but there is no blackout rule, no list
of which releases matter, no minimum distance.

### G-10 · The schema has no timing category
Nineteen rules were authored naturally as `filter`, `trigger` or `target` — none
of which exist in the brief's category enum
(`bias | liquidity | entry_model | entry_mechanic | risk | management | invalidation | psychology`).
Session-timing rules in particular have no natural home. Each was mapped to the
closest allowed value with the original recorded in its notes.

**To close:** add a `timing` or `filter` category to the schema.

---

## Corpus coverage

**48 of 139 videos produced rules.** The other 91 were fetched, indexed and
searched, but no passage from them survived review into a cited rule. Extraction
read the highest-ranked passages per concept rather than every word, so it is
likely — not certain — that some material was missed.

**36 of 181 queued videos returned no captions** and are absent entirely. Several
were titled `[Silent]` (silent trade recordings, genuinely nothing to
transcribe), but this was not verified case by case.

**Only 20 of 102 citations carry a publish date.** Dates were recovered from
titles where ICT included one. Flat enumeration returns no dates and fetching
them needs video pages the fetch environment cannot open. This weakens the
recency criterion for resolving conflicts.

**3 of 63 rules are NBB-sourced.** His own channel holds 16 videos, mostly
beginner series. See `extraction/ict-vs-nbb.md` — the comparison is lopsided and
the conclusions there are provisional.

---

## Not a gap, but stated plainly

**This is a synthesis of what two educators say, not evidence that it works.**
No rule has been tested against price data. 112 of 139 transcripts are
auto-generated captions that mangle trading jargon; every rule was read in
context, but a mis-transcribed term surviving into a rule is possible.
