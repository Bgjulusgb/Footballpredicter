"""Unit tests for the sentiment engine, prediction math and import rules.

Run:  python3 -m unittest backend.tests   (or)   python3 -m backend.tests
Pure stdlib, no network — safe to run anywhere.
"""

import unittest

from . import model, sentiment, enrich
from .sources.base import STATUS_OK


class TestSentiment(unittest.TestCase):
    def test_positive(self):
        self.assertGreater(sentiment.score_text("Brunson was absolutely clutch, MVP!")["compound"], 0.3)

    def test_negative(self):
        self.assertLess(sentiment.score_text("The refs robbed us, this is rigged garbage")["compound"], -0.3)

    def test_negation_flips(self):
        pos = sentiment.score_text("this is great")["compound"]
        neg = sentiment.score_text("this is not great")["compound"]
        self.assertGreater(pos, neg)

    def test_toxicity(self):
        s = sentiment.score_text("rigged scam, refball, what a clown fraud")
        self.assertGreater(s["toxicity"], 0.2)

    def test_empty(self):
        self.assertEqual(sentiment.score_text("")["compound"], 0.0)


class TestOdds(unittest.TestCase):
    def test_american_to_decimal(self):
        self.assertAlmostEqual(model.american_to_decimal(100), 2.0)
        self.assertAlmostEqual(model.american_to_decimal(-200), 1.5)
        self.assertAlmostEqual(model.american_to_decimal(110), 2.10, places=2)

    def test_devig_sums_to_one(self):
        m = model.devig_two_way(110, -130)
        self.assertAlmostEqual(m["home"] + m["away"], 1.0, places=6)
        self.assertGreater(m["overround"], 1.0)          # vig present
        self.assertGreater(m["away"], m["home"])          # -130 favorite

    def test_spread_prob(self):
        p = model.prob_from_spread(2.5)
        self.assertTrue(0.5 < p < 0.65)
        self.assertAlmostEqual(model.prob_from_spread(0), 0.5)


class TestElo(unittest.TestCase):
    def test_home_advantage(self):
        # Equal ratings -> home favored by the home-court bump.
        self.assertGreater(model.elo_expected(1500, 1500), 0.5)

    def test_monotonic(self):
        self.assertGreater(model.elo_expected(1700, 1500),
                           model.elo_expected(1550, 1500))

    def test_log5(self):
        self.assertAlmostEqual(model.log5(0.6, 0.6), 0.5, places=6)
        self.assertGreater(model.log5(0.7, 0.5), 0.5)


class TestLive(unittest.TestCase):
    def test_run_detection(self):
        events = [{"team": "CLE", "points": 2}, {"team": "NYK", "points": 3},
                  {"team": "NYK", "points": 2}, {"team": "NYK", "points": 2}]
        run = model.detect_current_run(events)
        self.assertEqual(run["team"], "NYK")
        self.assertEqual(run["points"], 7)

    def test_momentum_sign(self):
        # All recent scoring by the away team -> negative (home) momentum.
        events = [{"team": "NYK", "points": 2} for _ in range(5)]
        self.assertLess(model.momentum(events), 0)

    def test_sentiment_spike(self):
        buckets = [0.2, 0.1, 0.15, -0.9]
        self.assertLess(model.sentiment_spike(buckets), -1.0)


class TestSeries(unittest.TestCase):
    def test_clinch_from_3_0(self):
        # Leader strongly favored each remaining game -> very high clinch prob.
        p = model.series_clinch([0.6, 0.65, 0.6, 0.65])
        self.assertGreater(p, 0.95)

    def test_clinch_bounds(self):
        self.assertLessEqual(model.series_clinch([0.5, 0.5, 0.5, 0.5]), 1.0)


class TestEnsemble(unittest.TestCase):
    def test_market_dominates(self):
        ens = model.ensemble(0.7, 0.5, 0.0)
        self.assertTrue(0.6 < ens["home"] < 0.7)   # weighted toward market

    def test_sentiment_bounded(self):
        # Even an extreme differential cannot move the result more than the cap.
        base = model.ensemble(0.5, 0.5, 0.0)["home"]
        nudged = model.ensemble(0.5, 0.5, model.sentiment_delta(
            {"home": 1.0, "away": -1.0}))["home"]
        self.assertLessEqual(nudged - base, model.SENT_MAX_DELTA + 1e-9)


class TestImportRule(unittest.TestCase):
    def test_ok_imported_without_refilter(self):
        records = [
            {"title": "Knicks roll past Cavaliers", "text": "great win",
             "url": "http://x/1", "published": "2026-05-25T00:00:00+00:00",
             "kind": "article", "engagement": 0},          # -> ok
            {"title": "", "text": "", "url": "", "kind": "article",
             "engagement": 0},                               # -> error (dropped)
        ]
        imported, stats = enrich.enrich_and_import(records)
        self.assertEqual(stats["ok"], 1)
        self.assertEqual(len(imported), 1)
        self.assertEqual(imported[0]["status"], STATUS_OK)
        # The ok record was imported directly, not via repair.
        self.assertNotIn("imported_via", imported[0])

    def test_partial_repaired(self):
        records = [{"title": "NBA playoff roundup", "text": "neutral notes",
                    "url": "http://x/2", "kind": "article", "engagement": 0}]
        imported, stats = enrich.enrich_and_import(records)
        self.assertEqual(stats["repaired"], 1)
        self.assertEqual(imported[0]["imported_via"], "repair")


if __name__ == "__main__":
    unittest.main()
