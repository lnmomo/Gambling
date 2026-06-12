from __future__ import annotations

import unittest

from football_agents.integrations.odds import OddsApiClient, normalize_team


class IntegrationTests(unittest.TestCase):
    def test_team_aliases_support_chinese_official_names(self) -> None:
        self.assertEqual(normalize_team("加拿大"), "canada")
        self.assertEqual(normalize_team("Bosnia and Herzegovina"), "bosniaandherzegovina")

    def test_market_consensus_averages_bookmakers(self) -> None:
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
        self.assertEqual(OddsApiClient.consensus(event), {"home": 1.9, "draw": 3.5, "away": 4.3})


if __name__ == "__main__":
    unittest.main()
