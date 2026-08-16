"""BM25 search over transcript segments.

Pure-Python and dependency-free by design: the corpus is tens of thousands of
short documents, which BM25 handles fine in memory, and avoiding a vector store
keeps the whole knowledge base reproducible from a git checkout plus a re-run.

Search exists to surface candidate evidence for human review. It does not
decide what is true; it decides what a reviewer should read next.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

_TOKEN_RE = re.compile(r"[a-z0-9']+")

# Common English words plus filler that dominates spoken-word transcripts.
_STOPWORDS = {
    "a", "about", "all", "also", "am", "an", "and", "any", "are", "as", "at", "be",
    "because", "been", "but", "by", "can", "do", "does", "for", "from", "get", "go",
    "going", "had", "has", "have", "he", "her", "here", "his", "how", "i", "if", "in",
    "into", "is", "it", "its", "just", "know", "like", "me", "more", "my", "no", "not",
    "now", "of", "ok", "okay", "on", "one", "or", "our", "out", "over", "right", "said",
    "say", "see", "she", "so", "some", "than", "that", "the", "their", "them", "then",
    "there", "these", "they", "this", "to", "too", "up", "us", "very", "was", "we",
    "well", "were", "what", "when", "where", "which", "who", "will", "with", "would",
    "you", "your", "yeah", "gonna", "want", "really", "think", "thing", "things",
}


def tokenize(text: str, *, drop_stopwords: bool = True) -> list[str]:
    toks = _TOKEN_RE.findall((text or "").lower())
    if drop_stopwords:
        return [t for t in toks if t not in _STOPWORDS]
    return toks


@dataclass
class Hit:
    segment_id: str
    video_id: str
    source_key: str
    start_s: float
    url: str
    score: float
    text: str
    video_title: str = ""

    def citation(self) -> str:
        return f"{self.video_id}@{int(self.start_s)}s"


class BM25Index:
    """Standard Okapi BM25."""

    def __init__(self, segments: Sequence[dict[str, Any]], *, k1: float = 1.5, b: float = 0.75):
        self.segments = list(segments)
        self.k1 = k1
        self.b = b
        self._postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        self._doc_len: list[int] = []
        self._build()

    def _build(self) -> None:
        for idx, seg in enumerate(self.segments):
            toks = tokenize(seg.get("text", ""))
            self._doc_len.append(len(toks))
            for term, tf in Counter(toks).items():
                self._postings[term].append((idx, tf))
        n = len(self.segments)
        self._avg_len = (sum(self._doc_len) / n) if n else 0.0
        self._n = n

    def _idf(self, term: str) -> float:
        df = len(self._postings.get(term, ()))
        if df == 0:
            return 0.0
        # BM25 probabilistic idf with the standard +0.5 smoothing, floored at a
        # small positive value so terms present in most documents still rank
        # above absent terms instead of contributing negative score.
        return max(1e-6, math.log((self._n - df + 0.5) / (df + 0.5) + 1.0))

    def search(
        self,
        query: str,
        *,
        top_k: int = 20,
        source_key: str | None = None,
        min_score: float = 0.0,
    ) -> list[Hit]:
        terms = tokenize(query, drop_stopwords=False)
        # Keep stopwords out of scoring but preserve multiword phrases like
        # "power of three", whose content words still discriminate.
        terms = [t for t in terms if t not in _STOPWORDS] or tokenize(query, drop_stopwords=False)
        if not terms:
            return []

        scores: dict[int, float] = defaultdict(float)
        for term in terms:
            idf = self._idf(term)
            if idf == 0.0:
                continue
            for idx, tf in self._postings[term]:
                dl = self._doc_len[idx] or 1
                denom = tf + self.k1 * (1 - self.b + self.b * dl / (self._avg_len or 1))
                scores[idx] += idf * (tf * (self.k1 + 1)) / denom

        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        hits: list[Hit] = []
        for idx, score in ranked:
            if score <= min_score:
                break
            seg = self.segments[idx]
            if source_key and seg.get("source_key") != source_key:
                continue
            hits.append(
                Hit(
                    segment_id=seg["segment_id"],
                    video_id=seg["video_id"],
                    source_key=seg.get("source_key", ""),
                    start_s=float(seg.get("start_s", 0.0)),
                    url=seg.get("url", ""),
                    score=round(score, 4),
                    text=seg.get("text", ""),
                    video_title=seg.get("video_title", ""),
                )
            )
            if len(hits) >= top_k:
                break
        return hits

    def search_any(
        self, queries: Iterable[str], *, top_k: int = 20, source_key: str | None = None
    ) -> list[Hit]:
        """Union of several alias queries, best score per segment wins."""
        best: dict[str, Hit] = {}
        for q in queries:
            for hit in self.search(q, top_k=top_k, source_key=source_key):
                prev = best.get(hit.segment_id)
                if prev is None or hit.score > prev.score:
                    best[hit.segment_id] = hit
        return sorted(best.values(), key=lambda h: h.score, reverse=True)[:top_k]
