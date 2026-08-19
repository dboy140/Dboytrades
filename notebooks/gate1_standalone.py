"""Gate 1, self-contained. No repo, no clone, no GitHub, no API key.

GENERATED FILE -- edit scripts/gate1_template.py and run
`python -m scripts.gen_standalone` instead of editing this directly.

Paste into a blank Google Colab cell and run.

Usage:
    python gate1.py              # title matching only (fast)
    python gate1.py --deep-scan  # also read descriptions (slower, better recall)
"""

import json
import re
import shutil
import subprocess
import sys


def ensure_ytdlp():
    """Install yt-dlp if it is not already present.

    A fresh Colab runtime has no yt-dlp, and "Disconnect and delete runtime"
    (the standard fix for a bot challenge) wipes it again. Making the script
    self-sufficient removes a step that is easy to forget and produces a
    confusing failure when it is.
    """
    if shutil.which("yt-dlp"):
        return
    print("yt-dlp not found -- installing, takes about 20 seconds...")
    proc = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q", "--upgrade", "yt-dlp"],
        capture_output=True, text=True)
    if not shutil.which("yt-dlp"):
        sys.exit("Could not install yt-dlp automatically. Run this in a cell first:\n"
                 "    !pip install -U yt-dlp\n\n" + (proc.stderr or "")[:600])
    print("  installed.\n")

# --------------------------------------------------------------- config ----

ICT_CHANNEL = "UCtjxa77NqamhVC8atV85Rog"
NBB_CANDIDATES = ["UCo6TS8uarO5r562d4lESg9w", "UCmtJ3lDd2fjt-IMf6lfzlcA"]
ICT_MAX = 1200
NBB_MAX = 1500
GUEST_QUERIES = ["NBBTRADER", "NBB trader interview", "NBB trader podcast", "NBBTRADER Words of Rizdom", "Words of Rizdom trading NBB", "NBB trader strategy explained"]
SEARCH_MAX = 30

BUCKETS = {
    "Money Maker Model (MMxM)": [
        "money maker model", "MMxM", "market maker model", "market maker buy model",
        "MMBM", "market maker sell model", "MMSM", "smart money reversal",
        "original consolidation", "low resistance liquidity run",
        "high resistance liquidity run", "resistance liquidity run",
        "smart money reversals",
    ],
    "ICT Silver Bullet": [
        "silver bullet", "ICT silver bullet", "silver bullet 10am",
        "silver bullet 3am", "silver bullet 2pm", "silver bullet setup",
        "silver bullet strategy",
    ],
    "Fair Value Gaps": [
        "fair value gap", "FVG", "imbalance", "balanced price range", "BPR",
        "consequent encroachment", "liquidity void", "inefficiency", "inefficiencies",
    ],
    "Inversion Fair Value Gaps": [
        "inversion fair value gap", "IFVG", "inverted fair value gap", "inversion FVG",
        "FVG inversion",
    ],
    "London Session": [
        "London killzone", "London open", "London session", "London open killzone",
        "London judas swing", "London close", "LDN killzone", "LDN open",
        "LDN session", "judas swing",
    ],
    "New York Session": [
        "New York killzone", "New York open", "New York session", "NY AM session",
        "NY PM session", "NY lunch", "opening range gap", "New York AM", "New York PM",
        "NY AM", "NY PM", "NY killzone", "NY open", "NY session",
        "New York AM session", "New York PM session", "AM session", "PM session",
        "ORG", "RTH ORG",
    ],
    "Higher Timeframe": [
        "higher timeframe bias", "HTF bias", "daily bias", "weekly profile",
        "monthly bias", "HTF narrative", "top down analysis",
    ],
    "Smart Money Concepts": [
        "smart money concepts", "SMC", "institutional order flow", "IPDA",
        "order block", "market structure shift", "displacement",
        "premium and discount", "dealing range", "buyside liquidity",
        "sellside liquidity",
    ],
}

# ------------------------------------------------------------- matching ----

# Word boundaries, not substrings: "FVG" must not fire inside "IFVG".
# Trailing s? because real titles pluralise ("Fair Value Gaps").
_PATTERNS = {
    name: [re.compile(r"(?<!\w)" + r"\s+".join(map(re.escape, kw.split())) + r"s?(?!\w)", re.I)
           for kw in kws]
    for name, kws in BUCKETS.items()
}


def match_buckets(title, description=""):
    hits = []
    for name, pats in _PATTERNS.items():
        if any(p.search(title or "") or p.search(description or "") for p in pats):
            hits.append(name)
    return hits


# --------------------------------------------------------------- yt-dlp ----

def run_ytdlp(args, timeout=1800):
    try:
        return subprocess.run(
            ["yt-dlp", "--ignore-config", "--no-warnings", "--no-progress"] + args,
            capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        sys.exit("yt-dlp vanished mid-run. Rerun the cell.")
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args, 1, "", "timed out")


def is_blocked(stderr):
    low = (stderr or "").lower()
    return ("sign in to confirm" in low or "not a bot" in low
            or "tunnel connection failed" in low or "unable to connect to proxy" in low)


def _jsonlines(text):
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def enumerate_tab(channel_id, tab, limit):
    url = "https://www.youtube.com/channel/%s/%s" % (channel_id, tab)
    proc = run_ytdlp(["--flat-playlist", "--dump-json", "--playlist-end", str(limit), url])
    if is_blocked(proc.stderr):
        raise RuntimeError("BLOCKED_BY_YOUTUBE")
    return _jsonlines(proc.stdout)


def search_videos(query, limit):
    proc = run_ytdlp(["--flat-playlist", "--dump-json", "ytsearch%d:%s" % (limit, query)])
    if is_blocked(proc.stderr):
        raise RuntimeError("BLOCKED_BY_YOUTUBE")
    return _jsonlines(proc.stdout)


def video_details(video_id):
    """Full metadata for one video: uploader name and description."""
    proc = run_ytdlp(["--dump-json", "--skip-download",
                      "https://www.youtube.com/watch?v=" + video_id], timeout=120)
    if is_blocked(proc.stderr):
        raise RuntimeError("BLOCKED_BY_YOUTUBE")
    rows = _jsonlines(proc.stdout)
    return rows[0] if rows else None


def to_video(entry, tab=""):
    vid = str(entry.get("id") or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", vid):
        return None
    d = entry.get("duration")
    return {
        "video_id": vid,
        "title": str(entry.get("title") or ""),
        "url": str(entry.get("url") or "https://www.youtube.com/watch?v=" + vid),
        "channel_name": str(entry.get("channel") or entry.get("uploader") or ""),
        "channel_id": str(entry.get("channel_id") or ""),
        "duration_seconds": int(d) if isinstance(d, (int, float)) else None,
        "is_short": tab == "shorts",
        "description": "",
        "buckets": [],
    }


def identify_channel(channel_id):
    """Resolve a channel's real name.

    Flat enumeration often returns an empty channel name, which is useless for
    confirming identity -- so fall back to full metadata on one video, where
    the uploader is always present.
    """
    try:
        sample = enumerate_tab(channel_id, "videos", 3)
    except RuntimeError:
        raise
    except Exception as exc:
        return {"channel_id": channel_id, "error": str(exc)[:200]}

    info = {"channel_id": channel_id, "sampled": len(sample),
            "titles": [str(e.get("title") or "")[:80] for e in sample[:3]]}
    if not sample:
        info["name"] = "(no videos -- channel empty, wrong id, or removed)"
        return info

    vid = str(sample[0].get("id") or "")
    detail = video_details(vid) if vid else None
    if detail:
        info["name"] = str(detail.get("uploader") or detail.get("channel") or "(unknown)")
        info["handle"] = str(detail.get("uploader_id") or "")
        info["channel_url"] = str(detail.get("channel_url") or "")
        info["subscribers"] = detail.get("channel_follower_count")
    else:
        info["name"] = "(could not resolve)"
    return info


# ----------------------------------------------------------------- main ----

def main():
    deep = "--deep-scan" in sys.argv
    line = "=" * 68

    ensure_ytdlp()

    print("Checking YouTube is reachable...")
    try:
        probe = enumerate_tab(ICT_CHANNEL, "videos", 1)
    except RuntimeError:
        sys.exit("\nBLOCKED: YouTube is challenging this machine as a bot.\n"
                 "Fix: Runtime -> Disconnect and delete runtime, then run again.")
    if not probe:
        sys.exit("Got no videos back. Paste this whole output into the chat.")

    print("Confirming channel identities (this is the bit that catches a wrong id)...")
    ict_info = identify_channel(ICT_CHANNEL)
    print("  ICT  %s -> %s" % (ICT_CHANNEL, ict_info.get("name")))
    nbb_info = {}
    for cid in NBB_CANDIDATES:
        try:
            nbb_info[cid] = identify_channel(cid)
        except RuntimeError:
            sys.exit("BLOCKED while probing channels. Recycle the runtime and retry.")
        print("  NBB  %s -> %s" % (cid, nbb_info[cid].get("name")))
    print()

    print("Listing ICT videos (slow)...")
    ict_raw = []
    for tab in ("videos", "streams"):
        try:
            ict_raw += enumerate_tab(ICT_CHANNEL, tab, ICT_MAX)
        except RuntimeError:
            sys.exit("BLOCKED partway through. Recycle the runtime and retry.")
    ict, seen = [], set()
    for e in ict_raw:
        v = to_video(e)
        if v and v["video_id"] not in seen:
            seen.add(v["video_id"])
            ict.append(v)
    print("  %d ICT videos found" % len(ict))

    kept, excluded = [], []
    for v in ict:
        b = match_buckets(v["title"])
        if b:
            v["buckets"] = b
            kept.append(v)
        else:
            excluded.append(v)
    print("  %d matched on title, %d unmatched" % (len(kept), len(excluded)))

    recovered = 0
    if deep and excluded:
        print("\nDeep scan: reading descriptions of %d unmatched videos." % len(excluded))
        print("This takes roughly %d-%d minutes. Progress every 25:"
              % (len(excluded) // 60, len(excluded) // 20))
        still_out = []
        for i, v in enumerate(excluded, 1):
            if i % 25 == 0:
                print("  %d/%d, recovered %d" % (i, len(excluded), recovered), flush=True)
            try:
                detail = video_details(v["video_id"])
            except RuntimeError:
                print("  blocked during deep scan -- keeping what we have")
                still_out += excluded[i - 1:]
                break
            desc = str((detail or {}).get("description") or "")[:4000]
            b = match_buckets(v["title"], desc)
            if b:
                v["description"] = desc
                v["buckets"] = b
                kept.append(v)
                recovered += 1
            else:
                still_out.append(v)
        excluded = still_out
        print("  deep scan recovered %d videos" % recovered)

    print("\nListing NBBTRADER videos...")
    nbb, seen_n = [], set()
    for tab in ("videos", "shorts", "streams"):
        try:
            for e in enumerate_tab(NBB_CANDIDATES[0], tab, NBB_MAX):
                v = to_video(e, tab)
                if v and v["video_id"] not in seen_n:
                    seen_n.add(v["video_id"])
                    nbb.append(v)
        except RuntimeError:
            print("  blocked on /%s, continuing" % tab)
    print("  %d from his own channel" % len(nbb))

    print("Searching for guest appearances on other channels...")
    guests = []
    for q in GUEST_QUERIES:
        try:
            for e in search_videos(q, SEARCH_MAX):
                v = to_video(e)
                if not v or v["video_id"] in seen_n:
                    continue
                if v["channel_id"] == NBB_CANDIDATES[0]:
                    continue
                seen_n.add(v["video_id"])
                v["found_via"] = q
                guests.append(v)
        except RuntimeError:
            print("  blocked during search, continuing")
            break
        except Exception:
            continue
    print("  %d candidate guest appearances" % len(guests))

    per_bucket = {name: 0 for name in BUCKETS}
    for v in kept:
        for b in v["buckets"]:
            per_bucket[b] += 1
    hours = sum((v["duration_seconds"] or 0) for v in kept + nbb) / 3600.0

    print("\n" + line)
    print("GATE 1 -- DISCOVERY REPORT")
    print(line)
    print("\nICT enumerated:      %d" % len(ict))
    print("ICT in scope:        %d" % len(kept))
    print("ICT excluded:        %d" % len(excluded))
    if deep:
        print("  recovered by desc: %d" % recovered)
    print("\nPer bucket:")
    for name in BUCKETS:
        print("  %-34s %5d" % (name, per_bucket[name]))
    print("\nNBBTRADER own channel: %d" % len(nbb))
    print("  of which Shorts:     %d" % sum(1 for v in nbb if v["is_short"]))
    print("Guest appearances:     %d  (unverified -- need eyeballing)" % len(guests))
    print("\nTotal runtime:       %.1f hours" % hours)
    print("Estimated cost:      $0.00  (yt-dlp)")
    thin = [n for n, c in per_bucket.items() if c < 3]
    if thin:
        print("\n! thin buckets (<3 videos): %s" % ", ".join(thin))
    if not deep:
        print("! title-only matching -- rerun with --deep-scan to read descriptions")

    print("\n" + "-" * 68)
    print("CHANNEL IDENTITIES")
    print("  ICT  %s" % ICT_CHANNEL)
    print("       name: %s" % ict_info.get("name"))
    print("       handle: %s" % ict_info.get("handle", ""))
    for cid, info in nbb_info.items():
        print("\n  NBB candidate %s" % cid)
        if info.get("error"):
            print("       ERROR: %s" % info["error"])
            continue
        print("       name: %s" % info.get("name"))
        print("       handle: %s" % info.get("handle", ""))
        print("       subscribers: %s" % info.get("subscribers"))
        print("       videos sampled: %s" % info.get("sampled"))
        for t in info.get("titles", []):
            print("         - %s" % t)

    if guests:
        print("\n" + "-" * 68)
        print("GUEST APPEARANCE CANDIDATES -- are these the right person?")
        for v in guests[:15]:
            print("  - [%s] %s" % (v["channel_name"][:22], v["title"][:60]))

    print("\n" + line)
    print("EXCLUDED SAMPLE -- first 40 ICT videos the filter cut:")
    print(line)
    for v in excluded[:40]:
        print("  - %s" % v["title"][:88])
    if len(excluded) > 40:
        print("  ... and %d more" % (len(excluded) - 40))

    with open("gate1_manifest.json", "w") as fh:
        json.dump({"ict_in_scope": kept, "ict_excluded": excluded, "nbb": nbb,
                   "guests": guests, "ict_info": ict_info, "nbb_info": nbb_info},
                  fh, indent=2)
    print("\nSaved gate1_manifest.json")
    print("\nCopy everything above and paste it into the chat.")


if __name__ == "__main__":
    main()
