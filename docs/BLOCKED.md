# Gate 1 cannot be reached: Apify and YouTube are blocked

**Status: Phase 0 complete. Phase 1 discovery has never run. `data/manifest.json`
does not exist. Zero videos have been discovered, zero transcripts fetched.**

## What was attempted

Both services this pipeline depends on are refused at the egress gateway, and
no Apify credential is present in the environment.

| Requirement | Result |
| --- | --- |
| `api.apify.com:443` | `403` to `CONNECT` — organization egress policy denial |
| `www.youtube.com:443` | `403` to `CONNECT` — organization egress policy denial |
| `APIFY_TOKEN` / `APIFY_API_TOKEN` | not set |
| `pypi.org`, `api.github.com` | reachable |

The proxy recorded the denials itself:

```json
{"kind": "connect_rejected",
 "detail": "gateway answered 403 to CONNECT (policy denial or upstream failure)",
 "host": "api.apify.com:443"}
```

A 403 on `CONNECT` is a policy decision, not a transient fault. The environment's
operating guidance is explicit that such denials are reported rather than
retried or routed around, so no workaround was attempted. `apify_runner.py`
encodes this distinction: transient faults retry with backoff, policy denials
raise `ApifyBlocked` immediately.

Reproduce the diagnosis at any time:

```bash
python -m scripts.verify_env      # exit 2 while blocked
```

## What this means for the gates

- **Gate 1** cannot produce real numbers. Video counts per bucket, NBB totals,
  runtime hours and Apify cost estimates all require enumeration to have run.
  Any figure presented for them now would be fabricated.
- **The actor bake-off** cannot run either, so `CHOSEN_TRANSCRIPT_ACTOR` in
  `scripts/config.py` is still `None`. Which of the four transcript actors to
  use is an open question that only a live test can answer, since the deciding
  factors are timestamp granularity and real cost per video.

## What was deliberately not done

No manifest was invented, no video IDs were guessed, and no rules were written
from general knowledge of ICT material.

Fabricated citations would be worse than an empty repository. An empty repo is
visibly unfinished; a fabricated one is indistinguishable from real research
until someone opens a video at the cited timestamp and finds nothing there.
Since the whole premise is that every rule traces to a video ID and timestamp,
inventing provenance would invert the goal rather than approximate it.

The channel IDs in `scripts/config.py` are recorded as `operator_supplied` with
`verified: False`. They came from the task brief, not from a live lookup, and
`verify_channels()` must confirm them before any paid run — including resolving
which of the two candidate NBBTRADER channels is the live one.

## Unblocking

1. **Allowlist the hosts.** `api.apify.com` is required. `www.youtube.com` is
   needed to verify channels by hand and to spot-check that a citation lands
   where it claims.

2. **Provide a token.**

   ```bash
   cp .env.example .env      # then paste your token
   # or: export APIFY_TOKEN=apify_api_...
   ```

3. **Preflight.**

   ```bash
   python -m scripts.verify_env
   ```

   Confirms the token, probes the enumeration actor and reports which of the
   four transcript candidates are reachable.

4. **Resolve the channels, then discover.**

   ```bash
   python -m scripts.discover --dry-run     # exercise plumbing, no spend
   python -m scripts.discover               # real enumeration
   ```

   `verify_channels()` runs first and writes `data/channel_probe.json` with
   sample titles from both NBBTRADER candidates. Confirm which is live and set
   `verified: True` before trusting the manifest.

5. **Bake off the transcript actors, then choose.**

   ```bash
   python -m scripts.actor_bakeoff
   ```

   Reports success, segment count, timestamp granularity and real cost per
   video for each candidate. An actor that returns one untimed block of text is
   unusable here at any price, because every citation would read 00:00:00.

## If Apify stays blocked

Apify is confined to `scripts/apify_runner.py` and the fetch functions in
`scripts/discover.py`. Everything downstream — bucket filtering, the manifest,
the models, rule extraction and verification — operates on plain JSON and does
not care how it was produced.

Any transcript source that can emit the `Transcript` shape in `scripts/models.py`
works unchanged, including a local `yt-dlp --write-auto-sub` run on a machine
with YouTube access. That is an ingestion-adapter change, not a rewrite.
