# Phase 6 — Verification

Run 2026-08-19. Every check below is executable, not asserted.
Reproduce: `python -m scripts.verify_deliverables` helpers, `python -m pytest`.

---

## 1. Citations resolve — 10 spot-checked at random

Ten citations drawn at random (seed 7) and resolved against the corpus:

| Rule | Video @ timestamp | Nearest cue | Result |
| --- | --- | --- | --- |
| FVG-001 | `_NWG_eJRBpU` @ 00:04:58 | 0.32s | PASS |
| MM-005 | `i8xt0EQDjNY` @ 00:09:46 | 0.80s | PASS |
| OTE-004 | `lL6maBEfjwU` @ 00:23:08 | 0.32s | PASS |
| SMC-001 | `YFsn7BUMJ_s` @ 00:20:17 | 0.00s | PASS |
| HTF-002 | `g7jchu4g31c` @ 00:20:02 | 0.68s | PASS |
| OTE-002 | `PrbvJ5Gzh4Q` @ 00:13:30 | 0.40s | PASS |
| MM-002 | `AKg_r0DIa3k` @ 00:30:26 | 0.28s | PASS |
| OTE-001 | `PrbvJ5Gzh4Q` @ 00:06:14 | 0.80s | PASS |
| HTF-006 | `-cXnnHjy9s0` @ 00:39:11 | 0.46s | PASS |
| SB-001 | `cgsltOB736E` @ 00:28:35 | 0.64s | PASS |

**10/10.** Worst case lands 0.8s from a transcript cue.

Across all 63 rules, **102/102 citations** pass the full check: video in corpus,
timestamp inside the real runtime, transcript within 90s, deep link matching the
timestamp. The verifier is negative-tested — moving a timestamp past the end,
swapping the video id, desyncing the link and stripping sources are all caught.

## 2. No transcript text leaked

Every 12-word window of all 139 transcripts (735,464 n-grams) was indexed and
matched against every deliverable.

| Rule field | Verbatim runs |
| --- | ---: |
| `statement` | **0** |
| `trigger`, `entry`, `stop_loss`, `target`, `invalidation` | **0** |
| `notes` | 4 |

All rule *logic* is paraphrased, as required. The four runs in `notes` are
short attributed quotes inside quotation marks, kept as evidence — for example
OTE-002's *"your stop has to be five pips above the old high"*, which is the
precise instruction the rule encodes.

`CONFLICTS.md`, `GAPS.md`, `SOURCES.md`, `checklist.md`, `backtest-plan.md` and
`ict-vs-nbb.md` are entirely clean. `00-SYSTEM.md`'s runs are all inside
markdown blockquotes.

**Nothing is presented as my prose that is actually the source's.** If you would
rather have zero verbatim text at all, the four notes can be paraphrased — say
the word.

## 3. Every setup has stop, target and invalidation

| Setup | Tier | Stop | Target | Invalidation |
| --- | --- | --- | --- | --- |
| Silver Bullet | A | ✅ | ✅ | ✅ |
| MMBM | A | ✅ | ✅ | ✅ |
| MMSM | A | ✅ | ✅ | ✅ |
| LDN to New York OTE | B | ✅ | ✅ | ✅ |

No demotions needed.

## 4. Session times correct for GMT and BST

The published DST table was verified against the IANA database (`zoneinfo`),
not hand-computed:

| Date | NY 10:00 → UK | Offset |
| --- | --- | --- |
| 15 Jan 2026 | 15:00 | +5 |
| 15 Mar 2026 | **14:00** | **+4** |
| 15 Jun 2026 | 15:00 | +5 |
| 28 Oct 2026 | **14:00** | **+4** |
| 15 Nov 2026 | 15:00 | +5 |

2026 mismatch windows: **8–29 Mar** and **25 Oct – 1 Nov**. Regenerate for any
year with `python -m scripts.dst_table 2027`. 13 tests cover the conversion.

## 5. All eight buckets represented

| Bucket | Rules |
| --- | ---: |
| Smart Money Concepts | 12 |
| Money Maker Model (MMxM) | 10 |
| ICT Silver Bullet | 9 |
| New York Session | 7 |
| Higher Timeframe | 7 |
| Fair Value Gaps | 6 |
| Inversion Fair Value Gaps | 6 |
| London Session | 6 |

None thin on count. **But Higher Timeframe is thin on substance**, and that is a
finding rather than a search failure: the corpus offers a framework for daily
bias, not a decidable procedure. Its most concrete statement argues against
forcing a daily bias at all (`HTF-003`). §2 of the system doc is the closest
decidable checklist the material supports, and it legitimately outputs "no bias".

The four OTE rules sit under Smart Money Concepts because the eight buckets have
no OTE category — which is why that count reads 12.

## 6. Limitations

This is a synthesis of what two educators **say**, not evidence that any of it
works. No rule here has been tested against a single bar of price data; the
expected-R figures, all risk parameters and the checklist threshold are
engineering defaults marked **[UNSOURCED]**, and the corpus contains no position
sizing whatsoever. 112 of 139 transcripts are auto-generated captions that
demonstrably mangle trading jargon — every rule was read in context and obvious
false positives were discarded, but a mis-transcribed term surviving into a rule
remains possible. Only 48 of 139 videos produced rules and 36 queued videos
returned no captions at all, so coverage is partial. Just 3 of 63 rules come
from NBBTRADER, making the ICT/NBB comparison lopsided and its conclusions
provisional. Both sources sell education, which is a reason for care rather than
an accusation. **Backtest before risking money.**
