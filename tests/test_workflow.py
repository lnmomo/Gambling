import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from football_agents.agents import DecisionWorkflow
from football_agents.db import Database
from football_agents.repository import Repository


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        database = Database(Path(self.temp.name) / "test.db")
        database.initialize()
        self.repo = Repository(database)
        self.workflow = DecisionWorkflow(self.repo)
        self.match_id = self.repo.create_match({
            "official_match_id": "T-1", "league": "Test", "home_team": "A", "away_team": "B",
            "kickoff_time": datetime.now(timezone.utc).isoformat(), "status": "scheduled",
        })

    def tearDown(self):
        self.temp.cleanup()

    def test_missing_market_data_is_no_bet(self):
        self.repo.add_odds(self.match_id, {"home": 2, "draw": 3.4, "away": 4}, "official")
        result = self.workflow.evaluate(self.match_id)
        self.assertEqual(result["signal"]["status"], "NO_BET")

    def test_complete_data_creates_audited_signal(self):
        now = datetime.now(timezone.utc).isoformat()
        self.repo.add_odds(self.match_id, {"home": 2.4, "draw": 3.4, "away": 3.1}, "official", now)
        self.repo.add_odds(self.match_id, {"home": 2.0, "draw": 3.5, "away": 4.0}, "market", now, True)
        self.repo.add_features(self.match_id, {"home_rating": 1600, "away_rating": 1450,
                                               "lambda_home": 1.8, "lambda_away": .8,
                                               "source_confidence": .95})
        result = self.workflow.evaluate(self.match_id)
        self.assertIn(result["signal"]["status"], {"BET", "WATCH", "NO_BET"})
        self.assertAlmostEqual(sum(result["ensemble"].values()), 1, places=8)
        self.assertIsNotNone(self.repo.latest_signal(self.match_id))


if __name__ == "__main__":
    unittest.main()

