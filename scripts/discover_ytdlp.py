"""Phase 1 discovery via yt-dlp. No Apify account, no per-video billing.

Reuses the bucket filter, report builder and writers from discover.py — only
the fetching changes, so both backends produce byte-identical manifest shapes.

One honest difference from the Apify path: `--flat-playlist` is a single cheap
request per channel tab but returns no description, so bucket matching is
title-only by default. `--deep-scan` adds a second pass that fetches
descriptions for videos which did NOT match on title, catching videos whose
titles are vague but whose descriptions name the concept. That pass costs one
request per unmatched video, so it is opt-in and reported separately.
"""

from __future__ import annotations

import argparse
import logging

from . import config as cfg
from .bucketing import match_buckets
from .discover import apply_bucket_filter, build_report, print_gate1
from .models import VideoMeta
from .util import read_json, setup_logging, write_json
from .ytdlp_adapter import (
    YtdlpBlocked,
    YtdlpError,
    enumerate_channel,
    fetch_metadata,
    ytdlp_available,
)

log = logging.getLogger(__name__)


def deep_scan_unmatched(unmatched: list[VideoMeta], limit: int | None = None) -> list[VideoMeta]:
    """Fetch descriptions for title-unmatched videos and re-test the filter.

    Returns those that match once the description is available. One request per
    video, so `limit` exists to bound the cost on a large back catalogue.
    """
    recovered: list[VideoMeta] = []
    targets = unmatched[:limit] if limit else unmatched

    for i, meta in enumerate(targets, 1):
        if i % 25 == 0:
            log.info("deep scan %d/%d, recovered %d so far", i, len(targets), len(recovered))
        try:
            info = fetch_metadata(meta.video_id)
        except YtdlpBlocked:
            raise
        except YtdlpError as exc:
            log.warning("deep scan failed for %s: %s", meta.video_id, exc)
            continue
        if not info:
            continue

        description = str(info.get("description") or "")[:4000]
        matches = match_buckets(meta.title, description)
        if matches:
            meta.description = description
            meta.buckets = [m.bucket_key for m in matches]
            meta.discovered_via += "+deep_scan"
            recovered.append(meta)
        # Backfill fields flat enumeration omitted, whether or not it matched.
        if not meta.published and info.get("upload_date"):
            raw = str(info["upload_date"])
            if len(raw) == 8 and raw.isdigit():
                meta.published = f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"

    return recovered


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Phase 1 discovery via yt-dlp")
    ap.add_argument("--refresh", action="store_true", help="re-enumerate even if a manifest exists")
    ap.add_argument(
        "--deep-scan",
        action="store_true",
        help="second pass fetching descriptions for title-unmatched ICT videos "
        "(one request each — slower, better recall)",
    )
    ap.add_argument("--deep-scan-limit", type=int, help="cap the deep scan at N videos")
    ap.add_argument("--ict-max", type=int, default=cfg.ICT_ENUMERATION_MAX)
    ap.add_argument("--nbb-max", type=int, default=cfg.NBB_ENUMERATION_MAX)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    setup_logging(args.verbose, logfile="discover_ytdlp.log")
    cfg.ensure_dirs()

    ok, version = ytdlp_available()
    if not ok:
        print(f"yt-dlp unavailable: {version}")
        return 2
    log.info("yt-dlp %s", version)

    existing = read_json(cfg.MANIFEST, default=None)
    if existing and not args.refresh:
        print(f"manifest already present with {len(existing)} videos; pass --refresh to rebuild")
        return 0

    try:
        log.info("enumerating ICT (filtered to eight buckets)")
        ict_all = enumerate_channel("ICT", args.ict_max)
        log.info("ICT enumerated: %d", len(ict_all))

        ict_kept, ict_excluded = apply_bucket_filter(ict_all)
        log.info("ICT matched on title: %d, unmatched: %d", len(ict_kept), len(ict_excluded))

        recovered_count = 0
        if args.deep_scan and ict_excluded:
            excluded_ids = {e.video_id for e in ict_excluded}
            unmatched = [v for v in ict_all if v.video_id in excluded_ids]
            log.info("deep scanning %d title-unmatched videos", len(unmatched))
            recovered = deep_scan_unmatched(unmatched, args.deep_scan_limit)
            recovered_count = len(recovered)
            if recovered:
                recovered_ids = {v.video_id for v in recovered}
                ict_kept += recovered
                ict_excluded = [e for e in ict_excluded if e.video_id not in recovered_ids]
                log.info("deep scan recovered %d videos", recovered_count)

        log.info("enumerating NBBTRADER (complete)")
        nbb = enumerate_channel("NBBTRADER", args.nbb_max)
        log.info("NBB enumerated: %d", len(nbb))

    except YtdlpBlocked as exc:
        print(f"\nBLOCKED: {exc}\n")
        print("See docs/BLOCKED.md.")
        return 2
    except YtdlpError as exc:
        print(f"\nyt-dlp error: {exc}\n")
        return 1

    manifest = ict_kept + nbb
    write_json(cfg.MANIFEST, [v.model_dump() for v in manifest])
    write_json(cfg.EXCLUDED, [e.model_dump() for e in ict_excluded])

    report = build_report(manifest, ict_excluded, ict_enumerated=len(ict_all))
    report.estimated_cost_usd = 0.0  # yt-dlp is free; cost is time, not money
    report.notes.append("backend: yt-dlp (no Apify, no per-video cost)")
    if not args.deep_scan:
        report.notes.append(
            f"title-only matching — {len(ict_excluded)} ICT videos unmatched; "
            "run with --deep-scan to also test descriptions"
        )
    else:
        report.notes.append(f"deep scan recovered {recovered_count} videos via description match")

    write_json(cfg.LOGS / "gate1_report.json", report.model_dump())
    print_gate1(report)

    print("Channel sanity check — confirm these look right before Phase 2:")
    for key in ("ICT", "NBBTRADER"):
        names = sorted({v.channel_name for v in manifest if v.channel_key == key and v.channel_name})
        sample = [v.title[:60] for v in manifest if v.channel_key == key][:3]
        print(f"\n  {key}  (id {cfg.channel(key).channel_id})")
        print(f"    reported channel name(s): {names or '(none returned)'}")
        for s in sample:
            print(f"    - {s}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
