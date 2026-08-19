"""The standalone Colab script duplicates logic by necessity — it has to run
with no repo present. These tests make the duplication safe by asserting it
stays identical to the real pipeline."""

import importlib.util
import pathlib

import pytest

from scripts import config as cfg
from scripts.bucketing import bucket_keys

_PATH = pathlib.Path(__file__).resolve().parents[1] / "notebooks" / "gate1_standalone.py"


@pytest.fixture(scope="module")
def standalone():
    spec = importlib.util.spec_from_file_location("gate1_standalone", _PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestNoDrift:
    def test_same_number_of_buckets(self, standalone):
        assert len(standalone.BUCKETS) == len(cfg.ICT_BUCKETS)

    def test_bucket_display_names_match(self, standalone):
        assert set(standalone.BUCKETS) == {b.display_name for b in cfg.ICT_BUCKETS}

    def test_keyword_lists_match_exactly(self, standalone):
        """Including the pipeline-added extra_keywords."""
        for b in cfg.ICT_BUCKETS:
            assert standalone.BUCKETS[b.display_name] == b.all_keywords, (
                f"{b.display_name} drifted from scripts/config.py"
            )

    def test_channel_ids_match(self, standalone):
        assert standalone.ICT_CHANNEL == cfg.channel("ICT").channel_id
        assert standalone.NBB_CANDIDATES == cfg.NBB_CANDIDATE_IDS

    def test_enumeration_caps_match(self, standalone):
        assert standalone.ICT_MAX == cfg.ICT_ENUMERATION_MAX
        assert standalone.NBB_MAX == cfg.NBB_ENUMERATION_MAX


class TestSameMatchingBehaviour:
    CASES = [
        "ICT Silver Bullet Strategy",
        "Understanding Fair Value Gaps",
        "IFVG Explained",
        "FVG Explained",
        "New York AM Session Breakdown",
        "London Killzones",
        "Market Maker Buy Model Deep Dive",
        "Institutional Order Flow 101",
        "How To Set Your Daily Bias",
        "My Thoughts On Life And Discipline",
        "SMCorporation quarterly results",
        "Order Blocks Explained",
    ]

    @pytest.mark.parametrize("title", CASES)
    def test_agrees_with_pipeline(self, standalone, title):
        display_to_key = {b.display_name: b.key for b in cfg.ICT_BUCKETS}
        got = {display_to_key[n] for n in standalone.match_buckets(title)}
        assert got == set(bucket_keys(title)), f"disagreement on {title!r}"

    def test_ifvg_does_not_leak_into_fvg(self, standalone):
        hits = standalone.match_buckets("IFVG explained")
        assert "Inversion Fair Value Gaps" in hits
        assert "Fair Value Gaps" not in hits

    def test_plurals_match(self, standalone):
        assert "Fair Value Gaps" in standalone.match_buckets("Understanding Fair Value Gaps")

    def test_out_of_scope_excluded(self, standalone):
        assert standalone.match_buckets("Random Life Vlog") == []


class TestBlockDetection:
    def test_bot_challenge_recognised(self, standalone):
        assert standalone.is_blocked("ERROR: Sign in to confirm you're not a bot")

    def test_proxy_denial_recognised(self, standalone):
        assert standalone.is_blocked("Tunnel connection failed: 403 Forbidden")

    def test_private_video_is_not_a_block(self, standalone):
        assert not standalone.is_blocked("ERROR: Video unavailable. This video is private.")


class TestToVideo:
    def test_valid_entry(self, standalone):
        v = standalone.to_video({"id": "abcDEF12345", "title": "t", "duration": 60})
        assert v["video_id"] == "abcDEF12345"
        assert v["duration_seconds"] == 60

    def test_bad_id_rejected(self, standalone):
        assert standalone.to_video({"id": "short"}) is None

    def test_shorts_tab_flagged(self, standalone):
        v = standalone.to_video({"id": "abcDEF12345", "title": "t"}, tab="shorts")
        assert v["is_short"]
