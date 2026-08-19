"""Classify guest-appearance search hits by how confidently they are NBB.

The raw search returns 60 candidates, but keyword search on "NBB trader"
also surfaces videos that merely sit in the same ICT/prop-firm niche --
other traders' strategy videos, guru-critique content, unrelated interviews.
Including those would put another person's words in the corpus under NBB's
name, so hits are tiered rather than taken wholesale.
"""

from __future__ import annotations

import re

# "NBB" as a standalone token. Deliberately not a bare substring: it must not
# fire inside unrelated words.
_NBB = re.compile(r"(?<!\w)nbb\w*", re.IGNORECASE)


def classify_guest(title: str, channel_name: str = "") -> str:
    """Return 'confident', 'review' or 'reject'.

    confident -- the title names NBB, so the video is about or featuring him
    review    -- same channel as a confident hit, but the title does not say;
                 could be a follow-up or a different guest entirely
    reject    -- neither
    """
    if _NBB.search(title or ""):
        return "confident"
    if _NBB.search(channel_name or ""):
        return "confident"
    return "review"


def tier_guests(candidates: list[dict]) -> dict[str, list[dict]]:
    """Split candidates into confident / review / reject.

    A candidate is promoted to 'review' only if it shares a channel with a
    confident hit; everything else is rejected outright, because a search
    result with no NBB mention on an unrelated channel is just niche noise.
    """
    confident: list[dict] = []
    rest: list[dict] = []
    for c in candidates:
        if classify_guest(c.get("title", ""), c.get("channel_name", "")) == "confident":
            confident.append(c)
        else:
            rest.append(c)

    confident_channels = {c.get("channel_name", "") for c in confident} - {""}
    review = [c for c in rest if c.get("channel_name", "") in confident_channels]
    reject = [c for c in rest if c.get("channel_name", "") not in confident_channels]
    return {"confident": confident, "review": review, "reject": reject}
