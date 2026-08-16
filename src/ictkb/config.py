"""Project paths and configuration loading."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
SCHEMA_DIR = ROOT / "schemas"
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
DERIVED_DIR = DATA_DIR / "derived"
KB_DIR = ROOT / "kb"
CLAIMS_DIR = KB_DIR / "claims"
RULES_DIR = KB_DIR / "rules"
SYSTEM_DIR = ROOT / "system"

SEGMENTS_PATH = DERIVED_DIR / "segments.jsonl"
VIDEOS_PATH = RAW_DIR / "videos.jsonl"


class ConfigError(RuntimeError):
    """Raised when configuration is missing or internally inconsistent."""


@dataclass(frozen=True)
class Source:
    key: str
    display_name: str
    handle: str
    url: str
    channel_id: str | None
    verified: bool
    notes: str = ""


@dataclass(frozen=True)
class ActorSpec:
    id: str
    verified: bool
    default_input: dict[str, Any] = field(default_factory=dict)
    fallbacks: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class IngestionSettings:
    window_seconds: int
    window_overlap_seconds: int
    language_preference: list[str]
    allow_auto_captions: bool

    def __post_init__(self) -> None:
        if self.window_overlap_seconds >= self.window_seconds:
            raise ConfigError(
                "window_overlap_seconds must be smaller than window_seconds, "
                f"got overlap={self.window_overlap_seconds} window={self.window_seconds}. "
                "Equal or larger overlap makes the window stride zero and the "
                "segmenter would not advance."
            )


@dataclass(frozen=True)
class Config:
    sources: list[Source]
    actors: dict[str, ActorSpec]
    ingestion: IngestionSettings
    taxonomy: dict[str, Any]

    def source(self, key: str) -> Source:
        for s in self.sources:
            if s.key == key:
                return s
        raise ConfigError(f"unknown source key {key!r}; configured: {[s.key for s in self.sources]}")

    @property
    def source_keys(self) -> list[str]:
        return [s.key for s in self.sources]

    @property
    def required_phases(self) -> list[str]:
        return list(self.taxonomy.get("required_phases", []))

    def concept_queries(self) -> dict[str, list[str]]:
        """Map concept key -> search terms, for corpus mining."""
        out: dict[str, list[str]] = {}
        for key, body in (self.taxonomy.get("concepts") or {}).items():
            out[key] = list((body or {}).get("aliases") or [])
        return out


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"missing config file: {path}")
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_config(config_dir: Path | None = None) -> Config:
    cdir = config_dir or CONFIG_DIR
    raw = _read_yaml(cdir / "sources.yaml")
    taxonomy = _read_yaml(cdir / "taxonomy.yaml")

    sources = [
        Source(
            key=s["key"],
            display_name=s.get("display_name", s["key"]),
            handle=s.get("handle", ""),
            url=s.get("url", ""),
            channel_id=s.get("channel_id"),
            verified=bool(s.get("verified", False)),
            notes=s.get("notes", "") or "",
        )
        for s in (raw.get("sources") or [])
    ]
    if not sources:
        raise ConfigError("no sources configured in sources.yaml")

    actors = {
        name: ActorSpec(
            id=spec["id"],
            verified=bool(spec.get("verified", False)),
            default_input=dict(spec.get("default_input") or {}),
            fallbacks=list(spec.get("fallbacks") or []),
        )
        for name, spec in (raw.get("actors") or {}).items()
    }

    ing = raw.get("ingestion") or {}
    ingestion = IngestionSettings(
        window_seconds=int(ing.get("window_seconds", 45)),
        window_overlap_seconds=int(ing.get("window_overlap_seconds", 15)),
        language_preference=list(ing.get("language_preference") or ["en"]),
        allow_auto_captions=bool(ing.get("allow_auto_captions", True)),
    )

    return Config(sources=sources, actors=actors, ingestion=ingestion, taxonomy=taxonomy)


def apify_token() -> str:
    """Return the Apify API token, or raise with actionable guidance."""
    token = os.environ.get("APIFY_TOKEN") or os.environ.get("APIFY_API_TOKEN")
    if not token:
        raise ConfigError(
            "APIFY_TOKEN is not set. Create a token at "
            "https://console.apify.com/account/integrations and export it:\n"
            "    export APIFY_TOKEN=apify_api_...\n"
            "Ingestion cannot proceed without it."
        )
    return token


def ensure_dirs() -> None:
    for d in (RAW_DIR, DERIVED_DIR, CLAIMS_DIR, RULES_DIR, SYSTEM_DIR):
        d.mkdir(parents=True, exist_ok=True)
