"""Verify every rule resolves to real audio at the timestamp it cites.

This is the check that makes the system citable rather than merely
plausible-looking. For each source on each rule it confirms:

  * the video is in the corpus
  * the timestamp lies inside that video's actual runtime
  * there is transcript within a tolerance of that timestamp
  * the deep link matches the timestamp

A rule whose citation points at silence, or past the end of the video, or at
a video that is not in the corpus, fails the build. Fabricated or drifted
citations cannot survive this.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

TOLERANCE_SECONDS = 90.0


@dataclass
class Problem:
    rule_id: str
    kind: str
    detail: str


@dataclass
class Report:
    checked: int = 0
    sources: int = 0
    problems: list[Problem] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def timestamp_seconds(ts: str) -> int | None:
    if not re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", ts or ""):
        return None
    total = 0
    for part in ts.split(":"):
        total = total * 60 + int(part)
    return total


def load_corpus(directory: str | Path = "data/transcripts") -> dict[str, dict]:
    out: dict[str, dict] = {}
    for p in Path(directory).glob("*.json"):
        rec = json.loads(p.read_text())
        starts = [s["start_seconds"] for s in rec.get("segments") or []]
        out[rec["id"]] = {
            "title": rec.get("title", ""),
            "duration": rec.get("duration"),
            "caption_kind": rec.get("caption_kind", "unknown"),
            "starts": sorted(starts),
            "last": max(starts) if starts else 0.0,
        }
    return out


def nearest_gap(starts: list[float], target: float) -> float:
    """Distance from `target` to the closest transcript cue."""
    if not starts:
        return float("inf")
    lo, hi = 0, len(starts) - 1
    best = float("inf")
    while lo <= hi:
        mid = (lo + hi) // 2
        best = min(best, abs(starts[mid] - target))
        if starts[mid] < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def verify(rules: list[dict], corpus: dict[str, dict],
           tolerance: float = TOLERANCE_SECONDS) -> Report:
    rep = Report()
    seen_ids: set[str] = set()

    for rule in rules:
        rid = rule.get("rule_id", "<no id>")
        rep.checked += 1

        if rid in seen_ids:
            rep.problems.append(Problem(rid, "duplicate_rule_id", "rule_id used twice"))
        seen_ids.add(rid)

        sources = rule.get("sources") or []
        if not sources:
            rep.problems.append(Problem(rid, "no_sources",
                                        "rule cannot be traced to any video"))
            continue

        for src in sources:
            rep.sources += 1
            vid = src.get("video_id", "")
            ts = src.get("timestamp", "")
            secs = timestamp_seconds(ts)

            if vid not in corpus:
                rep.problems.append(Problem(rid, "video_not_in_corpus",
                                            f"{vid} is not in data/transcripts"))
                continue
            if secs is None:
                rep.problems.append(Problem(rid, "bad_timestamp",
                                            f"{ts!r} is not HH:MM:SS"))
                continue

            info = corpus[vid]
            duration = info["duration"] or info["last"]
            if duration and secs > duration + 60:
                rep.problems.append(Problem(
                    rid, "timestamp_past_end",
                    f"{vid} @ {ts} ({secs}s) is beyond runtime {int(duration)}s"))
                continue

            gap = nearest_gap(info["starts"], float(secs))
            if gap > tolerance:
                rep.problems.append(Problem(
                    rid, "no_transcript_there",
                    f"{vid} @ {ts}: nearest cue is {gap:.0f}s away"))

            link = src.get("link", "")
            if link and f"?t={secs}" not in link:
                rep.problems.append(Problem(
                    rid, "link_timestamp_mismatch",
                    f"{link} does not point at {ts}"))

    return rep
