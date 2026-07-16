import tempfile
import unittest
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from football_agents.db import Database
from football_agents.official_data import OfficialDataService
from football_agents.official_data.service import STATUS_MAP
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
            "away_team": "瑞士", "sale_status": "已完成", "home_score": 2, "away_score": 1, "odds": {},
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
        self.assertEqual(report["hourly_observations"], 1)
        self.assertEqual(report["availability_observations"], 2)
        self.assertEqual(report["incomplete_odds"], 1)
        self.assertEqual(report["results_settled"], 1)
        matches = self.repository.list_matches()
        self.assertEqual(matches[0]["official_match_id"], "sporttery-2040164")
        self.assertEqual(len(self.repository.latest_odds(matches[0]["id"])["odds"]), 3)
        with self.repository.db.connect() as connection:
            availability = connection.execute("""SELECT raw_sale_status,has_valid_three_way_sp,missing_reason
                FROM official_market_availability_observations ORDER BY id""").fetchall()
        self.assertEqual([tuple(row) for row in availability], [
            ("已开售", 1, None), ("已完成", 0, "post_match"),
        ])
        with self.assertRaises(sqlite3.IntegrityError), self.repository.db.connect() as connection:
            connection.execute("""UPDATE official_market_availability_observations
                SET raw_sale_status='待开售' WHERE id=(
                    SELECT MIN(id) FROM official_market_availability_observations)""")

    def test_duplicate_snapshot_is_not_inserted_twice(self):
        self.service.sync(force=True)
        report = self.service.sync(force=True)
        self.assertEqual(report["odds_snapshots"], 0)
        self.assertEqual(report["hourly_observations"], 1)
        self.assertEqual(len(self.repository.list_official_odds_observations()), 2)

    def test_observations_are_immutable_and_join_to_results(self):
        self.service.sync(force=True)
        match = self.repository.list_matches()[0]
        self.repository.archive_official_odds_observation(
            match["id"], match["official_match_id"], {"home": 1.7, "draw": 3.3, "away": 4.5},
            "2026-06-12T12:00:00+00:00", match["kickoff_time"], "scheduled",
            "中国竞彩网", "https://example.test", "earlier",
        )
        observation = self.repository.list_official_odds_observations(match["official_match_id"])[0]
        with self.assertRaises(sqlite3.IntegrityError), self.repository.db.connect() as connection:
            connection.execute("UPDATE official_odds_observations SET home_sp=2 WHERE id=?", (observation["id"],))
        self.repository.upsert_result(match["id"], 2, 1, "2026-06-13T06:00:00+00:00")
        samples = self.repository.list_official_odds_training_samples()
        self.assertEqual(len(samples), 1)
        self.assertEqual(samples[0]["outcome"], "home")
        self.assertEqual(samples[0]["closing_home_sp"], 1.7)

    def test_latest_odds_freshness_uses_latest_official_verification(self):
        self.service.sync(force=True)
        match = self.repository.list_matches()[0]
        verified_at = "2030-01-01T00:00:00+00:00"
        with self.repository.db.connect() as connection:
            connection.execute("UPDATE matches SET last_seen_at=? WHERE id=?", (verified_at, match["id"]))
        latest = self.repository.latest_odds(match["id"])
        self.assertEqual(latest["fetched_at"], verified_at)
        with self.repository.db.connect() as connection:
            rows = connection.execute("SELECT COUNT(*) FROM odds_snapshots WHERE match_id=?", (match["id"],)).fetchone()[0]
        self.assertEqual(rows, 3)

    def test_official_pool_can_be_filtered_from_local_match_date(self):
        self.service.sync(force=True)
        june_13 = self.repository.list_official_matches("2026-06-13")
        june_14 = self.repository.list_official_matches("2026-06-14")
        self.assertEqual([row["official_match_id"] for row in june_13],
                         ["sporttery-2040164", "sporttery-2040166"])
        self.assertEqual([row["official_match_id"] for row in june_14], ["sporttery-2040166"])

    def test_current_official_sale_statuses_are_mapped(self):
        self.assertEqual(STATUS_MAP["直播结束"], "finished")
        self.assertEqual(STATUS_MAP["暂停销售"], "closed")


    def test_active_official_pool_excludes_stale_scheduled_rows(self):
        now = datetime(2026, 7, 16, 12, tzinfo=timezone.utc)
        for suffix, kickoff, status in (
            ("stale", now - timedelta(days=2), "scheduled"),
            ("future", now + timedelta(hours=2), "NOT_STARTED"),
            ("live", now - timedelta(hours=1), "LIVE"),
            ("old-live", now - timedelta(hours=5), "LIVE"),
        ):
            self.repository.upsert_official_match({
                "official_match_id": f"sporttery-{suffix}",
                "match_no": suffix,
                "league": "test",
                "home_team": f"home-{suffix}",
                "away_team": f"away-{suffix}",
                "kickoff_time": kickoff.isoformat(),
                "status": status,
                "source_url": "https://example.test",
                "data_quality_score": 1.0,
                "raw_hash": suffix,
            })

        active = self.repository.list_active_official_matches(10, now)

        self.assertEqual(
            {row["official_match_id"] for row in active},
            {"sporttery-live", "sporttery-future"},
        )


if __name__ == "__main__":
    unittest.main()
