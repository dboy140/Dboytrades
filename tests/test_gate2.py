"""Tests for the Phase 2 standalone script.

Only the offline logic is exercised: selection, actor-output parsing and
caption parsing. Network paths cannot be tested from this environment.
"""

import importlib.util
import json
import pathlib
import shutil
import sys

import pytest

NB = pathlib.Path(__file__).resolve().parents[1] / "notebooks"


@pytest.fixture(scope="module")
def gate2(tmp_path_factory):
    """Load gate2 with gate1 importable beside it, as in Colab."""
    d = tmp_path_factory.mktemp("nb")
    shutil.copy(NB / "gate1_standalone.py", d / "gate1.py")
    shutil.copy(NB / "gate2_standalone.py", d / "gate2.py")
    sys.path.insert(0, str(d))
    spec = importlib.util.spec_from_file_location("gate2", d / "gate2.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    yield mod
    sys.path.remove(str(d))


def v(vid, buckets, position=0, duration=1800):
    return {"video_id": vid, "buckets": list(buckets), "position": position,
            "duration_seconds": duration}


class TestSelection:
    def test_respects_target(self, gate2):
        vids = [v("%011d" % i, ["a"], position=i) for i in range(300)]
        sel, _ = gate2.select(vids, target=150, per_bucket_floor=12)
        assert len(sel) == 150

    def test_small_bucket_not_starved_by_large_one(self, gate2):
        """The real shape of this corpus: SMC 186 vs Inversion FVG 51."""
        vids = [v("b%010d" % i, ["smc"], position=i) for i in range(186)]
        vids += [v("i%010d" % i, ["ifvg"], position=i) for i in range(51)]
        sel, coverage = gate2.select(vids, target=150, per_bucket_floor=12)
        assert coverage["ifvg"] >= 12
        assert coverage["smc"] >= 12

    def test_multi_bucket_videos_preferred(self, gate2):
        vids = [v("m%010d" % i, ["a", "b", "c"], position=200 + i) for i in range(10)]
        vids += [v("s%010d" % i, ["a"], position=i) for i in range(200)]
        sel, _ = gate2.select(vids, target=10, per_bucket_floor=0)
        assert sum(1 for x in sel if len(x["buckets"]) == 3) >= 8

    def test_no_duplicates(self, gate2):
        vids = [v("%011d" % i, ["a", "b"], position=i) for i in range(80)]
        sel, _ = gate2.select(vids, target=40, per_bucket_floor=10)
        assert len({x["video_id"] for x in sel}) == len(sel)

    def test_empty(self, gate2):
        assert gate2.select([], target=150) == ([], {})

    def test_short_videos_penalised(self, gate2):
        assert gate2.score_video(v("a" * 11, ["a"], duration=60), 10) < \
               gate2.score_video(v("b" * 11, ["a"], duration=1800), 10)


class TestExtractSegments:
    def test_plain_seconds(self, gate2):
        out = gate2.extract_segments(
            {"transcript": [{"text": "hello", "start": 12.5}]})
        assert out == [{"start_seconds": 12.5, "text": "hello"}]

    def test_explicit_ms_field(self, gate2):
        out = gate2.extract_segments(
            {"captions": [{"text": "x", "startMs": "90000"}]})
        assert out[0]["start_seconds"] == 90.0

    def test_large_integer_treated_as_ms(self, gate2):
        """7,200,000 as seconds is 83 days; it is milliseconds."""
        out = gate2.extract_segments({"segments": [{"text": "x", "start": 7200000}]})
        assert out[0]["start_seconds"] == 7200.0

    def test_plausible_float_kept_as_seconds(self, gate2):
        out = gate2.extract_segments({"segments": [{"text": "x", "start": 7200.5}]})
        assert out[0]["start_seconds"] == 7200.5

    def test_nested_payload(self, gate2):
        out = gate2.extract_segments(
            {"data": {"transcript": [{"text": "deep", "start": 1}]}})
        assert out and out[0]["text"] == "deep"

    def test_empty_text_dropped(self, gate2):
        out = gate2.extract_segments(
            {"transcript": [{"text": "  ", "start": 1}, {"text": "ok", "start": 2}]})
        assert len(out) == 1

    def test_untimestamped_actor_output_is_visible(self, gate2):
        """An actor returning text with no timestamps must not look fine --
        every citation would read 00:00:00."""
        out = gate2.extract_segments({"transcript": [{"text": "a"}, {"text": "b"}]})
        assert all(s["start_seconds"] == 0.0 for s in out)

    def test_no_cue_array(self, gate2):
        assert gate2.extract_segments({"title": "nothing here"}) == []


class TestParseJson3:
    def test_milliseconds_converted(self, gate2, tmp_path):
        p = tmp_path / "x.json3"
        p.write_text(json.dumps({"events": [
            {"tStartMs": 930000, "segs": [{"utf8": "the teaching"}]}]}))
        out = gate2.parse_json3(str(p))
        assert out[0]["start_seconds"] == 930.0

    def test_padding_and_blank_events_dropped(self, gate2, tmp_path):
        p = tmp_path / "x.json3"
        p.write_text(json.dumps({"events": [
            {"tStartMs": 0, "aAppend": 1},
            {"tStartMs": 500, "segs": [{"utf8": "\n"}]},
            {"tStartMs": 1000, "segs": [{"utf8": "real"}]}]}))
        out = gate2.parse_json3(str(p))
        assert len(out) == 1 and out[0]["text"] == "real"

    def test_output_sorted(self, gate2, tmp_path):
        p = tmp_path / "x.json3"
        p.write_text(json.dumps({"events": [
            {"tStartMs": 9000, "segs": [{"utf8": "later"}]},
            {"tStartMs": 1000, "segs": [{"utf8": "earlier"}]}]}))
        assert [s["text"] for s in gate2.parse_json3(str(p))] == ["earlier", "later"]

    def test_malformed_returns_empty(self, gate2, tmp_path):
        p = tmp_path / "bad.json3"
        p.write_text("{not json")
        assert gate2.parse_json3(str(p)) == []


class TestActorList:
    def test_actors_configured(self, gate2):
        assert len(gate2.APIFY_ACTORS) >= 4
        assert all("~" in a for a in gate2.APIFY_ACTORS), "REST API needs tilde form"


class TestPayloadVideoId:
    """Batched runs return rows unordered, so results must be matched by id.
    Pairing by position would attach one video's transcript to another's
    citations -- silently, and unfixably after the fact."""

    def test_direct_id_field(self, gate2):
        assert gate2.payload_video_id({"videoId": "abcDEF12345"}) == "abcDEF12345"

    def test_alternate_id_fields(self, gate2):
        assert gate2.payload_video_id({"video_id": "abcDEF12345"}) == "abcDEF12345"
        assert gate2.payload_video_id({"id": "abcDEF12345"}) == "abcDEF12345"

    def test_recovered_from_url(self, gate2):
        got = gate2.payload_video_id(
            {"url": "https://www.youtube.com/watch?v=abcDEF12345"})
        assert got == "abcDEF12345"

    def test_short_url_form(self, gate2):
        assert gate2.payload_video_id({"link": "https://youtu.be/abcDEF12345"}) == "abcDEF12345"

    def test_non_id_in_id_field_falls_back_to_url(self, gate2):
        got = gate2.payload_video_id(
            {"id": "row-42", "videoUrl": "https://youtu.be/abcDEF12345"})
        assert got == "abcDEF12345"

    def test_nested(self, gate2):
        got = gate2.payload_video_id({"meta": {"videoId": "abcDEF12345"}})
        assert got == "abcDEF12345"

    def test_unresolvable_returns_none(self, gate2):
        assert gate2.payload_video_id({"title": "no id anywhere"}) is None

    def test_wrong_length_rejected(self, gate2):
        assert gate2.payload_video_id({"id": "tooshort"}) is None
