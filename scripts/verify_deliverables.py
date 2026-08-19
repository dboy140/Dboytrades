"""Phase 6 verification.

Checks the finished deliverables against the brief's acceptance criteria,
including the one that is easiest to violate by accident: transcript text
leaking into a deliverable. Ground rule 3 requires paraphrase, so any long
verbatim run from the corpus is a defect even when it is well-intentioned.
"""

from __future__ import annotations

import glob
import json
import random
import re
from pathlib import Path

NGRAM = 12  # a run this long is a transcript block, not an attributed phrase


def _norm(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", (text or "").lower())


def corpus_ngrams(directory: str = "data/transcripts", n: int = NGRAM) -> set[tuple]:
    grams: set[tuple] = set()
    for p in glob.glob(f"{directory}/*.json"):
        rec = json.loads(Path(p).read_text())
        words = _norm(" ".join(s["text"] for s in rec.get("segments") or []))
        for i in range(len(words) - n + 1):
            grams.add(tuple(words[i:i + n]))
    return grams


def find_leaks(path: str, grams: set[tuple], n: int = NGRAM) -> list[str]:
    words = _norm(Path(path).read_text())
    hits = []
    for i in range(len(words) - n + 1):
        if tuple(words[i:i + n]) in grams:
            hits.append(" ".join(words[i:i + n]))
    return hits


def spot_check(rules: list[dict], k: int = 10, seed: int = 7) -> list[dict]:
    """Pick k citations at random and resolve each against the corpus."""
    from scripts.verify_rules import load_corpus, nearest_gap, timestamp_seconds

    corpus = load_corpus()
    pairs = [(r, s) for r in rules for s in r["sources"]]
    random.Random(seed).shuffle(pairs)
    out = []
    for r, s in pairs[:k]:
        info = corpus.get(s["video_id"])
        secs = timestamp_seconds(s["timestamp"])
        gap = nearest_gap(info["starts"], float(secs)) if info else float("inf")
        runtime = (info or {}).get("duration") or (info or {}).get("last") or 0
        out.append({
            "rule_id": r["rule_id"], "video_id": s["video_id"],
            "timestamp": s["timestamp"], "link": s["link"],
            "in_corpus": info is not None,
            "within_runtime": bool(runtime and secs <= runtime + 60),
            "nearest_cue_gap_s": round(gap, 2) if gap != float("inf") else None,
            "caption_kind": (info or {}).get("caption_kind"),
        })
    return out


def setup_completeness(engine: dict) -> list[dict]:
    """Tier A and B setups must each have a stop, a target and an invalidation."""
    out = []
    for s in engine["phases"]["setup_pattern"]["setups"]:
        out.append({
            "setup": s["setup"], "tier": s["tier"],
            "has_stop": bool(s.get("stop")),
            "has_target": bool(s.get("target")),
            "has_invalidation": bool(s.get("invalidation")),
        })
    return out
