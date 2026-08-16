"""Claim construction with content-addressed IDs.

A claim ID is a hash of the statement plus its evidence anchors. Editing either
changes the ID, so a rule can never keep pointing at a claim whose content has
drifted underneath it — the reference simply stops resolving and `validate`
fails loudly.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Any, Sequence

from .normalize import normalize_for_match, timestamp_url


class ClaimError(ValueError):
    pass


@dataclass(frozen=True)
class Evidence:
    segment_id: str
    video_id: str
    start_s: float
    quote: str
    url: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["url"] = self.url or timestamp_url(self.video_id, self.start_s)
        return d


@dataclass
class Claim:
    statement: str
    concept: str
    source_key: str
    evidence: list[Evidence]
    confidence: str = "medium"
    contradicts: list[str] = field(default_factory=list)
    method: str = "llm_proposed"
    reviewer: str | None = None
    extracted_at: str = ""
    claim_id: str = ""

    def __post_init__(self) -> None:
        if not self.evidence:
            raise ClaimError(
                f"claim {self.statement[:60]!r} has no evidence. A claim without a "
                "video ID and timestamp cannot exist in this knowledge base."
            )
        if self.confidence not in {"high", "medium", "low"}:
            raise ClaimError(f"invalid confidence {self.confidence!r}")
        if self.method not in {"human", "llm_assisted", "llm_proposed"}:
            raise ClaimError(f"invalid extraction method {self.method!r}")
        if not self.extracted_at:
            self.extracted_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if not self.claim_id:
            self.claim_id = compute_claim_id(self.statement, self.evidence)

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "statement": self.statement,
            "concept": self.concept,
            "source_key": self.source_key,
            "evidence": [e.to_dict() for e in self.evidence],
            "confidence": self.confidence,
            "contradicts": list(self.contradicts),
            "extraction": {
                "method": self.method,
                "extracted_at": self.extracted_at,
                "reviewer": self.reviewer,
            },
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Claim":
        ext = d.get("extraction") or {}
        return cls(
            statement=d["statement"],
            concept=d.get("concept", ""),
            source_key=d.get("source_key", ""),
            evidence=[
                Evidence(
                    segment_id=e["segment_id"],
                    video_id=e["video_id"],
                    start_s=float(e["start_s"]),
                    quote=e["quote"],
                    url=e.get("url", ""),
                )
                for e in d.get("evidence", [])
            ],
            confidence=d.get("confidence", "medium"),
            contradicts=list(d.get("contradicts") or []),
            method=ext.get("method", "llm_proposed"),
            reviewer=ext.get("reviewer"),
            extracted_at=ext.get("extracted_at", ""),
            claim_id=d.get("claim_id", ""),
        )


def compute_claim_id(statement: str, evidence: Sequence[Evidence]) -> str:
    h = hashlib.sha256()
    h.update(normalize_for_match(statement).encode("utf-8"))
    for ev in sorted(evidence, key=lambda e: (e.segment_id, e.quote)):
        h.update(b"\x00")
        h.update(ev.segment_id.encode("utf-8"))
        h.update(b"\x00")
        h.update(normalize_for_match(ev.quote).encode("utf-8"))
    return f"clm_{h.hexdigest()[:12]}"


def quote_is_grounded(quote: str, segment_text: str) -> bool:
    """True when `quote` appears verbatim in `segment_text`.

    Comparison is whitespace-normalised and case-insensitive because caption
    formatting is noisy, but no word may differ: this is the check that makes
    an invented quote fail the build.
    """
    return normalize_for_match(quote) in normalize_for_match(segment_text)


def claim_filename(claim: Claim) -> str:
    safe_concept = "".join(c if c.isalnum() or c == "_" else "_" for c in claim.concept) or "misc"
    return f"{claim.source_key}__{safe_concept}__{claim.claim_id}.json"
