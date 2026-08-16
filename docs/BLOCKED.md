# Why the knowledge base is empty

**Status: ingestion has never run. The corpus contains zero videos and zero
segments. No claim or rule in this repository is derived from source material,
because no source material could be fetched.**

## What was attempted

The session that built this pipeline had no route to either service the task
depends on. Both hosts are refused at the egress gateway, and there is no Apify
credential in the environment.

| Requirement | Result |
| --- | --- |
| `api.apify.com:443` | `403` to `CONNECT` — organization egress policy denial |
| `www.youtube.com:443` | `403` to `CONNECT` — organization egress policy denial |
| `APIFY_TOKEN` / `APIFY_API_TOKEN` | not set |
| `pypi.org`, `api.github.com` | reachable |

The proxy recorded both denials itself:

```json
{"kind": "connect_rejected",
 "detail": "gateway answered 403 to CONNECT (policy denial or upstream failure)",
 "host": "api.apify.com:443"}
```

A 403 on `CONNECT` is a policy decision, not a transient fault. The environment's
own operating guidance is explicit that such denials must be reported rather
than retried or routed around, so no workaround was attempted.

You can reproduce the diagnosis at any time:

```bash
python -m ictkb doctor
```

## What was deliberately not done

The obvious way to produce a finished-looking deliverable here would have been
to write out a trading system from general knowledge of ICT concepts and attach
video IDs and timestamps to it.

That was not done, and the tooling is built to make it hard to do by accident.
Invented citations are worse than an empty repository: an empty repository is
visibly unfinished, whereas a fabricated one is indistinguishable from real
research until somebody opens a video at the cited timestamp and finds nothing
there. Since the entire premise of this project is that every claim traces to a
video ID and timestamp, fabricated provenance would not be a shortcut to the
goal — it would be the precise opposite of it.

Concretely, the following are absent by design:

- no claim files in `kb/claims/`
- no rule files in `kb/rules/`
- no transcript data in `data/`
- `system/TRADING_SYSTEM.md` reports itself as **not executable** and names
  every phase that has no sourced rule

`config/sources.yaml` carries `verified: false` on every source and actor for
the same reason: the channel handles and Apify actor IDs in it are conventional
guesses that could not be checked against a live service. `NBBTRADER` in
particular must be confirmed against the real channel before ingestion — several
similarly-named accounts exist, and ingesting the wrong one would attribute
another person's words to this source key.

## Unblocking

1. **Allowlist the hosts.** `api.apify.com` is required. `www.youtube.com` is
   not strictly required if all fetching happens through Apify's own
   infrastructure, but it is needed to verify channels by hand and to spot-check
   a citation by opening it.

2. **Provide a token.**

   ```bash
   export APIFY_TOKEN=apify_api_...   # console.apify.com/account/integrations
   ```

3. **Verify configuration, then flip the `verified` flags.**

   ```bash
   python -m ictkb doctor
   ```

   `doctor` confirms the token, probes each configured actor, and falls back
   through the alternates listed in `config/sources.yaml`. Fix anything it
   reports before spending money on a run — the channel scraper bills per video.

4. **Ingest, starting small.**

   ```bash
   python -m ictkb ingest --limit 25
   ```

   Inspect `data/derived/segments.jsonl` and confirm that timestamps in the
   `url` field actually land on the words in the `text` field. Transcript actors
   disagree about units, and a silent seconds/milliseconds error would misplace
   every citation in the corpus while still looking well-formed. Only scale up
   once a handful of URLs have been opened and checked by hand.

5. **Then follow `docs/PROVENANCE.md`** to turn segments into claims, claims
   into rules, and rules into the system.

## If Apify stays blocked

The pipeline's dependency on Apify is confined to `src/ictkb/apify.py` and the
two fetch functions in `src/ictkb/ingest.py`. Everything downstream — windowing,
search, claim grounding, validation, distillation — operates on
`data/derived/segments.jsonl` and does not care how that file was produced.

Any transcript source that can emit segments matching `schemas/segment.schema.json`
will work unchanged, including a local run of `yt-dlp --write-auto-sub` on a
machine that does have YouTube access. That substitution is a config and
ingestion-adapter change, not a rewrite.
