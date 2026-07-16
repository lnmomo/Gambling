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


def _ready_sp1_match(database: Database, repo: Repository, official_id: str, kickoff: str) -> int:
    match_id = repo.create_match({
        "official_match_id": official_id,
        "league": "Spanish La Liga",
        "home_team": "Home",
        "away_team": "Away",
        "kickoff_time": kickoff,
        "status": "scheduled",
    })
    repo.archive_official_odds_observation(
        match_id, official_id, {"home": 1.45, "draw": 4.2, "away": 7.0},
        "2026-06-01T08:00:00+00:00", kickoff, "ON_SALE", "official", "test", official_id,
    )
    history = []
    for index in range(130):
        history.append({
            "league": "Spanish La Liga",
            "home_team": "Home" if index % 2 == 0 else f"H{index}",
            "away_team": "Away" if index % 2 else f"A{index}",
            "home_goals": 2,
            "away_goals": 0,
            "played_at": f"2025-{index % 12 + 1:02d}-01",
            "match_type": "LEAGUE",
        })
    repo.upsert_historical_matches(history, "test")
    repo.add_features(match_id, {
        "lambda_home": 1.8, "lambda_away": 0.8,
        "home_weighted_points_per_match": 1.9, "away_weighted_points_per_match": 1.0,
        "home_weighted_goal_difference": 0.8, "away_weighted_goal_difference": -0.2,
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
    assert report["active_months"] == 1
    assert report["closing_sp_samples"] == 1
    assert report["closing_sp_coverage"] == 1.0
    assert report["average_clv"] == 0.0


def test_prospective_validation_settles_sp1_home_artifact_as_home(tmp_path: Path) -> None:
    database = Database(tmp_path / "sp1-settled.db")
    database.initialize()
    repo = Repository(database)
    match_id = _ready_sp1_match(database, repo, "sp1-settled", "2026-06-01T12:00:00+00:00")
    repo.upsert_historical_matches([
        {"league": "Spanish La Liga", "home_team": "Home", "away_team": "RecentH",
         "home_goals": 2, "away_goals": 0, "played_at": "2026-05-28", "match_type": "LEAGUE"},
        {"league": "Spanish La Liga", "home_team": "RecentA", "away_team": "Away",
         "home_goals": 1, "away_goals": 1, "played_at": "2026-05-30", "match_type": "LEAGUE"},
    ], "test-recent")
    repo.archive_official_odds_observation(
        match_id, "sp1-settled", {"home": 1.40, "draw": 4.4, "away": 7.5},
        "2026-06-01T11:30:00+00:00", "2026-06-01T12:00:00+00:00",
        "ON_SALE", "official", "test", "sp1-settled-close",
    )
    repo.upsert_result(match_id, 2, 0, "2026-06-01T14:00:00+00:00")
    artifact = tmp_path / "scorer.json"
    _artifact(artifact, selected_rule="SP1_home_market_ge_55")

    report = validate_profit_scorer_on_official_sp(database, artifact)

    assert report["settled_selected_snapshots"] == 1
    assert report["winning_count"] == 1
    assert report["selected"][0]["selected_outcome"] == "HOME"
    assert report["profit"] == 0.45
    assert report["selected"][0]["closing_sp"] == 1.4
    assert report["average_clv"] > 0
    assert report["positive_clv_rate"] == 1.0
    assert report["feature_engine"] == "market-anchored-research-parity-v1"
    assert report["immutable_evidence_written"] == 1
    evidence = repo.list_profit_scorer_evidence()
    assert len(evidence) == 1
    assert evidence[0]["selected_outcome"] == "HOME"
    assert evidence[0]["feature_engine"] == "market-anchored-research-parity-v1"
    assert evidence[0]["features"]["rest_days_delta"] != 0

    repeated = validate_profit_scorer_on_official_sp(database, artifact)

    assert repeated["immutable_evidence_written"] == 0
    assert len(repo.list_profit_scorer_evidence()) == 1
