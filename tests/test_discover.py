"""Tests for Phase 1 filtering and Gate 1 reporting.

Video-level parsing tolerance lives in test_ytdlp_adapter.py; this module
covers what happens once videos exist as VideoMeta.
"""

from scripts import config as cfg
from scripts.discover import apply_bucket_filter, build_report, print_gate1
from scripts.models import ExcludedVideo, VideoMeta


def v(vid: str, title: str, channel_key: str = "ICT", **kw) -> VideoMeta:
    return VideoMeta(video_id=vid, title=title, url="u", channel_key=channel_key, **kw)


class TestBucketFilter:
    def test_splits_kept_and_excluded(self):
        kept, excluded = apply_bucket_filter([
            v("aaaaaaaaaaa", "ICT Silver Bullet Strategy"),
            v("bbbbbbbbbbb", "Random Life Vlog"),
        ])
        assert [x.video_id for x in kept] == ["aaaaaaaaaaa"]
        assert [x.video_id for x in excluded] == ["bbbbbbbbbbb"]

    def test_kept_videos_carry_their_buckets(self):
        kept, _ = apply_bucket_filter([v("aaaaaaaaaaa", "Silver Bullet in the London Killzone")])
        assert set(kept[0].buckets) == {"silver_bullet", "london_session"}

    def test_multi_bucket_membership_preserved(self):
        kept, _ = apply_bucket_filter([
            v("aaaaaaaaaaa", "Silver Bullet in the New York Killzone using FVG")
        ])
        assert {"silver_bullet", "new_york_session", "fair_value_gaps"} <= set(kept[0].buckets)

    def test_excluded_records_title_and_reason(self):
        _, excluded = apply_bucket_filter([v("bbbbbbbbbbb", "Unrelated Chat")])
        assert excluded[0].reason == "no_bucket_match"
        assert excluded[0].title == "Unrelated Chat"

    def test_description_match_counts(self):
        kept, _ = apply_bucket_filter([
            v("aaaaaaaaaaa", "Episode 12", description="today we cover the judas swing")
        ])
        assert "london_session" in kept[0].buckets

    def test_empty_input(self):
        kept, excluded = apply_bucket_filter([])
        assert kept == [] and excluded == []


class TestReport:
    def test_counts_per_bucket_and_runtime(self):
        manifest = [
            v("aaaaaaaaaaa", "Silver Bullet", buckets=["silver_bullet"], duration_seconds=3600),
            v("ccccccccccc", "NBB video", channel_key="NBBTRADER", duration_seconds=1800),
        ]
        r = build_report(manifest, [], ict_enumerated=50)

        assert r.ict_total_enumerated == 50
        assert r.ict_in_scope == 1
        assert r.nbb_total == 1
        assert r.total_runtime_hours == 1.5
        assert r.ict_per_bucket["silver_bullet"] == 1
        assert r.ict_per_bucket["money_maker_model"] == 0

    def test_cost_is_zero_on_ytdlp(self):
        assert build_report([], [], 0).estimated_cost_usd == 0.0

    def test_thin_buckets_surfaced(self):
        r = build_report([v("aaaaaaaaaaa", "x", buckets=["silver_bullet"])], [], 1)
        assert any("thin buckets" in n for n in r.notes)

    def test_every_bucket_present_in_report(self):
        """A bucket with zero hits must still appear, so gaps are visible."""
        r = build_report([], [], 0)
        assert set(r.ict_per_bucket) == {b.key for b in cfg.ICT_BUCKETS}

    def test_counts_shorts_and_guest_appearances(self):
        manifest = [
            v("ddddddddddd", "s", channel_key="NBBTRADER", is_short=True),
            v("eeeeeeeeeee", "g", channel_key="NBBTRADER",
              discovered_via="guest_search:NBBTRADER podcast"),
        ]
        r = build_report(manifest, [], 0)
        assert r.nbb_shorts == 1
        assert r.nbb_guest_appearances == 1

    def test_excluded_count_reported(self):
        excluded = [ExcludedVideo(video_id="fffffffffff", title="cut")]
        assert build_report([], excluded, 10).ict_excluded == 1


class TestGate1Output:
    def test_prints_all_eight_buckets_and_probe(self, capsys):
        r = build_report([v("aaaaaaaaaaa", "Silver Bullet", buckets=["silver_bullet"])], [], 1)
        probe = {
            "UCo6TS8uarO5r562d4lESg9w": {
                "channel_id": "UCo6TS8uarO5r562d4lESg9w",
                "video_count_sampled": 5,
                "channel_names": ["NBBTRADER"],
                "sample_titles": ["A video title"],
            },
            "UCmtJ3lDd2fjt-IMf6lfzlcA": {
                "channel_id": "UCmtJ3lDd2fjt-IMf6lfzlcA",
                "error": "channel not found",
            },
        }
        print_gate1(r, probe)
        out = capsys.readouterr().out

        for b in cfg.ICT_BUCKETS:
            assert b.display_name in out
        # Both candidates must be shown so the operator can adjudicate.
        assert "UCo6TS8uarO5r562d4lESg9w" in out
        assert "UCmtJ3lDd2fjt-IMf6lfzlcA" in out
        assert "STOP" in out
