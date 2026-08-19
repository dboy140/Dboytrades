# Conflicts

Two genuine contradictions surfaced. Both are recorded on the rules themselves
via `contradicts`, and neither was silently resolved during extraction.

Resolution order, per the brief: recency, then frequency across the corpus, then
specificity.

---

## C-01 — London killzone start time

| Position | Rule | Window | Sources |
| --- | --- | --- | --- |
| A | `LDN-001` | **02:00–05:00** NY | `cxdjcXec3eA` @04:43, `9_qyz3TNcJU` @33:06 |
| B | `LDN-002` | **01:00–05:00** NY | `_2nUKLAD9ig` @08:28, `_2nUKLAD9ig` @03:14 |

Both agree the window **ends at 05:00**. Only the start is disputed.

**Resolution: use 02:00–05:00.**

- *Frequency*: A appears in two separate videos; B in one video twice.
- *Specificity*: B comes from Core Content Month 08, where the surrounding text
  is defining killzones generally. A comes from a live review naming the window
  while trading it, and from a lecture listing every killzone together.
- *Recency* does not separate them — neither citation carries a reliable date.

The practical cost of being wrong is small and asymmetric: taking 02:00 means
possibly missing an hour of setup, while taking 01:00 means an extra hour of
lower-quality signals. Missing a setup is the cheaper error.

**Watch for**: if backtesting shows qualifying setups clustering in the 01:00–02:00
hour, revisit this.

---

## C-02 — Silver Bullet windows: ICT vs NBB

| Position | Rule | Windows | Instruments |
| --- | --- | --- | --- |
| ICT | `SB-001` | 10:00–11:00 NY (AM), 14:00–15:00 (PM) | index futures |
| NBB | `SB-010` | 03:00–04:00 and 08:00–09:00 NY | EURUSD, GBPUSD |

**Resolution: not a disagreement — treat as instrument-specific.**

NBB states his windows while discussing EU and GU specifically; ICT's are given
for index futures. NBB's 03:00–04:00 sits inside ICT's London killzone and his
08:00–09:00 sits inside ICT's New York killzone (`NY-001`, 07:00–09:00), so the
two are consistent once instrument and session are held constant.

**Consequence for this system**: because the operator trades **both** XAUUSD/FX
and NAS100, both sets apply — ICT's windows on NAS100, NBB's on EURUSD/GBPUSD.
They are kept as separate rules rather than merged.

**Watch for**: XAUUSD is covered by neither statement. Treated as unsourced —
see `GAPS.md`.
