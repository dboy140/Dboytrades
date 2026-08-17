"""Tests for the yt-dlp backend.

Uses real json3 and --flat-playlist structures, so the parsers are pinned
against the actual formats rather than an idealised guess. No network.
"""

import json

import pytest

from scripts.models import VideoMeta
from scripts.ytdlp_adapter import (
    SCOPE_TABS,
    YtdlpError,
    _is_block,
    _language_from_filename,
    _norm_upload_date,
    channel_tab_url,
    flat_entry_to_meta,
    parse_json3,
)

VID = "abcDEF12345"


class TestChannelUrls:
    def test_tab_url(self):
        assert channel_tab_url("UC123", "videos") == "https://www.youtube.com/channel/UC123/videos"

    def test_complete_scope_includes_shorts_and_streams(self):
        assert SCOPE_TABS["complete"] == ("videos", "shorts", "streams")

    def test_filtered_scope_excludes_shorts(self):
        # ICT teaching content is long-form; Shorts would be noise.
        assert "shorts" not in SCOPE_TABS["filtered"]


class TestUploadDate:
    def test_yyyymmdd_normalised_to_iso(self):
        assert _norm_upload_date("20230614") == "2023-06-14"

    def test_already_iso_passes_through(self):
        assert _norm_upload_date("2023-06-14") == "2023-06-14"

    def test_empty_is_none(self):
        assert _norm_upload_date(None) is None
        assert _norm_upload_date("") is None


class TestFlatEntry:
    def _entry(self, **kw):
        base = {
            "_type": "url",
            "id": VID,
            "title": "ICT Silver Bullet",
            "url": f"https://www.youtube.com/watch?v={VID}",
            "duration": 3600,
            "view_count": 12345,
            "channel": "Inner Circle Trader",
            "upload_date": "20230614",
        }
        base.update(kw)
        return base

    def test_parses_flat_entry(self):
        m = flat_entry_to_meta(self._entry(), "ICT", "ytdlp:videos", "videos")
        assert m is not None
        assert m.video_id == VID
        assert m.duration_seconds == 3600
        assert m.published == "2023-06-14"
        assert m.channel_name == "Inner Circle Trader"

    def test_description_is_empty_not_invented(self):
        # Flat enumeration genuinely has no description; it must stay empty
        # rather than be back-filled with the title or a placeholder.
        m = flat_entry_to_meta(self._entry(), "ICT", "ytdlp:videos", "videos")
        assert m.description == ""

    def test_shorts_tab_marks_is_short(self):
        m = flat_entry_to_meta(self._entry(), "NBBTRADER", "ytdlp:shorts", "shorts")
        assert m.is_short

    def test_streams_tab_marks_is_live(self):
        m = flat_entry_to_meta(self._entry(), "NBBTRADER", "ytdlp:streams", "streams")
        assert m.is_live

    def test_missing_duration_tolerated(self):
        m = flat_entry_to_meta(self._entry(duration=None), "ICT", "ytdlp:videos", "videos")
        assert m is not None and m.duration_seconds is None

    def test_entry_without_id_rejected(self):
        assert flat_entry_to_meta({"title": "orphan"}, "ICT", "ytdlp:videos") is None

    def test_bad_id_rejected(self):
        assert flat_entry_to_meta({"id": "short"}, "ICT", "ytdlp:videos") is None


class TestParseJson3:
    def _write(self, tmp_path, payload):
        p = tmp_path / f"{VID}.en.json3"
        p.write_text(json.dumps(payload), encoding="utf-8")
        return p

    def test_parses_events(self, tmp_path):
        path = self._write(tmp_path, {
            "events": [
                {"tStartMs": 0, "dDurationMs": 2000, "segs": [{"utf8": "hello"}, {"utf8": " world"}]},
                {"tStartMs": 5000, "dDurationMs": 2000, "segs": [{"utf8": "second line"}]},
            ]
        })
        segs = parse_json3(path)
        assert len(segs) == 2
        assert segs[0].start_seconds == 0.0
        assert segs[0].text == "hello world"
        assert segs[1].start_seconds == 5.0

    def test_milliseconds_converted_correctly(self, tmp_path):
        # json3 is unambiguously ms — a 1000x error here would misplace every
        # citation in the corpus while still looking well-formed.
        path = self._write(tmp_path, {
            "events": [{"tStartMs": 930000, "segs": [{"utf8": "x"}]}]
        })
        assert parse_json3(path)[0].start_seconds == 930.0

    def test_padding_events_without_segs_dropped(self, tmp_path):
        path = self._write(tmp_path, {
            "events": [
                {"tStartMs": 0, "aAppend": 1},
                {"tStartMs": 1000, "segs": [{"utf8": "real"}]},
            ]
        })
        segs = parse_json3(path)
        assert len(segs) == 1 and segs[0].text == "real"

    def test_whitespace_only_events_dropped(self, tmp_path):
        path = self._write(tmp_path, {
            "events": [
                {"tStartMs": 0, "segs": [{"utf8": "\n"}]},
                {"tStartMs": 1000, "segs": [{"utf8": "real"}]},
            ]
        })
        assert len(parse_json3(path)) == 1

    def test_events_without_timestamp_dropped(self, tmp_path):
        path = self._write(tmp_path, {"events": [{"segs": [{"utf8": "no time"}]}]})
        assert parse_json3(path) == []

    def test_newlines_flattened(self, tmp_path):
        path = self._write(tmp_path, {
            "events": [{"tStartMs": 0, "segs": [{"utf8": "line one\nline two"}]}]
        })
        assert parse_json3(path)[0].text == "line one line two"

    def test_output_is_time_sorted(self, tmp_path):
        path = self._write(tmp_path, {
            "events": [
                {"tStartMs": 9000, "segs": [{"utf8": "later"}]},
                {"tStartMs": 1000, "segs": [{"utf8": "earlier"}]},
            ]
        })
        segs = parse_json3(path)
        assert [s.text for s in segs] == ["earlier", "later"]

    def test_empty_events_yields_nothing(self, tmp_path):
        assert parse_json3(self._write(tmp_path, {"events": []})) == []

    def test_malformed_file_raises(self, tmp_path):
        p = tmp_path / "bad.json3"
        p.write_text("{not json", encoding="utf-8")
        with pytest.raises(YtdlpError):
            parse_json3(p)


class TestLanguageDetection:
    @pytest.mark.parametrize(
        "filename,expected",
        [
            (f"{VID}.en.json3", "en"),
            (f"{VID}.en-GB.json3", "en-GB"),
            (f"{VID}.en-orig.json3", "en-orig"),
        ],
    )
    def test_language_from_filename(self, tmp_path, filename, expected):
        p = tmp_path / filename
        p.touch()
        assert _language_from_filename(p, VID) == expected


class TestBlockDetection:
    def test_recognises_proxy_tunnel_failure(self):
        assert _is_block("ERROR: Unable to connect to proxy, Tunnel connection failed: 403 Forbidden")

    def test_recognises_generic_tunnel_message(self):
        assert _is_block("OSError('Tunnel connection failed: 403 Forbidden')")

    def test_ordinary_error_is_not_a_block(self):
        # A private or removed video must not be misreported as a network block.
        assert not _is_block("ERROR: Video unavailable. This video is private.")

    def test_missing_captions_is_not_a_block(self):
        assert not _is_block("WARNING: There are no subtitles for the requested languages")


class TestTranscriptIntegration:
    def test_video_meta_to_transcript_shape(self, tmp_path):
        """The Transcript a caller builds must satisfy the model contract."""
        from scripts.models import Transcript

        meta = VideoMeta(
            video_id=VID, title="t", url="u", channel_key="ICT",
            buckets=["silver_bullet"], duration_seconds=600,
        )
        path = tmp_path / f"{VID}.en.json3"
        path.write_text(json.dumps({
            "events": [{"tStartMs": 1000, "segs": [{"utf8": "alpha bravo charlie"}]}]
        }), encoding="utf-8")

        t = Transcript(
            id=meta.video_id, title=meta.title, channel=meta.channel_key,
            duration=meta.duration_seconds, url=meta.url, buckets=meta.buckets,
            segments=parse_json3(path), caption_kind="manual",
            language="en", actor_used="yt-dlp",
        )
        assert t.word_count == 3
        assert t.segment_at(1.0) is not None
        assert t.segment_at(9999, tolerance=60) is None
