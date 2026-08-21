# Dboytrades — ICT + NBBTRADER corpus → executable trading system

Builds a local, citable knowledge base from a defined slice of ICT content plus
the complete NBBTRADER catalogue, then distils it into one executable trading
system with machine-readable rules.

Every rule must trace back to a specific video ID and timestamp. That is
enforced by the type system and the verification pass, not by discipline.

---

## Status

All seven phases have run. The corpus was built, the rules were extracted and
verified against it, and the system was turned into an execution engine.

| | |
| --- | --- |
| Transcripts | 145 pulled, 139 kept (5 quarantined as a different show, 1 empty) |
| Words | 775,614 |
| Rules | 63, every one carrying a source |
| Citations | **102/102 verified** — video in corpus, timestamp inside the real runtime, transcript cue within 90s, deep link matching |
| Deliverables | `strategy/` — system, sources, conflicts, gaps, verification |
| Engine | `bot/` — signals, filters, backtest, walk-forward validation, live rails |

The verifier is negative-tested: moving a timestamp past the end of a video,
swapping the video id, desyncing a deep link and stripping sources are all
caught.

**What has not happened: the system has never been validated on real price
data.** The engine runs, the machinery is tested, and on a random walk it
correctly reports no edge (expectancy −0.0R, profit factor 1.0). But no
conclusion about whether these rules make money is available yet, because that
needs a couple of years of 1-minute bars that this build environment cannot
reach and that nobody has supplied. Any win rate quoted before that would be
invented.

### Running it without a dev machine

The build environment cannot reach YouTube (`403` to `CONNECT` — an egress
policy denial, reported rather than routed around), so each phase ships as a
Colab notebook that runs on Google's machines instead:

| Notebook | Does | Needs |
| --- | --- | --- |
| `notebooks/see_for_yourself.ipynb` | **Start here.** Proves the machinery is honest — finds no edge in random data, refuses a lucky result, accepts a real one | nothing |
| `notebooks/gate1_colab.ipynb` | Discovery — which videos exist, filtered to the eight ICT topics |
| `notebooks/get_data_colab.ipynb` | **Fetch 1-minute price data** — the web form is one day per download; this pulls a two-year range | nothing |
| `notebooks/backtest_colab.ipynb` | Backtest one setup | your CSV |
| `notebooks/validate_colab.ipynb` | Walk-forward validation — the one that can say no | your CSV |

`notebooks/gate1_standalone.py` and `gate2_standalone.py` are generated from
`scripts/`, and `tests/test_standalone.py` regenerates them and fails if they
have drifted, so the Colab copy cannot silently diverge from the real pipeline.

### Or locally

```bash
git clone https://github.com/dboy140/Dboytrades.git && cd Dboytrades
git checkout claude/ict-nbbtrader-trading-system-43hipg
pip install -r requirements.txt

python -m scripts.discover                      # Phase 1 -> Gate 1
python -m bot.inspect_data your_data.csv        # check the timestamps first
python -m bot.run_validate your_data.csv --instrument EURUSD
```

## Scope

**ICT — eight topics only.** The full back catalogue is not scraped. Buckets:
Money Maker Model, Silver Bullet, Fair Value Gaps, Inversion Fair Value Gaps,
London Session, New York Session, Higher Timeframe, Smart Money Concepts.

**NBBTRADER — everything.** Long-form, Shorts, lives, plus guest appearances on
other channels (reached by keyword search, since channel enumeration cannot see
them).

Adjacent concepts (SMT divergence, DXY, order blocks, displacement, OTE) are
captured as context inside an in-scope video's notes. They never trigger a
separate video hunt — `find_adjacent_concepts()` exists for exactly this, and
the bucket filter deliberately does not match on them.

## Fetching

yt-dlp only. Apify has been removed entirely — no API key, no account, no
per-video billing. `--flat-playlist --dump-json` enumerates a channel in one
request per tab; captions come from YouTube's own `json3` format, whose
timestamps are unambiguously milliseconds.

Dependencies are `yt-dlp` and `pydantic`. That is the whole runtime.

## Layout

```
scripts/config.py         single source of truth: channels, 8 buckets, paths
scripts/models.py         pydantic contracts; a Rule cannot exist without a source
scripts/bucketing.py      the eight-bucket filter
scripts/ytdlp_adapter.py  yt-dlp enumeration, search, json3 caption parsing
scripts/discover.py       Phase 1: enumerate -> filter -> Gate 1
scripts/ingest.py         Phase 2: transcripts -> Gate 2
scripts/verify_env.py     preflight
data/transcripts/         raw, local only, gitignored
data/notes/               per-video structured extraction
extraction/rules.json     atomic deduped rules
strategy/                 final deliverables
```

## Running

```bash
pip install -r requirements.txt

python -m scripts.verify_env            # yt-dlp present? YouTube reachable?
python -m scripts.discover              # Phase 1 -> Gate 1
python -m scripts.discover --deep-scan  # slower, better recall (see below)

python -m scripts.ingest --limit 5      # trial run first
python -m scripts.ingest                # full pull -> Gate 2

python -m pytest -q                     # 96 tests, no network
```

Both phases are idempotent. Discovery short-circuits on an existing manifest
unless `--refresh`; ingestion skips any transcript already on disk, so an
interrupted run resumes for free.

### The `--deep-scan` tradeoff

`--flat-playlist` is one cheap request per channel tab but returns **no
description**, so bucket matching is title-only by default. `--deep-scan` adds
a second pass that fetches descriptions for videos which did *not* match on
title, catching ones whose titles are vague. It costs one request per unmatched
video, so on a large back catalogue it is slow. Gate 1 reports which mode ran.

### If YouTube throttles you

Long runs from datacentre IPs get challenged. In `config.py`:

```python
YTDLP_COOKIES_FROM_BROWSER = "chrome"   # or "firefox"
YTDLP_SLEEP_REQUESTS = 2.0
YTDLP_SLEEP_BETWEEN_VIDEOS = 2.0
```

## Design notes

**Channel verification precedes enumeration.** Two similarly-named NBBTRADER
channels exist. Discovery probes both and prints sample titles from each in the
Gate 1 output (also saved to `data/channel_probe.json`) for the operator to
adjudicate. Scraping the wrong one would attribute another person's words to the
corpus permanently, so the code does not guess.

**Channel IDs are marked unverified.** They came from the task brief, not a live
lookup, and carry `provenance: operator_supplied`, `verified: False`.

**Word-boundary matching, not substring.** A naive `"FVG" in title` test would
drag every Inversion FVG video into the plain FVG bucket through the substring
inside "IFVG". Boundaries keep the two buckets distinct — there is a test for
exactly this.

**Plurals are handled.** The operator keyword list is singular; real titles say
"Fair Value Gaps". Without a trailing `s?` the filter silently drops them. Two
tests caught this during development.

**Added keywords are quarantined.** Real titles like "New York AM Session"
contain none of the supplied New York keywords as a contiguous phrase. Rather
than editing the operator's list, additions live in a separate `extra_keywords`
field so they can be reviewed and rejected. **These are worth a look before the
first real run.**

**Caption kind is established, not guessed.** Manual captions are requested in
their own pass first; only if none exist is the auto-generated track fetched.
That makes `caption_kind` a fact, which matters because auto-captions
routinely mangle trading jargon and the field caps a claim's confidence.

**json3, not VTT.** YouTube's `json3` caption format carries `tStartMs`
directly, so there is no seconds-versus-milliseconds ambiguity to resolve. A
silent 1000x error would misplace every citation in the corpus while leaving it
perfectly well-formed; there is a test pinning the conversion.

**Network blocks are distinguished from ordinary errors.** A refused CONNECT
tunnel raises `YtdlpBlocked` and stops the run; a private or removed video does
not. Retrying a 403 from an egress gateway just hides the real problem, and
misreporting a deleted video as an outage would send you chasing the wrong
thing. There are tests for both directions.

**Paraphrase is enforced.** `Rule.statement` rejects spoken filler, a crude but
effective guard against transcript text leaking into deliverables. Raw
transcripts stay in `data/transcripts/`, gitignored — personal research, not
redistribution.

## Tests

96 tests, no network required. They cover the bucket filter's edge cases
(IFVG/FVG separation, plurals, acronyms inside words), json3 caption parsing
against the real format (millisecond conversion, padding events, unsorted
input), network-block detection that does not misclassify a private video as an
outage, and the model contracts that make an
uncited rule unrepresentable.
