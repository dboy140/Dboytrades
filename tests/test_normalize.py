"""Tests for cue parsing and segment windowing.

All transcript text here is synthetic filler invented for these tests. It is
not a quotation of any real creator and carries no meaning about trading.
"""

import pytest

from ictkb.normalize import (
    Cue,
    build_segments,
    clean_text,
    extract_video_id,
    normalize_for_match,
    parse_cue,
    parse_cues,
    timestamp_url,
)

VID = "TESTvid0001"


class TestExtractVideoId:
    @pytest.mark.parametrize(
        "value",
        [
            VID,
            f"https://www.youtube.com/watch?v={VID}",
            f"https://www.youtube.com/watch?t=30&v={VID}",
            f"https://youtu.be/{VID}",
            f"https://www.youtube.com/embed/{VID}",
            f"https://www.youtube.com/shorts/{VID}",
            f"https://www.youtube.com/live/{VID}",
        ],
    )
    def test_recognised_forms(self, value):
        assert extract_video_id(value) == VID

    @pytest.mark.parametrize(
        "value",
        [None, "", "tooshort", "waytoolongtobeanid", "bad!chars!!", "https://example.com/watch?v=abc"],
    )
    def test_rejects_junk(self, value):
        assert extract_video_id(value) is None

    def test_hyphens_and_underscores_are_valid_id_characters(self):
        # Real YouTube IDs use the URL-safe base64 alphabet, so a string like
        # "not-a-video" is a legitimate 11-char ID and must not be rejected.
        assert extract_video_id("not-a-video") == "not-a-video"
        assert extract_video_id("_ab-CD12_x-") == "_ab-CD12_x-"


class TestParseCue:
    def test_seconds_with_duration(self):
        cue = parse_cue({"text": "alpha bravo", "start": 12.5, "duration": 4.0})
        assert cue == Cue(start_s=12.5, end_s=16.5, text="alpha bravo")

    def test_explicit_millisecond_fields(self):
        cue = parse_cue({"text": "charlie", "startMs": "90000", "durationMs": "3000"})
        assert cue.start_s == 90.0
        assert cue.end_s == 93.0

    def test_string_numbers(self):
        cue = parse_cue({"snippet": "delta", "start": "7.25", "dur": "2"})
        assert cue.start_s == 7.25

    def test_clock_format(self):
        cue = parse_cue({"text": "echo", "start": "01:02:03", "duration": 1})
        assert cue.start_s == pytest.approx(3723.0)

    def test_unsuffixed_large_integer_treated_as_ms(self):
        # 7,200,000 as seconds would be 83 days; it is milliseconds (2 hours).
        cue = parse_cue({"text": "foxtrot", "start": 7_200_000, "duration": 2})
        assert cue.start_s == 7200.0

    def test_plausible_large_float_kept_as_seconds(self):
        cue = parse_cue({"text": "golf", "start": 7200.5, "duration": 2})
        assert cue.start_s == 7200.5

    def test_absurd_duration_clamped(self):
        cue = parse_cue({"text": "hotel", "start": 1, "duration": 999_999})
        assert cue.end_s - cue.start_s <= 120.0

    def test_missing_text_rejected(self):
        assert parse_cue({"start": 1, "duration": 2}) is None

    def test_missing_start_rejected(self):
        assert parse_cue({"text": "india"}) is None

    def test_negative_start_rejected(self):
        assert parse_cue({"text": "juliet", "start": -5}) is None


class TestParseCues:
    def test_sorts_and_drops_bad_rows(self):
        cues = parse_cues(
            [
                {"text": "second", "start": 10},
                "not a dict",
                {"text": "first", "start": 1},
                {"no_text": True, "start": 5},
            ]
        )
        assert [c.text for c in cues] == ["first", "second"]


class TestCleanText:
    def test_strips_sound_tags_and_entities(self):
        assert clean_text("[Music] risk &amp; reward   here") == "risk & reward here"

    def test_preserves_wording(self):
        # Cleaning must never rewrite words; quotes have to stay verbatim.
        original = "the price moved into the zone"
        assert clean_text(original) == original


class TestBuildSegments:
    def _cues(self, n, step=5.0):
        return [Cue(start_s=i * step, end_s=i * step + step, text=f"word{i}") for i in range(n)]

    def test_window_and_stride(self):
        segs = build_segments(
            video_id=VID,
            source_key="ICT",
            cues=self._cues(20),
            window_seconds=45,
            overlap_seconds=15,
        )
        assert segs
        assert segs[0].start_s == 0.0
        # stride = 45 - 15 = 30s
        assert segs[1].start_s == 30.0

    def test_segment_ids_are_stable_and_wellformed(self):
        kwargs = dict(
            video_id=VID, source_key="ICT", cues=self._cues(20),
            window_seconds=45, overlap_seconds=15,
        )
        first = build_segments(**kwargs)
        second = build_segments(**kwargs)
        assert [s.segment_id for s in first] == [s.segment_id for s in second]
        assert first[0].segment_id == f"{VID}:0"
        assert first[1].segment_id == f"{VID}:30000"

    def test_overlap_keeps_boundary_sentences_intact(self):
        cues = [
            Cue(start_s=28.0, end_s=30.0, text="a sentence that"),
            Cue(start_s=30.0, end_s=32.0, text="straddles the boundary"),
        ]
        segs = build_segments(
            video_id=VID, source_key="ICT", cues=cues,
            window_seconds=45, overlap_seconds=15,
        )
        # The whole phrase must be quotable from a single segment.
        assert any("a sentence that straddles the boundary" in s.text for s in segs)

    def test_dense_cluster_does_not_stall(self):
        cues = [Cue(start_s=1.0 + i * 0.01, end_s=2.0, text=f"t{i}") for i in range(200)]
        segs = build_segments(
            video_id=VID, source_key="ICT", cues=cues,
            window_seconds=45, overlap_seconds=15,
        )
        assert 1 <= len(segs) < 200

    def test_url_points_at_the_timestamp(self):
        segs = build_segments(
            video_id=VID, source_key="ICT", cues=self._cues(20),
            window_seconds=45, overlap_seconds=15,
        )
        assert segs[1].url == timestamp_url(VID, 30.0)
        assert segs[1].url.endswith("&t=30s")

    def test_empty_cues(self):
        assert build_segments(
            video_id=VID, source_key="ICT", cues=[], window_seconds=45, overlap_seconds=15
        ) == []

    def test_bad_video_id_rejected(self):
        from ictkb.normalize import NormalizeError

        with pytest.raises(NormalizeError):
            build_segments(
                video_id="short", source_key="ICT", cues=self._cues(3),
                window_seconds=45, overlap_seconds=15,
            )

    def test_overlap_not_smaller_than_window_rejected(self):
        from ictkb.normalize import NormalizeError

        with pytest.raises(NormalizeError):
            build_segments(
                video_id=VID, source_key="ICT", cues=self._cues(3),
                window_seconds=30, overlap_seconds=30,
            )


def test_normalize_for_match_is_whitespace_and_case_insensitive():
    assert normalize_for_match("  The   PRICE\nmoved ") == "the price moved"
