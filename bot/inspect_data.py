"""Validate a bar CSV before trusting a backtest built on it.

The failure this exists for: MT4/MT5 exports are stamped in BROKER SERVER time,
which is usually UTC+2 or UTC+3, not UTC. Label those as UTC and every session
window is wrong by two or three hours -- the Silver Bullet windows, the
killzones, all of it -- and the backtest will still run and still produce
confident-looking numbers.

So rather than trust the label, this infers the timezone from the data itself.
Index futures and index CFDs have a large, reliable volatility spike at the
09:30 New York equities open; find the hour that spikes and the offset falls
out.

    python -m bot.inspect_data data/bars/NAS100_1m.csv
"""

from __future__ import annotations

import argparse
import statistics
from collections import defaultdict
from datetime import timedelta

from .bars import NY, Bar


def hourly_range_profile(bars: list[Bar]) -> dict[int, float]:
    """Average bar range by hour, in the file's own declared timezone."""
    buckets: dict[int, list[float]] = defaultdict(list)
    for b in bars:
        buckets[b.ts.hour].append(b.range)
    return {h: statistics.mean(v) for h, v in sorted(buckets.items()) if v}


MIN_HOURS_COVERED = 20      # a daily cycle needs most of a day represented
MIN_SPAN_DAYS = 2           # and at least two of them, so one quiet day cannot skew it
MIN_SPIKE_RATIO = 1.8       # below this there is no identifiable open


def infer_ny_offset(bars: list[Bar], reference_ny_hour: int = 9) -> tuple[int, dict]:
    """Infer how many hours the file's clock leads New York.

    Returns (offset_hours, diagnostics). The method depends on a visible daily
    volatility cycle, so it REFUSES on data too short to contain one. Without
    that guard a two-hour file reports a confident nine-hour shift, purely
    because the loudest of its two hours is not the New York open -- which is
    exactly the sort of wrong-but-plausible answer this tool exists to prevent.
    """
    profile = hourly_range_profile(bars)
    if not profile:
        return 0, {"error": "no bars", "confident": False}

    span_days = (bars[-1].ts - bars[0].ts).total_seconds() / 86400
    if len(profile) < MIN_HOURS_COVERED or span_days < MIN_SPAN_DAYS:
        return 0, {
            "confident": False,
            "reason": (f"only {len(profile)} distinct hours across {span_days:.1f} days; "
                       f"need {MIN_HOURS_COVERED} hours over {MIN_SPAN_DAYS}+ days to see "
                       "a daily cycle"),
            "hours_covered": len(profile),
            "span_days": round(span_days, 2),
        }

    peak_hour = max(profile, key=profile.get)

    # What hour does the file's clock show at the moment it is 09:30 in New York?
    sample = bars[len(bars) // 2].ts
    expected = (sample.astimezone(NY).replace(hour=reference_ny_hour, minute=30)
                .astimezone(sample.tzinfo).hour)
    drift = (peak_hour - expected) % 24
    if drift > 12:
        drift -= 24

    median = statistics.median(profile.values())
    ratio = (profile[peak_hour] / median) if median else 0.0
    if ratio < MIN_SPIKE_RATIO:
        return 0, {
            "confident": False,
            "reason": (f"no clear volatility peak (ratio {ratio:.2f} < {MIN_SPIKE_RATIO}); "
                       "cannot locate the New York open in this data"),
            "spike_ratio": round(ratio, 2),
        }

    return drift, {
        "confident": True,
        "peak_hour_in_file_clock": peak_hour,
        "expected_hour_for_0930_ny": expected,
        "peak_avg_range": round(profile[peak_hour], 5),
        "median_avg_range": round(statistics.median(profile.values()), 5),
        "spike_ratio": round(profile[peak_hour] / statistics.median(profile.values()), 2)
        if statistics.median(profile.values()) else None,
    }


def find_gaps(bars: list[Bar], expected_minutes: int = 1,
              tolerance_multiple: int = 5) -> list[tuple]:
    """Runs of missing bars beyond normal weekend/holiday closures."""
    gaps = []
    for a, b in zip(bars, bars[1:]):
        delta = (b.ts - a.ts).total_seconds() / 60
        if delta > expected_minutes * tolerance_multiple:
            gaps.append((a.ts, b.ts, int(delta)))
    return gaps


def duplicates(bars: list[Bar]) -> int:
    seen, dupes = set(), 0
    for b in bars:
        if b.ts in seen:
            dupes += 1
        seen.add(b.ts)
    return dupes


def session_coverage(bars: list[Bar]) -> dict[str, int]:
    """How many bars land inside each window the rules care about.

    A file with zero bars in the Silver Bullet window cannot test SB-001,
    however many rows it has.
    """
    from .sessions import WINDOWS
    out = {}
    for w in WINDOWS:
        out[w.key] = sum(1 for b in bars if w.contains(b.ts))
    return out


def restamp(path: str, shift_hours: int) -> str:
    """Rewrite a CSV with timestamps shifted, leaving the original untouched.

    Used when the file is stamped in broker server time. Shifting the clock is
    the correct fix; adjusting the session windows instead would leave the data
    wrong for every other consumer.
    """
    import csv as _csv
    from datetime import datetime as _dt

    out_path = path.rsplit(".", 1)[0] + ".fixed.csv"
    with open(path, newline="") as fh:
        rows = list(_csv.DictReader(fh))
        fields = list(rows[0].keys())
    for row in rows:
        key = "timestamp" if "timestamp" in row else ("time" if "time" in row else "date")
        ts = _dt.fromisoformat(row[key].replace("Z", "+00:00"))
        row[key] = (ts + timedelta(hours=shift_hours)).isoformat().replace("+00:00", "Z")
    with open(out_path, "w", newline="") as fh:
        w = _csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    return out_path


def main(argv: list[str] | None = None) -> int:
    from .run_backtest import load_csv

    ap = argparse.ArgumentParser(description="Validate a bar CSV")
    ap.add_argument("csv")
    ap.add_argument("--restamp", type=int, metavar="HOURS",
                    help="rewrite timestamps shifted by HOURS (use the negative of "
                         "the reported drift) and save alongside as *.fixed.csv")
    args = ap.parse_args(argv)

    bars = load_csv(args.csv)
    print(f"\n{args.csv}")
    print(f"  bars      {len(bars):,}")
    print(f"  from      {bars[0].ts.astimezone(NY)}  (NY)")
    print(f"  to        {bars[-1].ts.astimezone(NY)}  (NY)")
    span = (bars[-1].ts - bars[0].ts).days
    print(f"  span      {span} days")

    dupes = duplicates(bars)
    print(f"\n  duplicate timestamps: {dupes}" + ("  <-- fix before use" if dupes else ""))

    gaps = find_gaps(bars)
    weekday_gaps = [g for g in gaps if g[0].astimezone(NY).weekday() < 4]
    print(f"  gaps > 5 min:         {len(gaps)}  ({len(weekday_gaps)} on weekdays)")
    for g in weekday_gaps[:3]:
        print(f"      {g[0].astimezone(NY)} -> {g[1].astimezone(NY)}  ({g[2]} min)")

    offset, diag = infer_ny_offset(bars)
    print(f"\n  TIMEZONE CHECK")
    if not diag.get("confident"):
        print(f"    INCONCLUSIVE  {diag.get('reason', diag.get('error'))}")
        print("    No claim made about the timezone. Re-run on a longer file.")
        offset = 0
    else:
        print(f"    volatility peaks at hour {diag.get('peak_hour_in_file_clock')} "
              f"(file clock); expected {diag.get('expected_hour_for_0930_ny')} "
              f"if the timestamps are correct")
        print(f"    spike ratio vs median hour: {diag.get('spike_ratio')}")
    if diag.get("confident") and offset == 0:
        print("    OK  timestamps look correctly stamped")
    elif diag.get("confident"):
        print(f"    WARNING  data appears shifted by {offset:+d} hours.")
        print(f"    MT4/MT5 exports are in broker server time (often UTC+2/+3),")
        print(f"    not UTC. If so, every session window is wrong by that much")
        print(f"    and the backtest will run anyway. Re-stamp before trusting it.")

    print("\n  SESSION COVERAGE (bars inside each window)")
    for key, n in session_coverage(bars).items():
        flag = "" if n else "   <-- no data; rules using this window are untestable"
        print(f"    {key:<20} {n:>7,}{flag}")

    if args.restamp:
        out = restamp(args.csv, args.restamp)
        print(f"\n  wrote {out} with timestamps shifted {args.restamp:+d}h")
        print("  re-run inspect on it to confirm the drift is now 0")
    elif offset:
        print(f"\n  to correct: python -m bot.inspect_data {args.csv} "
              f"--restamp {-offset:+d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
