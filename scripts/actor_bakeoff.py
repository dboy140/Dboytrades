"""Test each transcript actor candidate on a single video, then report.

Run this before any batch ingestion. The four candidates differ in cost,
reliability and — most importantly — timestamp granularity, which directly
determines how precise a citation can be. An actor that returns one block of
text per video is useless here regardless of price, because every rule would
cite 00:00:00.

This script never picks a winner. It reports, and the operator chooses.
"""

from __future__ import annotations

import argparse
import logging
import statistics
from typing import Any

from . import config as cfg
from .apify_runner import ApifyBlocked, ApifyRunner
from .models import ActorProbe
from .util import read_json, setup_logging, write_json

log = logging.getLogger(__name__)

# Actors disagree about the input key for "which video". Extra keys are ignored
# by actors that do not recognise them, so sending several is safe and saves a
# round of guessing per actor.
def _input_variants(video_url: str, video_id: str) -> list[dict[str, Any]]:
    return [
        {"videoUrls": [video_url], "urls": [video_url], "startUrls": [{"url": video_url}],
         "videoUrl": video_url, "videoId": video_id, "language": "en"},
        {"startUrls": [{"url": video_url}], "maxResults": 1, "language": "en"},
        {"videoUrl": video_url},
    ]


_CUE_KEYS = ("transcript", "captions", "segments", "subtitles", "data", "items", "lines")
_START_KEYS = ("start", "startMs", "start_ms", "offset", "offsetMs", "startTime", "tStartMs", "begin")


def _find_cues(payload: dict[str, Any]) -> list[dict[str, Any]] | None:
    for key in _CUE_KEYS:
        val = payload.get(key)
        if isinstance(val, list) and val and isinstance(val[0], dict):
            return val
    for val in payload.values():
        if isinstance(val, dict):
            nested = _find_cues(val)
            if nested:
                return nested
    return None


def _starts(cues: list[dict[str, Any]]) -> list[float]:
    out: list[float] = []
    for c in cues:
        for k in _START_KEYS:
            if k in c and c[k] not in (None, ""):
                try:
                    v = float(str(c[k]).strip())
                except ValueError:
                    continue
                # Explicit ms fields, or an implausibly large integer, are ms.
                if k.lower().endswith("ms") or (v > 36_000 and float(v).is_integer()):
                    v /= 1000.0
                out.append(v)
                break
    return sorted(out)


def probe_actor(runner: ApifyRunner, candidate: cfg.ActorCandidate, video_url: str, video_id: str) -> ActorProbe:
    probe = ActorProbe(actor_id=candidate.actor_id, label=candidate.label)

    exists, detail = runner.actor_exists(candidate.actor_id)
    probe.reachable = exists
    if not exists:
        probe.error = f"actor not reachable: {detail}"
        return probe

    last_error = ""
    for variant in _input_variants(video_url, video_id):
        try:
            out = runner.run(
                candidate.actor_id,
                variant,
                operation=f"bakeoff_{candidate.actor_id}",
                estimated_cost_usd=0.05,
            )
        except ApifyBlocked:
            raise
        except Exception as exc:
            last_error = str(exc)[:300]
            continue

        if not out.items:
            last_error = "run succeeded but returned zero items"
            continue

        payload = out.items[0]
        probe.output_keys = sorted(payload.keys())[:25]
        probe.cost_usd = out.cost_usd
        probe.runtime_seconds = round(out.runtime_seconds, 1)

        cues = _find_cues(payload)
        if not cues:
            last_error = f"no cue array found; top-level keys={probe.output_keys}"
            continue

        probe.succeeded = True
        probe.segment_count = len(cues)
        starts = _starts(cues)
        probe.has_timestamps = len(starts) > 1
        if len(starts) > 2:
            gaps = [b - a for a, b in zip(starts, starts[1:]) if b > a]
            if gaps:
                probe.timestamp_granularity_seconds = round(statistics.median(gaps), 2)
        return probe

    probe.error = last_error or "all input variants failed"
    return probe


def print_comparison(probes: list[ActorProbe]) -> None:
    print("\n" + "=" * 92)
    print("TRANSCRIPT ACTOR BAKE-OFF")
    print("=" * 92)
    header = f"{'actor':<46} {'ok':<4} {'segs':>6} {'granularity':>12} {'cost':>9} {'runtime':>8}"
    print("\n" + header)
    print("-" * 92)
    for p in probes:
        ok = "yes" if p.succeeded else "no"
        segs = str(p.segment_count) if p.succeeded else "-"
        gran = f"{p.timestamp_granularity_seconds}s" if p.timestamp_granularity_seconds else "-"
        cost = f"${p.cost_usd:.4f}" if p.cost_usd is not None else "-"
        rt = f"{p.runtime_seconds}s" if p.runtime_seconds is not None else "-"
        print(f"{p.label:<46} {ok:<4} {segs:>6} {gran:>12} {cost:>9} {rt:>8}")

    print("\nDetail:")
    for p in probes:
        print(f"\n  {p.label}")
        print(f"    reachable: {p.reachable}   succeeded: {p.succeeded}")
        if p.output_keys:
            print(f"    output keys: {', '.join(p.output_keys)}")
        if p.error:
            print(f"    error: {p.error}")

    usable = [p for p in probes if p.succeeded and p.has_timestamps]
    print("\n" + "-" * 92)
    if not usable:
        print("No candidate produced timestamped segments. Without timestamps every")
        print("citation would point at 00:00:00, so none of these can be used as-is.")
    else:
        print("Usable candidates (timestamped output), cheapest first:")
        for p in sorted(usable, key=lambda x: (x.cost_usd if x.cost_usd is not None else 9e9)):
            gran = f"{p.timestamp_granularity_seconds}s" if p.timestamp_granularity_seconds else "unknown"
            cost = f"${p.cost_usd:.4f}" if p.cost_usd is not None else "unknown"
            print(f"  - {p.label}: {p.segment_count} segments, ~{gran} granularity, {cost}/video")
    print("\nSTOP. Tell me which actor to use; I will set CHOSEN_TRANSCRIPT_ACTOR in config.py.")
    print("=" * 92 + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Compare transcript actors on one video")
    ap.add_argument("--video-id", help="11-char YouTube id to test against")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    setup_logging(args.verbose, logfile="bakeoff.log")
    cfg.ensure_dirs()

    video_id = args.video_id
    if not video_id:
        # Default to the first in-scope ICT video in the manifest, so the test
        # runs against material the project actually cares about.
        manifest = read_json(cfg.MANIFEST, default=[]) or []
        ict = [v for v in manifest if v.get("channel_key") == "ICT"]
        if not ict:
            print(
                "No manifest yet and no --video-id given. Run discovery first, or pass\n"
                "  python -m scripts.actor_bakeoff --video-id <11-char id>"
            )
            return 1
        video_id = ict[0]["video_id"]
        print(f"testing against first in-scope ICT video: {video_id} — {ict[0].get('title', '')[:70]}")

    video_url = f"https://www.youtube.com/watch?v={video_id}"
    runner = ApifyRunner()

    status = runner.probe()
    if not status["reachable"]:
        print("\nCannot reach Apify.\n")
        print(status["error"])
        print("\nSee docs/BLOCKED.md.")
        return 2

    probes: list[ActorProbe] = []
    try:
        for candidate in cfg.TRANSCRIPT_ACTOR_CANDIDATES:
            log.info("probing %s", candidate.label)
            probes.append(probe_actor(runner, candidate, video_url, video_id))
    except ApifyBlocked as exc:
        print(f"\nBLOCKED: {exc}\n")
        return 2

    write_json(cfg.BAKEOFF_REPORT, {"video_id": video_id, "probes": [p.model_dump() for p in probes]})
    print_comparison(probes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
