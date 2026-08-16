"""Preflight: token, egress, actor availability. Run this before spending.

Exit codes: 0 ready, 2 blocked or unauthenticated, 3 actors unavailable.
"""

from __future__ import annotations

import argparse
import socket
import ssl
from urllib.request import ProxyHandler, build_opener

from . import config as cfg
from .apify_runner import ApifyBlocked, ApifyRunner


def check_host(host: str, port: int = 443, timeout: int = 15) -> tuple[bool, str]:
    """Probe a host, honouring HTTPS_PROXY so a policy denial is visible."""
    import os

    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if proxy:
        try:
            opener = build_opener(ProxyHandler({"https": proxy}))
            opener.open(f"https://{host}", timeout=timeout)
            return True, "reachable"
        except Exception as exc:
            msg = str(exc)
            if "403" in msg or "407" in msg or "tunnel" in msg.lower():
                return False, f"policy denial via proxy ({msg[:120]})"
            return False, msg[:160]
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host):
                return True, "reachable"
    except Exception as exc:
        return False, str(exc)[:160]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Preflight checks")
    ap.add_argument("--skip-actors", action="store_true")
    args = ap.parse_args(argv)

    cfg.ensure_dirs()
    print("=" * 70)
    print("PREFLIGHT")
    print("=" * 70)

    print("\nConfiguration")
    for ch in cfg.CHANNELS:
        flag = "verified" if ch.verified else "UNVERIFIED"
        print(f"  {ch.key:<10} {ch.channel_id}  scope={ch.scope:<9} [{flag}]")
    print(f"  ICT buckets: {len(cfg.ICT_BUCKETS)}")
    print(f"  NBB candidate ids to resolve: {len(cfg.NBB_CANDIDATE_IDS)}")

    print("\nNetwork")
    exit_code = 0
    for host in ("api.apify.com", "www.youtube.com"):
        ok, detail = check_host(host)
        print(f"  {'OK  ' if ok else 'FAIL'} {host:<20} {detail}")
        if not ok and host == "api.apify.com":
            exit_code = 2

    print("\nCredentials")
    runner = ApifyRunner()
    status = runner.probe()
    if not status["token_present"]:
        print("  FAIL APIFY_TOKEN not set")
        print("       cp .env.example .env  and add your token")
        return 2
    print("  OK   APIFY_TOKEN present")

    if not status["reachable"]:
        print(f"  FAIL Apify unreachable\n       {status['error'][:400]}")
        return 2
    print(f"  OK   authenticated as {status['user']}")

    if args.skip_actors:
        return exit_code

    print("\nActors")
    try:
        ok, title = runner.actor_exists(cfg.ENUMERATION_ACTOR.actor_id)
        print(f"  {'OK  ' if ok else 'FAIL'} enumeration  {cfg.ENUMERATION_ACTOR.label}  {title or ''}")
        if not ok:
            exit_code = 3
        for cand in cfg.TRANSCRIPT_ACTOR_CANDIDATES:
            ok, title = runner.actor_exists(cand.actor_id)
            print(f"  {'OK  ' if ok else '--  '} transcript   {cand.label}  {title or ''}")
    except ApifyBlocked as exc:
        print(f"  FAIL {exc}")
        return 2

    print("\nReady." if exit_code == 0 else "\nNot ready — see failures above.")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
