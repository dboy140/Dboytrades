"""Tests for guest-appearance tiering, using the real search results from the
2026-08-19 Gate 1 run."""

from scripts.guests import classify_guest, tier_guests

# Verbatim from the live run.
REAL = [
    ("Words of Rizdom", "NBB Trader Part II: This ICT Strategy Will Change Everything"),
    ("Chart Fanatics", "TAKE This EASY ICT Trading Strategy For Prop Firms (INSANE E"),
    ("PropFirmTrader", "NBB Trader: After $2.5M+ In Profit, THIS Is What Actually Wo"),
    ("david", "the only NQ trading course you'll ever need (beginner to adv"),
    ("Words of Rizdom", "ICT Roundtable: NBB Trader, JadeCapFX, Ali khan ICT, Kimmel"),
    ("Words of Rizdom", "Umar Ashraf, JadeCap & Trader Kane - The Path to Becoming an"),
    ("Words of Rizdom", "Best ICT Trader: He Exposes Why 90% of SMC Traders FAIL!"),
    ("ImanTrading", "Exposing the #1 Day Trading Show & ALL Fake Gurus"),
    ("Justin Werlein", "ICT MMXM - Explained in Depth!"),
    ("JadeCap", "My Trading Strategy is Boring, But it Broke The World Record"),
    ("Titans Of Tomorrow", "The Incredible Journey Of UK's #1 Forex Trader - Nasser Al Y"),
    ("Andre Mcclendon", "NBB Trader & Ali khan ICT: Scam or Legit Guru? Let's Find Ou"),
    ("Chart Fanatics", "The SIMPLE $10 Million ICT Blueprint They Don't Want You To"),
    ("Tom Crown", "The ONLY Optimal Trade Entry Guide You'll EVER Need!"),
    ("Chart Fanatics", "This SIMPLE ICT Futures Trading Strategy Made Her Over $100,"),
]
CANDIDATES = [{"channel_name": c, "title": t} for c, t in REAL]


class TestClassify:
    def test_title_naming_nbb_is_confident(self):
        assert classify_guest("NBB Trader Part II: This ICT Strategy") == "confident"

    def test_nbbtrader_one_word_matches(self):
        assert classify_guest("NBBTRADER explains his model") == "confident"

    def test_channel_named_nbb_is_confident(self):
        assert classify_guest("Some title", "NBBTRADER") == "confident"

    def test_unrelated_title_is_not_confident(self):
        assert classify_guest("The ONLY Optimal Trade Entry Guide", "Tom Crown") == "review"

    def test_nbb_not_matched_inside_a_word(self):
        assert classify_guest("SNBBQ index review", "x") == "review"


class TestTiering:
    def test_real_run_splits_sensibly(self):
        tiers = tier_guests(CANDIDATES)
        confident_titles = [c["title"][:28] for c in tiers["confident"]]

        # The four that explicitly name him.
        assert len(tiers["confident"]) == 4
        assert any("NBB Trader Part II" in t for t in confident_titles)
        assert any("NBB Trader: After $2.5M" in t for t in confident_titles)
        assert any("ICT Roundtable: NBB Trader" in t for t in confident_titles)
        assert any("NBB Trader & Ali khan" in t for t in confident_titles)

    def test_same_channel_unnamed_goes_to_review_not_reject(self):
        tiers = tier_guests(CANDIDATES)
        review_titles = [c["title"] for c in tiers["review"]]
        # Words of Rizdom hosted confident hits, so its other videos are worth
        # a look rather than being binned unseen.
        assert any("Best ICT Trader" in t for t in review_titles)
        assert any("Umar Ashraf" in t for t in review_titles)

    def test_unrelated_channels_rejected(self):
        tiers = tier_guests(CANDIDATES)
        rejected = [c["title"] for c in tiers["reject"]]
        assert any("Optimal Trade Entry Guide" in t for t in rejected)
        assert any("Nasser Al Y" in t for t in rejected)
        assert any("NQ trading course" in t for t in rejected)

    def test_every_candidate_lands_in_exactly_one_tier(self):
        tiers = tier_guests(CANDIDATES)
        total = sum(len(v) for v in tiers.values())
        assert total == len(CANDIDATES)

    def test_empty_input(self):
        tiers = tier_guests([])
        assert tiers == {"confident": [], "review": [], "reject": []}
