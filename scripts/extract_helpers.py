"""Helpers for authoring cited rules."""

from __future__ import annotations

import json
import re
from pathlib import Path

RULES = Path("extraction/rules.json")

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"])}


def timestamp_seconds(ts: str) -> int:
    total = 0
    for part in ts.split(":"):
        total = total * 60 + int(part)
    return total


def published_from_title(title: str) -> str | None:
    """Recover a publish date from the title.

    Flat enumeration returns no dates and fetching them needs video pages,
    which the fetch environment cannot open -- but ICT dates most of his
    review titles, so a good share are recoverable this way.
    """
    m = re.search(r"(January|February|March|April|May|June|July|August|"
                  r"September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})", title)
    if m:
        return f"{m.group(3)}-{_MONTHS[m.group(1)]:02d}-{int(m.group(2)):02d}"
    m = re.search(r"\b(\d{2})/(\d{2})/(\d{4})\b", title)
    if m:
        return f"{m.group(3)}-{m.group(1)}-{m.group(2)}"
    return None


def src(video_id: str, title: str, timestamp: str, channel: str = "ICT",
        published: str | None = None) -> dict:
    return {
        "channel": channel,
        "video_id": video_id,
        "title": title,
        "published": published or published_from_title(title),
        "timestamp": timestamp,
        "link": f"https://youtu.be/{video_id}?t={timestamp_seconds(timestamp)}",
    }


def rule(rule_id, bucket, concept, category, statement, sources, **kw) -> dict:
    """Build a rule with the schema's defaults filled in."""
    base = {
        "rule_id": rule_id, "topic_bucket": bucket, "concept": concept,
        "category": category, "statement": statement,
        "preconditions": [], "trigger": "", "entry": "", "stop_loss": "",
        "target": "", "invalidation": "",
        "timeframes": {"htf": None, "mtf": None, "ltf": None},
        "session": "any",
        "time_window": {"ny": None, "london": None, "dst_sensitive": False},
        "instruments": ["any"], "confluences_required": [],
        "sources": sources, "confidence": "medium",
        "mentions": len(sources), "contradicts": [], "notes": "",
    }
    base.update(kw)
    return base


def append_rules(new: list[dict]) -> int:
    existing = json.loads(RULES.read_text()) if RULES.exists() else []
    ids = {r["rule_id"] for r in existing}
    clash = ids & {r["rule_id"] for r in new}
    if clash:
        raise SystemExit(f"duplicate rule ids: {sorted(clash)}")
    existing += new
    RULES.write_text(json.dumps(existing, indent=2))
    return len(existing)
