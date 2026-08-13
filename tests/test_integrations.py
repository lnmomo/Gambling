from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from datetime import datetime, timedelta, timezone

from football_agents.db import Database
from football_agents.integrations.odds import OddsApiClient, normalize_team
from football_agents.integrations.service import (
    DataEnrichmentService, _capture_window_label, _odds_capture_targets,
    _requests_remaining,
)
from football_agents.repository import Repository


class IntegrationTests(unittest.TestCase):
    def test_external_odds_targets_only_near_term_matches(self) -> None:
        now = datetime.now(timezone.utc)
        matches = [
            {"id": 1, "kickoff_time": (now + timedelta(minutes=120)).isoformat()},
            {"id": 2, "kickoff_time": (now + timedelta(minutes=181)).isoformat()},
            {"id": 3, "kickoff_time": (now - timedelta(minutes=1)).isoformat()},
        ]

        targets = _odds_capture_targets(matches, now, 180)

        self.assertEqual([row["id"] for row in targets], [1])

    def test_primary_horizon_targets_only_t60_to_t120(self) -> None:
        now = datetime.now(timezone.utc)
        matches = [
            {"id": 1, "kickoff_time": (now + timedelta(minutes=59)).isoformat()},
            {"id": 2, "kickoff_time": (now + timedelta(minutes=60)).isoformat()},
            {"id": 3, "kickoff_time": (now + timedelta(minutes=120)).isoformat()},
            {"id": 4, "kickoff_time": (now + timedelta(minutes=121)).isoformat()},
        ]

        targets = _odds_capture_targets(matches, now, 120, 60)

        self.assertEqual([row["id"] for row in targets], [2, 3])

    def test_last_fifteen_minutes_are_archived_as_closing(self) -> None:
        now = datetime.now(timezone.utc)
        match = {"kickoff_time": (now + timedelta(minutes=10)).isoformat()}

        self.assertEqual(_capture_window_label(match, now), "CLOSING")

    def test_primary_horizon_capture_is_not_requested_twice(self) -> None:
        with TemporaryDirectory() as directory:
            database = Database(Path(directory) / "horizon.db")
            database.initialize()
            repository = Repository(database)
            now = datetime.now(timezone.utc)
            kickoff = now + timedelta(minutes=90)
            match_id, _, _ = repository.upsert_official_match({
                "official_match_id": "sporttery-horizon-1", "match_no": "001",
                "league": "Test League", "home_team": "Home", "away_team": "Away",
                "kickoff_time": kickoff.isoformat(), "status": "scheduled",
                "source_url": "https://example.test", "data_quality_score": 1.0,
                "raw_hash": "horizon-match",
            })
            service = DataEnrichmentService(repository)
            service.odds.configured = Mock(return_value=True)
            service.odds.events = Mock(return_value=([{"id": "event"}], {
                "x-requests-remaining": "99",
            }))
            service.odds.match_event = Mock(return_value={"id": "event"})
            service.odds.consensus = Mock(return_value={"home": 2.0, "draw": 3.5, "away": 4.0})
            service.odds.bookmaker_odds = Mock(return_value=[{
                "bookmaker": "Book", "bookmaker_key": "book", "market": "H2H",
                "odds": {"home": 2.0, "draw": 3.5, "away": 4.0},
                "last_update": now.isoformat(),
            }])

            first = service.sync(10, evaluate=False, include_news_weather=False,
                                 odds_minimum_minutes=60, odds_window_minutes=120,
                                 skip_existing_horizon_capture=True)
            second = service.sync(10, evaluate=False, include_news_weather=False,
                                  odds_minimum_minutes=60, odds_window_minutes=120,
                                  skip_existing_horizon_capture=True)

            self.assertEqual(first["market_odds"], 1)
            self.assertEqual(second["market_status"], "horizon_captured")
            self.assertEqual(second["market_already_captured"], 1)
            self.assertEqual(service.odds.events.call_count, 1)
            self.assertTrue(repository.has_external_odds_capture_in_horizon(match_id, 60, 120))

    def test_reads_latest_odds_api_quota_for_reserve_guard(self) -> None:
        rows = [
            {"provider": "open_meteo", "message": "ok"},
            {"provider": "the_odds_api", "message": "requests_remaining=224"},
        ]

        self.assertEqual(_requests_remaining(rows), 224)

    def test_reads_quota_preserved_in_waiting_horizon_status(self) -> None:
        rows = [{
            "provider": "the_odds_api",
            "status": "waiting_horizon",
            "message": "requests_remaining=224; target_matches=0; capture_window_minutes=180",
        }]

        self.assertEqual(_requests_remaining(rows), 224)

    def test_team_aliases_support_chinese_official_names(self) -> None:
        self.assertEqual(normalize_team("加拿大"), "canada")
        self.assertEqual(normalize_team("Bosnia and Herzegovina"), "bosniaandherzegovina")

    def test_team_aliases_cover_current_official_club_pool(self) -> None:
        self.assertEqual(normalize_team("\u535a\u5854\u5f17\u6208"), "botafogo")
        self.assertEqual(normalize_team("\u8499\u7279\u5229\u5c14"), "cfmontreal")
        self.assertEqual(normalize_team("\u74e6\u52d2\u4f26\u52a0"), "valerenga")

    def test_kleague_aliases_match_current_official_pool(self) -> None:
        self.assertEqual(normalize_team("\u6d4e\u5ddeSK"), "jejuunitedfc")
        self.assertEqual(normalize_team("\u5168\u5317\u73b0\u4ee3"), "jeonbukhundaimotors")
        self.assertEqual(normalize_team("\u851a\u5c71\u73b0\u4ee3"), "ulsanhyundaifc")

    def test_event_match_uses_klague_aliases_when_kickoffs_are_shared(self) -> None:
        kickoff = "2026-07-21T10:30:00+00:00"
        events = [
            {"id": "jeju", "commence_time": kickoff, "home_team": "Jeju SK FC", "away_team": "Gangwon FC"},
            {"id": "jeonbuk", "commence_time": kickoff, "home_team": "Jeonbuk Hyundai Motors", "away_team": "Daejeon Citizen"},
            {"id": "ulsan", "commence_time": kickoff, "home_team": "Ulsan HD FC", "away_team": "Incheon United"},
        ]
        match = {
            "kickoff_time": kickoff,
            "home_team": "\u5168\u5317\u73b0\u4ee3",
            "away_team": "\u5927\u7530\u5e02\u6c11",
        }

        self.assertEqual(OddsApiClient.match_event(match, events)["id"], "jeonbuk")

    def test_sport_keys_are_derived_from_current_official_leagues(self) -> None:
        self.assertEqual(
            OddsApiClient.sport_keys_for_leagues({"\u5df4\u7532", "\u7f8e\u804c", "\u632a\u8d85", "\u6b27\u7f57\u5df4"}),
            ("soccer_brazil_campeonato", "soccer_norway_eliteserien", "soccer_usa_mls"),
        )

    def test_sport_keys_cover_champions_league_qualifying_label(self) -> None:
        self.assertEqual(
            OddsApiClient.sport_keys_for_leagues({"\u6b27\u51a0"}),
            ("soccer_uefa_champs_league_qualification",),
        )

    def test_event_match_uses_current_pool_chinese_aliases(self) -> None:
        match = {
            "kickoff_time": "2026-07-28T23:00:00+08:00",
            "home_team": "\u5e93\u5965\u76ae\u5965",
            "away_team": "\u8428\u5df4\u8d6b",
        }
        event = {
            "id": "kups-sabah",
            "commence_time": "2026-07-28T15:00:00Z",
            "home_team": "KuPS Kuopio",
            "away_team": "Sabah FK",
        }

        self.assertEqual(OddsApiClient.match_event(match, [event])["id"], "kups-sabah")

    def test_market_consensus_averages_devigged_bookmaker_probabilities(self) -> None:
        event = {"home_team": "Canada", "away_team": "Bosnia and Herzegovina", "bookmakers": [
            {"markets": [{"key": "h2h", "outcomes": [
                {"name": "Canada", "price": 1.8}, {"name": "Draw", "price": 3.4},
                {"name": "Bosnia and Herzegovina", "price": 4.2},
            ]}]},
            {"markets": [{"key": "h2h", "outcomes": [
                {"name": "Canada", "price": 2.0}, {"name": "Draw", "price": 3.6},
                {"name": "Bosnia and Herzegovina", "price": 4.4},
            ]}]},
        ]}
        consensus = OddsApiClient.consensus(event)
        self.assertIsNotNone(consensus)
        self.assertAlmostEqual(consensus["home"], 1.9837, places=4)
        self.assertAlmostEqual(consensus["draw"], 3.6579, places=4)
        self.assertAlmostEqual(consensus["away"], 4.4942, places=4)
        self.assertAlmostEqual(sum(1 / value for value in consensus.values()), 1, places=4)

    def test_market_consensus_skips_incomplete_bookmaker_markets(self) -> None:
        event = {"home_team": "A", "away_team": "B", "bookmakers": [
            {"markets": [{"key": "h2h", "outcomes": [
                {"name": "A", "price": 2.0}, {"name": "Draw", "price": 3.5},
            ]}]},
            {"markets": [{"key": "h2h", "outcomes": [
                {"name": "A", "price": 2.0}, {"name": "Draw", "price": 4.0},
                {"name": "B", "price": 4.0},
            ]}]},
        ]}
        self.assertEqual(OddsApiClient.consensus(event), {"home": 2.0, "draw": 4.0, "away": 4.0})

    def test_extracts_bookmaker_detail_for_frontend_consensus(self) -> None:
        event = {"home_team": "A", "away_team": "B", "bookmakers": [{"key": "pinnacle",
            "title": "Pinnacle", "last_update": "2026-06-14T10:00:00Z", "markets": [{"key": "h2h",
            "outcomes": [{"name": "A", "price": 2.0}, {"name": "Draw", "price": 3.5},
                         {"name": "B", "price": 4.0}]}]}]}
        rows = OddsApiClient.bookmaker_odds(event)
        self.assertEqual(rows[0]["bookmaker_key"], "pinnacle")
        self.assertEqual(rows[0]["odds"], {"home": 2.0, "draw": 3.5, "away": 4.0})

    def test_auto_sport_keys_cover_supported_official_league_labels(self) -> None:
        keys = OddsApiClient.sport_keys_for_leagues({"韩职", "英超", "西甲", "巴乙", "南美杯"})

        self.assertEqual(keys, tuple(sorted((
            "soccer_korea_kleague1",
            "soccer_epl",
            "soccer_spain_la_liga",
            "soccer_brazil_serie_b",
            "soccer_conmebol_copa_sudamericana",
        ))))

    @patch("football_agents.integrations.odds.settings")
    @patch("football_agents.integrations.odds.get_json")
    def test_events_skips_unavailable_sport_keys(self, get_json, settings) -> None:
        settings.odds_api_key = "test"
        settings.odds_api_base_url = "https://example.test/v4"
        settings.odds_api_sport_keys = ("soccer_valid", "soccer_removed")
        settings.odds_api_auto_sport_keys = False
        settings.odds_api_regions = "eu"
        settings.enrichment_timeout_seconds = 5
        get_json.side_effect = [
            ([{"key": "soccer_valid", "active": True}], {"x-requests-remaining": "10"}),
            ([{"id": "event-1"}], {"x-requests-remaining": "9"}),
        ]
        client = OddsApiClient()
        events, _ = client.events()
        self.assertEqual([{"id": "event-1"}], events)
        self.assertIn("soccer_removed", client.warnings[0])


if __name__ == "__main__":
    unittest.main()
