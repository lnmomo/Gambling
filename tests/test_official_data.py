import tempfile
import unittest
from pathlib import Path

from football_agents.db import Database
from football_agents.official_data import OfficialDataService
from football_agents.repository import Repository


class FakeClient:
    def fetch(self, url):
        return {"html": "<div>official</div>", "matches": [{
            "source_match_id": "2040164", "match_no": "周五003", "league": "世界杯",
            "match_date": "2026-06-13", "match_time": "03:00", "home_team": "加拿大",
            "away_team": "波黑", "sale_status": "已开售",
            "odds": {"home": 1.61, "draw": 3.36, "away": 4.75},
        }, {
            "source_match_id": "2040166", "match_no": "周六005", "league": "世界杯",
            "match_date": "2026-06-14", "match_time": "03:00", "home_team": "卡塔尔",
            "away_team": "瑞士", "sale_status": "已开售", "odds": {},
        }]}


class OfficialDataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        database = Database(Path(self.temp.name) / "test.db")
        database.initialize()
        self.repository = Repository(database)
        self.service = OfficialDataService(self.repository, FakeClient())

    def tearDown(self):
        self.temp.cleanup()

    def test_sync_upserts_matches_and_only_complete_odds(self):
        report = self.service.sync(force=True)
        self.assertEqual(report["created"], 2)
        self.assertEqual(report["odds_snapshots"], 1)
        self.assertEqual(report["incomplete_odds"], 1)
        matches = self.repository.list_matches()
        self.assertEqual(matches[0]["official_match_id"], "sporttery-2040164")
        self.assertEqual(len(self.repository.latest_odds(matches[0]["id"])["odds"]), 3)

    def test_duplicate_snapshot_is_not_inserted_twice(self):
        self.service.sync(force=True)
        report = self.service.sync(force=True)
        self.assertEqual(report["odds_snapshots"], 0)


if __name__ == "__main__":
    unittest.main()
