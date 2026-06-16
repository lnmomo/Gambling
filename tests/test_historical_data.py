import tempfile
import unittest
from pathlib import Path

from football_agents.db import Database
from football_agents.historical_data import HistoricalDataService
from football_agents.historical_agent import HistoricalCollectionAgent, HistoricalSource
from football_agents.repository import Repository


CSV = """date,league,home_team,away_team,home_score,away_score
2025-01-01,Test League,A,B,2,1
2025-01-08,Test League,B,A,0,0
"""


class HistoricalDataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        database = Database(Path(self.temp.name) / "history.db")
        database.initialize()
        self.repository = Repository(database)
        self.service = HistoricalDataService(self.repository)

    def tearDown(self):
        self.temp.cleanup()

    def test_import_is_idempotent_and_query_respects_cutoff(self):
        first = self.service.import_csv_text(CSV, "test")
        second = self.service.import_csv_text(CSV, "test")
        self.assertEqual(first["imported"], 2)
        self.assertEqual(first["pandas_rows"], 2)
        self.assertEqual(first["pandas_dropped"], 0)
        self.assertEqual(second["updated"], 2)
        rows = self.repository.list_historical_matches("2025-01-05")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["home_team"], "A")

    def test_team_filter_returns_both_home_and_away_matches(self):
        self.service.import_csv_text(CSV, "test")
        rows = self.repository.list_historical_matches(teams=["A"])
        self.assertEqual(len(rows), 2)

    def test_invalid_csv_is_rejected(self):
        with self.assertRaises(ValueError):
            self.service.import_csv_text("league,home_team\nL,A\n")

    def test_collection_agent_normalizes_football_data_csv(self):
        agent = HistoricalCollectionAgent(self.repository, Path(self.temp.name) / "archive")
        rows = agent.normalize_csv(
            "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG\nE0,01/08/2025,Arsenal,Chelsea,2,1\n",
            HistoricalSource("2526", "E0"),
        )
        self.assertEqual(rows[0]["league"], "English Premier League")
        self.assertEqual(rows[0]["played_at"], "2025-08-01")
        result = self.repository.upsert_historical_matches(rows, "test-source")
        self.assertEqual(result["imported"], 1)

    def test_collection_agent_normalizes_worldwide_csv(self):
        agent = HistoricalCollectionAgent(self.repository, Path(self.temp.name) / "archive")
        rows = agent.normalize_csv(
            "Country,League,Season,Date,Home,Away,HG,AG\n"
            "Finland,Veikkausliiga,2026,01/06/2026,HJK,Mariehamn,2,0\n",
            HistoricalSource("new", "FIN"),
        )
        self.assertEqual(rows[0]["league"], "Veikkausliiga")
        self.assertEqual(rows[0]["home_team"], "HJK")
        self.assertEqual(rows[0]["played_at"], "2026-06-01")

    def test_worldwide_source_uses_new_csv_url(self):
        agent = HistoricalCollectionAgent(self.repository, Path(self.temp.name) / "archive")
        source = agent.worldwide_sources(["FIN"])[0]
        self.assertEqual(source.season, "new")
        self.assertTrue(source.url.endswith("/new/FIN.csv"))

    def test_collection_agent_uses_archive_when_network_fails(self):
        archive = Path(self.temp.name) / "archive"
        agent = HistoricalCollectionAgent(self.repository, archive)
        source = HistoricalSource("2526", "E0")
        path = agent.archive_path(source)
        path.parent.mkdir(parents=True)
        path.write_text(
            "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG\nE0,01/08/2025,Arsenal,Chelsea,2,1\n",
            encoding="utf-8",
        )
        agent.sources = lambda years_back, divisions=None: [source]
        agent.fetch = lambda item: (_ for _ in ()).throw(OSError("DNS unavailable"))
        result = agent.sync(1)
        self.assertEqual(result["downloaded"], 0)
        self.assertEqual(result["cached"], 1)
        self.assertEqual(result["stale"], 1)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["database_matches"], 1)
        self.assertEqual(result["sources"][0]["status"], "cached")

    def test_pandas_parser_accepts_aliases_and_drops_dirty_rows(self):
        text = """playedAt,league,homeTeam,awayTeam,homeGoals,awayGoals,matchType
2025-02-01,Alias League,Home,Away,3,1,CUP
2025-02-02,Alias League,Same,Same,1,0,CUP
2025-02-03,Alias League,Home2,Away2,,0,CUP
"""
        result = self.service.import_csv_text(text, "alias")
        self.assertEqual(result["imported"], 1)
        self.assertEqual(result["pandas_rows"], 1)
        self.assertEqual(result["pandas_dropped"], 2)
        rows = self.repository.list_historical_matches(league="Alias League")
        self.assertEqual(rows[0]["match_type"], "CUP")


if __name__ == "__main__":
    unittest.main()
