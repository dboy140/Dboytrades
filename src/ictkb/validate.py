"""Provenance enforcement.

This module is the reason the project is trustworthy. It answers one question
for every rule in the system: can this be traced, mechanically, to a specific
human saying a specific thing at a specific timestamp in a specific video?

Failure modes it is built to catch:
  * a rule citing a claim that does not exist
  * a claim citing a segment that is not in the corpus
  * a quote that does not actually appear in the segment it cites  <- fabrication
  * a claim ID that no longer matches its own content (silent edit)
  * a rule whose numeric parameters were invented but not declared as such
  * a rule built on an unresolved contradiction between sources

Exit status is non-zero if any error-level finding is present, so this can gate
CI and no ungrounded rule can reach the compiled system.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from . import config as cfg
from .claims import Claim, compute_claim_id, quote_is_grounded
from .store import load_dir_json, read_jsonl


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass
class Finding:
    severity: Severity
    code: str
    message: str
    subject: str = ""

    def __str__(self) -> str:
        where = f" [{self.subject}]" if self.subject else ""
        return f"{self.severity.value.upper()} {self.code}{where}: {self.message}"


@dataclass
class ValidationReport:
    findings: list[Finding]
    n_segments: int
    n_claims: int
    n_rules: int

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity is Severity.WARNING]

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        lines = [
            f"corpus:  {self.n_segments} segments",
            f"claims:  {self.n_claims}",
            f"rules:   {self.n_rules}",
            f"errors:  {len(self.errors)}",
            f"warnings:{len(self.warnings)}",
        ]
        return "\n".join(lines)


def _load_schema(name: str) -> dict[str, Any] | None:
    path = cfg.SCHEMA_DIR / name
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _schema_findings(
    instances: Iterable[tuple[str, dict[str, Any]]], schema_name: str, code: str
) -> list[Finding]:
    schema = _load_schema(schema_name)
    if schema is None:
        return [
            Finding(Severity.WARNING, "schema_missing", f"{schema_name} not found; skipped")
        ]
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        return [
            Finding(
                Severity.WARNING,
                "jsonschema_missing",
                "jsonschema not installed; structural validation skipped "
                "(pip install -r requirements.txt)",
            )
        ]
    validator = Draft202012Validator(schema)
    out: list[Finding] = []
    for subject, inst in instances:
        for err in validator.iter_errors(inst):
            loc = "/".join(str(p) for p in err.absolute_path) or "<root>"
            out.append(Finding(Severity.ERROR, code, f"{loc}: {err.message}", subject))
    return out


def validate(
    *,
    segments_path: Path | None = None,
    claims_dir: Path | None = None,
    rules_dir: Path | None = None,
    strict_empty: bool = False,
) -> ValidationReport:
    segments_path = segments_path or cfg.SEGMENTS_PATH
    claims_dir = claims_dir or cfg.CLAIMS_DIR
    rules_dir = rules_dir or cfg.RULES_DIR

    findings: list[Finding] = []

    segments = {s["segment_id"]: s for s in read_jsonl(segments_path) if "segment_id" in s}
    raw_claims = load_dir_json(claims_dir)
    raw_rules = load_dir_json(rules_dir)

    # --- structural ---
    findings += _schema_findings(
        ((s.get("segment_id", "?"), s) for s in segments.values()),
        "segment.schema.json",
        "segment_schema",
    )
    findings += _schema_findings(
        ((c.get("claim_id", "?"), c) for c in raw_claims), "claim.schema.json", "claim_schema"
    )
    findings += _schema_findings(
        ((r.get("rule_id", "?"), r) for r in raw_rules), "rule.schema.json", "rule_schema"
    )

    # --- emptiness ---
    if not segments:
        sev = Severity.ERROR if strict_empty else Severity.WARNING
        findings.append(
            Finding(
                sev,
                "empty_corpus",
                "no transcript segments ingested. Nothing can be cited until "
                "`ictkb ingest` runs successfully against Apify.",
            )
        )
    if not raw_claims:
        sev = Severity.ERROR if strict_empty else Severity.WARNING
        findings.append(Finding(sev, "empty_claims", "knowledge base contains no claims"))
    if not raw_rules:
        sev = Severity.ERROR if strict_empty else Severity.WARNING
        findings.append(Finding(sev, "empty_rules", "no rules defined"))

    # --- claims ---
    claims_by_id: dict[str, Claim] = {}
    for raw in raw_claims:
        cid = raw.get("claim_id", "<no id>")
        try:
            claim = Claim.from_dict(raw)
        except Exception as exc:  # malformed beyond schema repair
            findings.append(Finding(Severity.ERROR, "claim_unloadable", str(exc), cid))
            continue

        if claim.claim_id in claims_by_id:
            findings.append(
                Finding(Severity.ERROR, "claim_duplicate", "duplicate claim_id", claim.claim_id)
            )
        claims_by_id[claim.claim_id] = claim

        expected = compute_claim_id(claim.statement, claim.evidence)
        if expected != claim.claim_id:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "claim_id_mismatch",
                    f"content-addressed id should be {expected}. The statement or its "
                    "evidence was edited without regenerating the id, so any rule "
                    "citing this claim is citing something that no longer exists.",
                    claim.claim_id,
                )
            )

        auto_only = True
        for ev in claim.evidence:
            seg = segments.get(ev.segment_id)
            if seg is None:
                findings.append(
                    Finding(
                        Severity.ERROR,
                        "evidence_segment_missing",
                        f"segment {ev.segment_id} is not in the corpus, so this quote "
                        "cannot be verified against anything.",
                        claim.claim_id,
                    )
                )
                continue

            if seg.get("video_id") != ev.video_id:
                findings.append(
                    Finding(
                        Severity.ERROR,
                        "evidence_video_mismatch",
                        f"evidence says video {ev.video_id} but segment {ev.segment_id} "
                        f"belongs to {seg.get('video_id')}",
                        claim.claim_id,
                    )
                )

            if not quote_is_grounded(ev.quote, seg.get("text", "")):
                findings.append(
                    Finding(
                        Severity.ERROR,
                        "quote_not_grounded",
                        f"quote does not appear in segment {ev.segment_id} "
                        f"({ev.video_id} @ {int(ev.start_s)}s). Either the wording was "
                        "altered or the citation is fabricated.",
                        claim.claim_id,
                    )
                )

            if seg.get("caption_kind") != "auto":
                auto_only = False

        if auto_only and claim.confidence == "high":
            findings.append(
                Finding(
                    Severity.WARNING,
                    "high_confidence_auto_captions",
                    "confidence 'high' rests only on auto-generated captions, which "
                    "routinely mis-transcribe trading jargon. Downgrade to 'medium' "
                    "or verify against the video.",
                    claim.claim_id,
                )
            )

        if claim.method == "llm_proposed" and claim.reviewer is None:
            findings.append(
                Finding(
                    Severity.WARNING,
                    "claim_unreviewed",
                    "llm_proposed claim has no reviewer; the distiller will ignore it",
                    claim.claim_id,
                )
            )

    # contradictions must point somewhere real
    for claim in claims_by_id.values():
        for other in claim.contradicts:
            if other not in claims_by_id:
                findings.append(
                    Finding(
                        Severity.ERROR,
                        "contradiction_unresolved_ref",
                        f"contradicts unknown claim {other}",
                        claim.claim_id,
                    )
                )

    # --- rules ---
    seen_rule_ids: set[str] = set()
    for raw in raw_rules:
        rid = raw.get("rule_id", "<no id>")
        if rid in seen_rule_ids:
            findings.append(Finding(Severity.ERROR, "rule_duplicate", "duplicate rule_id", rid))
        seen_rule_ids.add(rid)

        derived = raw.get("derived_from") or []
        if not derived:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "rule_ungrounded",
                    "rule derives from no claim; it cannot be traced to any video",
                    rid,
                )
            )
        for cid in derived:
            if cid not in claims_by_id:
                findings.append(
                    Finding(
                        Severity.ERROR,
                        "rule_claim_missing",
                        f"derives from unknown claim {cid}",
                        rid,
                    )
                )

        # A rule accepted on the back of contradicted claims is a silent bet on
        # one side of a disagreement. Force it to be resolved explicitly.
        if raw.get("status") == "accepted":
            for cid in derived:
                claim = claims_by_id.get(cid)
                if claim and claim.contradicts:
                    findings.append(
                        Finding(
                            Severity.ERROR,
                            "accepted_on_contradiction",
                            f"accepted rule rests on claim {cid}, which is marked as "
                            f"contradicting {claim.contradicts}. Resolve the conflict "
                            "and clear `contradicts` before accepting.",
                            rid,
                        )
                    )

        params = ((raw.get("then") or {}).get("params") or {})
        declared = set(raw.get("unsourced_params") or [])
        numeric = {k for k, v in params.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
        undeclared = numeric - declared
        if undeclared and raw.get("status") == "accepted":
            findings.append(
                Finding(
                    Severity.WARNING,
                    "param_provenance_unclear",
                    f"numeric parameters {sorted(undeclared)} are not declared in "
                    "`unsourced_params` and are not obviously quoted from a source. "
                    "Declare them, or cite where the number came from.",
                    rid,
                )
            )

    return ValidationReport(
        findings=findings,
        n_segments=len(segments),
        n_claims=len(claims_by_id),
        n_rules=len(raw_rules),
    )
