from __future__ import annotations

import json
from pathlib import Path

from football_agents.db import Database
from football_agents.profit_scorer_official import diagnose_official_profit_scorer_pool
from football_agents.repository import Repository


def _artifact(path: Path) -> None:
    path.write_text(json.dumps({
        "selection": {
            "feature_columns": [
                "market_probability", "log_odds", "is_draw", "is_home", "league_draw_rate",
                "league_prior_matches_scaled", "form_points_diff", "abs_form_points_diff",
                "form_goal_diff_delta", "abs_form_goal_diff_delta", "season_points_per_match_delta",
                "abs_season_points_per_match_delta", "season_goal_diff_per_match_delta",
                "abs_season_goal_diff_per_match_delta", "rest_days_delta", "lambda_total", "lambda_diff",
            ],
            "residual_cap": 0.08,
            "min_predicted_ev": 0.02,
        },
        "model": {
            "intercept_and_coefficients": [0.08] + [0.0] * 17,
            "feature_means": {key: 0.0 for key in [
                "market_probability", "log_odds", "is_draw", "is_home", "league_draw_rate",
                "league_prior_matches_scaled", "form_points_diff", "abs_form_points_diff",
                "form_goal_diff_delta", "abs_form_goal_diff_delta", "season_points_per_match_delta",
                "abs_season_points_per_match_delta", "season_goal_diff_per_match_delta",
                "abs_season_goal_diff_per_match_delta", "rest_days_delta", "lambda_total", "lambda_diff",
            ]},
            "feature_stds": {key: 1.0 for key in [
                "market_probability", "log_odds", "is_draw", "is_home", "league_draw_rate",
                "league_prior_matches_scaled", "form_points_diff", "abs_form_points_diff",
                "form_goal_diff_delta", "abs_form_goal_diff_delta", "season_points_per_match_delta",
                "abs_season_points_per_match_delta", "season_goal_diff_per_match_delta",
                "abs_season_goal_diff_per_match_delta", "rest_days_delta", "lambda_total", "lambda_diff",
            ]},
        },
    }), encoding="utf-8")


def _official_match(repo: Repository, database: Database) -> int:
    match_id = repo.create_match({
        "official_match_id": "sporttery-i2-profit",
        "league": "Italian Serie B",
        "home_team": "Home",
        "away_team": "Away",
        "kickoff_time": "2026-06-01T12:00:00+00:00",
        "status": "scheduled",
    })
    with database.connect() as c:
        c.execute("UPDATE matches SET source_url=? WHERE id=?", ("test", match_id))
    repo.add_odds(match_id, {"home": 2.4, "draw": 3.1, "away": 3.2}, "official", "2026-06-01T08:00:00+00:00")
    return match_id


def test_official_profit_scorer_reports_missing_features(tmp_path):
    database = Database(tmp_path / "missing.db")
    database.initialize()
    repo = Repository(database)
    _official_match(repo, database)
    artifact = tmp_path / "scorer.json"
    _artifact(artifact)

    report = diagnose_official_profit_scorer_pool(database, artifact)

    assert report["scored_matches"] == 0
    reasons = {row["reason"] for row in report["blocker_counts"]}
    assert "missing_feature:lambda_home" in reasons


def test_official_profit_scorer_scores_ready_i2_match(tmp_path):
    database = Database(tmp_path / "ready.db")
    database.initialize()
    repo = Repository(database)
    match_id = _official_match(repo, database)
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
    artifact = tmp_path / "scorer.json"
    _artifact(artifact)

    report = diagnose_official_profit_scorer_pool(database, artifact)

    assert report["scored_matches"] == 1
    assert report["passed_scorer"] == 1
    candidate = report["candidates"][0]
    assert candidate["outcome"] == "DRAW"
    assert candidate["predicted_ev"] > 0.02
