"""Gate 2 -- prioritised transcript pull.

GENERATED FILE -- edit scripts/gate2_template.py and run
`python -m scripts.gen_standalone` instead of editing this directly.

Reuses gate1.py rather than duplicating discovery, so both files must be
downloaded side by side.

    python gate2.py                 # test captions, then fetch if free path works
    python gate2.py --target 150    # size of the ICT subset
    python gate2.py --apify TOKEN   # force the paid path
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

import gate1

TARGET_DEFAULT = 150
PER_BUCKET_FLOOR = 12

APIFY_ACTORS = @@APIFY_ACTORS@@


# ---------------------------------------------------------- prioritise ----

def recency_score(position, total):
    if total <= 1:
        return 1.0
    return 1.0 - (position / float(total - 1))


def score_video(video, total):
    buckets = video.get("buckets") or []
    rec = recency_score(int(video.get("position", 0)), total)
    # Breadth dominates, recency breaks ties: a multi-bucket video is usually a
    # synthesis of how concepts combine, which is worth more than another
    # single-concept explainer however recent.
    score = len(buckets) * 10.0 + rec * 5.0
    dur = video.get("duration_seconds") or 0
    if 0 < dur < 300:
        score -= 4.0
    return score


def select(videos, target=TARGET_DEFAULT, per_bucket_floor=PER_BUCKET_FLOOR):
    """Stratified then ranked.

    Pure top-N would fill the subset with Smart Money Concepts (186 videos)
    and starve Inversion FVG (51), leaving the system silent on a bucket that
    was explicitly asked for.
    """
    if not videos:
        return [], {}
    total = len(videos)
    ranked = sorted(videos, key=lambda v: score_video(v, total), reverse=True)
    all_buckets = sorted({b for v in videos for b in (v.get("buckets") or [])})

    chosen = {}
    for bucket in all_buckets:
        taken = 0
        for v in ranked:
            if taken >= per_bucket_floor:
                break
            if bucket in (v.get("buckets") or []):
                chosen.setdefault(v["video_id"], v)
                taken += 1
    for v in ranked:
        if len(chosen) >= target:
            break
        chosen.setdefault(v["video_id"], v)

    selection = list(chosen.values())
    coverage = {}
    for v in selection:
        for b in (v.get("buckets") or []):
            coverage[b] = coverage.get(b, 0) + 1
    return selection, coverage


# ------------------------------------------------------------- captions ----

def try_ytdlp_captions(video_id, outdir="subs"):
    """Attempt captions with yt-dlp. Returns (segments, kind) or (None, reason).

    Worth testing before paying: the earlier block was on --dump-json metadata,
    and caption download is a different request. It may or may not behave the
    same, and one test settles it.
    """
    os.makedirs(outdir, exist_ok=True)
    url = "https://www.youtube.com/watch?v=" + video_id
    for kind, flag in (("manual", "--write-subs"), ("auto", "--write-auto-subs")):
        proc = gate1.run_ytdlp([
            "--skip-download", flag, "--sub-langs", "en.*,en",
            "--sub-format", "json3", "-o", os.path.join(outdir, "%(id)s.%(ext)s"), url,
        ], timeout=180)
        if gate1.is_blocked(proc.stderr):
            return None, "BLOCKED"
        for fn in sorted(os.listdir(outdir)):
            if fn.startswith(video_id) and fn.endswith(".json3"):
                segs = parse_json3(os.path.join(outdir, fn))
                if segs:
                    return segs, kind
    return None, "no captions"


def parse_json3(path):
    """json3 carries tStartMs, so timestamps are unambiguously milliseconds --
    no unit guessing, and a 1000x error cannot creep into citations."""
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (ValueError, OSError):
        return []
    out = []
    for ev in data.get("events") or []:
        segs = ev.get("segs")
        if not segs:
            continue
        text = "".join(s.get("utf8", "") for s in segs).replace("\n", " ").strip()
        start = ev.get("tStartMs")
        if text and start is not None:
            out.append({"start_seconds": float(start) / 1000.0, "text": text})
    out.sort(key=lambda s: s["start_seconds"])
    return out


# ---------------------------------------------------------------- apify ----

def apify_call(path, token, payload=None, method="GET", timeout=300):
    url = "https://api.apify.com/v2%s" % path
    sep = "&" if "?" in url else "?"
    url = "%s%stoken=%s" % (url, sep, token)
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode()
        return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()[:300]
        raise RuntimeError("Apify %s: %s" % (exc.code, detail))


def apify_transcripts(video_ids, token, actor):
    """Run one transcript actor over a batch and return {video_id: segments}."""
    urls = ["https://www.youtube.com/watch?v=" + v for v in video_ids]
    payload = {"videoUrls": urls, "urls": urls, "startUrls": [{"url": u} for u in urls],
               "language": "en"}
    run = apify_call("/acts/%s/runs" % actor, token, payload, method="POST")
    data = run.get("data") or {}
    run_id = data.get("id")
    if not run_id:
        raise RuntimeError("actor %s did not start" % actor)

    waited = 0
    while waited < 1800:
        time.sleep(10)
        waited += 10
        status = (apify_call("/actor-runs/%s" % run_id, token).get("data") or {})
        state = status.get("status")
        if state == "SUCCEEDED":
            ds = status.get("defaultDatasetId")
            items = apify_call("/datasets/%s/items?clean=true&format=json" % ds, token)
            return items if isinstance(items, list) else []
        if state in ("FAILED", "ABORTED", "TIMED-OUT"):
            raise RuntimeError("actor %s run %s ended %s" % (actor, run_id, state))
    raise RuntimeError("actor %s run %s timed out" % (actor, run_id))


def find_working_actor(token, probe_video):
    """Bake-off: try each actor on one video, report what comes back.

    An actor that returns text with no timestamps is unusable here at any
    price, because every citation would read 00:00:00.
    """
    print("\nTesting transcript actors on one video (%s)..." % probe_video)
    for actor in APIFY_ACTORS:
        try:
            items = apify_transcripts([probe_video], token, actor)
        except Exception as exc:
            print("  %-46s unavailable (%s)" % (actor, str(exc)[:70]))
            continue
        if not items:
            print("  %-46s returned nothing" % actor)
            continue
        segs = extract_segments(items[0])
        if not segs:
            print("  %-46s no usable segments; keys=%s"
                  % (actor, sorted(items[0].keys())[:8]))
            continue
        timed = sum(1 for s in segs if s.get("start_seconds", 0) > 0)
        print("  %-46s OK: %d segments, %d timestamped" % (actor, len(segs), timed))
        if timed > 1:
            return actor
        print("       ^ rejected: no real timestamps")
    return None


_ID_RE = re.compile(r"(?:v=|youtu\.be/|/shorts/|/live/|/embed/)([A-Za-z0-9_-]{11})")


def payload_video_id(payload):
    """Recover which video an actor result belongs to.

    Batched runs return rows in no guaranteed order, so results must be
    matched back by id rather than by position -- pairing by index would
    silently attach one video's transcript to another's citations.
    """
    for key in ("videoId", "video_id", "id"):
        val = str(payload.get(key) or "")
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", val):
            return val
    for key in ("url", "videoUrl", "video_url", "link", "webUrl"):
        m = _ID_RE.search(str(payload.get(key) or ""))
        if m:
            return m.group(1)
    for val in payload.values():
        if isinstance(val, dict):
            got = payload_video_id(val)
            if got:
                return got
    return None


_CUE_KEYS = ("transcript", "captions", "segments", "subtitles", "data", "items", "lines")
_START_KEYS = ("start", "startMs", "start_ms", "offset", "offsetMs", "startTime", "tStartMs")


def extract_segments(payload):
    """Pull timestamped segments out of whatever shape an actor returns."""
    cues = None
    for k in _CUE_KEYS:
        val = payload.get(k)
        if isinstance(val, list) and val and isinstance(val[0], dict):
            cues = val
            break
    if cues is None:
        for val in payload.values():
            if isinstance(val, dict):
                nested = extract_segments(val)
                if nested:
                    return nested
        return []

    out = []
    for c in cues:
        text = str(c.get("text") or c.get("utf8") or c.get("snippet") or "").strip()
        if not text:
            continue
        start = None
        for k in _START_KEYS:
            if k in c and c[k] not in (None, ""):
                try:
                    val = float(str(c[k]))
                except ValueError:
                    continue
                # Explicit ms suffix, or an integer too large to be seconds.
                if k.lower().endswith("ms") or (val > 36000 and float(val).is_integer()):
                    val /= 1000.0
                start = val
                break
        out.append({"start_seconds": start or 0.0, "text": text})
    return out


# ----------------------------------------------------------------- main ----

def load_manifest():
    if os.path.exists("gate1_manifest.json"):
        print("Reusing gate1_manifest.json")
        with open("gate1_manifest.json") as fh:
            return json.load(fh)
    print("No manifest found -- running discovery first.\n")
    sys.argv = ["gate1.py", "--deep-scan"]
    gate1.main()
    with open("gate1_manifest.json") as fh:
        return json.load(fh)


def main():
    args = sys.argv[1:]
    target = TARGET_DEFAULT
    if "--target" in args:
        target = int(args[args.index("--target") + 1])
    token = None
    if "--apify" in args:
        token = args[args.index("--apify") + 1]
    token = token or os.environ.get("APIFY_TOKEN")

    gate1.ensure_ytdlp()
    manifest = load_manifest()

    ict = manifest.get("ict_in_scope") or []
    nbb = manifest.get("nbb") or []
    guests_raw = manifest.get("guests") or []

    # Guest hits are tiered: searching "NBB trader" also surfaces unrelated
    # ICT and prop-firm content, and including that would attribute another
    # person's words to him.
    nbb_re = re.compile(r"(?<!\w)nbb\w*", re.IGNORECASE)
    confident = [g for g in guests_raw
                 if nbb_re.search(g.get("title", "") or "")
                 or nbb_re.search(g.get("channel_name", "") or "")]
    confident_channels = {g.get("channel_name", "") for g in confident} - {""}
    review = [g for g in guests_raw
              if g not in confident and g.get("channel_name", "") in confident_channels]

    print("\nCorpus: %d ICT in scope, %d NBB own, %d guest candidates"
          % (len(ict), len(nbb), len(guests_raw)))
    print("Guests tiered: %d confident, %d need review, %d rejected"
          % (len(confident), len(review), len(guests_raw) - len(confident) - len(review)))

    selection, coverage = select(ict, target=target)
    print("\nSelected %d of %d ICT videos (target %d)" % (len(selection), len(ict), target))
    print("Bucket coverage in the subset:")
    for b in sorted(coverage):
        print("  %-34s %4d" % (b, coverage[b]))

    # NBB material is scarce and high value -- take all of it.
    queue = selection + nbb + confident
    hours = sum((v.get("duration_seconds") or 0) for v in queue) / 3600.0
    print("\nQueue: %d videos, %.1f hours" % (len(queue), hours))

    print("\n" + "=" * 68)
    print("Testing whether captions can be fetched for free...")
    print("=" * 68)
    probe_id = queue[0]["video_id"]
    segs, why = try_ytdlp_captions(probe_id)

    use_apify = False
    if segs:
        print("yt-dlp captions WORK here (%s, %d segments). No Apify needed."
              % (why, len(segs)))
    elif why == "BLOCKED":
        print("yt-dlp captions are BLOCKED from this machine, as expected.")
        use_apify = True
    else:
        print("Probe video has no captions; trying two more before deciding...")
        for alt in queue[1:3]:
            segs, why = try_ytdlp_captions(alt["video_id"])
            if segs or why == "BLOCKED":
                break
        use_apify = (why == "BLOCKED")
        if segs:
            print("yt-dlp captions WORK here. No Apify needed.")

    actor = None
    if use_apify:
        if not token:
            print("\nApify is needed but no token was supplied.")
            print("Rerun with:  python gate2.py --apify apify_api_YOURTOKEN")
            print("\nNothing has been fetched and nothing has been spent.")
            return 2
        actor = find_working_actor(token, probe_id)
        if not actor:
            print("\nNo transcript actor produced timestamped output.")
            print("Paste this output into the chat and I will switch approach.")
            return 3
        print("\nUsing actor: %s" % actor)

    os.makedirs("transcripts", exist_ok=True)
    done = sum(1 for f in os.listdir("transcripts") if f.endswith(".json"))
    print("\nFetching %d transcripts (%d already on disk, will be skipped)..."
          % (len(queue), done))

    ok = failed = nocaps = skipped = 0
    words = 0
    started = time.time()

    pending = []
    for v in queue:
        if os.path.exists(os.path.join("transcripts", v["video_id"] + ".json")):
            skipped += 1
        else:
            pending.append(v)

    def write_record(v, segments, kind, source):
        record = {"id": v["video_id"], "title": v.get("title", ""),
                  "channel": v.get("channel_name", ""), "url": v.get("url", ""),
                  "buckets": v.get("buckets") or [],
                  "duration": v.get("duration_seconds"),
                  "caption_kind": kind, "source": source, "segments": segments}
        with open(os.path.join("transcripts", v["video_id"] + ".json"), "w") as fh:
            json.dump(record, fh)
        return sum(len(s["text"].split()) for s in segments)

    if use_apify:
        # Batched deliberately: one actor run per video would mean 181 runs,
        # each paying startup overhead and each polled separately. Batches of
        # 25 cut both the bill and the wall-clock time by roughly an order of
        # magnitude.
        BATCH = 25
        for start in range(0, len(pending), BATCH):
            batch = pending[start:start + BATCH]
            ids = [v["video_id"] for v in batch]
            by_id = {v["video_id"]: v for v in batch}
            try:
                items = apify_transcripts(ids, token, actor)
            except Exception as exc:
                print("  batch %d-%d failed: %s"
                      % (start + 1, start + len(batch), str(exc)[:100]))
                failed += len(batch)
                continue

            seen_ids = set()
            for item in items:
                vid = payload_video_id(item)
                v = by_id.get(vid) if vid else None
                if v is None:
                    continue
                seen_ids.add(vid)
                segments = extract_segments(item)
                if not segments:
                    nocaps += 1
                    continue
                words += write_record(v, segments, "unknown", "apify:" + actor)
                ok += 1
            nocaps += len(set(ids) - seen_ids)

            elapsed = time.time() - started
            done = start + len(batch)
            rate = done / elapsed if elapsed else 0
            left = (len(pending) - done) / rate / 60 if rate else 0
            print("  %d/%d  ok=%d none=%d fail=%d  ~%.0fm left"
                  % (done, len(pending), ok, nocaps, failed, left), flush=True)
    else:
        for i, v in enumerate(pending, 1):
            try:
                segments, kind = try_ytdlp_captions(v["video_id"])
            except Exception as exc:
                print("  %s failed: %s" % (v["video_id"], str(exc)[:90]))
                failed += 1
                continue
            if not segments:
                nocaps += 1
                continue
            words += write_record(v, segments, kind, "yt-dlp")
            ok += 1
            if i % 10 == 0 or i == len(pending):
                elapsed = time.time() - started
                rate = i / elapsed if elapsed else 0
                left = (len(pending) - i) / rate / 60 if rate else 0
                print("  %d/%d  ok=%d none=%d fail=%d  ~%.0fm left"
                      % (i, len(pending), ok, nocaps, failed, left), flush=True)

    line = "=" * 68
    print("\n" + line)
    print("GATE 2 -- TRANSCRIPT INGESTION")
    print(line)
    print("\nQueued:          %d" % len(queue))
    print("Retrieved:       %d" % ok)
    print("Already on disk: %d" % skipped)
    print("No captions:     %d" % nocaps)
    print("Failed:          %d" % failed)
    print("\nTotal words:     %d" % words)
    print("Elapsed:         %.1f min" % ((time.time() - started) / 60))
    print("Source:          %s" % ("Apify " + str(actor) if use_apify else "yt-dlp (free)"))
    print("\n" + line)
    print("STOP. Awaiting go-ahead before Phase 3 rule extraction.")
    print(line)

    import shutil
    shutil.make_archive("transcripts_bundle", "zip", "transcripts")
    print("\nSaved transcripts_bundle.zip -- download it from the file browser.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
