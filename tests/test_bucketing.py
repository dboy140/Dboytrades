"""Tests for the eight-bucket ICT filter.

The filter decides what gets scraped and what gets thrown away, so its edge
cases are worth pinning down. All titles below are invented for the tests.
"""

import pytest

from scripts import config as cfg
from scripts.bucketing import bucket_keys, find_adjacent_concepts, is_in_scope, match_buckets


class TestBucketCoverage:
    def test_exactly_eight_buckets(self):
        assert len(cfg.ICT_BUCKETS) == 8

    def test_bucket_keys_unique(self):
        keys = [b.key for b in cfg.ICT_BUCKETS]
        assert len(keys) == len(set(keys))

    def test_every_bucket_has_keywords(self):
        for b in cfg.ICT_BUCKETS:
            assert b.keywords, f"{b.key} has no keywords"


class TestMatching:
    @pytest.mark.parametrize(
        "title,expected",
        [
            ("ICT Silver Bullet Strategy", "silver_bullet"),
            ("The Market Maker Buy Model Explained", "money_maker_model"),
            ("Understanding Fair Value Gaps", "fair_value_gaps"),
            ("Inversion Fair Value Gap Tutorial", "inversion_fair_value_gaps"),
            ("London Killzone Deep Dive", "london_session"),
            ("New York AM Session Breakdown", "new_york_session"),
            ("How To Set Your Daily Bias", "higher_timeframe"),
            ("Institutional Order Flow 101", "smart_money_concepts"),
        ],
    )
    def test_each_bucket_matches(self, title, expected):
        assert expected in bucket_keys(title)

    def test_matches_in_description_when_title_is_vague(self):
        keys = bucket_keys("Episode 42", "Today we cover the silver bullet setup in detail")
        assert "silver_bullet" in keys

    def test_case_insensitive(self):
        assert "fair_value_gaps" in bucket_keys("FAIR VALUE GAP masterclass")

    def test_flexible_whitespace(self):
        assert "fair_value_gaps" in bucket_keys("fair  value   gap")

    def test_multi_bucket_video(self):
        keys = bucket_keys("Silver Bullet in the New York Killzone using FVG")
        assert {"silver_bullet", "new_york_session", "fair_value_gaps"} <= set(keys)

    def test_out_of_scope_title_excluded(self):
        assert not is_in_scope("My Trading Journey And Some Life Advice")

    def test_empty_input_safe(self):
        assert bucket_keys("") == []
        assert bucket_keys("", "") == []


class TestWordBoundaries:
    """The substring trap: naive matching conflates FVG and IFVG."""

    def test_ifvg_does_not_leak_into_plain_fvg_bucket(self):
        keys = bucket_keys("IFVG explained")
        assert "inversion_fair_value_gaps" in keys
        assert "fair_value_gaps" not in keys

    def test_plain_fvg_acronym_matches_its_own_bucket(self):
        assert "fair_value_gaps" in bucket_keys("FVG explained")

    def test_acronym_not_matched_inside_a_word(self):
        # "SMC" must not fire on "SMCorporation"; "OB" style false positives.
        assert "smart_money_concepts" not in bucket_keys("SMCorporation quarterly results")

    def test_spelled_out_inversion_matches_both(self):
        # A title naming the full phrase legitimately belongs to both buckets.
        keys = bucket_keys("Inversion Fair Value Gap")
        assert "inversion_fair_value_gaps" in keys
        assert "fair_value_gaps" in keys


class TestPlurals:
    """Real titles pluralise; the operator keyword list is singular."""

    @pytest.mark.parametrize(
        "title,expected",
        [
            ("Understanding Fair Value Gaps", "fair_value_gaps"),
            ("Multiple FVGs On The Chart", "fair_value_gaps"),
            ("Order Blocks Explained", "smart_money_concepts"),
            ("London Killzones", "london_session"),
        ],
    )
    def test_plural_titles_match(self, title, expected):
        assert expected in bucket_keys(title)

    def test_plural_does_not_break_boundaries(self):
        # "gaps" must still not match inside a longer word.
        assert "fair_value_gaps" not in bucket_keys("fair value gapsomething")


class TestExtraKeywords:
    """Pipeline-added variants are kept separate from the operator's list."""

    def test_ny_am_session_title_now_matches(self):
        assert "new_york_session" in bucket_keys("New York AM Session Breakdown")

    def test_operator_keywords_are_unmodified(self):
        ny = cfg.bucket("new_york_session")
        assert ny.keywords == [
            "New York killzone", "New York open", "New York session", "NY AM session",
            "NY PM session", "NY lunch", "opening range gap",
        ]

    def test_extras_are_separately_inspectable(self):
        ny = cfg.bucket("new_york_session")
        assert ny.extra_keywords
        assert set(ny.keywords).isdisjoint(ny.extra_keywords)
        assert ny.all_keywords == [*ny.keywords, *ny.extra_keywords]


class TestMatchEvidence:
    def test_match_records_which_keyword_fired(self):
        matches = match_buckets("ICT Silver Bullet Strategy")
        sb = next(m for m in matches if m.bucket_key == "silver_bullet")
        assert sb.matched_keywords
        assert "title" in sb.matched_in

    def test_description_only_match_is_labelled(self):
        matches = match_buckets("Episode 9", "we look at the london judas swing today")
        ldn = next(m for m in matches if m.bucket_key == "london_session")
        assert ldn.matched_in == ["description"]


class TestAdjacentConcepts:
    def test_finds_adjacent_concepts(self):
        found = find_adjacent_concepts("we confirm with SMT divergence and check DXY correlation")
        assert "SMT divergence" in found
        assert "DXY correlation" in found

    def test_adjacent_concepts_do_not_create_buckets(self):
        # Scope rule: adjacent concepts are context inside an in-scope video,
        # never a reason to pull in a separate video.
        assert not is_in_scope("SMT divergence and OTE basics")
