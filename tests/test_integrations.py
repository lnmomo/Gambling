from __future__ import annotations

import unittest
from unittest.mock import patch

from football_agents.integrations.odds import OddsApiClient, normalize_team


class IntegrationTests(unittest.TestCase):
    def test_team_aliases_support_chinese_official_names(self) -> None:
        self.assertEqual(normalize_team("加拿大"), "canada")
        self.assertEqual(normalize_team("Bosnia and Herzegovina"), "bosniaandherzegovina")

    def test_team_aliases_cover_current_official_club_pool(self) -> None:
        self.assertEqual(normalize_team("\u535a\u5854\u5f17\u6208"), "botafogo")
        self.assertEqual(normalize_team("\u8499\u7279\u5229\u5c14"), "cfmontreal")
        self.assertEqual(normalize_team("\u74e6\u52d2\u4f26\u52a0"), "valerenga")

    def test_sport_keys_are_derived_from_current_official_leagues(self) -> None:
        self.assertEqual(
            OddsApiClient.sport_keys_for_leagues({"\u5df4\u7532", "\u7f8e\u804c", "\u632a\u8d85", "\u6b27\u7f57\u5df4"}),
            ("soccer_brazil_campeonato", "soccer_norway_eliteserien", "soccer_usa_mls"),
        )

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
