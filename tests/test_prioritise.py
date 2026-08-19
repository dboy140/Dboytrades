"""Tests for subset selection."""

from scripts.prioritise import recency_score, score_video, select

BUCKETS = ["a", "b", "c", "d"]


def v(vid, buckets, position=0, duration=1800):
    return {"video_id": vid, "buckets": list(buckets),
            "position": position, "duration_seconds": duration}


class TestRecency:
    def test_newest_scores_one(self):
        assert recency_score(0, 100) == 1.0

    def test_oldest_scores_zero(self):
        assert recency_score(99, 100) == 0.0

    def test_single_video(self):
        assert recency_score(0, 1) == 1.0


class TestScoring:
    def test_breadth_dominates_recency(self):
        """A 2-bucket old video must outrank a 1-bucket brand new one."""
        wide_old = score_video(v("a" * 11, ["a", "b"], position=99), 100)
        narrow_new = score_video(v("b" * 11, ["a"], position=0), 100)
        assert wide_old.score > narrow_new.score

    def test_recency_breaks_ties(self):
        new = score_video(v("a" * 11, ["a"], position=0), 100)
        old = score_video(v("b" * 11, ["a"], position=99), 100)
        assert new.score > old.score

    def test_very_short_videos_penalised(self):
        short = score_video(v("a" * 11, ["a"], duration=60), 10)
        normal = score_video(v("b" * 11, ["a"], duration=1800), 10)
        assert short.score < normal.score

    def test_reason_is_populated(self):
        assert "buckets" in score_video(v("a" * 11, ["a"]), 10).reason


class TestSelection:
    def test_respects_target(self):
        videos = [v(f"{i:011d}", ["a"], position=i) for i in range(100)]
        sel, _ = select(videos, target=20, per_bucket_floor=5)
        assert len(sel) == 20

    def test_every_bucket_represented(self):
        """The point of stratifying: a big bucket must not starve a small one."""
        videos = [v(f"{i:011d}", ["big"], position=i) for i in range(200)]
        videos += [v(f"s{i:010d}", ["small"], position=i) for i in range(15)]
        sel, coverage = select(videos, target=50, per_bucket_floor=12)
        assert coverage["small"] >= 12
        assert coverage["big"] >= 12

    def test_no_duplicates(self):
        videos = [v(f"{i:011d}", ["a", "b"], position=i) for i in range(50)]
        sel, _ = select(videos, target=30, per_bucket_floor=10)
        assert len({x["video_id"] for x in sel}) == len(sel)

    def test_prefers_multi_bucket_videos(self):
        videos = [v(f"m{i:010d}", ["a", "b", "c"], position=50 + i) for i in range(10)]
        videos += [v(f"s{i:010d}", ["a"], position=i) for i in range(50)]
        sel, _ = select(videos, target=10, per_bucket_floor=0)
        assert sum(1 for x in sel if len(x["buckets"]) == 3) >= 8

    def test_small_corpus_returns_everything(self):
        videos = [v(f"{i:011d}", ["a"], position=i) for i in range(5)]
        sel, _ = select(videos, target=150, per_bucket_floor=12)
        assert len(sel) == 5

    def test_empty_input(self):
        sel, coverage = select([], target=150)
        assert sel == [] and coverage == {}

    def test_coverage_counts_match_selection(self):
        videos = [v(f"{i:011d}", ["a", "b"], position=i) for i in range(40)]
        sel, coverage = select(videos, target=20, per_bucket_floor=5)
        assert coverage["a"] == sum(1 for x in sel if "a" in x["buckets"])

    def test_floors_never_drop_a_bucket_when_trimming(self):
        """Even when floors overshoot the target, no bucket may vanish."""
        videos = []
        for bi, b in enumerate(BUCKETS):
            videos += [v(f"{b}{i:010d}", [b], position=bi * 10 + i) for i in range(20)]
        sel, coverage = select(videos, target=10, per_bucket_floor=12,
                               bucket_keys=BUCKETS)
        assert all(coverage[b] >= 1 for b in BUCKETS), coverage
