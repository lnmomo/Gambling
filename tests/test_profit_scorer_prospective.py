from __future__ import annotations

from pathlib import Path

from football_agents.db import Database
from football_agents.profit_scorer_prospective import validate_profit_scorer_on_official_sp
from football_agents.repository import Repository

from tests.test_profit_scorer_official import _artifact


def _ready_match(database: Database, repo: Repository, official_id: str, kickoff: str) -> int:
    match_id = repo.create_match({
        "official_match_id": official_id,
        "league": "Italian Serie B",
        "home_team": "Home",
        "away_team": "Away",
        "kickoff_time": kickoff,
        "status": "scheduled",
    })
    repo.archive_official_odds_observation(
        match_id,
        official_id,
        {"home": 2.4, "draw": 3.1, "away": 3.2},
        "2026-06-01T08:00:00+00:00",
        kickoff,
        "ON_SALE",
        "official",
        "test",
        official_id,
    )
    history = []
    for index in range(130):
        history.append({
            "league": "Italian Serie B",
            "home_team": "Home" if index % 2 == 0 else f"H{index}",
            "away_team": "Away" if index % 2 else f"A{index}",
            "home_goals": 1,
            "away_goals": 1 if index % 3 == 0 else 0,
            "played_at": f"2025-{index % 12 + 1:02d}-01",
            "match_type": "LEAGUE",
        })
    repo.upsert_historical_matches(history, "test")
    repo.add_features(match_id, {
        "lambda_home": 1.2,
        "lambda_away": 1.1,
        "home_weighted_points_per_match": 1.3,
        "away_weighted_points_per_match": 1.1,
        "home_weighted_goal_difference": 0.2,
        "away_weighted_goal_difference": 0.0,
    })
    return match_id


def test_prospective_validation_uses_opening_snapshot_and_waits_for_settlement(tmp_path: Path) -> None:
    database = Database(tmp_path / "prospective.db")
    database.initialize()
    repo = Repository(database)
    _ready_match(database, repo, "i2-pending", "2026-06-01T12:00:00+00:00")
    artifact = tmp_path / "scorer.json"
    _artifact(artifact)

    report = validate_profit_scorer_on_official_sp(database, artifact)

    assert report["opening_pre_match_snapshots"] == 1
    assert report["selected_snapshots"] == 1
    assert report["settled_selected_snapshots"] == 0
    assert "settled_selected<200" in report["decision_reasons"]
    assert report["selected"][0]["settled"] is False


def test_prospective_validation_settles_selected_snapshots_only_after_result(tmp_path: Path) -> None:
    database = Database(tmp_path / "settled.db")
    database.initialize()
    repo = Repository(database)
    match_id = _ready_match(database, repo, "i2-settled", "2026-06-01T12:00:00+00:00")
    repo.upsert_result(match_id, 1, 1, "2026-06-01T14:00:00+00:00")
    artifact = tmp_path / "scorer.json"
    _artifact(artifact)

    report = validate_profit_scorer_on_official_sp(database, artifact)

    assert report["settled_selected_snapshots"] == 1
    assert report["winning_count"] == 1
    assert report["profit"] == 2.1
    assert report["monthly"][0]["month"] == "2026-06"
