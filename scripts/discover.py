"""Phase 1 — Discovery. yt-dlp only.

  1. Enumerate ICT (metadata only) and filter to the eight topic buckets.
  2. Enumerate NBBTRADER completely — videos, Shorts, streams.
  3. Probe both NBBTRADER candidate channel IDs so the operator can settle
     which is live before anything downstream depends on it.
  4. Search for NBB's guest appearances on other channels.
  5. Report at Gate 1 and stop.

Idempotent: an existing non-empty manifest short-circuits unless --refresh.
"""

from __future__ import annotations

import argparse
import logging

from . import config as cfg
from .bucketing import match_buckets
from .models import DiscoveryReport, ExcludedVideo, VideoMeta
from .util import read_json, setup_logging, write_json
from .ytdlp_adapter import (
    YtdlpBlocked,
    YtdlpError,
    enumerate_channel,
    enumerate_tab,
    fetch_metadata,
    flat_entry_to_meta,
    search_videos,
    ytdlp_available,
)

log = logging.getLogger(__name__)


# ------------------------------------------------------------ filtering ----


def apply_bucket_filter(videos: list[VideoMeta]) -> tuple[list[VideoMeta], list[ExcludedVideo]]:
    """Split ICT videos into in-scope (bucket-tagged) and excluded."""
    kept: list[VideoMeta] = []
    excluded: list[ExcludedVideo] = []
    for v in videos:
        matches = match_buckets(v.title, v.description)
        if matches:
            v.buckets = [m.bucket_key for m in matches]
            kept.append(v)
        else:
            excluded.append(
                ExcludedVideo(
                    video_id=v.video_id,
                    title=v.title,
                    published=v.published,
                    duration_seconds=v.duration_seconds,
                    url=v.url,
                    reason="no_bucket_match",
                )
            )
    return kept, excluded


def deep_scan_unmatched(unmatched: list[VideoMeta], limit: int | None = None) -> list[VideoMeta]:
    """Fetch descriptions for title-unmatched videos and re-test the filter.

    Flat enumeration returns no description, so a video whose title is vague
    but whose description names the concept is invisible without this pass. One
    request per video, hence opt-in and bounded.
    """
    recovered: list[VideoMeta] = []
    targets = unmatched[:limit] if limit else unmatched

    for i, meta in enumerate(targets, 1):
        if i % 25 == 0:
            log.info("deep scan %d/%d, recovered %d", i, len(targets), len(recovered))
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
        if matches := match_buckets(meta.title, description):
            meta.description = description
            meta.buckets = [m.bucket_key for m in matches]
            meta.discovered_via += "+deep_scan"
            recovered.append(meta)

        raw = str(info.get("upload_date") or "")
        if not meta.published and len(raw) == 8 and raw.isdigit():
            meta.published = f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"

    return recovered


# ------------------------------------------------------ channel probing ----


def probe_nbb_candidates() -> dict[str, dict]:
    """Sample both candidate NBBTRADER channels so the operator can adjudicate.

    Scraping the wrong channel would attribute another person's words to the
    corpus permanently, so this reports and does not guess.
    """
    probe: dict[str, dict] = {}
    for cid in cfg.NBB_CANDIDATE_IDS:
        log.info("probing NBB candidate %s", cid)
        entry: dict = {"channel_id": cid}
        try:
            entries = enumerate_tab(cid, "videos", max_results=5)
            entry["video_count_sampled"] = len(entries)
            entry["channel_names"] = sorted(
                {str(e.get("channel") or e.get("uploader") or "") for e in entries} - {""}
            )
            entry["sample_titles"] = [str(e.get("title") or "")[:90] for e in entries[:5]]
        except YtdlpBlocked:
            raise
        except Exception as exc:
            entry["error"] = str(exc)[:300]
        probe[cid] = entry
    return probe


def find_guest_appearances(max_per_query: int = 30) -> list[VideoMeta]:
    """NBB on other people's channels — invisible to channel enumeration."""
    nbb_id = cfg.channel("NBBTRADER").channel_id
    found: list[VideoMeta] = []
    seen: set[str] = set()

    for query in cfg.GUEST_APPEARANCE_QUERIES:
        log.info("searching guest appearances: %r", query)
        try:
            entries = search_videos(query, max_per_query)
        except YtdlpBlocked:
            raise
        except Exception as exc:
            log.warning("search %r failed: %s", query, exc)
            continue

        for entry in entries:
            meta = flat_entry_to_meta(entry, "NBBTRADER", f"guest_search:{query}")
            if not meta or meta.video_id in seen:
                continue
            # His own channel arrives via enumeration; skip duplicates here.
            if str(entry.get("channel_id") or "") == nbb_id:
                continue
            seen.add(meta.video_id)
            found.append(meta)
    return found


# --------------------------------------------------------------- report ----


def build_report(
    manifest: list[VideoMeta], excluded: list[ExcludedVideo], ict_enumerated: int
) -> DiscoveryReport:
    ict = [v for v in manifest if v.channel_key == "ICT"]
    nbb = [v for v in manifest if v.channel_key == "NBBTRADER"]

    per_bucket: dict[str, int] = {b.key: 0 for b in cfg.ICT_BUCKETS}
    for v in ict:
        for b in v.buckets:
            per_bucket[b] = per_bucket.get(b, 0) + 1

    notes: list[str] = []
    if thin := [k for k, n in per_bucket.items() if n < 3]:
        notes.append(f"thin buckets (<3 videos): {', '.join(thin)}")

    return DiscoveryReport(
        ict_total_enumerated=ict_enumerated,
        ict_in_scope=len(ict),
        ict_excluded=len(excluded),
        ict_per_bucket=per_bucket,
        nbb_total=len(nbb),
        nbb_shorts=sum(1 for v in nbb if v.is_short),
        nbb_guest_appearances=sum(1 for v in nbb if v.discovered_via.startswith("guest_search")),
        total_runtime_hours=round(sum(v.duration_hours for v in manifest), 1),
        estimated_cost_usd=0.0,  # yt-dlp: costs time, not money
        notes=notes,
    )


def print_gate1(report: DiscoveryReport, probe: dict[str, dict] | None = None) -> None:
    print("\n" + "=" * 68)
    print("GATE 1 — DISCOVERY REPORT")
    print("=" * 68)
    print(f"\nICT enumerated:      {report.ict_total_enumerated}")
    print(f"ICT in scope:        {report.ict_in_scope}")
    print(f"ICT excluded:        {report.ict_excluded}   (see data/excluded.json)")
    print("\nPer bucket:")
    for b in cfg.ICT_BUCKETS:
        print(f"  {b.display_name:<34} {report.ict_per_bucket.get(b.key, 0):>5}")
    print(f"\nNBBTRADER total:     {report.nbb_total}")
    print(f"  of which Shorts:   {report.nbb_shorts}")
    print(f"  guest appearances: {report.nbb_guest_appearances}")
    print(f"\nTotal runtime:       {report.total_runtime_hours:.1f} hours")
    print(f"Estimated cost:      $0.00  (yt-dlp)")
    for n in report.notes:
        print(f"\n! {n}")

    if probe:
        print("\n" + "-" * 68)
        print("NBBTRADER channel resolution — which of these is the real one?")
        for cid, entry in probe.items():
            print(f"\n  {cid}")
            if entry.get("error"):
                print(f"    ERROR: {entry['error'][:160]}")
                continue
            print(f"    sampled videos: {entry.get('video_count_sampled', 0)}")
            print(f"    channel name:   {entry.get('channel_names') or '(none returned)'}")
            for t in entry.get("sample_titles", []):
                print(f"      - {t}")

    print("\n" + "=" * 68)
    print("STOP. Awaiting go-ahead before Phase 2 transcript ingestion.")
    print("=" * 68 + "\n")


# ------------------------------------------------------------------ cli ----


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Phase 1 discovery (yt-dlp)")
    ap.add_argument("--refresh", action="store_true", help="re-enumerate even if a manifest exists")
    ap.add_argument(
        "--deep-scan",
        action="store_true",
        help="second pass fetching descriptions for title-unmatched ICT videos",
    )
    ap.add_argument("--deep-scan-limit", type=int)
    ap.add_argument("--skip-guest-search", action="store_true")
    ap.add_argument("--ict-max", type=int, default=cfg.ICT_ENUMERATION_MAX)
    ap.add_argument("--nbb-max", type=int, default=cfg.NBB_ENUMERATION_MAX)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    setup_logging(args.verbose, logfile="discover.log")
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
        probe = probe_nbb_candidates()

        log.info("enumerating ICT")
        ict_all = enumerate_channel("ICT", args.ict_max)
        log.info("ICT enumerated: %d", len(ict_all))

        ict_kept, ict_excluded = apply_bucket_filter(ict_all)
        log.info("ICT title-matched: %d, unmatched: %d", len(ict_kept), len(ict_excluded))

        recovered_count = 0
        if args.deep_scan and ict_excluded:
            excluded_ids = {e.video_id for e in ict_excluded}
            unmatched = [v for v in ict_all if v.video_id in excluded_ids]
            recovered = deep_scan_unmatched(unmatched, args.deep_scan_limit)
            recovered_count = len(recovered)
            if recovered:
                rec_ids = {v.video_id for v in recovered}
                ict_kept += recovered
                ict_excluded = [e for e in ict_excluded if e.video_id not in rec_ids]

        log.info("enumerating NBBTRADER")
        nbb = enumerate_channel("NBBTRADER", args.nbb_max)
        if not args.skip_guest_search:
            guests = find_guest_appearances()
            known = {v.video_id for v in nbb}
            nbb += [g for g in guests if g.video_id not in known]
        log.info("NBB total: %d", len(nbb))

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
    write_json(cfg.CHANNEL_PROBE, probe)

    report = build_report(manifest, ict_excluded, ict_enumerated=len(ict_all))
    if args.deep_scan:
        report.notes.append(f"deep scan recovered {recovered_count} videos via description")
    else:
        report.notes.append(
            f"title-only matching — {len(ict_excluded)} ICT videos unmatched; "
            "rerun with --deep-scan to also test descriptions"
        )

    write_json(cfg.LOGS / "gate1_report.json", report.model_dump())
    print_gate1(report, probe)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
