from __future__ import annotations

import pandas as pd
import pytest

from football_agents.db import Database
from football_agents.market_bias_shadow_strategy import is_sp1_league
from football_agents.profit_scorer_features import build_research_parity_features
from football_agents.repository import Repository
from scripts.walk_forward_residual_strategy import build_feature_history


def test_live_profit_scorer_features_match_offline_training_definitions(tmp_path) -> None:
    database = Database(tmp_path / "feature-parity.db")
    database.initialize()
    repository = Repository(database)
    historical: list[dict] = []
    offline_rows: list[dict] = []
    for month in range(1, 13):
        rows = [
            {
                "league": "SP1", "home_team": "Home", "away_team": f"H{month}",
                "home_goals": 2 if month % 2 else 1, "away_goals": month % 2,
                "played_at": f"2025-{month:02d}-05", "match_type": "LEAGUE",
            },
            {
                "league": "SP1", "home_team": f"A{month}", "away_team": "Away",
                "home_goals": month % 3, "away_goals": 1 if month % 2 else 2,
                "played_at": f"2025-{month:02d}-08", "match_type": "LEAGUE",
            },
        ]
        historical.extend(rows)
        for row in rows:
            offline_rows.append({
                "match_date": pd.Timestamp(row["played_at"]),
                "league": row["league"],
                "HomeTeam": row["home_team"],
                "AwayTeam": row["away_team"],
                "home_goals": row["home_goals"],
                "away_goals": row["away_goals"],
                "odds_home": 2.0, "odds_draw": 3.2, "odds_away": 3.8,
            })
    repository.upsert_historical_matches(historical, "parity-test")
    target = {
        "id": 999,
        "league": "Spanish La Liga",
        "home_team": "Home",
        "away_team": "Away",
        "kickoff_time": "2025-12-12T20:00:00+00:00",
    }
    offline_rows.append({
        "match_date": pd.Timestamp("2025-12-12"),
        "league": "SP1", "HomeTeam": "Home", "AwayTeam": "Away",
        "home_goals": 0, "away_goals": 0,
        "odds_home": 1.55, "odds_draw": 4.0, "odds_away": 6.0,
    })

    expected = build_feature_history(pd.DataFrame(offline_rows)).iloc[-1]
    actual, warnings = build_research_parity_features(repository, target, is_sp1_league)

    assert actual is not None
    assert warnings == ["league_prior_matches<120:24"]
    for column in (
        "league_prior_matches", "league_draw_rate", "form_points_diff",
        "form_goal_diff_delta", "season_points_per_match_delta",
        "season_goal_diff_per_match_delta", "rest_days_delta", "lambda_total", "lambda_diff",
    ):
        assert actual[column] == pytest.approx(float(expected[column]), abs=1e-6), column

