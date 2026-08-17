"""yt-dlp backend: enumeration and transcripts, no Apify account required.

Only needs youtube.com reachable. Runs the yt-dlp binary as a subprocess rather
than importing it, so the pipeline is unaffected by yt-dlp's fast-moving Python
API and users can upgrade it independently (`yt-dlp -U`) when YouTube changes
something, which it does often.

Two things this module is careful about:

  * `--flat-playlist` is one cheap request per channel tab but returns NO
    description, so bucket matching from it is title-only. That is a real
    coverage difference from the Apify path and is surfaced, not hidden.
  * Manual and automatic captions are fetched in separate passes so
    `caption_kind` is known with certainty rather than guessed. It drives
    confidence tagging downstream, and auto-captions mangle trading jargon.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from . import config as cfg
from .models import Transcript, TranscriptSegment, VideoMeta

log = logging.getLogger(__name__)

# Channel tabs. NBB is "complete" scope so all three are enumerated; ICT is
# filtered down by bucket afterwards, so streams are included but Shorts are
# not (ICT teaching content is long-form).
TAB_VIDEOS = "videos"
TAB_SHORTS = "shorts"
TAB_STREAMS = "streams"

SCOPE_TABS = {
    "complete": (TAB_VIDEOS, TAB_SHORTS, TAB_STREAMS),
    "filtered": (TAB_VIDEOS, TAB_STREAMS),
}


class YtdlpError(RuntimeError):
    pass


class YtdlpBlocked(YtdlpError):
    """Network refused the request — reported, never retried."""


@dataclass
class SubtitleResult:
    path: Path
    language: str
    caption_kind: str  # "manual" | "auto"


def _is_block(stderr: str) -> bool:
    low = stderr.lower()
    return (
        "tunnel connection failed" in low
        or "unable to connect to proxy" in low
        or "403 forbidden" in low and "proxy" in low
    )


def ytdlp_available() -> tuple[bool, str]:
    """Is the yt-dlp binary present, and which version?"""
    exe = shutil.which("yt-dlp")
    if not exe:
        return False, "yt-dlp not found on PATH — install with: pip install -U yt-dlp"
    try:
        out = subprocess.run(
            ["yt-dlp", "--version"], capture_output=True, text=True, timeout=30
        )
        return (out.returncode == 0), out.stdout.strip() or out.stderr.strip()
    except Exception as exc:
        return False, str(exc)


def _base_args() -> list[str]:
    args = ["yt-dlp", "--ignore-config", "--no-warnings", "--no-progress"]
    if cfg.YTDLP_COOKIES_FROM_BROWSER:
        args += ["--cookies-from-browser", cfg.YTDLP_COOKIES_FROM_BROWSER]
    elif cfg.YTDLP_COOKIES_FILE:
        args += ["--cookies", cfg.YTDLP_COOKIES_FILE]
    if cfg.YTDLP_SLEEP_REQUESTS:
        args += ["--sleep-requests", str(cfg.YTDLP_SLEEP_REQUESTS)]
    return args


def _run(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    log.debug("running: %s", " ".join(args[:8]) + (" ..." if len(args) > 8 else ""))
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise YtdlpError(f"yt-dlp timed out after {timeout}s") from exc
    if proc.returncode != 0 and _is_block(proc.stderr):
        raise YtdlpBlocked(
            "yt-dlp could not reach YouTube: the network refused the connection.\n"
            f"{proc.stderr.strip()[:400]}\n\n"
            "This is an egress policy denial, not a transient fault. Run on a "
            "machine that can reach youtube.com."
        )
    return proc


# ---------------------------------------------------------- enumeration ----


def channel_tab_url(channel_id: str, tab: str) -> str:
    return f"https://www.youtube.com/channel/{channel_id}/{tab}"


def enumerate_tab(
    channel_id: str, tab: str, max_results: int, *, timeout: int = 900
) -> list[dict[str, Any]]:
    """`yt-dlp --flat-playlist --dump-json` over one channel tab.

    Returns raw flat entries. A tab that does not exist (no Shorts, no streams)
    is not an error — it yields nothing and the caller moves on.
    """
    url = channel_tab_url(channel_id, tab)
    args = _base_args() + [
        "--flat-playlist",
        "--dump-json",
        "--playlist-end",
        str(max_results),
        url,
    ]
    proc = _run(args, timeout)

    entries: list[dict[str, Any]] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            log.debug("skipping non-JSON line from yt-dlp: %s", line[:120])

    if not entries and proc.returncode != 0:
        # Distinguish "tab is empty" from "the request actually failed".
        stderr = proc.stderr.strip()
        if "does not have a" in stderr.lower() or "not found" in stderr.lower():
            log.info("channel %s has no %s tab", channel_id, tab)
        else:
            log.warning("enumeration of %s/%s returned nothing: %s", channel_id, tab, stderr[:300])
    return entries


def _norm_upload_date(value: Any) -> str | None:
    """yt-dlp gives YYYYMMDD; normalise to ISO so dates sort and compare."""
    s = str(value or "").strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    return s or None


def flat_entry_to_meta(
    entry: dict[str, Any], channel_key: str, discovered_via: str, tab: str = ""
) -> VideoMeta | None:
    vid = str(entry.get("id") or "").strip()
    if not vid:
        return None
    url = str(entry.get("url") or f"https://www.youtube.com/watch?v={vid}")
    duration = entry.get("duration")
    try:
        return VideoMeta(
            video_id=vid,
            title=str(entry.get("title") or ""),
            url=url,
            channel_key=channel_key,
            channel_name=str(entry.get("channel") or entry.get("uploader") or ""),
            published=_norm_upload_date(entry.get("upload_date") or entry.get("release_date")),
            duration_seconds=int(duration) if isinstance(duration, (int, float)) else None,
            view_count=entry.get("view_count") if isinstance(entry.get("view_count"), int) else None,
            # Flat enumeration does not return descriptions. Deliberately left
            # empty rather than filled with a placeholder — see fetch_metadata.
            description="",
            discovered_via=discovered_via,
            is_short=(tab == TAB_SHORTS) or "/shorts/" in url.lower(),
            is_live=(tab == TAB_STREAMS),
        )
    except Exception as exc:
        log.warning("malformed flat entry %s: %s", vid, exc)
        return None


def enumerate_channel(
    channel_key: str, max_results: int, *, tabs: tuple[str, ...] | None = None
) -> list[VideoMeta]:
    ch = cfg.channel(channel_key)
    use_tabs = tabs or SCOPE_TABS.get(ch.scope, (TAB_VIDEOS,))
    out: list[VideoMeta] = []
    seen: set[str] = set()

    for tab in use_tabs:
        log.info("enumerating %s /%s", channel_key, tab)
        entries = enumerate_tab(ch.channel_id, tab, max_results)
        log.info("  %d entries from /%s", len(entries), tab)
        for entry in entries:
            meta = flat_entry_to_meta(entry, channel_key, f"ytdlp:{tab}", tab)
            if meta and meta.video_id not in seen:
                seen.add(meta.video_id)
                out.append(meta)
    return out


def search_videos(query: str, max_results: int = 30, *, timeout: int = 300) -> list[dict[str, Any]]:
    """YouTube search via yt-dlp's `ytsearchN:` pseudo-URL.

    Used for NBB's guest appearances on other people's channels, which channel
    enumeration cannot see by definition.
    """
    args = _base_args() + [
        "--flat-playlist",
        "--dump-json",
        f"ytsearch{int(max_results)}:{query}",
    ]
    proc = _run(args, timeout)

    entries: list[dict[str, Any]] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def fetch_metadata(video_id: str, *, timeout: int = 120) -> dict[str, Any] | None:
    """Full metadata for one video, including the description.

    One request per video, so this is the expensive path. Used only for the
    optional second pass over videos that did not match a bucket on title
    alone.
    """
    args = _base_args() + [
        "--dump-json",
        "--skip-download",
        f"https://www.youtube.com/watch?v={video_id}",
    ]
    proc = _run(args, timeout)
    if proc.returncode != 0:
        log.warning("metadata fetch failed for %s: %s", video_id, proc.stderr.strip()[:200])
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None


# ----------------------------------------------------------- transcripts ----


def fetch_subtitles(
    video_id: str, outdir: Path, *, languages: list[str] | None = None, timeout: int = 300
) -> SubtitleResult | None:
    """Download captions as json3, preferring manual over auto-generated.

    Two passes so caption_kind is a fact rather than an inference: manual
    captions are requested alone first, and only if none exist do we ask for
    the auto-generated track.
    """
    outdir.mkdir(parents=True, exist_ok=True)
    langs = ",".join(languages or cfg.YTDLP_SUB_LANGS)
    url = f"https://www.youtube.com/watch?v={video_id}"

    for kind, flag in (("manual", "--write-subs"), ("auto", "--write-auto-subs")):
        args = _base_args() + [
            "--skip-download",
            flag,
            "--sub-langs", langs,
            "--sub-format", "json3",
            "-o", str(outdir / "%(id)s.%(ext)s"),
            url,
        ]
        proc = _run(args, timeout)
        found = sorted(outdir.glob(f"{video_id}*.json3"))
        if found:
            path = found[0]
            language = _language_from_filename(path, video_id)
            return SubtitleResult(path=path, language=language, caption_kind=kind)
        if proc.returncode != 0 and not _is_block(proc.stderr):
            log.debug("%s pass for %s: %s", kind, video_id, proc.stderr.strip()[:200])

    return None


def _language_from_filename(path: Path, video_id: str) -> str:
    # "<id>.en.json3" -> "en";  "<id>.en-GB.json3" -> "en-GB"
    stem = path.name[len(video_id) :].lstrip(".")
    parts = stem.split(".")
    return parts[0] if parts and parts[0] != "json3" else "en"


def parse_json3(path: Path) -> list[TranscriptSegment]:
    """Parse YouTube's json3 caption format into timestamped segments.

    Events without a `segs` array are layout padding and carry no text; events
    whose text is only whitespace are dropped. Timestamps are milliseconds in
    this format, which is unambiguous — no unit guessing needed.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise YtdlpError(f"could not read caption file {path}: {exc}") from exc

    segments: list[TranscriptSegment] = []
    for event in data.get("events") or []:
        segs = event.get("segs")
        if not segs:
            continue
        text = "".join(s.get("utf8", "") for s in segs)
        text = text.replace("\n", " ").strip()
        if not text:
            continue
        start_ms = event.get("tStartMs")
        if start_ms is None:
            continue
        segments.append(TranscriptSegment(start_seconds=float(start_ms) / 1000.0, text=text))

    segments.sort(key=lambda s: s.start_seconds)
    return segments


def fetch_transcript(meta: VideoMeta, outdir: Path | None = None) -> Transcript | None:
    """Full transcript for one video, or None if it has no captions at all."""
    outdir = outdir or cfg.TRANSCRIPTS
    workdir = outdir / "_raw"
    result = fetch_subtitles(meta.video_id, workdir)
    if not result:
        log.info("%s has no captions", meta.video_id)
        return None

    segments = parse_json3(result.path)
    if not segments:
        log.warning("%s: caption file parsed to zero segments", meta.video_id)
        return None

    transcript = Transcript(
        id=meta.video_id,
        title=meta.title,
        channel=meta.channel_key,
        published=meta.published,
        duration=meta.duration_seconds,
        url=meta.url,
        buckets=list(meta.buckets),
        segments=segments,
        caption_kind=result.caption_kind,
        actor_used="yt-dlp",
        fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        language=result.language,
    )

    # The json3 file is an intermediate; the Transcript JSON is the artifact.
    try:
        result.path.unlink()
    except OSError:
        pass
    return transcript


def iter_transcripts(
    videos: list[VideoMeta], *, skip_existing: bool = True, sleep_between: float | None = None
) -> Iterator[tuple[VideoMeta, Transcript | None, str]]:
    """Yield (video, transcript, status) for each video.

    Resumable: anything already on disk is skipped, so an interrupted run costs
    nothing to restart.
    """
    delay = cfg.YTDLP_SLEEP_BETWEEN_VIDEOS if sleep_between is None else sleep_between

    for meta in videos:
        dest = cfg.TRANSCRIPTS / f"{meta.video_id}.json"
        if skip_existing and dest.exists():
            yield meta, None, "skipped"
            continue
        try:
            transcript = fetch_transcript(meta)
        except YtdlpBlocked:
            raise
        except YtdlpError as exc:
            log.warning("%s failed: %s", meta.video_id, exc)
            yield meta, None, f"error: {exc}"
            continue

        if transcript is None:
            yield meta, None, "no_captions"
        else:
            yield meta, transcript, "ok"

        if delay:
            time.sleep(delay)
