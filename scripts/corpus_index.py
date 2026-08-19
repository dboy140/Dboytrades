"""Window the transcripts and search them.

Two jobs:

1. Merge the fine-grained caption cues (~2.2s each) into overlapping windows.
   A cue is too short to be a citable unit -- "welcome back folks this is" is
   not a claim. Windows are the unit a rule cites, and they overlap so a
   sentence spanning a boundary is still quotable as one contiguous string.

2. BM25 over those windows, so extraction reads the passages that discuss a
   concept instead of all 734,000 words.

Search decides what a human reads next. It does not decide what is true.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

WINDOW_SECONDS = 45
OVERLAP_SECONDS = 15

_TOKEN = re.compile(r"[a-z0-9']+")

_STOP = {
    "a", "about", "all", "also", "am", "an", "and", "any", "are", "as", "at",
    "be", "because", "been", "but", "by", "can", "do", "does", "for", "from",
    "get", "go", "going", "had", "has", "have", "he", "her", "here", "his",
    "how", "i", "if", "in", "into", "is", "it", "its", "just", "know", "like",
    "me", "more", "my", "no", "not", "now", "of", "ok", "okay", "on", "one",
    "or", "our", "out", "over", "right", "said", "say", "see", "she", "so",
    "some", "than", "that", "the", "their", "them", "then", "there", "these",
    "they", "this", "to", "too", "up", "us", "very", "was", "we", "well",
    "were", "what", "when", "where", "which", "who", "will", "with", "would",
    "you", "your", "yeah", "gonna", "want", "really", "think", "thing",
    "things", "were", "got", "let", "come", "look", "back", "little", "im",
    "dont", "thats", "youre", "were", "cant", "were", "ive", "its",
}


@dataclass
class Window:
    window_id: str
    video_id: str
    title: str
    channel: str
    buckets: list[str]
    caption_kind: str
    start_s: float
    end_s: float
    text: str

    @property
    def url(self) -> str:
        return f"https://youtu.be/{self.video_id}?t={int(self.start_s)}"

    @property
    def timestamp(self) -> str:
        t = int(self.start_s)
        return f"{t//3600:02d}:{(t%3600)//60:02d}:{t%60:02d}"


def tokenize(text: str, drop_stop: bool = True) -> list[str]:
    toks = _TOKEN.findall((text or "").lower())
    return [t for t in toks if t not in _STOP] if drop_stop else toks


def build_windows(record: dict,
                  window_seconds: int = WINDOW_SECONDS,
                  overlap_seconds: int = OVERLAP_SECONDS) -> list[Window]:
    segs = sorted(record.get("segments") or [], key=lambda s: s["start_seconds"])
    if not segs:
        return []
    stride = window_seconds - overlap_seconds
    if stride <= 0:
        raise ValueError("overlap must be smaller than the window")

    out: list[Window] = []
    seen: set[str] = set()
    i, n = 0, len(segs)
    while i < n:
        start = float(segs[i]["start_seconds"])
        end = start + window_seconds
        chunk = []
        j = i
        while j < n and float(segs[j]["start_seconds"]) < end:
            chunk.append(segs[j])
            j += 1
        text = re.sub(r"\s+", " ", " ".join(c["text"] for c in chunk)).strip()
        if text:
            wid = f"{record['id']}:{int(round(start * 1000))}"
            if wid not in seen:
                seen.add(wid)
                out.append(Window(
                    window_id=wid, video_id=record["id"],
                    title=record.get("title", ""), channel=record.get("channel", ""),
                    buckets=list(record.get("buckets") or []),
                    caption_kind=record.get("caption_kind", "unknown"),
                    start_s=round(start, 2),
                    end_s=round(float(chunk[-1]["start_seconds"]), 2),
                    text=text,
                ))
        nxt = start + stride
        k = i + 1
        while k < n and float(segs[k]["start_seconds"]) < nxt:
            k += 1
        i = k
    return out


def load_corpus(directory: str | Path = "data/transcripts") -> list[Window]:
    windows: list[Window] = []
    for p in sorted(Path(directory).glob("*.json")):
        windows += build_windows(json.loads(p.read_text()))
    return windows


class BM25:
    def __init__(self, windows: list[Window], k1: float = 1.5, b: float = 0.75):
        self.windows = windows
        self.k1, self.b = k1, b
        self._post: dict[str, list[tuple[int, int]]] = defaultdict(list)
        self._len: list[int] = []
        for idx, w in enumerate(windows):
            toks = tokenize(w.text)
            self._len.append(len(toks))
            for term, tf in Counter(toks).items():
                self._post[term].append((idx, tf))
        self._n = len(windows)
        self._avg = (sum(self._len) / self._n) if self._n else 0.0

    def _idf(self, term: str) -> float:
        df = len(self._post.get(term, ()))
        if df == 0:
            return 0.0
        return max(1e-6, math.log((self._n - df + 0.5) / (df + 0.5) + 1.0))

    def search(self, query: str, top_k: int = 20,
               bucket: str | None = None,
               video_id: str | None = None) -> list[tuple[Window, float]]:
        terms = [t for t in tokenize(query, drop_stop=False) if t not in _STOP]
        terms = terms or tokenize(query, drop_stop=False)
        if not terms:
            return []
        scores: dict[int, float] = defaultdict(float)
        for term in terms:
            idf = self._idf(term)
            if idf == 0.0:
                continue
            for idx, tf in self._post[term]:
                dl = self._len[idx] or 1
                denom = tf + self.k1 * (1 - self.b + self.b * dl / (self._avg or 1))
                scores[idx] += idf * (tf * (self.k1 + 1)) / denom

        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        out: list[tuple[Window, float]] = []
        for idx, sc in ranked:
            w = self.windows[idx]
            if bucket and bucket not in w.buckets:
                continue
            if video_id and w.video_id != video_id:
                continue
            out.append((w, round(sc, 3)))
            if len(out) >= top_k:
                break
        return out

    def search_any(self, queries: Iterable[str], top_k: int = 20,
                   bucket: str | None = None) -> list[tuple[Window, float]]:
        """Union over alias queries, best score per window, then de-overlapped.

        Overlapping windows from the same moment are near-duplicates; keeping
        both wastes reading budget on the same passage twice.
        """
        best: dict[str, tuple[Window, float]] = {}
        for q in queries:
            for w, sc in self.search(q, top_k=top_k * 3, bucket=bucket):
                prev = best.get(w.window_id)
                if prev is None or sc > prev[1]:
                    best[w.window_id] = (w, sc)

        ordered = sorted(best.values(), key=lambda p: p[1], reverse=True)
        kept: list[tuple[Window, float]] = []
        claimed: dict[str, list[float]] = defaultdict(list)
        for w, sc in ordered:
            if any(abs(w.start_s - s) < WINDOW_SECONDS for s in claimed[w.video_id]):
                continue
            claimed[w.video_id].append(w.start_s)
            kept.append((w, sc))
            if len(kept) >= top_k:
                break
        return kept
