"""Print the NY/UK daylight-saving mismatch windows for a given year.

US and UK daylight-saving dates differ, so for roughly four weeks a year the
New York to London offset is +4h rather than +5h. Every session window in the
system shifts an hour in UK terms during those weeks, which is the single
easiest way to trade the wrong hour.

    python -m scripts.dst_table 2027
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
LDN = ZoneInfo("Europe/London")


def offset_hours(when: datetime) -> int:
    return int((when.astimezone(LDN).utcoffset() - when.utcoffset()).total_seconds() // 3600)


def mismatch_windows(year: int) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    day = datetime(year, 1, 1, 12, 0, tzinfo=NY)
    start = None
    while day.year == year:
        off = offset_hours(day)
        if off != 5 and start is None:
            start = day
        elif off == 5 and start is not None:
            out.append((str(start.date()), str(day.date())))
            start = None
        day += timedelta(days=1)
    if start is not None:
        out.append((str(start.date()), f"{year}-12-31"))
    return out


def convert(ny_hhmm: str, on: datetime) -> str:
    h, m = map(int, ny_hhmm.split(":"))
    return datetime(on.year, on.month, on.day, h, m, tzinfo=NY).astimezone(LDN).strftime("%H:%M")


def main(argv: list[str]) -> int:
    year = int(argv[1]) if len(argv) > 1 else datetime.now().year
    print(f"NY->UK offset is normally +5h. Mismatch windows for {year} (+4h):\n")
    for a, b in mismatch_windows(year):
        print(f"  {a}  to  {b}")
    print("\nDuring those windows every NY time converts an hour earlier in the UK:")
    normal = datetime(year, 6, 15, 12, tzinfo=NY)
    windows = mismatch_windows(year)
    # Sample the MIDDLE of the window, not its first day: on the US
    # spring-forward date the 02:00 hour does not exist, which makes the
    # transition day a misleading example.
    if windows:
        a = datetime.fromisoformat(windows[0][0])
        b = datetime.fromisoformat(windows[0][1])
        odd = (a + (b - a) / 2).replace(hour=12, tzinfo=NY)
    else:
        odd = normal
    for w in ("02:00", "10:00", "14:00"):
        print(f"  NY {w}  ->  UK {convert(w, normal)} normally,  {convert(w, odd)} in the window")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
