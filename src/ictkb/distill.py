"""Compile accepted rules into one executable trading system.

The distiller refuses to invent connective tissue. If a phase has no accepted
rule, the emitted system records the gap rather than filling it with a sensible
default, because a plausible default is indistinguishable from a sourced rule
once it is written down.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config as cfg
from .claims import Claim
from .store import load_dir_json, read_jsonl, write_json

PHASE_ORDER = ["bias", "filter", "setup", "entry", "stop", "target", "risk"]


def _phase_sort_key(rule: dict[str, Any]) -> tuple[int, int, str]:
    phase = rule.get("phase", "")
    pidx = PHASE_ORDER.index(phase) if phase in PHASE_ORDER else len(PHASE_ORDER)
    return (pidx, int(rule.get("priority", 100)), rule.get("rule_id", ""))


def build_system(
    *,
    claims_dir: Path | None = None,
    rules_dir: Path | None = None,
    segments_path: Path | None = None,
    conf: cfg.Config | None = None,
) -> dict[str, Any]:
    conf = conf or cfg.load_config()
    claims_dir = claims_dir or cfg.CLAIMS_DIR
    rules_dir = rules_dir or cfg.RULES_DIR
    segments_path = segments_path or cfg.SEGMENTS_PATH

    segments = {s["segment_id"]: s for s in read_jsonl(segments_path) if "segment_id" in s}
    claims = {}
    for raw in load_dir_json(claims_dir):
        try:
            c = Claim.from_dict(raw)
            claims[c.claim_id] = c
        except Exception:
            continue

    all_rules = load_dir_json(rules_dir)
    accepted = [r for r in all_rules if r.get("status") == "accepted"]
    accepted.sort(key=_phase_sort_key)

    required = conf.required_phases or PHASE_ORDER
    covered = {r.get("phase") for r in accepted}
    missing_phases = [p for p in required if p not in covered]

    compiled_rules = []
    for rule in accepted:
        citations = []
        for cid in rule.get("derived_from", []):
            claim = claims.get(cid)
            if not claim:
                continue
            for ev in claim.evidence:
                seg = segments.get(ev.segment_id)
                citations.append(
                    {
                        "claim_id": cid,
                        "source_key": claim.source_key,
                        "video_id": ev.video_id,
                        "start_s": ev.start_s,
                        "url": ev.url or f"https://www.youtube.com/watch?v={ev.video_id}&t={int(ev.start_s)}s",
                        "quote": ev.quote,
                        "video_title": (seg or {}).get("video_title", ""),
                    }
                )
        compiled = dict(rule)
        compiled["citations"] = citations
        compiled_rules.append(compiled)

    facts_required = sorted(
        {
            cond.get("fact")
            for rule in accepted
            for cond in (rule.get("when") or [])
            if cond.get("fact")
        }
    )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "corpus": {
            "segments": len(segments),
            "videos": len({s["video_id"] for s in segments.values()}),
            "sources": sorted({s.get("source_key", "") for s in segments.values()} - {""}),
        },
        "counts": {
            "claims": len(claims),
            "rules_total": len(all_rules),
            "rules_accepted": len(accepted),
        },
        "completeness": {
            "required_phases": required,
            "covered_phases": sorted(p for p in covered if p),
            "missing_phases": missing_phases,
            "executable": not missing_phases and bool(accepted),
        },
        "facts_required": facts_required,
        "rules": compiled_rules,
    }


def render_markdown(system: dict[str, Any]) -> str:
    lines: list[str] = []
    a = lines.append

    a("# Distilled Trading System")
    a("")
    a(f"Generated: {system['generated_at']}")
    a("")

    comp = system["completeness"]
    corpus = system["corpus"]

    if not comp["executable"]:
        a("> **This system is not executable.**")
        a(">")
        if corpus["segments"] == 0:
            a("> The transcript corpus is empty — no source material has been ingested,")
            a("> so there is nothing to distil. See `docs/BLOCKED.md`.")
        if comp["missing_phases"]:
            a(f"> Missing required phases: `{'`, `'.join(comp['missing_phases'])}`.")
        a(">")
        a("> No rules have been invented to fill these gaps. A system assembled from")
        a("> plausible defaults would be indistinguishable from one grounded in the")
        a("> sources, which would defeat the purpose of this repository.")
        a("")

    a("## Corpus")
    a("")
    a(f"- Videos ingested: **{corpus['videos']}**")
    a(f"- Citable segments: **{corpus['segments']}**")
    a(f"- Sources: {', '.join(corpus['sources']) or '_none_'}")
    a(f"- Claims: **{system['counts']['claims']}**")
    a(f"- Rules accepted: **{system['counts']['rules_accepted']}** of {system['counts']['rules_total']}")
    a("")

    if system["facts_required"]:
        a("## Market facts the engine must supply")
        a("")
        a("Every condition below must be computable from price data before this")
        a("system can be backtested.")
        a("")
        for fact in system["facts_required"]:
            a(f"- `{fact}`")
        a("")

    if not system["rules"]:
        a("## Rules")
        a("")
        a("_No accepted rules._")
        return "\n".join(lines) + "\n"

    current_phase = None
    for rule in system["rules"]:
        if rule.get("phase") != current_phase:
            current_phase = rule.get("phase")
            a(f"## Phase: {current_phase}")
            a("")

        a(f"### {rule.get('name')} (`{rule.get('rule_id')}`)")
        a("")
        a("**When all of:**")
        a("")
        for cond in rule.get("when", []):
            tf = f" on `{cond['timeframe']}`" if cond.get("timeframe") else ""
            a(f"- `{cond.get('fact')}` {cond.get('op')} `{cond.get('value')}`{tf}")
        a("")
        then = rule.get("then", {})
        a(f"**Then:** `{then.get('action')}`")
        if then.get("params"):
            a("")
            for k, v in sorted(then["params"].items()):
                flag = " _(unsourced default)_" if k in (rule.get("unsourced_params") or []) else ""
                a(f"- `{k}` = `{v}`{flag}")
        a("")
        a("**Sources:**")
        a("")
        for c in rule.get("citations", []):
            title = f" — {c['video_title']}" if c.get("video_title") else ""
            a(f"- [{c['source_key']} {c['video_id']} @ {int(c['start_s'])}s]({c['url']}){title}")
            a(f"  > {c['quote']}")
        if not rule.get("citations"):
            a("- _none resolved_")
        a("")

    return "\n".join(lines) + "\n"


def write_system(system: dict[str, Any], out_dir: Path | None = None) -> tuple[Path, Path]:
    out_dir = out_dir or cfg.SYSTEM_DIR
    json_path = out_dir / "trading_system.json"
    md_path = out_dir / "TRADING_SYSTEM.md"
    write_json(json_path, system)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_markdown(system), encoding="utf-8")
    return json_path, md_path
