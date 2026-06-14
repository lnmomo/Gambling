import tempfile
import unittest
from pathlib import Path

from football_agents.db import Database
from football_agents.international_history_agent import InternationalHistoryAgent
from football_agents.repository import Repository


CSV = """date,home_team,away_team,home_score,away_score,tournament,city,country,neutral
2025-01-01,United States,Germany,1,2,Friendly,Miami,United States,FALSE
2025-02-01,Brazil,Argentina,3,1,FIFA World Cup qualification,Rio,Brazil,FALSE
"""


class InternationalHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        database = Database(Path(self.temp.name) / "international.db")
        database.initialize()
        self.repository = Repository(database)

    def tearDown(self):
        self.temp.cleanup()

    def test_normalizes_friendly_and_competitive_matches(self):
        rows = InternationalHistoryAgent.normalize_csv(CSV)
        self.assertEqual(2, len(rows))
        self.assertEqual("FRIENDLY", rows[0]["match_type"])
        self.assertEqual("CUP", rows[1]["match_type"])
        self.assertTrue(rows[0]["id"].startswith("intl-"))

    def test_sync_is_idempotent_and_archives_csv(self):
        archive = Path(self.temp.name) / "archive" / "results.csv"
        agent = InternationalHistoryAgent(self.repository, archive)
        agent.fetch = lambda: CSV
        first, second = agent.sync(), agent.sync()
        self.assertEqual(2, first["imported"])
        self.assertEqual(2, second["updated"])
        self.assertTrue(archive.exists())


if __name__ == "__main__":
    unittest.main()
