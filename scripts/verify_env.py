"""Preflight: yt-dlp present, YouTube reachable, config sane.

Exit codes: 0 ready, 2 blocked or yt-dlp missing.
"""

from __future__ import annotations

import argparse
import os
import socket
import ssl
from urllib.request import ProxyHandler, build_opener

from . import config as cfg
from .ytdlp_adapter import ytdlp_available


def check_host(host: str, port: int = 443, timeout: int = 15) -> tuple[bool, str]:
    """Probe a host, honouring HTTPS_PROXY so a policy denial is visible."""
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if proxy:
        try:
            build_opener(ProxyHandler({"https": proxy})).open(f"https://{host}", timeout=timeout)
            return True, "reachable"
        except Exception as exc:
            msg = str(exc)
            if "403" in msg or "407" in msg or "tunnel" in msg.lower():
                return False, f"policy denial via proxy ({msg[:110]})"
            return False, msg[:160]
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host):
                return True, "reachable"
    except Exception as exc:
        return False, str(exc)[:160]


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description="Preflight checks").parse_args(argv)
    cfg.ensure_dirs()

    print("=" * 70)
    print("PREFLIGHT")
    print("=" * 70)

    print("\nConfiguration")
    for ch in cfg.CHANNELS:
        flag = "verified" if ch.verified else "UNVERIFIED"
        print(f"  {ch.key:<10} {ch.channel_id}  scope={ch.scope:<9} [{flag}]")
    print(f"  ICT buckets:                  {len(cfg.ICT_BUCKETS)}")
    print(f"  NBB candidate ids to resolve: {len(cfg.NBB_CANDIDATE_IDS)}")
    extras = sum(len(b.extra_keywords) for b in cfg.ICT_BUCKETS)
    if extras:
        print(f"  pipeline-added keywords:      {extras}  (review: see README)")

    print("\nTooling")
    ok, version = ytdlp_available()
    print(f"  {'OK  ' if ok else 'FAIL'} yt-dlp  {version}")
    if not ok:
        print("\n       pip install -U yt-dlp")
        return 2

    print("\nNetwork")
    reachable, detail = check_host("www.youtube.com")
    print(f"  {'OK  ' if reachable else 'FAIL'} www.youtube.com   {detail}")
    if not reachable:
        print(
            "\nYouTube is not reachable from here, so discovery cannot run.\n"
            "This is an egress policy decision, not a transient fault.\n"
            "Run the pipeline on a machine with normal network access.\n"
            "See docs/BLOCKED.md."
        )
        return 2

    print("\nReady.")
    print("  next:  python -m scripts.discover")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
