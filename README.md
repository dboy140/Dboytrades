# Dboytrades — ICT + NBBTRADER corpus → executable trading system

Builds a local, citable knowledge base from a defined slice of ICT content plus
the complete NBBTRADER catalogue, then distils it into one executable trading
system with machine-readable rules.

Every rule must trace back to a specific video ID and timestamp. That is
enforced by the type system and the verification pass, not by discipline.

---

## Status: pipeline complete, Gate 1 blocked in the build environment

**Discovery has never run. `data/manifest.json` does not exist. Zero videos
found, zero transcripts fetched.**

The environment this was built in cannot reach YouTube *or* Apify:

| Host | Result |
| --- | --- |
| `www.youtube.com:443` | `403` to `CONNECT` — org egress policy denial |
| `api.apify.com:443` | `403` to `CONNECT` — org egress policy denial |

yt-dlp confirms it directly: `Tunnel connection failed: 403 Forbidden`.

Gate 1 asks for video counts per bucket, NBB totals, runtime hours and cost.
All four require enumeration to have happened, so presenting any number for
them would mean inventing it. Nothing was invented — see
[docs/BLOCKED.md](docs/BLOCKED.md).

**This is an environment limitation, not a code one.** The pipeline runs
anywhere YouTube is reachable, and needs no API key or paid account:

```bash
pip install -r requirements.txt
python -m scripts.discover_ytdlp      # Gate 1
python -m scripts.ingest_ytdlp        # Gate 2
```

Reproduce the block: `python -m scripts.verify_env` (exit 2 while blocked).

---

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

## Two backends

**yt-dlp (default).** Needs only `youtube.com`. No account, no API key, no
per-video billing. `--flat-playlist --dump-json` enumerates a channel in one
request per tab; captions come from YouTube's own `json3` format, whose
timestamps are unambiguously milliseconds.

**Apify (optional).** Retained and working. Needs `api.apify.com` plus a token,
and bills per video. Use it if YouTube blocks your IP and you would rather pay
someone else's infrastructure to fetch than manage cookies.

Nothing downstream knows which backend produced the data — both emit identical
manifest and transcript shapes.

## Layout

```
scripts/config.py         single source of truth: channels, 8 buckets, paths
scripts/models.py         pydantic contracts; a Rule cannot exist without a source
scripts/bucketing.py      the eight-bucket filter
scripts/ytdlp_adapter.py  yt-dlp enumeration + json3 caption parsing
scripts/discover_ytdlp.py Phase 1 via yt-dlp -> Gate 1
scripts/ingest_ytdlp.py   Phase 2 via yt-dlp -> Gate 2
scripts/apify_runner.py   Apify path: retries transient, never retries denials
scripts/discover.py       Phase 1 via Apify; shared filter/report used by both
scripts/actor_bakeoff.py  compares the four Apify transcript actors
scripts/verify_env.py     preflight
data/transcripts/         raw, local only, gitignored
data/notes/               per-video structured extraction
extraction/rules.json     atomic deduped rules
strategy/                 final deliverables
```

## Running (yt-dlp path)

```bash
pip install -r requirements.txt

python -m scripts.discover_ytdlp              # Phase 1 -> Gate 1
python -m scripts.discover_ytdlp --deep-scan  # slower, better recall (see below)

python -m scripts.ingest_ytdlp --limit 5      # trial run first
python -m scripts.ingest_ytdlp                # full pull -> Gate 2

python -m pytest -q                           # 103 tests, no network
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
channels exist. `verify_channels()` probes both and writes sample titles to
`data/channel_probe.json` for the operator to adjudicate. Scraping the wrong one
would attribute another person's words to the corpus permanently, so the code
does not guess.

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

**Spend is guarded and logged.** On the Apify path, any run estimated above
`COST_ALERT_THRESHOLD_USD` ($5) raises `SpendGuard` rather than executing, and
every run appends to `logs/cost_ledger.json`. The yt-dlp path costs nothing but
time.

**Caption kind is established, not guessed.** Manual captions are requested in
their own pass first; only if none exist is the auto-generated track fetched.
That makes `caption_kind` a fact, which matters because auto-captions
routinely mangle trading jargon and the field caps a claim's confidence.

**json3, not VTT.** YouTube's `json3` caption format carries `tStartMs`
directly, so there is no seconds-versus-milliseconds ambiguity to resolve. A
silent 1000x error would misplace every citation in the corpus while leaving it
perfectly well-formed; there is a test pinning the conversion.

**Policy denials are never retried.** `apify_runner` splits failures into
transient (retry with exponential backoff via tenacity) and blocked (raise
immediately). Retrying a 403 from an egress gateway just hides the real problem.

**Paraphrase is enforced.** `Rule.statement` rejects spoken filler, a crude but
effective guard against transcript text leaking into deliverables. Raw
transcripts stay in `data/transcripts/`, gitignored — personal research, not
redistribution.

## Tests

103 tests, no network required. They cover the bucket filter's edge cases
(IFVG/FVG separation, plurals, acronyms inside words), json3 caption parsing
against the real format (millisecond conversion, padding events, unsorted
input), the tolerant actor-output parser, network-block detection that does not
misclassify a private video as an outage, and the model contracts that make an
uncited rule unrepresentable.
