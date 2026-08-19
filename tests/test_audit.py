"""Tests for corpus auditing, using the real problems found in the
2026-08-19 fetch."""

from scripts.audit_corpus import audit_record, detect_caption_kind, english_ratio


def segs(texts, step=2.0):
    return [{"start_seconds": i * step, "text": t} for i, t in enumerate(texts)]


def rec(**kw):
    base = {"id": "abcDEF12345", "title": "t", "channel": "",
            "segments": segs(["the price is going into the zone"] * 100)}
    base.update(kw)
    return base


class TestEnglishRatio:
    def test_english_scores_high(self):
        assert english_ratio(segs(["this is the price and that is what you would do"] * 20)) > 0.3

    def test_portuguese_scores_low(self):
        # Verbatim from the real fetch.
        assert english_ratio(segs(["minha contta foi zero de 4K para 17k"] * 20)) < 0.10

    def test_empty(self):
        assert english_ratio([]) == 0.0


class TestCaptionKind:
    def test_auto_captions_detected(self):
        # Real opening line: lowercase, unpunctuated.
        assert detect_caption_kind(segs(["welcome back folks this is april 2017s"] * 50)) == "auto"

    def test_manual_captions_detected(self):
        assert detect_caption_kind(
            segs(["I'm going to say something controversial. Right off the bat."] * 50)
        ) == "manual"

    def test_empty_is_unknown(self):
        assert detect_caption_kind([]) == "unknown"


class TestAudit:
    def test_clean_record_kept(self):
        assert audit_record(rec()).verdict == "keep"

    def test_spam_clip_rejected(self):
        """Real case: 3-7 segment ads that just name-drop a course."""
        f = audit_record(rec(segments=segs(["NBB OMR ICT trading mentorship"] * 5)))
        assert "too_short" in f.flags
        assert f.verdict == "reject"

    def test_foreign_language_rejected(self):
        f = audit_record(rec(segments=segs(["minha contta foi zero de 4K para 17k"] * 100)))
        assert "not_english" in f.flags
        assert f.verdict == "reject"

    def test_acronym_collision_rejected(self):
        """Real case: 'Northern Border Banter Podcast' is NBB but not NBBTRADER
        -- 2780 segments of an entirely unrelated show."""
        f = audit_record(rec(channel="Northern Border Banter Podcast",
                             title="NBB Podcast - Episode 23"))
        assert "acronym_collision" in f.flags
        assert f.verdict == "reject"

    def test_commentary_flagged_for_review_not_rejected(self):
        """Someone else's opinion about him is not his teaching, but it is a
        judgement call rather than obvious junk."""
        f = audit_record(rec(title="NBB Trader & Ali khan ICT: Scam or Legit Guru?"))
        assert "third_party_commentary" in f.flags
        assert f.verdict == "review"

    def test_genuine_guest_appearance_kept(self):
        f = audit_record(rec(
            channel="Words of Rizdom",
            title="NBB Trader Part II: This ICT Strategy Will Change Everything",
            segments=segs(["no matter how good the setup is in the end you have to manage risk"] * 500),
        ))
        assert f.verdict == "keep"

    def test_flags_are_reported_not_silently_applied(self):
        f = audit_record(rec(segments=segs(["x"] * 3)))
        assert f.segments == 3 and f.flags
