"""IO, logging and idempotency helpers."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Iterable

from . import config as cfg


def setup_logging(verbose: bool = False, logfile: str | None = None) -> logging.Logger:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if logfile:
        cfg.LOGS.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(cfg.LOGS / logfile, encoding="utf-8"))
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
        force=True,
    )
    return logging.getLogger("pipeline")


def write_json(path: Path, obj: Any) -> None:
    """Atomic write: an interrupted run never leaves a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2, default=str)
        fh.write("\n")
    tmp.replace(path)


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def already_have_transcript(video_id: str) -> bool:
    """Idempotency check for Phase 2 — runs are interrupted routinely."""
    return (cfg.TRANSCRIPTS / f"{video_id}.json").exists()


def already_have_notes(video_id: str) -> bool:
    return (cfg.NOTES / f"{video_id}.json").exists()


def load_manifest() -> list[dict[str, Any]]:
    return read_json(cfg.MANIFEST, default=[]) or []


def append_failure(stage: str, video_id: str, error: str) -> None:
    """Permanent failures are recorded, never silently dropped."""
    failures = read_json(cfg.FAILED_LOG, default=[]) or []
    failures.append({"stage": stage, "video_id": video_id, "error": error[:800]})
    write_json(cfg.FAILED_LOG, failures)


def record_cost(operation: str, actor_id: str, usd: float, units: int = 0) -> float:
    """Append to the cost ledger and return the new running total."""
    ledger = read_json(cfg.COST_LEDGER, default={"entries": [], "total_usd": 0.0})
    ledger["entries"].append(
        {"operation": operation, "actor_id": actor_id, "usd": round(usd, 4), "units": units}
    )
    ledger["total_usd"] = round(sum(e["usd"] for e in ledger["entries"]), 4)
    write_json(cfg.COST_LEDGER, ledger)
    return ledger["total_usd"]


def fmt_duration(seconds: float | int | None) -> str:
    if not seconds:
        return "?"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"


def seconds_to_timestamp(seconds: float) -> str:
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def dedupe_by_id(items: Iterable[dict[str, Any]], key: str = "video_id") -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for it in items:
        v = it.get(key)
        if v and v not in seen:
            seen.add(v)
            out.append(it)
    return out
