"""Turn raw transcript payloads into stable, citable segments.

Transcript actors on the Apify store disagree about field names and time units,
and the pipeline must not silently mis-time a citation because an actor emitted
milliseconds where seconds were assumed — a 1000x timing error would point every
quote at the wrong moment in the video while still looking well-formed. So cue
parsing is explicit and defensive, and anything unparseable is dropped loudly
rather than coerced into a plausible-looking number.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, asdict
from typing import Any, Iterable, Sequence

log = logging.getLogger(__name__)

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

_URL_ID_PATTERNS = (
    re.compile(r"(?:youtube\.com/watch\?(?:.*&)?v=)([A-Za-z0-9_-]{11})"),
    re.compile(r"(?:youtu\.be/)([A-Za-z0-9_-]{11})"),
    re.compile(r"(?:youtube\.com/(?:embed|shorts|live)/)([A-Za-z0-9_-]{11})"),
)

# Candidate field names, most explicit first.
_TEXT_FIELDS = ("text", "snippet", "caption", "content", "line")
_START_FIELDS_MS = ("startMs", "start_ms", "offsetMs", "offset_ms", "tStartMs")
_START_FIELDS_S = ("start", "startTime", "start_time", "offset", "startSeconds", "begin")
_DUR_FIELDS_MS = ("durationMs", "duration_ms", "dur_ms")
_DUR_FIELDS_S = ("duration", "dur", "durationSeconds", "length")

# A single caption cue longer than this is almost certainly a unit error
# (milliseconds read as seconds) rather than a genuinely long cue.
_MAX_PLAUSIBLE_CUE_SECONDS = 120.0
# Seconds value above which an integer is far more likely to be milliseconds:
# 10 hours. Longer real videos exist, but not with cue starts this large in a
# field that also lacks an explicit unit suffix.
_MS_HEURISTIC_THRESHOLD = 36_000


class NormalizeError(ValueError):
    pass


@dataclass(frozen=True)
class Cue:
    start_s: float
    end_s: float
    text: str


@dataclass(frozen=True)
class Segment:
    segment_id: str
    video_id: str
    source_key: str
    start_s: float
    end_s: float
    text: str
    url: str
    caption_kind: str
    video_title: str = ""
    published_at: str | None = None
    language: str = "en"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def extract_video_id(value: str | None) -> str | None:
    """Pull an 11-char video ID out of a bare ID or any common YouTube URL form."""
    if not value:
        return None
    value = value.strip()
    if VIDEO_ID_RE.match(value):
        return value
    for pat in _URL_ID_PATTERNS:
        m = pat.search(value)
        if m:
            return m.group(1)
    return None


def timestamp_url(video_id: str, start_s: float) -> str:
    return f"https://www.youtube.com/watch?v={video_id}&t={int(start_s)}s"


def _first_present(d: dict[str, Any], keys: Sequence[str]) -> tuple[str, Any] | None:
    for k in keys:
        if k in d and d[k] is not None and d[k] != "":
            return k, d[k]
    return None


def _to_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            # Some actors emit "00:01:23.400"
            parts = value.strip().split(":")
            try:
                nums = [float(p) for p in parts]
            except ValueError:
                return None
            total = 0.0
            for n in nums:
                total = total * 60 + n
            return total
    return None


def parse_cue(raw: dict[str, Any]) -> Cue | None:
    """Parse one caption cue, or return None if it cannot be trusted."""
    text_hit = _first_present(raw, _TEXT_FIELDS)
    if not text_hit:
        return None
    text = str(text_hit[1]).strip()
    if not text:
        return None

    start_s: float | None = None
    ms_hit = _first_present(raw, _START_FIELDS_MS)
    if ms_hit:
        v = _to_float(ms_hit[1])
        start_s = v / 1000.0 if v is not None else None
    else:
        s_hit = _first_present(raw, _START_FIELDS_S)
        if s_hit:
            v = _to_float(s_hit[1])
            if v is not None:
                # Unsuffixed field: infer the unit. Documented heuristic, applied
                # only to integral values, since fractional seconds are already
                # unambiguous.
                if v > _MS_HEURISTIC_THRESHOLD and float(v).is_integer():
                    log.debug("treating start=%s as milliseconds", v)
                    start_s = v / 1000.0
                else:
                    start_s = v
    if start_s is None or start_s < 0:
        return None

    dur_s: float | None = None
    dms = _first_present(raw, _DUR_FIELDS_MS)
    if dms:
        v = _to_float(dms[1])
        dur_s = v / 1000.0 if v is not None else None
    else:
        ds = _first_present(raw, _DUR_FIELDS_S)
        if ds:
            v = _to_float(ds[1])
            if v is not None:
                dur_s = v / 1000.0 if v > _MAX_PLAUSIBLE_CUE_SECONDS else v

    if dur_s is None or dur_s <= 0:
        dur_s = 3.0  # conservative default; end_s is advisory, start_s is the citation anchor
    dur_s = min(dur_s, _MAX_PLAUSIBLE_CUE_SECONDS)

    return Cue(start_s=start_s, end_s=start_s + dur_s, text=text)


def parse_cues(raw_cues: Iterable[dict[str, Any]]) -> list[Cue]:
    cues: list[Cue] = []
    dropped = 0
    for raw in raw_cues:
        if not isinstance(raw, dict):
            dropped += 1
            continue
        cue = parse_cue(raw)
        if cue is None:
            dropped += 1
            continue
        cues.append(cue)
    if dropped:
        log.warning("dropped %d unparseable caption cues", dropped)
    cues.sort(key=lambda c: c.start_s)
    return cues


def clean_text(text: str) -> str:
    """Normalise caption noise without altering wording.

    Only whitespace, bracketed sound tags and stray HTML entities are touched.
    Words are never rewritten: quotes stored in the KB must remain verbatim
    against what the source actually said.
    """
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&#39;|&apos;", "'", text)
    text = re.sub(r"&quot;", '"', text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"\[(?:music|applause|laughter|inaudible)[^\]]*\]", " ", text, flags=re.I)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_for_match(text: str) -> str:
    """Canonical form used when checking a quote against a segment."""
    return re.sub(r"\s+", " ", text or "").strip().lower()


def build_segments(
    *,
    video_id: str,
    source_key: str,
    cues: Sequence[Cue],
    window_seconds: int,
    overlap_seconds: int,
    caption_kind: str = "unknown",
    video_title: str = "",
    published_at: str | None = None,
    language: str = "en",
) -> list[Segment]:
    """Merge cues into overlapping windows.

    Overlap matters: a sentence that straddles a window boundary would otherwise
    be unquotable as a contiguous string, and the grounding check requires quotes
    to live inside a single segment.
    """
    if not VIDEO_ID_RE.match(video_id):
        raise NormalizeError(f"invalid video id {video_id!r}")
    stride = window_seconds - overlap_seconds
    if stride <= 0:
        raise NormalizeError(
            f"overlap {overlap_seconds}s must be smaller than window {window_seconds}s"
        )
    if not cues:
        return []

    segments: list[Segment] = []
    seen_ids: set[str] = set()
    i = 0
    n = len(cues)

    while i < n:
        window_start = cues[i].start_s
        window_end = window_start + window_seconds
        chunk: list[Cue] = []
        j = i
        while j < n and cues[j].start_s < window_end:
            chunk.append(cues[j])
            j += 1

        text = clean_text(" ".join(c.text for c in chunk))
        if text:
            start_ms = int(round(window_start * 1000))
            seg_id = f"{video_id}:{start_ms}"
            if seg_id not in seen_ids:
                seen_ids.add(seg_id)
                segments.append(
                    Segment(
                        segment_id=seg_id,
                        video_id=video_id,
                        source_key=source_key,
                        start_s=round(window_start, 3),
                        end_s=round(max(c.end_s for c in chunk), 3),
                        text=text,
                        url=timestamp_url(video_id, window_start),
                        caption_kind=caption_kind,
                        video_title=video_title,
                        published_at=published_at,
                        language=language,
                    )
                )

        # Advance to the first cue at or beyond the next window origin. Always
        # move at least one cue so a dense cluster cannot stall the loop.
        next_origin = window_start + stride
        k = i + 1
        while k < n and cues[k].start_s < next_origin:
            k += 1
        i = k

    return segments
