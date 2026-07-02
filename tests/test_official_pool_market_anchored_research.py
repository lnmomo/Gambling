from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from official_pool_market_anchored_research import (  # noqa: E402
    AnchoredRuleSpec,
    _decision,
    _decision_reasons,
    _matches_spec,
    build_anchored_spec_candidates,
)


def test_rule_spec_matches_only_declared_fields() -> None:
    row = pd.Series({
        "league": "FIN",
        "outcome": "away",
        "odds_bucket": "[2.8,3.5)",
        "market_prob_bucket": "[0.28,0.34)",
        "favorite_relation": "market_non_favorite",
    })

    assert _matches_spec(row, AnchoredRuleSpec("FIN", "away", market_prob_bucket="[0.28,0.34)"))
    assert not _matches_spec(row, AnchoredRuleSpec("FIN", "draw", market_prob_bucket="[0.28,0.34)"))


def test_build_candidates_joins_pre_match_features(monkeypatch) -> None:
    market = pd.DataFrame([{
        "date": "2024-01-01",
        "month": "2024-01",
        "league": "FIN",
        "home_team": "A",
        "away_team": "B",
        "outcome": "away",
        "actual_result": "away",
        "odds": 3.1,
        "odds_bucket": "[2.8,3.5)",
        "market_probability": 0.30,
        "market_prob_bucket": "[0.28,0.34)",
        "favorite_relation": "market_non_favorite",
        "odds_source": "AVG_OPEN",
        "won": True,
        "unit_profit": 2.1,
    }])
    features = pd.DataFrame([{
        "match_date": pd.Timestamp("2024-01-01"),
        "date": "2024-01-01",
        "league": "FIN",
        "home_team": "A",
        "away_team": "B",
        "league_prior_matches": 100,
        "league_draw_rate": 0.25,
        "form_points_diff": 0.1,
        "form_goal_diff_delta": 0.0,
        "season_points_per_match_delta": 0.0,
        "season_goal_diff_per_match_delta": 0.0,
        "rest_days_delta": 0.0,
        "lambda_total": 2.5,
        "lambda_diff": 0.2,
    }])

    monkeypatch.setattr("official_pool_market_anchored_research.build_market_frame", lambda *_args: market)
    candidates = build_anchored_spec_candidates(
        ("FIN",),
        "AVG_OPEN",
        (AnchoredRuleSpec("FIN", "away", market_prob_bucket="[0.28,0.34)"),),
        features,
    )

    assert len(candidates) == 1
    assert candidates.loc[0, "rule_label"] == "FIN_away_prob0p28_0p34"
    assert candidates.loc[0, "unit_profit"] == 2.1


def test_candidate_decision_requires_stability_not_just_profit() -> None:
    row = {
        "bets": 200,
        "profit": 50.0,
        "roi_pct": 5.0,
        "positive_months": 8,
        "negative_months": 6,
        "max_drawdown": 20.0,
        "active_pass_rate": 0.5,
    }

    assert _decision(row) == "REJECT_RESEARCH_GATES"
    assert _decision_reasons(row) == ["active_pass_rate<0.6"]
    row["active_pass_rate"] = 0.7
    assert _decision(row) == "RESEARCH_CANDIDATE_NEEDS_AUDIT"
