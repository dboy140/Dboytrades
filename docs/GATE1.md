# Gate 1 — Discovery results

**Run 2026-08-19 via Google Colab (yt-dlp, no Apify, $0.00).**

## Channels — both confirmed

| Key | Channel ID | Resolved name | Handle | Status |
| --- | --- | --- | --- | --- |
| ICT | `UCtjxa77NqamhVC8atV85Rog` | The Inner Circle Trader | `@InnerCircleTrader` | ✅ confirmed |
| NBBTRADER | `UCo6TS8uarO5r562d4lESg9w` | NBBTRADER | `@NBBTRADER` | ✅ confirmed, 2040 subs |
| — | `UCmtJ3lDd2fjt-IMf6lfzlcA` | — | — | ❌ ruled out, no data |

890 ICT videos enumerated, consistent with the ~850 the brief expected, which
independently corroborates the ICT channel id.

## ICT — 471 in scope of 890

| Bucket | Videos |
| --- | ---: |
| Smart Money Concepts | 186 |
| Money Maker Model (MMxM) | 136 |
| New York Session | 130 |
| Higher Timeframe | 103 |
| London Session | 84 |
| Fair Value Gaps | 79 |
| ICT Silver Bullet | 53 |
| Inversion Fair Value Gaps | 51 |

Counts sum to more than 471 because a video can belong to several buckets
(~1.7 each on average).

135 matched on title alone; **336 more were recovered by searching descriptions**
— so title-only matching would have missed 71% of the in-scope corpus. No bucket
is thin any more; Inversion FVG went from 1 to 51.

The 419 still excluded are, on inspection, genuinely out of scope: daily trade
reviews, market commentary, news recaps and session recordings rather than
teaching content.

## NBBTRADER — 16 own videos, 0 Shorts

His own channel is small. The brief predicted this: his fullest strategy
explanations are guest appearances elsewhere.

60 raw search candidates were tiered rather than taken wholesale, because
searching "NBB trader" also surfaces unrelated ICT/prop-firm content, and
including that would attribute another person's words to him:

- **confident** — title or channel names NBB
- **review** — same channel as a confident hit but title does not say
- **reject** — neither

On the first 15 candidates that split 4 / 2 / 9.

## Corpus size

**321.4 hours.** This is the number that should drive the Phase 3 decision: at
roughly 9,000 spoken words per hour that is on the order of 2.9M words, and rule
extraction over all of it is the most expensive step in the project.

## Open decisions

1. **Scope.** Take all 471 ICT videos, or prioritise a subset first?
2. **Transcript backend.** Colab serves channel listings but is challenged on
   individual video pages, and captions require video pages — so Phase 2 needs
   either Apify or cookies.
3. **Guest appearances.** Which of the `review` tier to include.
