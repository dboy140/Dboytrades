"""Phase 2 transcript ingestion via yt-dlp. Resumable; stops at Gate 2.

Every video already on disk is skipped, so an interrupted run costs nothing to
restart — which matters because a full catalogue pull takes hours.

Videos without captions are logged and skipped. Nothing is paid for and no AI
transcription is invoked; if a video has no captions it simply does not enter
the corpus, and Gate 2 reports how many.
"""

from __future__ import annotations

import argparse
import logging
import time

from . import config as cfg
from .models import VideoMeta
from .util import append_failure, read_json, setup_logging, write_json
from .ytdlp_adapter import YtdlpBlocked, iter_transcripts, ytdlp_available

log = logging.getLogger(__name__)


def load_targets(source: str | None, limit: int | None) -> list[VideoMeta]:
    rows = read_json(cfg.MANIFEST, default=[]) or []
    videos = [VideoMeta(**r) for r in rows]
    if source:
        videos = [v for v in videos if v.channel_key == source]
    return videos[:limit] if limit else videos


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Phase 2 transcript ingestion via yt-dlp")
    ap.add_argument("--source", choices=["ICT", "NBBTRADER"], help="limit to one channel")
    ap.add_argument("--limit", type=int, help="only the first N videos (use for a trial run)")
    ap.add_argument("--force", action="store_true", help="re-fetch transcripts already on disk")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    setup_logging(args.verbose, logfile="ingest.log")
    cfg.ensure_dirs()

    ok, version = ytdlp_available()
    if not ok:
        print(f"yt-dlp unavailable: {version}")
        return 2
    log.info("yt-dlp %s", version)

    targets = load_targets(args.source, args.limit)
    if not targets:
        print(f"no videos in {cfg.MANIFEST}. Run discovery first.")
        return 1

    print(f"{len(targets)} videos queued\n")

    counts = {"ok": 0, "skipped": 0, "no_captions": 0, "error": 0}
    words = 0
    manual = 0
    started = time.time()

    try:
        for i, (meta, transcript, status) in enumerate(
            iter_transcripts(targets, skip_existing=not args.force), 1
        ):
            if status == "ok" and transcript is not None:
                write_json(cfg.TRANSCRIPTS / f"{meta.video_id}.json", transcript.model_dump())
                counts["ok"] += 1
                words += transcript.word_count
                if transcript.caption_kind == "manual":
                    manual += 1
            elif status == "skipped":
                counts["skipped"] += 1
            elif status == "no_captions":
                counts["no_captions"] += 1
                append_failure("transcript", meta.video_id, "no captions available")
            else:
                counts["error"] += 1
                append_failure("transcript", meta.video_id, status)

            if i % 10 == 0 or i == len(targets):
                elapsed = time.time() - started
                rate = i / elapsed if elapsed else 0
                remaining = (len(targets) - i) / rate if rate else 0
                print(
                    f"  {i}/{len(targets)}  ok={counts['ok']} skip={counts['skipped']} "
                    f"none={counts['no_captions']} err={counts['error']}  "
                    f"~{remaining/60:.0f}m left",
                    flush=True,
                )

    except YtdlpBlocked as exc:
        print(f"\nBLOCKED: {exc}\n")
        return 2
    except KeyboardInterrupt:
        print("\ninterrupted — rerun to resume, everything fetched so far is on disk")
        return 130

    summary = {
        "queued": len(targets),
        **counts,
        "total_words": words,
        "manual_captions": manual,
        "auto_captions": counts["ok"] - manual,
        "elapsed_seconds": round(time.time() - started, 1),
        "cost_usd": 0.0,
    }
    write_json(cfg.LOGS / "gate2_report.json", summary)

    print("\n" + "=" * 66)
    print("GATE 2 — TRANSCRIPT INGESTION")
    print("=" * 66)
    print(f"\nQueued:           {summary['queued']}")
    print(f"Retrieved:        {counts['ok']}")
    print(f"  manual captions {manual}")
    print(f"  auto captions   {summary['auto_captions']}")
    print(f"Already on disk:  {counts['skipped']}")
    print(f"No captions:      {counts['no_captions']}")
    print(f"Errors:           {counts['error']}   (see logs/failed.json)")
    print(f"\nTotal words:      {words:,}")
    print(f"Elapsed:          {summary['elapsed_seconds']/60:.1f} min")
    print(f"Spend:            $0.00  (yt-dlp)")
    print("\n" + "=" * 66)
    print("STOP. Awaiting go-ahead before Phase 3 rule extraction.")
    print("=" * 66 + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
