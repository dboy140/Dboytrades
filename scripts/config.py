"""Single source of truth: channels, topic buckets, paths, settings.

Nothing in this repository hardcodes a channel ID, a bucket keyword or a
path. If you need to change what gets scraped, change it here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------- paths ----

DATA = ROOT / "data"
TRANSCRIPTS = DATA / "transcripts"
NOTES = DATA / "notes"
MANIFEST = DATA / "manifest.json"
EXCLUDED = DATA / "excluded.json"
CHANNEL_PROBE = DATA / "channel_probe.json"

EXTRACTION = ROOT / "extraction"
RULES_JSON = EXTRACTION / "rules.json"

STRATEGY = ROOT / "strategy"
LOGS = ROOT / "logs"
FAILED_LOG = LOGS / "failed.json"

ALL_DIRS = [DATA, TRANSCRIPTS, NOTES, EXTRACTION, STRATEGY, LOGS]


def ensure_dirs() -> None:
    for d in ALL_DIRS:
        d.mkdir(parents=True, exist_ok=True)


# ------------------------------------------------------------ operator ----

OPERATOR = {
    "handle": "DboyTrades",
    "base_timezone": "Europe/London",
    "instruments": ["XAUUSD", "EURUSD", "GBPUSD", "NAS100"],
    "journal_setups": ["Silver Bullet", "MMSM", "MMBM", "LDN to New York OTE"],
}


# ------------------------------------------------------------ channels ----


@dataclass
class Channel:
    key: str
    display_name: str
    channel_id: str
    handle: str | None
    scope: str  # "filtered" | "complete"
    # Operator-supplied values are recorded as such. They have NOT been checked
    # against the live site from this environment, so discovery probes and
    # reports them rather than assuming they are right.
    provenance: str = "operator_supplied"
    verified: bool = False
    note: str = ""

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/channel/{self.channel_id}"


CHANNELS: list[Channel] = [
    Channel(
        key="ICT",
        display_name="Inner Circle Trader (Michael J. Huddleston)",
        channel_id="UCtjxa77NqamhVC8atV85Rog",
        handle="@InnerCircleTrader",
        scope="filtered",
        note="Eight topic buckets only. Enumerate the full catalogue for "
        "metadata (cheap), but only pull transcripts for bucket matches.",
    ),
    Channel(
        key="NBBTRADER",
        display_name="NBBTRADER",
        channel_id="UCo6TS8uarO5r562d4lESg9w",
        handle=None,
        scope="complete",
        note="Complete catalogue: long-form, Shorts, lives.",
    ),
]

# A second similarly-named channel exists. Discovery probes both and reports
# samples from each so the right one can be promoted before scraping.
NBB_CANDIDATE_IDS = [
    "UCo6TS8uarO5r562d4lESg9w",  # primary per operator
    "UCmtJ3lDd2fjt-IMf6lfzlcA",  # alternate to rule out
]

# NBB's guest appearances live on other people's channels, so they cannot be
# reached by channel enumeration and need keyword search instead.
GUEST_APPEARANCE_QUERIES = [
    "NBBTRADER",
    "NBB trader interview",
    "NBB trader podcast",
    "NBBTRADER Words of Rizdom",
    "Words of Rizdom trading NBB",
    "NBB trader strategy explained",
]


def channel(key: str) -> Channel:
    for c in CHANNELS:
        if c.key == key:
            return c
    raise KeyError(f"unknown channel key {key!r}")


# -------------------------------------------------------- topic buckets ----


@dataclass
class Bucket:
    key: str
    display_name: str
    # `keywords` is the operator-supplied list, kept verbatim.
    keywords: list[str] = field(default_factory=list)
    # `extra_keywords` are title variants added by the pipeline because real
    # titles phrase things the operator list does not literally cover (e.g.
    # "New York AM Session" contains none of "New York session" / "NY AM
    # session" as a contiguous phrase). Kept separate so the operator can see
    # exactly what was added and reject any of it. REVIEW THESE.
    extra_keywords: list[str] = field(default_factory=list)

    @property
    def all_keywords(self) -> list[str]:
        return [*self.keywords, *self.extra_keywords]


# The eight in-scope ICT subjects. Keywords are matched against title and
# description, and are also issued as YouTube search queries so that
# playlist-buried or oddly-titled videos still surface.
ICT_BUCKETS: list[Bucket] = [
    Bucket(
        "money_maker_model",
        "Money Maker Model (MMxM)",
        [
            "money maker model", "MMxM", "market maker model", "market maker buy model",
            "MMBM", "market maker sell model", "MMSM", "smart money reversal",
            "original consolidation", "low resistance liquidity run",
        ],
        extra_keywords=[
            "high resistance liquidity run", "resistance liquidity run",
            "smart money reversals",
        ],
    ),
    Bucket(
        "silver_bullet",
        "ICT Silver Bullet",
        [
            "silver bullet", "ICT silver bullet", "silver bullet 10am", "silver bullet 3am",
            "silver bullet 2pm", "silver bullet setup", "silver bullet strategy",
        ],
    ),
    Bucket(
        "fair_value_gaps",
        "Fair Value Gaps",
        [
            "fair value gap", "FVG", "imbalance", "balanced price range", "BPR",
            "consequent encroachment", "liquidity void",
        ],
        extra_keywords=["inefficiency", "inefficiencies"],
    ),
    Bucket(
        "inversion_fair_value_gaps",
        "Inversion Fair Value Gaps",
        [
            "inversion fair value gap", "IFVG", "inverted fair value gap",
            "inversion FVG", "FVG inversion",
        ],
    ),
    Bucket(
        "london_session",
        "London Session",
        [
            "London killzone", "London open", "London session", "London open killzone",
            "London judas swing", "London close",
        ],
        extra_keywords=["LDN killzone", "LDN open", "LDN session", "judas swing"],
    ),
    Bucket(
        "new_york_session",
        "New York Session",
        [
            "New York killzone", "New York open", "New York session", "NY AM session",
            "NY PM session", "NY lunch", "opening range gap",
        ],
        extra_keywords=[
            "New York AM", "New York PM", "NY AM", "NY PM", "NY killzone",
            "NY open", "NY session", "New York AM session", "New York PM session",
            "AM session", "PM session", "ORG", "RTH ORG",
        ],
    ),
    Bucket(
        "higher_timeframe",
        "Higher Timeframe",
        [
            "higher timeframe bias", "HTF bias", "daily bias", "weekly profile",
            "monthly bias", "HTF narrative", "top down analysis",
        ],
    ),
    Bucket(
        "smart_money_concepts",
        "Smart Money Concepts",
        [
            "smart money concepts", "SMC", "institutional order flow", "IPDA",
            "order block", "market structure shift", "displacement",
            "premium and discount", "dealing range", "buyside liquidity",
            "sellside liquidity",
        ],
    ),
]

BUCKET_KEYS = [b.key for b in ICT_BUCKETS]


def bucket(key: str) -> Bucket:
    for b in ICT_BUCKETS:
        if b.key == key:
            return b
    raise KeyError(f"unknown bucket key {key!r}")


# Adjacent concepts. These are captured as supporting context INSIDE an
# in-scope video's notes. They must never trigger a separate video hunt.
ADJACENT_CONCEPTS = [
    "SMT divergence", "DXY correlation", "order block", "displacement",
    "optimal trade entry", "OTE", "breaker", "mitigation block", "power of three",
]


# ---------------------------------------------------------- yt-dlp path ----

# Fetching is yt-dlp only: it needs nothing but youtube.com — no API key, no
# account, no per-video billing.

# YouTube increasingly rate-limits or challenges datacentre IPs. If enumeration
# starts returning nothing, supplying cookies from a signed-in browser is the
# usual fix: set one of these (browser name e.g. "chrome"/"firefox", or a path
# to a cookies.txt export).
YTDLP_COOKIES_FROM_BROWSER: str | None = None
YTDLP_COOKIES_FILE: str | None = None

# Politeness. Raising these is the first thing to try if YouTube starts
# throttling a long run.
YTDLP_SLEEP_REQUESTS: float = 1.0        # between yt-dlp's own HTTP requests
YTDLP_SLEEP_BETWEEN_VIDEOS: float = 1.0  # between videos during transcript pulls

# Caption languages, in preference order. "en.*" catches en-GB, en-US and the
# auto-generated "en-orig" variants.
YTDLP_SUB_LANGS = ["en.*", "en"]


# ------------------------------------------------------------- settings ----

# Enumeration caps. Deliberately generous for ICT because filtering happens
# after enumeration, and metadata is cheap relative to transcripts.
ICT_ENUMERATION_MAX = 1200
NBB_ENUMERATION_MAX = 1500

# Guest-appearance search breadth.
SEARCH_QUERY_MAX_RESULTS = 30


