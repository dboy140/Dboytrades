# Provenance rules

One invariant governs this repository:

> Every rule in the distilled system traces, mechanically, to a specific person
> saying a specific thing at a specific timestamp in a specific video.

"Mechanically" is the operative word. This is not a documentation convention
that reviewers are trusted to follow — it is a chain of checks that fails the
build when it is broken.

## The chain

```
caption cue  ->  segment  ->  claim  ->  rule  ->  system
                    |           |         |
             video_id +     verbatim   derived_from
             timestamp       quote      (>= 1 claim)
```

Each link is enforced in `src/ictkb/validate.py`:

| Link | Check | On failure |
| --- | --- | --- |
| segment exists | evidence `segment_id` resolves in the corpus | `evidence_segment_missing` — error |
| quote is real | quote appears verbatim in that segment's text | `quote_not_grounded` — error |
| video matches | evidence `video_id` equals the segment's | `evidence_video_mismatch` — error |
| claim is intact | content hash matches the stored `claim_id` | `claim_id_mismatch` — error |
| rule is grounded | `derived_from` is non-empty and resolves | `rule_ungrounded` / `rule_claim_missing` — error |
| conflict resolved | accepted rules rest on uncontradicted claims | `accepted_on_contradiction` — error |

`python -m ictkb validate` exits non-zero if any error is present, and
`python -m ictkb distill` refuses to compile a system that fails validation.

## Why quotes must be verbatim

The grounding check is a plain substring test after whitespace and case
normalisation. Wording is never normalised beyond that, which means paraphrasing
inside an evidence `quote` field fails exactly as loudly as inventing one.

This is deliberate. A paraphrase is where a claim quietly becomes the KB
author's opinion wearing the source's name, and it is the failure mode that
looks most like diligence. Put the paraphrase in `statement`, where it is
labelled as yours; put the source's actual words in `quote`.

## Confidence

| Level | Meaning |
| --- | --- |
| `high` | Stated explicitly and unambiguously, in a manually-captioned segment. |
| `medium` | Stated explicitly but resting on auto-captions, or assembled from several segments. |
| `low` | Inferred from what was said rather than stated. Never the sole basis for an accepted rule. |

Auto-generated captions routinely mangle trading jargon, so a `high` confidence
claim resting only on `caption_kind: auto` segments raises
`high_confidence_auto_captions`. Either re-check the passage against the video
and correct the quote, or drop to `medium`.

## Numbers

Numeric parameters are where unsourced material enters most easily, because a
number looks equally authoritative whether it was taught or chosen. Every
numeric value in a rule's `then.params` must either be traceable to a quote, or
be listed in `unsourced_params`.

```json
"then": { "action": "size_position", "params": { "risk_pct": 0.5 } },
"unsourced_params": ["risk_pct"]
```

That declaration is not an admission of sloppiness — it is the honest labelling
that lets a reader tell a sourced threshold from an engineering default. The
validator warns about undeclared numbers on accepted rules
(`param_provenance_unclear`).

## Contradictions

Sources contradict themselves across years of content, and two sources
contradict each other. When you find a genuine conflict, record it in the
claim's `contradicts` array rather than silently picking a winner.

An accepted rule resting on a claim with a non-empty `contradicts` array is an
error. Resolve the conflict first — decide which reading is right, write down
why in the rule's `notes`, and clear the array — so that the choice is visible
rather than implicit.

## Review status

Claims carry an extraction method:

- `human` — a person read the segment and wrote the claim.
- `llm_assisted` — drafted by a model, checked by a person (set `reviewer`).
- `llm_proposed` — drafted by a model, unreviewed. **The distiller ignores
  these**, and validation warns while they lack a reviewer.

The intended workflow is that `mine` produces candidates, a model drafts
`llm_proposed` claims, and a human promotes them to `llm_assisted` or `human`
after opening the timestamps. Grounding is checked mechanically either way, but
a grounded quote can still be a misleading claim — the check proves the words
were said, not that the interpretation is fair.

## Workflow

```bash
# 1. surface candidate evidence per concept
python -m ictkb mine --concept liquidity --top 20

# 2. open the URLs, read the segments, write claim JSON into kb/claims/
#    (see docs/examples/claim.example.json)

# 3. write rule JSON into kb/rules/, citing those claim ids
#    (see docs/examples/rule.example.json)

# 4. enforce the chain
python -m ictkb validate

# 5. compile
python -m ictkb distill
```

Steps 2 and 3 are human work by design. The tooling finds evidence and proves
citations are real; it does not decide what the sources meant.
