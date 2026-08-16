"""Tests for the pydantic layer.

The Rule model is the contract that keeps the final system citable, so its
refusals matter as much as its acceptances.
"""

import pytest
from pydantic import ValidationError

from scripts.models import Rule, RuleSource, Transcript, TranscriptSegment, VideoMeta

VID = "abcDEF12345"


def a_source(**kw):
    base = dict(
        channel="ICT",
        video_id=VID,
        title="Some in-scope video",
        published="2023-06-14",
        timestamp="01:12:40",
    )
    base.update(kw)
    return RuleSource(**base)


def a_rule(**kw):
    base = dict(
        rule_id="SB-001",
        topic_bucket="silver_bullet",
        concept="Silver Bullet",
        category="entry_model",
        statement="Arm the setup only inside the defined execution window.",
        sources=[a_source()],
    )
    base.update(kw)
    return Rule(**base)


class TestRuleSource:
    def test_link_is_derived_from_timestamp(self):
        s = a_source(timestamp="01:12:40")
        assert s.timestamp_seconds == 4360
        assert s.link == f"https://youtu.be/{VID}?t=4360"

    def test_mmss_timestamp_accepted(self):
        assert a_source(timestamp="12:40").timestamp_seconds == 760

    def test_explicit_link_is_preserved(self):
        s = a_source(link="https://youtu.be/x?t=1")
        assert s.link == "https://youtu.be/x?t=1"

    def test_bad_timestamp_rejected(self):
        with pytest.raises(ValidationError):
            a_source(timestamp="about an hour in")

    def test_bad_video_id_rejected(self):
        with pytest.raises(ValidationError):
            a_source(video_id="tooshort")


class TestRule:
    def test_valid_rule_builds(self):
        assert a_rule().rule_id == "SB-001"

    def test_rule_without_sources_is_unrepresentable(self):
        """No citation, no rule — enforced by the type, not by convention."""
        with pytest.raises(ValidationError):
            a_rule(sources=[])

    def test_transcript_filler_is_rejected(self):
        # Guards ground rule 3: paraphrase, never transcribe.
        with pytest.raises(ValidationError) as exc:
            a_rule(statement="so you know we're gonna wait for the thing to happen here")
        assert "paraphrased" in str(exc.value)

    def test_short_statement_rejected(self):
        with pytest.raises(ValidationError):
            a_rule(statement="wait")

    def test_bad_category_rejected(self):
        with pytest.raises(ValidationError):
            a_rule(category="vibes")

    def test_completeness_requires_stop_target_invalidation(self):
        assert not a_rule().is_complete_setup
        full = a_rule(
            stop_loss="Below the swing low that produced displacement.",
            target="Opposing liquidity pool.",
            invalidation="Close back through the originating gap.",
        )
        assert full.is_complete_setup

    def test_defaults_are_conservative(self):
        r = a_rule()
        assert r.confidence == "medium"
        assert r.session == "any"
        assert r.mentions == 1


class TestVideoMeta:
    def test_link_at_builds_deep_link(self):
        v = VideoMeta(video_id=VID, title="t", url="u", channel_key="ICT")
        assert v.link_at(4360) == f"https://youtu.be/{VID}?t=4360"

    def test_duration_hours(self):
        v = VideoMeta(video_id=VID, title="t", url="u", channel_key="ICT", duration_seconds=5400)
        assert v.duration_hours == 1.5

    def test_invalid_id_rejected(self):
        with pytest.raises(ValidationError):
            VideoMeta(video_id="nope", title="t", url="u", channel_key="ICT")


class TestTranscript:
    def _t(self):
        return Transcript(
            id=VID,
            title="t",
            channel="ICT",
            segments=[
                TranscriptSegment(start_seconds=0, text="alpha bravo"),
                TranscriptSegment(start_seconds=30, text="charlie delta"),
                TranscriptSegment(start_seconds=90, text="echo foxtrot"),
            ],
        )

    def test_word_count(self):
        assert self._t().word_count == 6

    def test_segment_at_finds_nearest(self):
        seg = self._t().segment_at(32)
        assert seg is not None and seg.start_seconds == 30

    def test_segment_at_respects_tolerance(self):
        # A citation far from any segment must not silently resolve.
        assert self._t().segment_at(5000, tolerance=60) is None

    def test_empty_segment_text_rejected(self):
        with pytest.raises(ValidationError):
            TranscriptSegment(start_seconds=0, text="   ")

    def test_negative_start_rejected(self):
        with pytest.raises(ValidationError):
            TranscriptSegment(start_seconds=-1, text="x")
