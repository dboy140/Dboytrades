"""Gate 1, self-contained. No repo, no clone, no GitHub, no API key.

Paste into a blank Google Colab cell and run. Everything it needs is here.

Kept deliberately flat and dependency-light because it has to survive being
copy-pasted into a phone browser. The bucket keywords below are asserted
identical to scripts/config.py by tests/test_standalone.py, so this cannot
silently drift from the real pipeline.
"""

import json
import re
import subprocess
import sys

# --------------------------------------------------------------- config ----

ICT_CHANNEL = "UCtjxa77NqamhVC8atV85Rog"
NBB_CANDIDATES = ["UCo6TS8uarO5r562d4lESg9w", "UCmtJ3lDd2fjt-IMf6lfzlcA"]

ICT_MAX = 1200
NBB_MAX = 1500

BUCKETS = {
    "Money Maker Model (MMxM)": [
        "money maker model", "MMxM", "market maker model", "market maker buy model",
        "MMBM", "market maker sell model", "MMSM", "smart money reversal",
        "original consolidation", "low resistance liquidity run",
    ],
    "ICT Silver Bullet": [
        "silver bullet", "ICT silver bullet", "silver bullet 10am", "silver bullet 3am",
        "silver bullet 2pm", "silver bullet setup", "silver bullet strategy",
    ],
    "Fair Value Gaps": [
        "fair value gap", "FVG", "imbalance", "balanced price range", "BPR",
        "consequent encroachment", "liquidity void",
    ],
    "Inversion Fair Value Gaps": [
        "inversion fair value gap", "IFVG", "inverted fair value gap",
        "inversion FVG", "FVG inversion",
    ],
    "London Session": [
        "London killzone", "London open", "London session", "London open killzone",
        "London judas swing", "London close",
        "LDN killzone", "LDN open", "LDN session", "judas swing",
    ],
    "New York Session": [
        "New York killzone", "New York open", "New York session", "NY AM session",
        "NY PM session", "NY lunch", "opening range gap",
        "New York AM", "New York PM", "NY AM", "NY PM", "NY killzone",
        "NY open", "NY session", "New York AM session", "New York PM session",
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
    name: [(kw, re.compile(r"(?<!\w)" + r"\s+".join(map(re.escape, kw.split())) + r"s?(?!\w)", re.I))
           for kw in kws]
    for name, kws in BUCKETS.items()
}


def match_buckets(title, description=""):
    hits = []
    for name, pats in _PATTERNS.items():
        if any(p.search(title or "") or p.search(description or "") for _, p in pats):
            hits.append(name)
    return hits


# --------------------------------------------------------------- yt-dlp ----

def run_ytdlp(args, timeout=1800):
    try:
        return subprocess.run(["yt-dlp", "--ignore-config", "--no-warnings",
                               "--no-progress"] + args,
                              capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        sys.exit("yt-dlp is not installed. Run:  !pip install -U yt-dlp")


def is_blocked(stderr):
    low = (stderr or "").lower()
    return ("sign in to confirm" in low or "not a bot" in low
            or "tunnel connection failed" in low or "unable to connect to proxy" in low)


def enumerate_tab(channel_id, tab, limit):
    url = "https://www.youtube.com/channel/%s/%s" % (channel_id, tab)
    proc = run_ytdlp(["--flat-playlist", "--dump-json", "--playlist-end", str(limit), url])
    if is_blocked(proc.stderr):
        raise RuntimeError("BLOCKED_BY_YOUTUBE")
    out = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


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
        "duration_seconds": int(d) if isinstance(d, (int, float)) else None,
        "is_short": tab == "shorts",
        "buckets": [],
    }


# ----------------------------------------------------------------- main ----

def main():
    print("Checking YouTube is reachable...")
    try:
        probe = enumerate_tab(ICT_CHANNEL, "videos", 1)
    except RuntimeError:
        sys.exit(
            "\nBLOCKED: YouTube is challenging this machine as a bot.\n"
            "Fix: Runtime -> Disconnect and delete runtime, then run again.\n"
            "Colab gives a different address each time, which usually clears it."
        )
    if not probe:
        sys.exit("Got no videos back. Paste this whole output into the chat.")
    print("  OK -- channel reports as: %r\n" % probe[0].get("channel", ""))

    print("Probing both NBBTRADER channels...")
    nbb_probe = {}
    for cid in NBB_CANDIDATES:
        try:
            sample = enumerate_tab(cid, "videos", 5)
            nbb_probe[cid] = {
                "names": sorted({str(e.get("channel") or "") for e in sample} - {""}),
                "titles": [str(e.get("title") or "")[:80] for e in sample[:5]],
                "count": len(sample),
            }
        except Exception as exc:
            nbb_probe[cid] = {"error": str(exc)[:200]}
    print("  done\n")

    print("Listing ICT videos (this is the slow part)...")
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
    print("  %d ICT videos found\n" % len(ict))

    kept, excluded = [], []
    for v in ict:
        b = match_buckets(v["title"])
        if b:
            v["buckets"] = b
            kept.append(v)
        else:
            excluded.append(v)

    print("Listing NBBTRADER videos...")
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
    print("  %d NBB videos found\n" % len(nbb))

    per_bucket = {name: 0 for name in BUCKETS}
    for v in kept:
        for b in v["buckets"]:
            per_bucket[b] += 1
    hours = sum((v["duration_seconds"] or 0) for v in kept + nbb) / 3600.0

    line = "=" * 68
    print("\n" + line)
    print("GATE 1 -- DISCOVERY REPORT")
    print(line)
    print("\nICT enumerated:      %d" % len(ict))
    print("ICT in scope:        %d" % len(kept))
    print("ICT excluded:        %d" % len(excluded))
    print("\nPer bucket:")
    for name in BUCKETS:
        print("  %-34s %5d" % (name, per_bucket[name]))
    print("\nNBBTRADER total:     %d" % len(nbb))
    print("  of which Shorts:   %d" % sum(1 for v in nbb if v["is_short"]))
    print("\nTotal runtime:       %.1f hours" % hours)
    print("Estimated cost:      $0.00  (yt-dlp)")
    thin = [n for n, c in per_bucket.items() if c < 3]
    if thin:
        print("\n! thin buckets (<3 videos): %s" % ", ".join(thin))
    print("\n! title-only matching (descriptions not fetched)")

    print("\n" + "-" * 68)
    print("NBBTRADER channel resolution -- which of these is the real one?")
    for cid, info in nbb_probe.items():
        print("\n  %s" % cid)
        if "error" in info:
            print("    ERROR: %s" % info["error"])
            continue
        print("    sampled: %d   name: %s" % (info["count"], info["names"] or "(none)"))
        for t in info["titles"]:
            print("      - %s" % t)

    print("\n" + line)
    print("EXCLUDED SAMPLE -- first 30 ICT videos the filter cut:")
    print(line)
    for v in excluded[:30]:
        print("  - %s" % v["title"][:88])
    if len(excluded) > 30:
        print("  ... and %d more" % (len(excluded) - 30))

    with open("gate1_manifest.json", "w") as fh:
        json.dump({"ict_in_scope": kept, "ict_excluded": excluded,
                   "nbb": nbb, "nbb_probe": nbb_probe}, fh, indent=2)
    print("\nSaved gate1_manifest.json")
    print("\nCopy everything above and paste it into the chat.")


if __name__ == "__main__":
    main()
