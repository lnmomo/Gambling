from __future__ import annotations

from unittest.mock import patch

from football_agents.international_odds_sources import find_international_odds_sources


@patch("football_agents.international_odds_sources.settings")
def test_source_discovery_reports_public_sources_without_api_key(settings) -> None:
    settings.odds_api_key = ""
    settings.odds_api_base_url = "https://api.example.test/v4"
    settings.international_odds_sport_keys = ("soccer_fifa_world_cup", "soccer_uefa_nations_league")

    report = find_international_odds_sources()

    assert report["odds_api"]["configured"] is False
    assert "THE_ODDS_API_KEY is missing" in report["blockers"][0]
    assert report["public_csv_sources"][0]["status"] == "usable_integrated"
    assert report["odds_api"]["candidates"][0]["status"] == "not_probed_missing_api_key"


@patch("football_agents.international_odds_sources.settings")
@patch("football_agents.international_odds_sources.get_json")
def test_source_discovery_probes_odds_api_sports(get_json, settings) -> None:
    settings.odds_api_key = "test-key"
    settings.odds_api_base_url = "https://api.example.test/v4"
    settings.enrichment_timeout_seconds = 3
    settings.international_odds_sport_keys = (
        "soccer_fifa_world_cup",
        "soccer_uefa_nations_league",
        "soccer_missing",
    )
    get_json.return_value = ([
        {"key": "soccer_fifa_world_cup", "title": "FIFA World Cup", "active": False},
        {"key": "soccer_uefa_nations_league", "title": "UEFA Nations League", "active": True},
    ], {"x-requests-remaining": "10", "x-requests-used": "0"})

    report = find_international_odds_sources()

    assert report["odds_api"]["probe_used"] is True
    statuses = {item["sport_key"]: item["status"] for item in report["odds_api"]["candidates"]}
    assert statuses["soccer_fifa_world_cup"] == "available_out_of_season"
    assert statuses["soccer_uefa_nations_league"] == "available_active"
    assert statuses["soccer_missing"] == "not_returned_by_sports_endpoint"
