"""Select a working subset of the in-scope corpus.

471 ICT videos is 321 hours. Rule extraction over all of it is the most
expensive step in the project, and most of it is repetition — the same core
concepts taught many times. So Phase 2 runs on a prioritised subset, and
expands only if extraction shows real gaps.

Two ideas drive the ranking:

  * A video matching several buckets is usually a synthesis video — how the
    concepts combine — which is worth more than another single-concept
    explainer.
  * Newer material supersedes older. The brief resolves contradictions by
    recency, so seeding the corpus with recent teaching means fewer
    contradictions to resolve later.

Selection is stratified before it is ranked. A pure top-N by score would fill
the subset with Smart Money Concepts (186 videos) and starve Inversion FVG
(51), leaving the system unable to say anything about a bucket the operator
explicitly asked for.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Scored:
    video: dict
    score: float
    reason: str


def recency_score(position: int, total: int) -> float:
    """0..1 from enumeration position.

    Channel listings come back newest-first, so position is a reliable recency
    proxy. It is used instead of upload_date because flat enumeration does not
    return dates, and fetching them would mean opening every video page — the
    request type that gets challenged.
    """
    if total <= 1:
        return 1.0
    return 1.0 - (position / (total - 1))


def score_video(video: dict, total: int) -> Scored:
    buckets = video.get("buckets") or []
    position = int(video.get("position", 0))

    breadth = len(buckets)
    rec = recency_score(position, total)

    # Breadth dominates; recency breaks ties. A 3-bucket video always outranks
    # a 1-bucket video however new the latter is.
    score = breadth * 10.0 + rec * 5.0

    # Very short videos rarely contain a full teaching sequence.
    duration = video.get("duration_seconds") or 0
    if 0 < duration < 300:
        score -= 4.0

    return Scored(video=video, score=round(score, 3),
                  reason=f"{breadth} buckets, recency {rec:.2f}")


def select(
    videos: list[dict],
    target: int = 150,
    per_bucket_floor: int = 12,
    bucket_keys: list[str] | None = None,
) -> tuple[list[dict], dict[str, int]]:
    """Pick `target` videos, guaranteeing every bucket is represented.

    Returns the selection and a per-bucket count so coverage is auditable
    rather than assumed.
    """
    if not videos:
        return [], {}

    total = len(videos)
    scored = sorted((score_video(v, total) for v in videos),
                    key=lambda s: s.score, reverse=True)

    all_buckets = bucket_keys or sorted(
        {b for v in videos for b in (v.get("buckets") or [])}
    )

    chosen: dict[str, dict] = {}

    # Pass 1 — floor per bucket, best-scoring first.
    for bucket in all_buckets:
        taken = 0
        for s in scored:
            if taken >= per_bucket_floor:
                break
            if bucket in (s.video.get("buckets") or []):
                vid = s.video["video_id"]
                if vid not in chosen:
                    chosen[vid] = s.video
                taken += 1

    # Pass 2 — fill remaining slots by score.
    for s in scored:
        if len(chosen) >= target:
            break
        chosen.setdefault(s.video["video_id"], s.video)

    selection = list(chosen.values())

    # If the floors alone overshot the target, trim by score but never below
    # one video per bucket — losing a bucket entirely is worse than overshooting.
    if len(selection) > target:
        order = {s.video["video_id"]: s.score for s in scored}
        selection.sort(key=lambda v: order.get(v["video_id"], 0), reverse=True)
        kept, seen_buckets = [], set()
        for v in selection:
            if len(kept) < target:
                kept.append(v)
                seen_buckets.update(v.get("buckets") or [])
        missing = [b for b in all_buckets if b not in seen_buckets]
        for b in missing:
            for v in selection:
                if b in (v.get("buckets") or []) and v not in kept:
                    kept.append(v)
                    break
        selection = kept

    coverage: dict[str, int] = {b: 0 for b in all_buckets}
    for v in selection:
        for b in (v.get("buckets") or []):
            coverage[b] = coverage.get(b, 0) + 1

    return selection, coverage
