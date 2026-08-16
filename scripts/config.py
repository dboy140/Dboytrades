"""Single source of truth: channels, topic buckets, paths, settings.

Nothing in this repository hardcodes a channel ID, an actor name, a bucket
keyword or a path. If you need to change what gets scraped, change it here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

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
BAKEOFF_REPORT = LOGS / "actor_bakeoff.json"
COST_LEDGER = LOGS / "cost_ledger.json"

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
    # against the live YouTube API from this environment, so `verify_channels`
    # must confirm them before any paid enumeration run.
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
        note="Eight topic buckets only. Do NOT enumerate the full back catalogue "
        "into transcripts; metadata enumeration is cheap, transcripts are not.",
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

# A second similarly-named channel exists. `verify_channels` probes both and
# reports which is active so the right one can be promoted before scraping.
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


# --------------------------------------------------------------- actors ----


@dataclass
class ActorCandidate:
    actor_id: str          # tilde form, as the REST API expects
    label: str
    note: str = ""


# Stage 1: enumeration (cheap, metadata only).
ENUMERATION_ACTOR = ActorCandidate(
    "streamers~youtube-scraper",
    "streamers/youtube-scraper",
    "Channel + search enumeration. Verify availability with verify_env.py.",
)

# Stage 2: transcripts. Tested head-to-head by actor_bakeoff.py on a single
# video before any batch run; the operator picks the winner.
TRANSCRIPT_ACTOR_CANDIDATES = [
    ActorCandidate("automation-lab~youtube-transcript", "automation-lab/youtube-transcript"),
    ActorCandidate("topaz_sharingan~youtube-transcript-scraper", "topaz_sharingan/youtube-transcript-scraper"),
    ActorCandidate("openclawmara~youtube-transcript-scraper", "openclawmara/youtube-transcript-scraper"),
    ActorCandidate("visita~youtube-scraper", "visita/youtube-scraper", "Also returns metadata and comments."),
]

# Set once the bake-off has run and the operator has chosen.
CHOSEN_TRANSCRIPT_ACTOR: str | None = None


# ------------------------------------------------------------- settings ----

# Spend guard. Any run whose estimate exceeds this stops and asks first.
COST_ALERT_THRESHOLD_USD = 5.00

# Enumeration caps. Deliberately generous for ICT because filtering happens
# after enumeration, and metadata is cheap relative to transcripts.
ICT_ENUMERATION_MAX = 1200
NBB_ENUMERATION_MAX = 1500
SEARCH_QUERY_MAX_RESULTS = 60

RETRY_ATTEMPTS = 4
RETRY_BACKOFF_SECONDS = 2
RUN_POLL_SECONDS = 10
RUN_MAX_WAIT_SECONDS = 3600


def apify_token() -> str:
    token = os.environ.get("APIFY_TOKEN") or os.environ.get("APIFY_API_TOKEN")
    if not token:
        raise RuntimeError(
            "APIFY_TOKEN is not set. Copy .env.example to .env and add your token "
            "from https://console.apify.com/account/integrations, or export it:\n"
            "    export APIFY_TOKEN=apify_api_..."
        )
    return token
