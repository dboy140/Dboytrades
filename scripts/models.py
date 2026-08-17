"""Pydantic models for the pipeline.

The Rule model mirrors the extraction schema exactly. It is strict on purpose:
`sources` cannot be empty, so a rule that cannot be traced to a video and a
timestamp is not representable.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

Confidence = Literal["high", "medium", "low"]
Category = Literal[
    "bias", "liquidity", "entry_model", "entry_mechanic",
    "risk", "management", "invalidation", "psychology",
]
Session = Literal["Asia", "London", "NY AM", "NY Lunch", "NY PM", "any"]
Scope = Literal["filtered", "complete"]


# ------------------------------------------------------------ discovery ----


class VideoMeta(BaseModel):
    """One discovered video. Written to data/manifest.json."""

    video_id: str
    title: str
    url: str
    channel_key: str
    channel_name: str = ""
    published: str | None = None
    duration_seconds: int | None = None
    view_count: int | None = None
    description: str = ""
    # Which of the eight ICT buckets this matched. Empty for NBB (complete scope).
    buckets: list[str] = Field(default_factory=list)
    # What surfaced it: channel enumeration, or which search query.
    discovered_via: str = "channel"
    is_short: bool = False
    is_live: bool = False

    @field_validator("video_id")
    @classmethod
    def _valid_id(cls, v: str) -> str:
        if not VIDEO_ID_RE.match(v):
            raise ValueError(f"invalid YouTube video id: {v!r}")
        return v

    @property
    def duration_hours(self) -> float:
        return (self.duration_seconds or 0) / 3600.0

    def link_at(self, seconds: int) -> str:
        return f"https://youtu.be/{self.video_id}?t={int(seconds)}"


class ExcludedVideo(BaseModel):
    """An ICT video found but filtered out. Written to data/excluded.json.

    Kept with title and reason so the operator can eyeball whether the bucket
    filter is cutting anything worth keeping.
    """

    video_id: str
    title: str
    published: str | None = None
    duration_seconds: int | None = None
    url: str = ""
    reason: str = "no_bucket_match"


# ----------------------------------------------------------- transcripts ----


class TranscriptSegment(BaseModel):
    start_seconds: float = Field(ge=0)
    text: str

    @field_validator("text")
    @classmethod
    def _nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("empty segment text")
        return v.strip()


class Transcript(BaseModel):
    """Raw transcript. Stays local in data/transcripts/ — never redistributed,
    never pasted into a deliverable."""

    id: str
    title: str
    channel: str
    published: str | None = None
    duration: int | None = None
    url: str = ""
    buckets: list[str] = Field(default_factory=list)
    segments: list[TranscriptSegment] = Field(default_factory=list)
    caption_kind: Literal["manual", "auto", "unknown"] = "unknown"
    language: str = "en"
    # Which backend produced this: "yt-dlp" or an Apify actor id.
    actor_used: str = ""
    fetched_at: str = ""

    @property
    def word_count(self) -> int:
        return sum(len(s.text.split()) for s in self.segments)

    def segment_at(self, seconds: float, tolerance: float = 60.0) -> TranscriptSegment | None:
        """Nearest segment to a timestamp, used to verify a citation resolves."""
        best, best_gap = None, float("inf")
        for seg in self.segments:
            gap = abs(seg.start_seconds - seconds)
            if gap < best_gap:
                best, best_gap = seg, gap
        return best if best is not None and best_gap <= tolerance else None


# ----------------------------------------------------------------- rules ----


class RuleSource(BaseModel):
    channel: str
    video_id: str
    title: str
    published: str | None = None
    timestamp: str  # "HH:MM:SS"
    link: str = ""

    @field_validator("video_id")
    @classmethod
    def _valid_id(cls, v: str) -> str:
        if not VIDEO_ID_RE.match(v):
            raise ValueError(f"invalid YouTube video id: {v!r}")
        return v

    @field_validator("timestamp")
    @classmethod
    def _valid_ts(cls, v: str) -> str:
        if not re.match(r"^\d{1,2}:\d{2}:\d{2}$", v) and not re.match(r"^\d{1,3}:\d{2}$", v):
            raise ValueError(f"timestamp must be HH:MM:SS or MM:SS, got {v!r}")
        return v

    @property
    def timestamp_seconds(self) -> int:
        parts = [int(p) for p in self.timestamp.split(":")]
        total = 0
        for p in parts:
            total = total * 60 + p
        return total

    @model_validator(mode="after")
    def _fill_link(self) -> "RuleSource":
        if not self.link:
            object.__setattr__(
                self, "link", f"https://youtu.be/{self.video_id}?t={self.timestamp_seconds}"
            )
        return self


class Timeframes(BaseModel):
    htf: str | None = None
    mtf: str | None = None
    ltf: str | None = None


class TimeWindow(BaseModel):
    ny: str | None = None
    london: str | None = None
    dst_sensitive: bool = True


class Rule(BaseModel):
    """One atomic, cited rule. Written to extraction/rules.json.

    `statement` is a paraphrase in the researcher's own words — never transcript
    text. The citation, not a quotation, is what makes it checkable.
    """

    rule_id: str
    topic_bucket: str
    concept: str
    category: Category
    statement: str = Field(min_length=10)
    preconditions: list[str] = Field(default_factory=list)
    trigger: str = ""
    entry: str = ""
    stop_loss: str = ""
    target: str = ""
    invalidation: str = ""
    timeframes: Timeframes = Field(default_factory=Timeframes)
    session: Session = "any"
    time_window: TimeWindow = Field(default_factory=TimeWindow)
    instruments: list[str] = Field(default_factory=lambda: ["any"])
    confluences_required: list[str] = Field(default_factory=list)
    sources: Annotated[list[RuleSource], Field(min_length=1)]
    confidence: Confidence = "medium"
    mentions: int = 1
    contradicts: list[str] = Field(default_factory=list)
    notes: str = ""

    @field_validator("statement")
    @classmethod
    def _looks_paraphrased(cls, v: str) -> str:
        # A crude guard against pasted transcript: spoken filler in a rule
        # statement means it was copied rather than compressed into logic.
        filler = (" um ", " uh ", " you know ", " kinda ", " gonna ", " alright so ")
        low = f" {v.lower()} "
        hit = next((f for f in filler if f in low), None)
        if hit:
            raise ValueError(
                f"statement contains spoken filler ({hit.strip()!r}) and looks like "
                "transcript text. Rules must be paraphrased as compressed logic."
            )
        return v

    @property
    def is_complete_setup(self) -> bool:
        """A setup needs a stop, a target and an invalidation to be tradeable."""
        return bool(self.stop_loss and self.target and self.invalidation)


# ------------------------------------------------------------ bake-off ----


class ActorProbe(BaseModel):
    """One transcript actor tested against one video."""

    actor_id: str
    label: str
    reachable: bool = False
    succeeded: bool = False
    segment_count: int = 0
    has_timestamps: bool = False
    timestamp_granularity_seconds: float | None = None
    cost_usd: float | None = None
    runtime_seconds: float | None = None
    output_keys: list[str] = Field(default_factory=list)
    error: str = ""


class DiscoveryReport(BaseModel):
    """Gate 1 payload."""

    generated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat(timespec="seconds"))
    ict_total_enumerated: int = 0
    ict_in_scope: int = 0
    ict_excluded: int = 0
    ict_per_bucket: dict[str, int] = Field(default_factory=dict)
    nbb_total: int = 0
    nbb_shorts: int = 0
    nbb_guest_appearances: int = 0
    total_runtime_hours: float = 0.0
    estimated_cost_usd: float = 0.0
    notes: list[str] = Field(default_factory=list)
