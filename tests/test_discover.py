"""Tests for discovery parsing and filtering.

Actor output shapes are unverified (see docs/BLOCKED.md), so the parser is
tolerant by design. These tests pin down that tolerance: what it accepts, and
what it refuses to guess at.
"""

from scripts.discover import (
    _extract_video_id,
    _parse_duration,
    apply_bucket_filter,
    build_report,
    to_video_meta,
)
from scripts.models import VideoMeta

VID = "abcDEF12345"


class TestExtractVideoId:
    def test_direct_id_field(self):
        assert _extract_video_id({"id": VID}) == VID

    def test_alternate_id_fields(self):
        assert _extract_video_id({"videoId": VID}) == VID
        assert _extract_video_id({"video_id": VID}) == VID

    def test_falls_back_to_url(self):
        assert _extract_video_id({"url": f"https://www.youtube.com/watch?v={VID}"}) == VID

    def test_shorts_and_live_urls(self):
        assert _extract_video_id({"url": f"https://www.youtube.com/shorts/{VID}"}) == VID
        assert _extract_video_id({"url": f"https://www.youtube.com/live/{VID}"}) == VID
        assert _extract_video_id({"url": f"https://youtu.be/{VID}"}) == VID

    def test_non_id_in_id_field_recovered_from_url(self):
        # Some actors put a database key in `id` and the real id only in the URL.
        item = {"id": "12345", "url": f"https://youtu.be/{VID}"}
        assert _extract_video_id(item) == VID

    def test_returns_none_when_unresolvable(self):
        assert _extract_video_id({"title": "no id anywhere"}) is None


class TestParseDuration:
    def test_seconds_int(self):
        assert _parse_duration(3600) == 3600

    def test_numeric_string(self):
        assert _parse_duration("125") == 125

    def test_hhmmss(self):
        assert _parse_duration("01:02:03") == 3723

    def test_mmss(self):
        assert _parse_duration("07:30") == 450

    def test_garbage_returns_none(self):
        assert _parse_duration("a while") is None
        assert _parse_duration(None) is None


class TestToVideoMeta:
    def test_builds_from_minimal_row(self):
        m = to_video_meta({"id": VID, "title": "Silver Bullet"}, "ICT", "channel")
        assert m is not None
        assert m.video_id == VID
        assert m.channel_key == "ICT"
        assert m.discovered_via == "channel"

    def test_detects_shorts(self):
        m = to_video_meta({"url": f"https://www.youtube.com/shorts/{VID}"}, "NBBTRADER", "channel")
        assert m is not None and m.is_short

    def test_unresolvable_row_returns_none(self):
        assert to_video_meta({"title": "orphan"}, "ICT", "channel") is None

    def test_long_description_is_truncated(self):
        m = to_video_meta({"id": VID, "title": "t", "description": "x" * 9000}, "ICT", "channel")
        assert m is not None and len(m.description) <= 4000


class TestBucketFilter:
    def _v(self, vid, title):
        return VideoMeta(video_id=vid, title=title, url="u", channel_key="ICT")

    def test_splits_kept_and_excluded(self):
        videos = [
            self._v("aaaaaaaaaaa", "ICT Silver Bullet Strategy"),
            self._v("bbbbbbbbbbb", "Random Life Vlog"),
        ]
        kept, excluded = apply_bucket_filter(videos)
        assert [v.video_id for v in kept] == ["aaaaaaaaaaa"]
        assert [e.video_id for e in excluded] == ["bbbbbbbbbbb"]

    def test_kept_videos_carry_their_buckets(self):
        kept, _ = apply_bucket_filter([self._v("aaaaaaaaaaa", "Silver Bullet in the London Killzone")])
        assert set(kept[0].buckets) == {"silver_bullet", "london_session"}

    def test_excluded_records_a_reason(self):
        _, excluded = apply_bucket_filter([self._v("bbbbbbbbbbb", "Unrelated")])
        assert excluded[0].reason == "no_bucket_match"
        assert excluded[0].title == "Unrelated"


class TestReport:
    def test_counts_and_flags_thin_buckets(self):
        manifest = [
            VideoMeta(video_id="aaaaaaaaaaa", title="Silver Bullet", url="u",
                      channel_key="ICT", buckets=["silver_bullet"], duration_seconds=3600),
            VideoMeta(video_id="ccccccccccc", title="NBB video", url="u",
                      channel_key="NBBTRADER", duration_seconds=1800),
        ]
        report = build_report(manifest, [], ict_enumerated=50)

        assert report.ict_in_scope == 1
        assert report.nbb_total == 1
        assert report.ict_total_enumerated == 50
        assert report.total_runtime_hours == 1.5
        assert report.ict_per_bucket["silver_bullet"] == 1
        assert report.ict_per_bucket["money_maker_model"] == 0
        # Every bucket below three videos should be surfaced, not buried.
        assert any("thin buckets" in n for n in report.notes)

    def test_counts_shorts_and_guest_appearances(self):
        manifest = [
            VideoMeta(video_id="ddddddddddd", title="s", url="https://youtube.com/shorts/x",
                      channel_key="NBBTRADER", is_short=True),
            VideoMeta(video_id="eeeeeeeeeee", title="g", url="u", channel_key="NBBTRADER",
                      discovered_via="guest_search:NBBTRADER podcast"),
        ]
        report = build_report(manifest, [], ict_enumerated=0)
        assert report.nbb_shorts == 1
        assert report.nbb_guest_appearances == 1
