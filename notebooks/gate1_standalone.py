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


def channel_info(channel_id):
    """Channel name / handle / subscriber count via --dump-single-json.

    Deliberately avoids fetching an individual video page: on datacentre IPs
    (Colab) YouTube serves channel listings but challenges per-video requests,
    so anything that opens a video is unreliable there.
    """
    url = "https://www.youtube.com/channel/%s/videos" % channel_id
    proc = run_ytdlp(["--flat-playlist", "--dump-single-json",
                      "--playlist-end", "3", url], timeout=180)
    if is_blocked(proc.stderr):
        raise RuntimeError("BLOCKED_BY_YOUTUBE")
    try:
        return json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError):
        return None


def channel_search(channel_id, query, limit):
    """Search WITHIN a channel. YouTube matches descriptions server-side.

    This is how descriptions get covered without opening any video page: one
    listing request per keyword instead of one video fetch per unmatched
    video -- roughly 90 requests rather than 800, and it uses the only call
    that works reliably from a datacentre IP.
    """
    from urllib.parse import quote
    url = "https://www.youtube.com/channel/%s/search?query=%s" % (channel_id, quote(query))
    proc = run_ytdlp(["--flat-playlist", "--dump-json",
                      "--playlist-end", str(limit), url], timeout=300)
    if is_blocked(proc.stderr):
        raise RuntimeError("BLOCKED_BY_YOUTUBE")
    return _jsonlines(proc.stdout)


def to_video(entry, tab="", position=0):
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
        # Channel listings come back newest-first, so position is the recency
        # proxy. Upload dates are not in flat enumeration and fetching them
        # would mean opening every video page, which datacentre IPs cannot do.
        "position": position,
    }


def identify_channel(channel_id):
    """Resolve a channel's real name, without opening any video page."""
    info = {"channel_id": channel_id, "name": "(unresolved)", "handle": "",
            "subscribers": None, "sampled": 0, "titles": []}
    try:
        blob = channel_info(channel_id)
    except RuntimeError:
        raise
    except Exception as exc:
        info["error"] = str(exc)[:200]
        return info

    if not blob:
        info["name"] = "(no data -- wrong id, empty, or removed channel)"
        return info

    entries = [e for e in (blob.get("entries") or []) if isinstance(e, dict)]
    info["sampled"] = len(entries)
    info["titles"] = [str(e.get("title") or "")[:80] for e in entries[:3]]
    name = (blob.get("channel") or blob.get("uploader") or blob.get("title") or "")
    info["name"] = str(name) or "(name not returned)"
    info["handle"] = str(blob.get("uploader_id") or blob.get("channel_url") or "")
    info["subscribers"] = blob.get("channel_follower_count")
    if not entries:
        info["name"] += "  [NO VIDEOS LISTED]"
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
    for idx, e in enumerate(ict_raw):
        v = to_video(e, position=idx)
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
        # Descriptions are covered by searching WITHIN the channel rather than
        # opening each video: YouTube matches description text server-side, and
        # channel listings are the one request type that survives a datacentre
        # IP. Roughly 90 requests instead of 800, and far faster.
        by_id = {v["video_id"]: v for v in excluded}
        print("\nDescription scan: searching the channel for each keyword.")
        print("About %d searches, a few minutes. Progress every 10:"
              % sum(len(k) for k in BUCKETS.values()))
        try:
            check = channel_search(ICT_CHANNEL, "fair value gap", 5)
            if not check:
                print("  WARNING: channel search returned nothing for a keyword")
                print("  that matched 16 videos by title. The search endpoint may")
                print("  not be working -- description recovery will find nothing.")
                print("  Report this and I will switch approach.")
            else:
                print("  search endpoint OK (%d results on the probe)" % len(check))
        except RuntimeError:
            print("  blocked on the probe search -- skipping description scan")
            deep = False
        except Exception as exc:
            print("  probe failed (%s) -- continuing anyway" % str(exc)[:80])
        done = 0
        hit_block = False
        for bucket_name, keywords in BUCKETS.items():
            if hit_block:
                break
            for kw in keywords:
                done += 1
                if done % 10 == 0:
                    print("  %d searches, recovered %d" % (done, recovered), flush=True)
                try:
                    results = channel_search(ICT_CHANNEL, kw, 40)
                except RuntimeError:
                    print("  blocked during search -- keeping what we have")
                    hit_block = True
                    break
                except Exception:
                    continue
                for e in results:
                    vid = str(e.get("id") or "")
                    v = by_id.get(vid)
                    if v is not None and bucket_name not in v["buckets"]:
                        if not v["buckets"]:
                            recovered += 1
                        v["buckets"].append(bucket_name)
                        v["found_via"] = "channel_search:" + kw
        moved = [v for v in excluded if v["buckets"]]
        excluded = [v for v in excluded if not v["buckets"]]
        kept += moved
        print("  recovered %d videos via description search" % recovered)

    print("\nListing NBBTRADER videos...")
    nbb, seen_n = [], set()
    for tab in ("videos", "shorts", "streams"):
        try:
            for idx, e in enumerate(enumerate_tab(NBB_CANDIDATES[0], tab, NBB_MAX)):
                v = to_video(e, tab, position=idx)
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
