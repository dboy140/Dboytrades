"""Tests for provenance enforcement.

The transcript text and claims here are synthetic scaffolding invented to
exercise the validator. Nothing in this file quotes or characterises any real
creator.
"""

import json

import pytest

from ictkb.claims import Claim, Evidence, compute_claim_id, quote_is_grounded
from ictkb.validate import Severity, validate

VID = "TESTvid0001"
SEG_TEXT = "when the marker appears above the line we treat that as the signal to wait"


@pytest.fixture
def kb(tmp_path):
    """A minimal well-formed corpus + knowledge base on disk."""
    segments_path = tmp_path / "segments.jsonl"
    claims_dir = tmp_path / "claims"
    rules_dir = tmp_path / "rules"
    claims_dir.mkdir()
    rules_dir.mkdir()

    segment = {
        "segment_id": f"{VID}:0",
        "video_id": VID,
        "source_key": "ICT",
        "start_s": 0.0,
        "end_s": 45.0,
        "text": SEG_TEXT,
        "url": f"https://www.youtube.com/watch?v={VID}&t=0s",
        "caption_kind": "manual",
        "video_title": "Synthetic Fixture",
        "published_at": None,
        "language": "en",
    }
    segments_path.write_text(json.dumps(segment) + "\n", encoding="utf-8")

    def write_claim(claim: Claim):
        (claims_dir / f"{claim.claim_id}.json").write_text(
            json.dumps(claim.to_dict(), indent=2), encoding="utf-8"
        )
        return claim

    def write_rule(rule: dict):
        (rules_dir / f"{rule['rule_id']}.json").write_text(
            json.dumps(rule, indent=2), encoding="utf-8"
        )
        return rule

    def run(**kw):
        return validate(
            segments_path=segments_path, claims_dir=claims_dir, rules_dir=rules_dir, **kw
        )

    return {
        "tmp": tmp_path,
        "segments_path": segments_path,
        "claims_dir": claims_dir,
        "rules_dir": rules_dir,
        "write_claim": write_claim,
        "write_rule": write_rule,
        "run": run,
    }


def make_claim(quote=None, **overrides):
    kwargs = dict(
        statement="A marker above the line indicates waiting.",
        concept="execution",
        source_key="ICT",
        evidence=[
            Evidence(
                segment_id=f"{VID}:0",
                video_id=VID,
                start_s=0.0,
                quote=quote or "we treat that as the signal to wait",
                url=f"https://www.youtube.com/watch?v={VID}&t=0s",
            )
        ],
        confidence="high",
        method="human",
        reviewer="fixture",
    )
    kwargs.update(overrides)
    return Claim(**kwargs)


def make_rule(claim_ids, **overrides):
    rule = {
        "rule_id": "rul_wait_on_marker",
        "name": "Wait on marker",
        "phase": "filter",
        "priority": 10,
        "when": [{"fact": "marker.above_line", "op": "eq", "value": True, "timeframe": "5m"}],
        "then": {"action": "block_trading", "params": {}},
        "derived_from": list(claim_ids),
        "status": "accepted",
    }
    rule.update(overrides)
    return rule


def codes(report):
    return {f.code for f in report.findings}


def error_codes(report):
    return {f.code for f in report.errors}


class TestQuoteGrounding:
    def test_verbatim_quote_is_grounded(self):
        assert quote_is_grounded("the signal to wait", SEG_TEXT)

    def test_case_and_whitespace_insensitive(self):
        assert quote_is_grounded("  THE   SIGNAL\n to WAIT ", SEG_TEXT)

    def test_invented_quote_is_not_grounded(self):
        assert not quote_is_grounded("always enter at the london open", SEG_TEXT)

    def test_altered_wording_is_not_grounded(self):
        # One word changed: "signal" -> "sign".
        assert not quote_is_grounded("we treat that as the sign to wait", SEG_TEXT)


class TestHappyPath:
    def test_well_formed_kb_passes(self, kb):
        claim = kb["write_claim"](make_claim())
        kb["write_rule"](make_rule([claim.claim_id]))
        report = kb["run"]()
        assert report.ok, [str(f) for f in report.errors]
        assert report.n_claims == 1
        assert report.n_rules == 1
        assert report.n_segments == 1


class TestFabricationDetection:
    def test_fabricated_quote_fails_the_build(self, kb):
        """The headline guarantee: an invented quote cannot pass validation."""
        claim = make_claim(quote="you must always enter on the first retracement")
        kb["write_claim"](claim)
        kb["write_rule"](make_rule([claim.claim_id]))

        report = kb["run"]()

        assert not report.ok
        assert "quote_not_grounded" in error_codes(report)

    def test_evidence_pointing_at_absent_segment_fails(self, kb):
        claim = make_claim()
        # Repoint evidence at a segment that is not in the corpus.
        d = claim.to_dict()
        d["evidence"][0]["segment_id"] = f"{VID}:999999"
        d["claim_id"] = d["claim_id"]
        (kb["claims_dir"] / "bad.json").write_text(json.dumps(d), encoding="utf-8")

        report = kb["run"]()

        assert not report.ok
        assert "evidence_segment_missing" in error_codes(report)

    def test_video_id_mismatch_fails(self, kb):
        d = make_claim().to_dict()
        d["evidence"][0]["video_id"] = "OTHERvid001"
        (kb["claims_dir"] / "bad.json").write_text(json.dumps(d), encoding="utf-8")

        report = kb["run"]()

        assert "evidence_video_mismatch" in error_codes(report)

    def test_silently_edited_claim_is_caught(self, kb):
        """Editing a statement without regenerating the id must not slip through."""
        claim = make_claim()
        d = claim.to_dict()
        d["statement"] = "A completely different assertion that was swapped in later."
        (kb["claims_dir"] / "edited.json").write_text(json.dumps(d), encoding="utf-8")

        report = kb["run"]()

        assert not report.ok
        assert "claim_id_mismatch" in error_codes(report)


class TestRuleGrounding:
    def test_rule_citing_unknown_claim_fails(self, kb):
        kb["write_rule"](make_rule(["clm_000000000000"]))
        report = kb["run"]()
        assert not report.ok
        assert "rule_claim_missing" in error_codes(report)

    def test_rule_with_no_claims_fails_schema_and_grounding(self, kb):
        kb["write_rule"](make_rule([]))
        report = kb["run"]()
        assert not report.ok
        # minItems:1 in the schema, plus the explicit grounding check.
        assert {"rule_ungrounded", "rule_schema"} & error_codes(report)

    def test_accepted_rule_on_contradicted_claim_fails(self, kb):
        other = kb["write_claim"](
            make_claim(statement="A contradicting assertion for the fixture.")
        )
        conflicted = make_claim(
            statement="An assertion that conflicts with the other one.",
            contradicts=[other.claim_id],
        )
        kb["write_claim"](conflicted)
        kb["write_rule"](make_rule([conflicted.claim_id]))

        report = kb["run"]()

        assert not report.ok
        assert "accepted_on_contradiction" in error_codes(report)

    def test_draft_rule_on_contradiction_is_allowed(self, kb):
        other = kb["write_claim"](make_claim(statement="Another assertion for the fixture."))
        conflicted = kb["write_claim"](
            make_claim(
                statement="An assertion that conflicts, still under review.",
                contradicts=[other.claim_id],
            )
        )
        kb["write_rule"](make_rule([conflicted.claim_id], status="draft"))

        report = kb["run"]()

        assert "accepted_on_contradiction" not in error_codes(report)

    def test_contradiction_referencing_nothing_fails(self, kb):
        kb["write_claim"](make_claim(contradicts=["clm_ffffffffffff"]))
        report = kb["run"]()
        assert "contradiction_unresolved_ref" in error_codes(report)


class TestParameterHonesty:
    def test_undeclared_numeric_param_warns(self, kb):
        claim = kb["write_claim"](make_claim())
        kb["write_rule"](
            make_rule(
                [claim.claim_id],
                then={"action": "size_position", "params": {"risk_pct": 0.5}},
            )
        )
        report = kb["run"]()
        assert "param_provenance_unclear" in codes(report)

    def test_declared_unsourced_param_does_not_warn(self, kb):
        claim = kb["write_claim"](make_claim())
        kb["write_rule"](
            make_rule(
                [claim.claim_id],
                then={"action": "size_position", "params": {"risk_pct": 0.5}},
                unsourced_params=["risk_pct"],
            )
        )
        report = kb["run"]()
        assert "param_provenance_unclear" not in codes(report)


class TestConfidenceHygiene:
    def test_high_confidence_on_auto_captions_warns(self, kb):
        seg = json.loads(kb["segments_path"].read_text())
        seg["caption_kind"] = "auto"
        kb["segments_path"].write_text(json.dumps(seg) + "\n", encoding="utf-8")
        kb["write_claim"](make_claim(confidence="high"))

        report = kb["run"]()

        assert "high_confidence_auto_captions" in codes(report)


class TestEmptyKnowledgeBase:
    """The state this repository ships in: nothing ingested, nothing claimed."""

    @pytest.fixture
    def empty(self, tmp_path):
        claims_dir = tmp_path / "claims"
        rules_dir = tmp_path / "rules"
        claims_dir.mkdir()
        rules_dir.mkdir()

        def run(**kw):
            return validate(
                segments_path=tmp_path / "missing.jsonl",
                claims_dir=claims_dir,
                rules_dir=rules_dir,
                **kw,
            )

        return run

    def test_empty_is_a_warning_by_default(self, empty):
        report = empty()
        assert report.ok
        assert {"empty_corpus", "empty_claims", "empty_rules"} <= codes(report)

    def test_empty_is_an_error_under_strict(self, empty):
        report = empty(strict_empty=True)
        assert not report.ok
        assert "empty_corpus" in error_codes(report)


class TestClaimConstruction:
    def test_claim_without_evidence_is_unrepresentable(self):
        from ictkb.claims import ClaimError

        with pytest.raises(ClaimError):
            Claim(statement="An unsupported assertion.", concept="x", source_key="ICT", evidence=[])

    def test_claim_id_changes_when_statement_changes(self):
        ev = [Evidence(segment_id=f"{VID}:0", video_id=VID, start_s=0.0, quote="the signal to wait")]
        a = compute_claim_id("First assertion.", ev)
        b = compute_claim_id("Second assertion.", ev)
        assert a != b

    def test_claim_id_changes_when_evidence_changes(self):
        base = [Evidence(segment_id=f"{VID}:0", video_id=VID, start_s=0.0, quote="the signal to wait")]
        moved = [Evidence(segment_id=f"{VID}:30000", video_id=VID, start_s=30.0, quote="the signal to wait")]
        assert compute_claim_id("Same words.", base) != compute_claim_id("Same words.", moved)

    def test_claim_id_is_order_independent(self):
        e1 = Evidence(segment_id=f"{VID}:0", video_id=VID, start_s=0.0, quote="quote one here")
        e2 = Evidence(segment_id=f"{VID}:30000", video_id=VID, start_s=30.0, quote="quote two here")
        assert compute_claim_id("S.", [e1, e2]) == compute_claim_id("S.", [e2, e1])
