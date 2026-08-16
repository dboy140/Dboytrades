"""Command line interface.

    python -m ictkb <command>

Commands are ordered by pipeline stage: doctor -> ingest -> mine -> validate ->
distill.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import config as cfg
from .apify import ApifyClient, ApifyError, ApifyAccessDenied
from .distill import build_system, write_system
from .ingest import fetch_channel_videos, fetch_transcripts, load_segments, save_segments, save_videos
from .search import BM25Index
from .validate import Severity, validate


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def cmd_doctor(args: argparse.Namespace) -> int:
    """Probe credentials, egress and actor availability before spending money."""
    conf = cfg.load_config()
    print("Configuration")
    for src in conf.sources:
        mark = "ok" if src.verified else "UNVERIFIED"
        print(f"  source {src.key:<10} {src.url}  [{mark}]")
    for name, spec in conf.actors.items():
        mark = "ok" if spec.verified else "UNVERIFIED"
        print(f"  actor  {name:<16} {spec.id}  [{mark}]")
    print()

    try:
        token = cfg.apify_token()
    except cfg.ConfigError as exc:
        print(f"FAIL  {exc}")
        return 2

    client = ApifyClient(token)
    try:
        me = client.whoami()
        print(f"OK    Apify reachable; authenticated as {me.get('username') or me.get('id')}")
    except ApifyAccessDenied as exc:
        print(f"FAIL  {exc}")
        print(
            "\nThis is an access or egress-policy problem, not a transient one.\n"
            "Confirm APIFY_TOKEN is valid and that api.apify.com is allowlisted."
        )
        return 2
    except ApifyError as exc:
        print(f"FAIL  Apify unreachable: {exc}")
        return 2

    exit_code = 0
    for name, spec in conf.actors.items():
        candidates = [spec.id] + list(spec.fallbacks)
        working = None
        for actor_id in candidates:
            try:
                meta = client.get_actor(actor_id)
                working = actor_id
                print(f"OK    actor {name}: {actor_id} exists (\"{meta.get('title', '')}\")")
                break
            except ApifyError as exc:
                print(f"      actor {name}: {actor_id} unavailable ({str(exc)[:120]})")
        if not working:
            print(f"FAIL  no working actor for {name!r}; update config/sources.yaml")
            exit_code = 2
    return exit_code


def cmd_ingest(args: argparse.Namespace) -> int:
    conf = cfg.load_config()
    cfg.ensure_dirs()
    try:
        client = ApifyClient(cfg.apify_token())
    except cfg.ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    sources = args.sources or conf.source_keys
    try:
        videos = fetch_channel_videos(client, conf, sources, limit=args.limit)
    except ApifyError as exc:
        print(f"error: channel listing failed: {exc}", file=sys.stderr)
        return 2
    if not videos:
        print("error: no videos resolved; nothing to transcribe", file=sys.stderr)
        return 1

    save_videos(videos)
    print(f"resolved {len(videos)} videos")

    if args.videos_only:
        return 0

    segments = fetch_transcripts(client, conf, videos)
    if not segments:
        print("error: no transcripts retrieved", file=sys.stderr)
        return 1
    n = save_segments(segments)
    print(f"wrote {n} segments to {cfg.SEGMENTS_PATH}")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    segments = load_segments()
    if not segments:
        print(
            f"error: no corpus at {cfg.SEGMENTS_PATH}. Run `ingest` first.", file=sys.stderr
        )
        return 1
    index = BM25Index(segments)
    hits = index.search(args.query, top_k=args.top, source_key=args.source)
    if not hits:
        print("no matches")
        return 0
    for h in hits:
        print(f"[{h.score:7.3f}] {h.source_key} {h.citation()}  {h.url}")
        if h.video_title:
            print(f"           {h.video_title}")
        print(f"           {h.text[:300]}")
        print()
    return 0


def cmd_mine(args: argparse.Namespace) -> int:
    """Surface candidate evidence per concept, for human claim authoring."""
    conf = cfg.load_config()
    segments = load_segments()
    if not segments:
        print(f"error: no corpus at {cfg.SEGMENTS_PATH}. Run `ingest` first.", file=sys.stderr)
        return 1
    index = BM25Index(segments)
    queries = conf.concept_queries()
    for concept, aliases in queries.items():
        if args.concept and concept != args.concept:
            continue
        hits = index.search_any(aliases, top_k=args.top, source_key=args.source)
        print(f"\n=== {concept} ({len(hits)} hits) ===")
        for h in hits:
            print(f"  [{h.score:7.3f}] {h.source_key} {h.citation()} {h.url}")
            print(f"             {h.text[:240]}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    report = validate(strict_empty=args.strict_empty)
    for f in report.findings:
        stream = sys.stderr if f.severity is Severity.ERROR else sys.stdout
        print(str(f), file=stream)
    print()
    print(report.summary())
    if not report.ok:
        print("\nVALIDATION FAILED — the system is not citable end to end.", file=sys.stderr)
        return 1
    print("\nvalidation passed")
    return 0


def cmd_distill(args: argparse.Namespace) -> int:
    report = validate()
    if not report.ok and not args.force:
        for f in report.errors:
            print(str(f), file=sys.stderr)
        print(
            "\nrefusing to distil with validation errors; fix them or pass --force",
            file=sys.stderr,
        )
        return 1

    system = build_system()
    json_path, md_path = write_system(system)
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    comp = system["completeness"]
    if not comp["executable"]:
        missing = ", ".join(comp["missing_phases"]) or "no accepted rules"
        print(f"\nsystem is NOT executable — missing: {missing}")
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ictkb", description=__doc__)
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("doctor", help="check credentials, egress and actor availability")
    d.set_defaults(func=cmd_doctor)

    i = sub.add_parser("ingest", help="scrape channels and transcripts into the corpus")
    i.add_argument("--sources", nargs="*", help="source keys (default: all configured)")
    i.add_argument("--limit", type=int, help="max videos per channel")
    i.add_argument("--videos-only", action="store_true", help="list videos, skip transcripts")
    i.set_defaults(func=cmd_ingest)

    s = sub.add_parser("search", help="BM25 search the corpus")
    s.add_argument("query")
    s.add_argument("--top", type=int, default=15)
    s.add_argument("--source")
    s.set_defaults(func=cmd_search)

    m = sub.add_parser("mine", help="surface candidate evidence per taxonomy concept")
    m.add_argument("--concept")
    m.add_argument("--top", type=int, default=10)
    m.add_argument("--source")
    m.set_defaults(func=cmd_mine)

    v = sub.add_parser("validate", help="enforce provenance across claims and rules")
    v.add_argument(
        "--strict-empty",
        action="store_true",
        help="treat an empty corpus/KB as an error (use in CI once ingestion works)",
    )
    v.set_defaults(func=cmd_validate)

    x = sub.add_parser("distill", help="compile accepted rules into the system bundle")
    x.add_argument("--force", action="store_true", help="build despite validation errors")
    x.set_defaults(func=cmd_distill)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    try:
        return int(args.func(args))
    except cfg.ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
