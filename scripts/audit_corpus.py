"""Audit fetched transcripts for quality and misattribution.

Guest-appearance search is the weak point of the pipeline: it matches on the
token "NBB", and that token is not unique to NBBTRADER. Anything it lets
through ends up in the corpus as if NBB said it, so the corpus is audited
before extraction rather than trusted.

Three failure modes seen in the real 2026-08-19 fetch:

  * an unrelated podcast that abbreviates to NBB ("Northern Border Banter")
  * ad/spam clips a few seconds long that merely name-drop a course
  * third-party commentary and foreign-language reaction videos ABOUT him,
    which are someone else's words, not his
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Frequent English function words. A genuine English transcript is dense with
# these; another language is not.
_EN = {
    "the", "and", "that", "you", "this", "for", "with", "have", "not", "are",
    "was", "but", "what", "when", "your", "just", "going", "would", "there",
    "they", "here", "were", "from", "will", "about", "into", "then", "than",
}

# A caption track with real punctuation and capitalisation was written by a
# human; auto-generated tracks are flat lowercase with no sentence marks.
_SENTENCE_END = re.compile(r"[.!?]")


@dataclass
class Finding:
    video_id: str
    title: str
    channel: str
    segments: int
    flags: list[str] = field(default_factory=list)
    english_ratio: float = 0.0
    caption_kind: str = "unknown"

    @property
    def verdict(self) -> str:
        if any(f in self.flags for f in ("too_short", "not_english", "acronym_collision")):
            return "reject"
        if "third_party_commentary" in self.flags:
            return "review"
        return "keep"


def english_ratio(segments: list[dict], sample: int = 400) -> float:
    words: list[str] = []
    for s in segments[:sample]:
        words += re.findall(r"[a-z']+", (s.get("text") or "").lower())
    if not words:
        return 0.0
    return sum(1 for w in words if w in _EN) / len(words)


def detect_caption_kind(segments: list[dict], sample: int = 200) -> str:
    """Infer manual vs auto captions.

    The Apify actor does not report which it returned, and it matters: auto
    tracks mis-transcribe trading jargon, so a claim resting only on them
    cannot carry top confidence.
    """
    texts = [(s.get("text") or "") for s in segments[:sample]]
    if not texts:
        return "unknown"
    joined = " ".join(texts)
    if not joined.strip():
        return "unknown"
    punctuation = len(_SENTENCE_END.findall(joined)) / max(1, len(texts))
    uppercase = sum(1 for t in texts if t[:1].isupper()) / len(texts)
    # Auto tracks are essentially punctuation-free and uncapitalised.
    if punctuation < 0.05 and uppercase < 0.15:
        return "auto"
    if punctuation > 0.2 or uppercase > 0.4:
        return "manual"
    return "unknown"


# Channels whose name collides with the NBB acronym but are unrelated.
ACRONYM_COLLISIONS = ("northern border banter",)

# Phrasing that marks a video as being ABOUT him rather than BY him.
COMMENTARY_MARKERS = (
    "scam or legit", "exposing", "fake guru", "review of", "reaction",
    "is he legit", "truth about",
)


def audit_record(rec: dict, min_segments: int = 50, min_english: float = 0.10) -> Finding:
    segments = rec.get("segments") or []
    channel = str(rec.get("channel") or "")
    title = str(rec.get("title") or "")

    f = Finding(
        video_id=rec.get("id", ""),
        title=title,
        channel=channel,
        segments=len(segments),
        english_ratio=round(english_ratio(segments), 3),
        caption_kind=detect_caption_kind(segments),
    )

    if len(segments) < min_segments:
        f.flags.append("too_short")
    if f.english_ratio < min_english:
        f.flags.append("not_english")
    if any(c in channel.lower() for c in ACRONYM_COLLISIONS):
        f.flags.append("acronym_collision")
    low = f"{title.lower()} {channel.lower()}"
    if any(m in low for m in COMMENTARY_MARKERS):
        f.flags.append("third_party_commentary")

    return f


def audit(records: list[dict]) -> list[Finding]:
    return [audit_record(r) for r in records]
