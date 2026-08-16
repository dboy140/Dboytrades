"""Assign ICT videos to the eight in-scope topic buckets.

Matching is word-boundary aware rather than plain substring, which matters more
than it looks. A naive `"FVG" in title` test would pull every Inversion Fair
Value Gap video into the plain Fair Value Gaps bucket via the substring inside
"IFVG", and would match "SMC" inside unrelated words. Word boundaries keep the
two FVG buckets genuinely distinct.

Every match records which keyword fired, so the operator can audit the filter
rather than trust it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

from . import config as cfg


@dataclass
class BucketMatch:
    bucket_key: str
    matched_keywords: list[str] = field(default_factory=list)
    matched_in: list[str] = field(default_factory=list)  # "title" | "description"


def _build_pattern(keyword: str) -> re.Pattern[str]:
    """Word-boundary regex for one keyword, tolerating plurals.

    The trailing `s?` is load-bearing: without it "fair value gap" fails to
    match the very common title form "Fair Value Gaps", and the closing
    boundary makes that a silent miss rather than an obvious one. Whitespace
    between words is flexible for the same reason.
    """
    words = keyword.split()
    escaped = r"\s+".join(re.escape(w) for w in words)
    return re.compile(rf"(?<!\w){escaped}s?(?!\w)", re.IGNORECASE)


@lru_cache(maxsize=1)
def _compiled() -> list[tuple[str, list[tuple[str, re.Pattern[str]]]]]:
    """Compile every bucket keyword into a word-boundary regex, once."""
    out: list[tuple[str, list[tuple[str, re.Pattern[str]]]]] = []
    for bucket in cfg.ICT_BUCKETS:
        pats: list[tuple[str, re.Pattern[str]]] = []
        for kw in bucket.all_keywords:
            pats.append((kw, _build_pattern(kw)))
        out.append((bucket.key, pats))
    return out


def match_buckets(title: str, description: str = "") -> list[BucketMatch]:
    """Return every bucket this video belongs to, with the evidence for each."""
    title = title or ""
    description = description or ""
    results: list[BucketMatch] = []

    for bucket_key, patterns in _compiled():
        hit_keywords: list[str] = []
        hit_fields: set[str] = set()
        for kw, pat in patterns:
            if pat.search(title):
                hit_keywords.append(kw)
                hit_fields.add("title")
            elif pat.search(description):
                hit_keywords.append(kw)
                hit_fields.add("description")
        if hit_keywords:
            results.append(
                BucketMatch(
                    bucket_key=bucket_key,
                    matched_keywords=sorted(set(hit_keywords)),
                    matched_in=sorted(hit_fields),
                )
            )
    return results


def bucket_keys(title: str, description: str = "") -> list[str]:
    return [m.bucket_key for m in match_buckets(title, description)]


def is_in_scope(title: str, description: str = "") -> bool:
    return bool(match_buckets(title, description))


def find_adjacent_concepts(text: str) -> list[str]:
    """Adjacent concepts mentioned in an in-scope video.

    These are captured as supporting context inside that video's notes. They
    never justify hunting down a separate video, per the scope rules.
    """
    found: list[str] = []
    for concept in cfg.ADJACENT_CONCEPTS:
        escaped = r"\s+".join(re.escape(p) for p in concept.split())
        if re.search(rf"(?<!\w){escaped}(?!\w)", text or "", re.IGNORECASE):
            found.append(concept)
    return found
