from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from market_anchored_candidate_screener import (  # noqa: E402
    _decision_reasons,
    _matches_rule,
    _parse_rule,
    _rule_id,
    build_rule_candidates,
)


def test_parse_rule_requires_column_key_alignment() -> None:
    assert _parse_rule("league|outcome", "I2|draw") == {"league": "I2", "outcome": "draw"}
    assert _parse_rule("league|outcome", "I2") == {}


def test_matches_rule_applies_all_columns() -> None:
    frame = pd.DataFrame([
        {"league": "I2", "outcome": "draw", "odds_bucket": "[2.8,3.5)"},
        {"league": "I2", "outcome": "home", "odds_bucket": "[2.8,3.5)"},
    ])
    mask = _matches_rule(frame, {"league": "I2", "outcome": "draw"})
    assert mask.tolist() == [True, False]


def test_build_rule_candidates_joins_features(monkeypatch) -> None:
    market = pd.DataFrame([{
        "date": "2024-01-01",
        "month": "2024-01",
        "league": "I2",
        "home_team": "A",
        "away_team": "B",
        "outcome": "draw",
        "actual_result": "draw",
        "odds": 3.1,
        "odds_bucket": "[2.8,3.5)",
        "market_probability": 0.31,
        "market_prob_bucket": "[0.28,0.34)",
        "favorite_relation": "market_non_favorite",
        "odds_source": "AVG_OPEN",
        "won": True,
        "unit_profit": 2.1,
    }])
    features = pd.DataFrame([{
        "match_date": pd.Timestamp("2024-01-01"),
        "league": "I2",
        "home_team": "A",
        "away_team": "B",
        "league_prior_matches": 200,
        "league_draw_rate": 0.3,
        "form_points_diff": 0.0,
        "form_goal_diff_delta": 0.0,
        "season_points_per_match_delta": 0.0,
        "season_goal_diff_per_match_delta": 0.0,
        "rest_days_delta": 0.0,
        "lambda_total": 2.2,
        "lambda_diff": 0.1,
    }])
    monkeypatch.setattr("market_anchored_candidate_screener.build_market_frame", lambda *_args: market)
    candidates = build_rule_candidates(
        ("2526",),
        "AVG_OPEN",
        {"rule": {"league": "I2", "outcome": "draw"}},
        features,
    )

    assert len(candidates) == 1
    assert candidates.loc[0, "rule_label"].startswith("r")
    assert candidates.loc[0, "rule_description"].startswith("rule_")
    assert candidates.loc[0, "unit_profit"] == 2.1


def test_rule_id_is_unique_and_config_label_safe() -> None:
    first = _rule_id({"league": "I2", "outcome": "draw"})
    second = _rule_id({"league": "SP1", "outcome": "home"})

    assert first != second
    assert "_" not in first
    assert "_" not in second


def test_decision_reasons_require_walk_forward_stability() -> None:
    row = {
        "bets": 200,
        "profit": 50.0,
        "roi_pct": 5.0,
        "positive_months": 10,
        "negative_months": 6,
        "positive_seasons": 3,
        "negative_seasons": 1,
        "latest_season_bets": 30,
        "latest_season_profit": 4.0,
        "max_drawdown": 20.0,
        "active_pass_rate": 0.5,
    }
    assert _decision_reasons(row) == ["active_pass_rate<0.6"]
    row["active_pass_rate"] = 0.7
    assert _decision_reasons(row) == []


def test_decision_reasons_block_recent_season_failure() -> None:
    row = {
        "bets": 200,
        "profit": 50.0,
        "roi_pct": 5.0,
        "positive_months": 10,
        "negative_months": 6,
        "positive_seasons": 3,
        "negative_seasons": 1,
        "latest_season_bets": 30,
        "latest_season_profit": -1.0,
        "max_drawdown": 20.0,
        "active_pass_rate": 0.7,
    }

    assert _decision_reasons(row) == ["latest_season_profit<0"]
