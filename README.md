# Dboytrades

A citable knowledge base and rule distiller for ICT (Inner Circle Trader) and
NBBTRADER YouTube content.

The goal is one executable trading system with machine-readable rules, where
every rule traces back to a specific video ID and timestamp — and where that
traceability is enforced by tooling rather than trusted to discipline.

---

## Status: pipeline built, knowledge base empty

**No source material has been ingested. There are zero videos, zero segments,
zero claims and zero rules in this repository.**

The environment this was built in has no route to the services the task depends
on. Both are refused at the egress gateway, and no Apify credential is present:

| Requirement | Result |
| --- | --- |
| `api.apify.com:443` | `403` to `CONNECT` — organization egress policy denial |
| `www.youtube.com:443` | `403` to `CONNECT` — organization egress policy denial |
| `APIFY_TOKEN` | not set |

A trading system was **not** written from general knowledge and dressed in
plausible citations. Fabricated provenance would defeat the entire point of the
project: it is indistinguishable from real research until someone opens a video
at the cited timestamp and finds nothing there. `system/TRADING_SYSTEM.md`
therefore reports itself as not executable and names every phase that has no
sourced rule.

See **[docs/BLOCKED.md](docs/BLOCKED.md)** for the full diagnosis and the steps
to unblock. Diagnose it yourself at any time with `python -m ictkb doctor`.

---

## What is here

Everything except the data. The pipeline runs end to end the moment egress and a
token exist.

```
config/     sources, actors, and the concept vocabulary used to mine transcripts
schemas/    JSON Schema for segments, claims and rules
src/ictkb/  the pipeline
kb/         claims and rules  (empty — this is the reviewed, durable artifact)
data/       raw and derived corpora  (gitignored, re-fetchable)
system/     compiled output
docs/       provenance rules, blocker report, file templates
tests/      73 tests, all passing
```

## Install

```bash
pip install -e .          # or: pip install -r requirements.txt
export APIFY_TOKEN=apify_api_...
```

## Commands

```bash
python -m ictkb doctor              # check token, egress and actor availability
python -m ictkb ingest --limit 25   # channels -> videos -> transcripts -> segments
python -m ictkb search "liquidity"  # BM25 over the corpus, returns id@timestamp
python -m ictkb mine --concept liquidity   # candidate evidence per concept
python -m ictkb validate            # enforce provenance; non-zero exit on failure
python -m ictkb distill             # compile accepted rules into the system
```

Run `doctor` before `ingest`. The channel scraper bills per video, and `doctor`
catches a wrong actor ID or an unverified channel before it costs anything.

## How provenance is enforced

```
caption cue -> segment -> claim -> rule -> system
                  |         |        |
           video_id +   verbatim  derived_from
           timestamp     quote    (>= 1 claim)
```

The load-bearing check is that an evidence `quote` must appear **verbatim** in
the transcript segment it cites. Paraphrasing fails exactly as loudly as
inventing, which is the point — a paraphrase is where a claim quietly becomes
the author's opinion wearing the source's name.

Validation also catches evidence pointing at segments that are not in the
corpus, claims edited without regenerating their content-addressed ID, rules
citing claims that do not exist, rules accepted on top of unresolved
contradictions, and numeric parameters that were chosen rather than sourced.

`validate` exits non-zero on any of these, and `distill` refuses to compile a
system that fails validation. Full detail in
**[docs/PROVENANCE.md](docs/PROVENANCE.md)**.

## Design notes

**The corpus is disposable; the knowledge base is not.** `data/` is gitignored
because it can be re-fetched. `kb/` is tracked because it holds human judgement
that cannot be regenerated.

**Segments overlap.** Captions are merged into 45-second windows on a 30-second
stride, so a sentence spanning a window boundary is still quotable as one
contiguous string — necessary because grounding requires a quote to live inside
a single segment.

**Time units are treated as hostile.** Transcript actors disagree about field
names and about seconds versus milliseconds. A silent 1000x error would misplace
every citation in the corpus while leaving it perfectly well-formed, so cue
parsing is explicit and anything ambiguous is dropped with a warning rather than
guessed at. Spot-check real timestamps by hand after the first ingest.

**Search is BM25, not embeddings.** The corpus is many short documents, which
BM25 handles well, and it keeps the whole knowledge base reproducible from a git
checkout plus a re-run. Search surfaces what a reviewer should read next; it
does not decide what is true.

**Apify is confined to one module.** `src/ictkb/apify.py` and two functions in
`ingest.py` are the only Apify-aware code. Anything that can produce segments
matching `schemas/segment.schema.json` — including a local `yt-dlp` run — works
downstream unchanged.

## Tests

```bash
python -m pytest -q
```

All transcript text in the test suite is synthetic filler invented for the
tests. It quotes no real creator.
