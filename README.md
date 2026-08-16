# Dboytrades — ICT + NBBTRADER corpus → executable trading system

Builds a local, citable knowledge base from a defined slice of ICT content plus
the complete NBBTRADER catalogue, then distils it into one executable trading
system with machine-readable rules.

Every rule must trace back to a specific video ID and timestamp. That is
enforced by the type system and the verification pass, not by discipline.

---

## Status: Phase 0 complete, Gate 1 blocked

**Discovery has never run. `data/manifest.json` does not exist. Zero videos
found, zero transcripts fetched.**

| Requirement | Result |
| --- | --- |
| `api.apify.com:443` | `403` to `CONNECT` — org egress policy denial |
| `www.youtube.com:443` | `403` to `CONNECT` — org egress policy denial |
| `APIFY_TOKEN` | not set |

Gate 1 asks for video counts per bucket, NBB totals, runtime hours and cost.
All four require enumeration to have happened, so presenting any number for
them now would mean inventing it. Nothing was invented — see
[docs/BLOCKED.md](docs/BLOCKED.md).

Reproduce: `python -m scripts.verify_env` (exit 2 while blocked).

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

## Layout

```
scripts/config.py        single source of truth: channels, 8 buckets, paths
scripts/models.py        pydantic contracts; a Rule cannot exist without a source
scripts/bucketing.py     the eight-bucket filter
scripts/apify_runner.py  retries transient faults, refuses to retry policy denials
scripts/discover.py      Phase 1: verify -> enumerate -> filter -> Gate 1
scripts/actor_bakeoff.py compares the four transcript actors on one video
scripts/verify_env.py    preflight
data/transcripts/        raw, local only, gitignored
data/notes/              per-video structured extraction
extraction/rules.json    atomic deduped rules
strategy/                final deliverables
```

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env      # add APIFY_TOKEN
```

## Running

```bash
python -m scripts.verify_env             # preflight: token, egress, actors
python -m scripts.discover --dry-run     # exercise plumbing, zero spend
python -m scripts.discover               # Phase 1, stops at Gate 1
python -m scripts.actor_bakeoff          # compare transcript actors, then ask
python -m pytest -q                      # 73 tests
```

Discovery is idempotent: an existing non-empty manifest short-circuits the run
unless `--refresh` is passed.

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

**Spend is guarded and logged.** Any run estimated above
`COST_ALERT_THRESHOLD_USD` ($5) raises `SpendGuard` rather than executing. Every
run appends to `logs/cost_ledger.json`.

**Policy denials are never retried.** `apify_runner` splits failures into
transient (retry with exponential backoff via tenacity) and blocked (raise
immediately). Retrying a 403 from an egress gateway just hides the real problem.

**Paraphrase is enforced.** `Rule.statement` rejects spoken filler, a crude but
effective guard against transcript text leaking into deliverables. Raw
transcripts stay in `data/transcripts/`, gitignored — personal research, not
redistribution.

## Tests

73 tests, no network required. They cover the bucket filter's edge cases
(IFVG/FVG separation, plurals, acronyms inside words), the tolerant actor-output
parser, and the model contracts that make an uncited rule unrepresentable.
