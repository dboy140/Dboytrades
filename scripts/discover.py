"""Phase 1 — Discovery.

Order of operations matters here, because the expensive mistakes are made
early:

  1. Verify the channels resolve, and settle which NBBTRADER channel is real,
     BEFORE enumerating anything. Scraping the wrong channel would attribute
     another person's words to the corpus for the life of the project.
  2. Enumerate metadata only. Metadata is cheap; transcripts are not.
  3. Filter ICT down to the eight buckets, keeping a full record of what was
     cut so the filter can be audited.
  4. Report at Gate 1 and stop.

Idempotent: an existing manifest is reused unless --refresh is passed.
"""

from __future__ import annotations

import argparse
import logging
from typing import Any

from . import config as cfg
from .apify_runner import ApifyBlocked, ApifyRunner, SpendGuard
from .bucketing import match_buckets
from .models import DiscoveryReport, ExcludedVideo, VideoMeta
from .util import dedupe_by_id, read_json, setup_logging, write_json

log = logging.getLogger(__name__)

_ID_FIELDS = ("id", "videoId", "video_id")
_URL_FIELDS = ("url", "videoUrl", "link")
_TITLE_FIELDS = ("title", "name")
_DATE_FIELDS = ("date", "publishedAt", "uploadDate", "publishDate")
_DURATION_FIELDS = ("duration", "durationSeconds", "lengthSeconds")
_VIEWS_FIELDS = ("viewCount", "views", "numberOfViews")
_DESC_FIELDS = ("description", "descriptionText", "text")


def _pick(d: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return None


def _parse_duration(value: Any) -> int | None:
    """Accept seconds, or 'HH:MM:SS' / 'MM:SS' strings."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value).strip()
    if s.isdigit():
        return int(s)
    if ":" in s:
        try:
            total = 0
            for part in s.split(":"):
                total = total * 60 + int(part)
            return total
        except ValueError:
            return None
    return None


def _extract_video_id(item: dict[str, Any]) -> str | None:
    import re

    raw = _pick(item, _ID_FIELDS)
    if raw and re.fullmatch(r"[A-Za-z0-9_-]{11}", str(raw)):
        return str(raw)
    url = _pick(item, _URL_FIELDS)
    if url:
        m = re.search(r"(?:v=|youtu\.be/|/shorts/|/live/|/embed/)([A-Za-z0-9_-]{11})", str(url))
        if m:
            return m.group(1)
    return None


def to_video_meta(item: dict[str, Any], channel_key: str, discovered_via: str) -> VideoMeta | None:
    vid = _extract_video_id(item)
    if not vid:
        log.debug("row without resolvable video id; keys=%s", sorted(item)[:10])
        return None
    url = str(_pick(item, _URL_FIELDS) or f"https://www.youtube.com/watch?v={vid}")
    title = str(_pick(item, _TITLE_FIELDS) or "")
    try:
        return VideoMeta(
            video_id=vid,
            title=title,
            url=url,
            channel_key=channel_key,
            channel_name=str(item.get("channelName") or item.get("channel") or ""),
            published=(str(_pick(item, _DATE_FIELDS)) if _pick(item, _DATE_FIELDS) else None),
            duration_seconds=_parse_duration(_pick(item, _DURATION_FIELDS)),
            view_count=(int(_pick(item, _VIEWS_FIELDS)) if str(_pick(item, _VIEWS_FIELDS) or "").isdigit() else None),
            description=str(_pick(item, _DESC_FIELDS) or "")[:4000],
            discovered_via=discovered_via,
            is_short="/shorts/" in url.lower(),
            is_live=bool(item.get("isLive") or item.get("live")),
        )
    except Exception as exc:
        log.warning("skipping malformed row for %s: %s", vid, exc)
        return None


# ------------------------------------------------------ channel probing ----


def verify_channels(runner: ApifyRunner) -> dict[str, Any]:
    """Resolve which NBBTRADER channel is live before spending anything.

    Probes each candidate for a small sample of videos and reports what came
    back. The operator confirms the winner; this function does not guess.
    """
    probe: dict[str, Any] = {"ict": {}, "nbb_candidates": []}

    ict = cfg.channel("ICT")
    log.info("probing ICT channel %s", ict.channel_id)
    try:
        out = runner.run(
            cfg.ENUMERATION_ACTOR.actor_id,
            {"startUrls": [{"url": ict.url}], "maxResults": 5, "maxResultsShorts": 0, "maxResultStreams": 0},
            operation="probe_ict",
            estimated_cost_usd=0.05,
        )
        probe["ict"] = {
            "channel_id": ict.channel_id,
            "items": len(out.items),
            "sample_titles": [str(_pick(i, _TITLE_FIELDS) or "")[:90] for i in out.items[:5]],
            "channel_names": sorted({str(i.get("channelName") or "") for i in out.items} - {""}),
        }
    except ApifyBlocked:
        raise
    except Exception as exc:
        probe["ict"] = {"channel_id": ict.channel_id, "error": str(exc)[:300]}

    for cid in cfg.NBB_CANDIDATE_IDS:
        log.info("probing NBB candidate %s", cid)
        entry: dict[str, Any] = {"channel_id": cid}
        try:
            out = runner.run(
                cfg.ENUMERATION_ACTOR.actor_id,
                {
                    "startUrls": [{"url": f"https://www.youtube.com/channel/{cid}"}],
                    "maxResults": 5,
                },
                operation=f"probe_nbb_{cid[:6]}",
                estimated_cost_usd=0.05,
            )
            entry.update(
                items=len(out.items),
                sample_titles=[str(_pick(i, _TITLE_FIELDS) or "")[:90] for i in out.items[:5]],
                channel_names=sorted({str(i.get("channelName") or "") for i in out.items} - {""}),
                latest_dates=sorted(
                    [str(_pick(i, _DATE_FIELDS) or "") for i in out.items if _pick(i, _DATE_FIELDS)],
                    reverse=True,
                )[:3],
            )
        except ApifyBlocked:
            raise
        except Exception as exc:
            entry["error"] = str(exc)[:300]
        probe["nbb_candidates"].append(entry)

    write_json(cfg.CHANNEL_PROBE, probe)
    return probe


# ---------------------------------------------------------- enumeration ----


def enumerate_channel(runner: ApifyRunner, channel_key: str, max_results: int) -> list[VideoMeta]:
    ch = cfg.channel(channel_key)
    run_input: dict[str, Any] = {"startUrls": [{"url": ch.url}], "maxResults": max_results}
    if ch.scope == "complete":
        # NBB: take everything, including Shorts and streams.
        run_input.update(maxResultsShorts=max_results, maxResultStreams=max_results)
    else:
        # ICT: long-form only at enumeration time; buckets do the real filtering.
        run_input.update(maxResultsShorts=0, maxResultStreams=0)

    out = runner.run(
        cfg.ENUMERATION_ACTOR.actor_id,
        run_input,
        operation=f"enumerate_{channel_key}",
        estimated_cost_usd=max_results * 0.0005,
    )
    metas = [to_video_meta(i, channel_key, "channel") for i in out.items]
    return [m for m in metas if m]


def search_bucket_queries(runner: ApifyRunner) -> list[VideoMeta]:
    """Issue each bucket keyword as a YouTube search, restricted to ICT.

    Channel enumeration misses videos buried in playlists or titled oddly, so
    the buckets are searched as well as matched.
    """
    found: list[VideoMeta] = []
    for bucket in cfg.ICT_BUCKETS:
        for kw in bucket.keywords:
            query = f"ICT {kw}"
            try:
                out = runner.run(
                    cfg.ENUMERATION_ACTOR.actor_id,
                    {"searchQueries": [query], "maxResults": cfg.SEARCH_QUERY_MAX_RESULTS},
                    operation=f"search_{bucket.key}",
                    estimated_cost_usd=cfg.SEARCH_QUERY_MAX_RESULTS * 0.0005,
                )
            except ApifyBlocked:
                raise
            except Exception as exc:
                log.warning("search %r failed: %s", query, exc)
                continue
            for item in out.items:
                meta = to_video_meta(item, "ICT", f"search:{bucket.key}:{kw}")
                # Only keep hits that really are ICT's own uploads.
                if meta and _looks_like_ict(item, meta):
                    found.append(meta)
    return found


def _looks_like_ict(item: dict[str, Any], meta: VideoMeta) -> bool:
    ict = cfg.channel("ICT")
    name = str(item.get("channelName") or item.get("channel") or "").lower()
    cid = str(item.get("channelId") or item.get("channel_id") or "")
    if cid and cid == ict.channel_id:
        return True
    return "inner circle trader" in name or name.strip() == "ict"


def search_guest_appearances(runner: ApifyRunner) -> list[VideoMeta]:
    """NBB on other people's channels — unreachable by channel enumeration."""
    found: list[VideoMeta] = []
    for query in cfg.GUEST_APPEARANCE_QUERIES:
        try:
            out = runner.run(
                cfg.ENUMERATION_ACTOR.actor_id,
                {"searchQueries": [query], "maxResults": cfg.SEARCH_QUERY_MAX_RESULTS},
                operation="search_guest",
                estimated_cost_usd=cfg.SEARCH_QUERY_MAX_RESULTS * 0.0005,
            )
        except ApifyBlocked:
            raise
        except Exception as exc:
            log.warning("guest search %r failed: %s", query, exc)
            continue
        nbb = cfg.channel("NBBTRADER")
        for item in out.items:
            meta = to_video_meta(item, "NBBTRADER", f"guest_search:{query}")
            if not meta:
                continue
            # Exclude his own channel — those arrive via enumeration already.
            if str(item.get("channelId") or "") == nbb.channel_id:
                continue
            meta.discovered_via = f"guest_search:{query}"
            found.append(meta)
    return found


# ------------------------------------------------------------ filtering ----


def apply_bucket_filter(videos: list[VideoMeta]) -> tuple[list[VideoMeta], list[ExcludedVideo]]:
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


def build_report(manifest: list[VideoMeta], excluded: list[ExcludedVideo], ict_enumerated: int) -> DiscoveryReport:
    ict = [v for v in manifest if v.channel_key == "ICT"]
    nbb = [v for v in manifest if v.channel_key == "NBBTRADER"]

    per_bucket: dict[str, int] = {b.key: 0 for b in cfg.ICT_BUCKETS}
    for v in ict:
        for b in v.buckets:
            per_bucket[b] = per_bucket.get(b, 0) + 1

    runtime_hours = sum(v.duration_hours for v in manifest)

    # Transcript actors bill roughly per video. The real figure comes from the
    # bake-off; this is a placeholder order-of-magnitude only.
    est_cost = len(manifest) * 0.01

    notes: list[str] = []
    thin = [k for k, n in per_bucket.items() if n < 3]
    if thin:
        notes.append(f"thin buckets (<3 videos): {', '.join(thin)}")

    return DiscoveryReport(
        ict_total_enumerated=ict_enumerated,
        ict_in_scope=len(ict),
        ict_excluded=len(excluded),
        ict_per_bucket=per_bucket,
        nbb_total=len(nbb),
        nbb_shorts=sum(1 for v in nbb if v.is_short),
        nbb_guest_appearances=sum(1 for v in nbb if v.discovered_via.startswith("guest_search")),
        total_runtime_hours=round(runtime_hours, 1),
        estimated_cost_usd=round(est_cost, 2),
        notes=notes,
    )


def print_gate1(report: DiscoveryReport) -> None:
    print("\n" + "=" * 66)
    print("GATE 1 — DISCOVERY REPORT")
    print("=" * 66)
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
    print(f"Estimated cost:      ${report.estimated_cost_usd:.2f}")
    for n in report.notes:
        print(f"\n! {n}")
    print("\n" + "=" * 66)
    print("STOP. Awaiting go-ahead before Phase 2 transcript ingestion.")
    print("=" * 66 + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Phase 1 discovery")
    ap.add_argument("--refresh", action="store_true", help="re-enumerate even if a manifest exists")
    ap.add_argument("--skip-search", action="store_true", help="channel enumeration only, no keyword searches")
    ap.add_argument("--dry-run", action="store_true", help="exercise the pipeline without calling Apify")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    setup_logging(args.verbose, logfile="discover.log")
    cfg.ensure_dirs()

    existing = read_json(cfg.MANIFEST, default=None)
    if existing and not args.refresh:
        print(f"manifest already present with {len(existing)} videos; pass --refresh to rebuild")
        return 0

    runner = ApifyRunner(dry_run=args.dry_run)

    probe = runner.probe()
    if not probe["reachable"] and not args.dry_run:
        print("\nCannot reach Apify.\n")
        print(probe["error"])
        print("\nSee docs/BLOCKED.md. Discovery cannot run.")
        return 2

    try:
        log.info("verifying channels before enumeration")
        verify_channels(runner)

        ict_all = enumerate_channel(runner, "ICT", cfg.ICT_ENUMERATION_MAX)
        if not args.skip_search:
            ict_all += search_bucket_queries(runner)
        ict_all = [VideoMeta(**m) for m in dedupe_by_id([v.model_dump() for v in ict_all])]
        ict_enumerated = len(ict_all)

        ict_kept, ict_excluded = apply_bucket_filter(ict_all)

        nbb = enumerate_channel(runner, "NBBTRADER", cfg.NBB_ENUMERATION_MAX)
        if not args.skip_search:
            nbb += search_guest_appearances(runner)
        nbb = [VideoMeta(**m) for m in dedupe_by_id([v.model_dump() for v in nbb])]

    except ApifyBlocked as exc:
        print(f"\nBLOCKED: {exc}\n")
        print("See docs/BLOCKED.md. Not retried — this is a policy decision.")
        return 2
    except SpendGuard as exc:
        print(f"\nSPEND GUARD: {exc}\n")
        return 3

    manifest = ict_kept + nbb
    write_json(cfg.MANIFEST, [v.model_dump() for v in manifest])
    write_json(cfg.EXCLUDED, [e.model_dump() for e in ict_excluded])

    report = build_report(manifest, ict_excluded, ict_enumerated)
    write_json(cfg.LOGS / "gate1_report.json", report.model_dump())
    print_gate1(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
