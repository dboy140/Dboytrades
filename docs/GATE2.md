# Gate 2 — Transcript ingestion

**Run 2026-08-19 via Colab + Apify. 45.9 minutes.**

| | |
| --- | ---: |
| Queued | 181 |
| Retrieved | **145** |
| No captions | 36 (20%) |
| Failed | 0 |
| Total words | **775,614** |
| Actor | `automation-lab~youtube-transcript` |

Average ~5,350 words per video, consistent with ~36 minutes of speech each.

## Backend

yt-dlp captions were tested first and are blocked from Colab, as expected —
the same video-page restriction that broke the original `--deep-scan`. Channel
listings work there; video pages do not.

`automation-lab~youtube-transcript` was the first actor tried and returned 57
segments on the probe video, all 57 timestamped, so the bake-off stopped there.
The other four candidates were never exercised and remain unmeasured — if this
actor becomes unavailable or its pricing changes, they are still worth testing
rather than assumed dead.

Zero failures across 181 videos in 8 batched runs.

## Open items

**36 videos returned no captions.** Not yet diagnosed. The excluded-sample
titles seen during Gate 1 included several marked `[Silent]`, and silent trade
recordings genuinely have nothing to transcribe — but 20% is high enough to
check rather than assume. Whether those 36 are silent recordings, live streams,
or captions the actor simply could not reach changes whether they are
recoverable.

**Segment granularity is ~38 seconds** (57 segments over roughly 36 minutes).
That is workable for citation — it is close to the 45-second windowing this
project would have chosen anyway — but it means a citation points at a window,
not a sentence. Worth confirming against the real data before rules are
anchored to it.

## Not yet verified

The transcripts live in Colab and have not been inspected. Everything above is
read off the run summary. Before Phase 3, the corpus itself needs checking:
segment timing sanity, caption quality (manual vs auto), and whether the 36
gaps matter.
