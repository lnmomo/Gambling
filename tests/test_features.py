import tempfile
import unittest
from pathlib import Path

from football_agents.db import Database
from football_agents.features import HistoricalFeatureBuilder, canonical_team_name
from football_agents.repository import Repository


class HistoricalFeatureBuilderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        database = Database(Path(self.temp.name) / "features.db")
        database.initialize()
        self.repo = Repository(database)

    def tearDown(self):
        self.temp.cleanup()

    def test_builds_features_for_chinese_national_team_names(self):
        rows = []
        for index in range(12):
            rows.extend([
                {"league": "International", "home_team": "United States", "away_team": f"U{index}",
                 "home_goals": 2, "away_goals": 1, "played_at": f"2025-{index + 1:02d}-01",
                 "match_type": "FRIENDLY"},
                {"league": "International", "home_team": "Germany", "away_team": f"G{index}",
                 "home_goals": 2, "away_goals": 0, "played_at": f"2025-{index + 1:02d}-02",
                 "match_type": "FRIENDLY"},
            ])
        self.repo.upsert_historical_matches(rows, "test")
        match_id = self.repo.create_match({
            "official_match_id": "feature-1", "league": "International", "home_team": "\u7f8e\u56fd",
            "away_team": "\u5fb7\u56fd", "kickoff_time": "2026-01-01T12:00:00+00:00", "status": "scheduled",
        })
        result = HistoricalFeatureBuilder(self.repo).build(self.repo.get_match(match_id))
        self.assertTrue(result["built"])
        features = self.repo.latest_features(match_id)
        self.assertGreater(features["lambda_home"], 0)
        self.assertGreater(features["lambda_away"], 0)
        self.assertEqual(features["historical_home_team"], "United States")
        self.assertEqual(features["feature_engine"], "pandas-historical-v1")
        self.assertIn("home_weighted_points_per_match", features)
        self.assertIn("away_weighted_win_rate", features)

    def test_insufficient_history_is_not_fabricated(self):
        match_id = self.repo.create_match({
            "official_match_id": "feature-2", "league": "Test", "home_team": "A", "away_team": "B",
            "kickoff_time": "2026-01-01T12:00:00+00:00", "status": "scheduled",
        })
        result = HistoricalFeatureBuilder(self.repo).build(self.repo.get_match(match_id))
        self.assertFalse(result["built"])
        self.assertEqual(result["reason"], "insufficient_history")
        self.assertEqual(self.repo.latest_features(match_id), {})

    def test_alias_is_canonical(self):
        self.assertEqual(canonical_team_name("\u7f8e\u56fd"), "United States")


if __name__ == "__main__":
    unittest.main()
