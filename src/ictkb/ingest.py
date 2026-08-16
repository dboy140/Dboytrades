"""Corpus ingestion: channels -> video list -> transcripts -> citable segments.

Actor output shapes are treated as unknown at author time (see docs/BLOCKED.md).
Every field read from an actor payload goes through a tolerant extractor, and
anything that cannot be resolved to a real video ID and real timestamps is
skipped with a warning rather than guessed at. A skipped video costs coverage;
a guessed timestamp costs the integrity of every citation built on it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from . import config as cfg
from .apify import ApifyClient, ApifyError
from .normalize import Segment, build_segments, extract_video_id, parse_cues
from .store import read_jsonl, write_jsonl

log = logging.getLogger(__name__)

_VIDEO_URL_FIELDS = ("url", "videoUrl", "video_url", "link", "webUrl")
_VIDEO_ID_FIELDS = ("videoId", "video_id", "id")
_TITLE_FIELDS = ("title", "videoTitle", "name")
_DATE_FIELDS = ("date", "publishedAt", "published_at", "uploadDate", "publishDate")
_CUES_FIELDS = ("transcript", "captions", "segments", "subtitles", "data", "items", "lines")


@dataclass
class VideoRef:
    video_id: str
    source_key: str
    title: str = ""
    published_at: str | None = None
    url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "video_id": self.video_id,
            "source_key": self.source_key,
            "title": self.title,
            "published_at": self.published_at,
            "url": self.url or f"https://www.youtube.com/watch?v={self.video_id}",
        }


def _pick(d: dict[str, Any], keys: Sequence[str]) -> Any:
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return None


def parse_video_item(item: dict[str, Any], source_key: str) -> VideoRef | None:
    """Extract a VideoRef from one channel-scraper dataset row."""
    vid = None
    raw_id = _pick(item, _VIDEO_ID_FIELDS)
    if raw_id:
        vid = extract_video_id(str(raw_id))
    if not vid:
        raw_url = _pick(item, _VIDEO_URL_FIELDS)
        if raw_url:
            vid = extract_video_id(str(raw_url))
    if not vid:
        log.warning("channel row has no resolvable video id; keys=%s", sorted(item)[:12])
        return None

    return VideoRef(
        video_id=vid,
        source_key=source_key,
        title=str(_pick(item, _TITLE_FIELDS) or ""),
        published_at=(str(_pick(item, _DATE_FIELDS)) if _pick(item, _DATE_FIELDS) else None),
        url=str(_pick(item, _VIDEO_URL_FIELDS) or ""),
    )


def find_cue_list(payload: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Locate the caption-cue array inside an arbitrary transcript payload."""
    for key in _CUES_FIELDS:
        val = payload.get(key)
        if isinstance(val, list) and val and isinstance(val[0], dict):
            return val
    # Some actors nest one level deeper, e.g. {"data": {"transcript": [...]}}.
    for val in payload.values():
        if isinstance(val, dict):
            nested = find_cue_list(val)
            if nested:
                return nested
    return None


def detect_caption_kind(payload: dict[str, Any]) -> str:
    for key in ("captionKind", "kind", "type", "trackKind", "isGenerated", "auto"):
        v = payload.get(key)
        if isinstance(v, bool):
            return "auto" if v else "manual"
        if isinstance(v, str):
            low = v.lower()
            if "asr" in low or "auto" in low or "generated" in low:
                return "auto"
            if "manual" in low or "standard" in low:
                return "manual"
    return "unknown"


def fetch_channel_videos(
    client: ApifyClient, conf: cfg.Config, source_keys: Sequence[str], limit: int | None = None
) -> list[VideoRef]:
    spec = conf.actors.get("channel_videos")
    if not spec:
        raise ApifyError("no 'channel_videos' actor configured in sources.yaml")

    refs: list[VideoRef] = []
    for key in source_keys:
        src = conf.source(key)
        if not src.verified:
            log.warning(
                "source %s is marked verified:false in sources.yaml — confirm the channel "
                "before trusting anything ingested from it",
                key,
            )
        run_input: dict[str, Any] = dict(spec.default_input)
        run_input["startUrls"] = [{"url": src.url}]
        if limit:
            run_input["maxResults"] = limit

        log.info("listing videos for %s via actor %s", key, spec.id)
        items = client.run_and_collect(spec.id, run_input)
        got = 0
        for item in items:
            ref = parse_video_item(item, key)
            if ref:
                refs.append(ref)
                got += 1
        log.info("source %s: %d videos resolved from %d rows", key, got, len(items))

    # De-duplicate: channel scrapes overlap when playlists are included.
    seen: set[str] = set()
    unique: list[VideoRef] = []
    for r in refs:
        if r.video_id not in seen:
            seen.add(r.video_id)
            unique.append(r)
    return unique


def fetch_transcripts(
    client: ApifyClient,
    conf: cfg.Config,
    videos: Sequence[VideoRef],
    *,
    batch_size: int = 25,
) -> list[Segment]:
    spec = conf.actors.get("transcripts")
    if not spec:
        raise ApifyError("no 'transcripts' actor configured in sources.yaml")

    by_id = {v.video_id: v for v in videos}
    ing = conf.ingestion
    all_segments: list[Segment] = []

    for start in range(0, len(videos), batch_size):
        batch = videos[start : start + batch_size]
        urls = [f"https://www.youtube.com/watch?v={v.video_id}" for v in batch]
        run_input = {
            "videoUrls": urls,
            "urls": urls,  # actors differ on the input key; extra keys are ignored
            "language": ing.language_preference[0] if ing.language_preference else "en",
        }
        log.info("transcribing batch %d-%d of %d", start + 1, start + len(batch), len(videos))
        try:
            items = client.run_and_collect(spec.id, run_input)
        except ApifyError as exc:
            log.error("transcript batch starting at %d failed: %s", start, exc)
            continue

        for payload in items:
            vid = extract_video_id(str(_pick(payload, _VIDEO_ID_FIELDS) or "")) or extract_video_id(
                str(_pick(payload, _VIDEO_URL_FIELDS) or "")
            )
            if not vid or vid not in by_id:
                log.warning("transcript payload for unknown video %r, skipping", vid)
                continue
            cue_rows = find_cue_list(payload)
            if not cue_rows:
                log.warning("no cue array found for %s; keys=%s", vid, sorted(payload)[:12])
                continue
            cues = parse_cues(cue_rows)
            if not cues:
                log.warning("all cues unparseable for %s", vid)
                continue

            kind = detect_caption_kind(payload)
            if kind == "auto" and not ing.allow_auto_captions:
                log.info("skipping %s: auto captions disabled", vid)
                continue

            ref = by_id[vid]
            segs = build_segments(
                video_id=vid,
                source_key=ref.source_key,
                cues=cues,
                window_seconds=ing.window_seconds,
                overlap_seconds=ing.window_overlap_seconds,
                caption_kind=kind,
                video_title=ref.title,
                published_at=ref.published_at,
                language=ing.language_preference[0] if ing.language_preference else "en",
            )
            all_segments.extend(segs)
            log.info("%s -> %d segments", vid, len(segs))

    return all_segments


def load_segments(path: Path | None = None) -> list[dict[str, Any]]:
    return list(read_jsonl(path or cfg.SEGMENTS_PATH))


def save_segments(segments: Sequence[Segment], path: Path | None = None) -> int:
    return write_jsonl(path or cfg.SEGMENTS_PATH, (s.to_dict() for s in segments))


def save_videos(videos: Sequence[VideoRef], path: Path | None = None) -> int:
    return write_jsonl(path or cfg.VIDEOS_PATH, (v.to_dict() for v in videos))
