"""Session windows, DST-aware.  Rules: LDN-001, NY-001..005, SB-001, SB-002, SMC-007.

Windows are defined in New York local time and resolved through the IANA
database. Never compute them from a fixed UTC offset -- US and UK daylight
saving diverge for about four weeks a year, and a fixed offset silently shifts
every window by an hour during those weeks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time

from .bars import NY


@dataclass(frozen=True)
class Window:
    key: str
    start: time
    end: time
    instruments: tuple[str, ...]
    rule_ids: tuple[str, ...]

    def contains(self, when: datetime) -> bool:
        local = when.astimezone(NY).time()
        if self.start <= self.end:
            return self.start <= local < self.end
        return local >= self.start or local < self.end  # wraps midnight


WINDOWS: tuple[Window, ...] = (
    Window("london_killzone", time(2, 0), time(5, 0),
           ("EURUSD", "GBPUSD", "XAUUSD"), ("LDN-001",)),
    Window("nbb_london_sb", time(3, 0), time(4, 0),
           ("EURUSD", "GBPUSD"), ("SB-010",)),
    Window("ny_killzone", time(7, 0), time(9, 0),
           ("EURUSD", "GBPUSD", "XAUUSD"), ("NY-001",)),
    Window("nbb_ny_sb", time(8, 0), time(9, 0),
           ("EURUSD", "GBPUSD"), ("SB-010",)),
    Window("ny_am_session", time(8, 30), time(11, 0),
           ("NAS100",), ("NY-002",)),
    Window("silver_bullet_am", time(10, 0), time(11, 0),
           ("NAS100",), ("SB-001",)),
    Window("london_close", time(10, 0), time(12, 0),
           ("EURUSD", "GBPUSD", "XAUUSD"), ("LDN-003",)),
    Window("lunch_macro", time(12, 0), time(13, 30),
           ("NAS100",), ("SMC-007",)),
    Window("ny_pm_session", time(13, 0), time(16, 0),
           ("NAS100",), ("NY-005",)),
    Window("silver_bullet_pm", time(14, 0), time(15, 0),
           ("NAS100",), ("SB-002",)),
)

# SB-006: on scheduled-news days the AM Silver Bullet widens to 10:00-12:00.
NEWS_WIDENED_AM = Window("silver_bullet_am_news", time(10, 0), time(12, 0),
                         ("NAS100",), ("SB-001", "SB-006"))


def active_windows(when: datetime, instrument: str,
                   news_day: bool = False) -> list[Window]:
    windows = list(WINDOWS)
    if news_day:
        windows = [w for w in windows if w.key != "silver_bullet_am"]
        windows.append(NEWS_WIDENED_AM)
    return [w for w in windows if instrument in w.instruments and w.contains(when)]


def in_window(when: datetime, key: str) -> bool:
    for w in (*WINDOWS, NEWS_WIDENED_AM):
        if w.key == key:
            return w.contains(when)
    raise KeyError(f"unknown window {key!r}")


def uk_offset_hours(when: datetime) -> int:
    """Hours to add to New York time to get UK time: normally 5, sometimes 4."""
    from zoneinfo import ZoneInfo
    ldn = ZoneInfo("Europe/London")
    ny_when = when.astimezone(NY)
    return int((ny_when.astimezone(ldn).utcoffset() - ny_when.utcoffset()).total_seconds() // 3600)
