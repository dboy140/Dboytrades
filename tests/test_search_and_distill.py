"""Tests for BM25 retrieval and system compilation.

Transcript text is synthetic filler written for these tests only.
"""

import json

import pytest

from ictkb.distill import build_system, render_markdown
from ictkb.search import BM25Index, tokenize

VID_A = "TESTvidAAAA"
VID_B = "TESTvidBBBB"


def seg(video_id, start_ms, text, source_key="ICT"):
    start_s = start_ms / 1000
    return {
        "segment_id": f"{video_id}:{start_ms}",
        "video_id": video_id,
        "source_key": source_key,
        "start_s": start_s,
        "end_s": start_s + 45,
        "text": text,
        "url": f"https://www.youtube.com/watch?v={video_id}&t={int(start_s)}s",
        "caption_kind": "manual",
        "video_title": f"Fixture {video_id}",
    }


@pytest.fixture
def corpus():
    return [
        seg(VID_A, 0, "the orange marker sits above the blue line on the chart"),
        seg(VID_A, 30000, "we wait for the counter to reset before doing anything else"),
        seg(VID_B, 0, "the blue line crosses the orange marker in the other direction", "NBBTRADER"),
        seg(VID_B, 30000, "nothing relevant is discussed in this particular stretch"),
    ]


class TestTokenize:
    def test_lowercases_and_splits(self):
        assert tokenize("The Orange Marker!", drop_stopwords=False) == ["the", "orange", "marker"]

    def test_drops_stopwords_by_default(self):
        assert "the" not in tokenize("the orange marker")

    def test_keeps_apostrophes(self):
        assert "don't" in tokenize("don't", drop_stopwords=False)


class TestBM25:
    def test_finds_relevant_segment(self, corpus):
        hits = BM25Index(corpus).search("orange marker")
        assert hits
        assert hits[0].segment_id in {f"{VID_A}:0", f"{VID_B}:0"}

    def test_irrelevant_query_returns_nothing(self, corpus):
        assert BM25Index(corpus).search("zebra quantum helicopter") == []

    def test_source_filter(self, corpus):
        hits = BM25Index(corpus).search("orange marker", source_key="NBBTRADER")
        assert hits
        assert all(h.source_key == "NBBTRADER" for h in hits)

    def test_hit_carries_citation_anchors(self, corpus):
        hit = BM25Index(corpus).search("counter reset")[0]
        assert hit.video_id == VID_A
        assert hit.start_s == 30.0
        assert hit.url.endswith("&t=30s")
        assert hit.citation() == f"{VID_A}@30s"

    def test_search_any_dedupes_across_aliases(self, corpus):
        hits = BM25Index(corpus).search_any(["orange marker", "blue line"], top_k=10)
        assert len({h.segment_id for h in hits}) == len(hits)

    def test_empty_corpus_is_safe(self):
        assert BM25Index([]).search("anything") == []

    def test_stopword_only_query_is_safe(self, corpus):
        # Must not raise; falls back to unfiltered tokens.
        BM25Index(corpus).search("the and of")


class TestDistill:
    def _write(self, tmp_path, segments, claims, rules):
        seg_path = tmp_path / "segments.jsonl"
        seg_path.write_text("".join(json.dumps(s) + "\n" for s in segments), encoding="utf-8")
        cdir = tmp_path / "claims"
        rdir = tmp_path / "rules"
        cdir.mkdir()
        rdir.mkdir()
        for c in claims:
            (cdir / f"{c['claim_id']}.json").write_text(json.dumps(c), encoding="utf-8")
        for r in rules:
            (rdir / f"{r['rule_id']}.json").write_text(json.dumps(r), encoding="utf-8")
        return seg_path, cdir, rdir

    def test_empty_kb_is_not_executable_and_invents_nothing(self, tmp_path):
        seg_path, cdir, rdir = self._write(tmp_path, [], [], [])
        system = build_system(claims_dir=cdir, rules_dir=rdir, segments_path=seg_path)

        assert system["completeness"]["executable"] is False
        assert system["rules"] == []
        assert system["counts"]["rules_accepted"] == 0

        md = render_markdown(system)
        assert "not executable" in md.lower()
        assert "corpus is empty" in md.lower()

    def test_draft_rules_are_excluded(self, tmp_path, corpus):
        from ictkb.claims import Claim, Evidence

        claim = Claim(
            statement="A synthetic assertion for the distiller test.",
            concept="execution",
            source_key="ICT",
            evidence=[
                Evidence(
                    segment_id=f"{VID_A}:0",
                    video_id=VID_A,
                    start_s=0.0,
                    quote="the orange marker sits above the blue line",
                )
            ],
            method="human",
            reviewer="fixture",
        )
        rules = [
            {
                "rule_id": "rul_accepted_one",
                "name": "Accepted",
                "phase": "entry",
                "when": [{"fact": "marker.above", "op": "eq", "value": True}],
                "then": {"action": "enter"},
                "derived_from": [claim.claim_id],
                "status": "accepted",
            },
            {
                "rule_id": "rul_draft_one",
                "name": "Draft",
                "phase": "entry",
                "when": [{"fact": "marker.above", "op": "eq", "value": True}],
                "then": {"action": "enter"},
                "derived_from": [claim.claim_id],
                "status": "draft",
            },
        ]
        seg_path, cdir, rdir = self._write(tmp_path, corpus, [claim.to_dict()], rules)
        system = build_system(claims_dir=cdir, rules_dir=rdir, segments_path=seg_path)

        ids = [r["rule_id"] for r in system["rules"]]
        assert ids == ["rul_accepted_one"]

    def test_accepted_rule_carries_resolved_citations(self, tmp_path, corpus):
        from ictkb.claims import Claim, Evidence

        claim = Claim(
            statement="A synthetic assertion carrying a citation.",
            concept="execution",
            source_key="ICT",
            evidence=[
                Evidence(
                    segment_id=f"{VID_A}:30000",
                    video_id=VID_A,
                    start_s=30.0,
                    quote="we wait for the counter to reset",
                )
            ],
            method="human",
            reviewer="fixture",
        )
        rule = {
            "rule_id": "rul_cited",
            "name": "Cited rule",
            "phase": "filter",
            "when": [{"fact": "counter.reset", "op": "eq", "value": False}],
            "then": {"action": "block_trading"},
            "derived_from": [claim.claim_id],
            "status": "accepted",
        }
        seg_path, cdir, rdir = self._write(tmp_path, corpus, [claim.to_dict()], [rule])
        system = build_system(claims_dir=cdir, rules_dir=rdir, segments_path=seg_path)

        cites = system["rules"][0]["citations"]
        assert len(cites) == 1
        assert cites[0]["video_id"] == VID_A
        assert cites[0]["start_s"] == 30.0
        assert cites[0]["url"].endswith("&t=30s")

        md = render_markdown(system)
        assert VID_A in md
        assert "we wait for the counter to reset" in md

    def test_facts_required_are_collected(self, tmp_path, corpus):
        from ictkb.claims import Claim, Evidence

        claim = Claim(
            statement="Assertion used to collect required facts.",
            concept="execution",
            source_key="ICT",
            evidence=[
                Evidence(
                    segment_id=f"{VID_A}:0",
                    video_id=VID_A,
                    start_s=0.0,
                    quote="the orange marker sits above the blue line",
                )
            ],
            method="human",
            reviewer="fixture",
        )
        rule = {
            "rule_id": "rul_facts",
            "name": "Facts",
            "phase": "setup",
            "when": [
                {"fact": "session", "op": "in", "value": ["a", "b"]},
                {"fact": "marker.above", "op": "eq", "value": True},
            ],
            "then": {"action": "arm_setup"},
            "derived_from": [claim.claim_id],
            "status": "accepted",
        }
        seg_path, cdir, rdir = self._write(tmp_path, corpus, [claim.to_dict()], [rule])
        system = build_system(claims_dir=cdir, rules_dir=rdir, segments_path=seg_path)

        assert system["facts_required"] == ["marker.above", "session"]
