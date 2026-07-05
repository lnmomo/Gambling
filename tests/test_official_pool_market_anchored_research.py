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
    _config_grid,
    _decision,
    _decision_reasons,
    _default_specs_for_league,
    _matches_spec,
    build_anchored_spec_candidates,
    run_official_pool_market_anchored_research,
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
        "positive_seasons": 2,
        "negative_seasons": 1,
        "latest_season_bets": 25,
        "latest_season_profit": 5.0,
        "max_drawdown": 20.0,
        "active_pass_rate": 0.5,
    }

    assert _decision(row) == "REJECT_RESEARCH_GATES"
    assert _decision_reasons(row) == ["active_pass_rate<0.6"]
    row["active_pass_rate"] = 0.7
    assert _decision(row) == "SHADOW_READY_RESEARCH_CANDIDATE"


def test_fast_config_grid_uses_one_representative_config_per_rule() -> None:
    configs = _config_grid("AVG_CLOSE", ("FIN_home_prob0p55_1p00", "FIN_draw_odds2p8_3p5"), fast=True)

    assert len(configs) == 2
    assert all(config.train_months == 30 for config in configs)
    assert all(config.min_train_rows == 120 for config in configs)
    assert all(config.min_predicted_ev == 0.02 for config in configs)
    assert all(config.ridge == 10.0 for config in configs)


def test_default_specs_include_diagnostic_driven_true_ev_domains() -> None:
    rus = _default_specs_for_league("RUS")
    dnk = _default_specs_for_league("DNK")
    chn = _default_specs_for_league("CHN")

    assert AnchoredRuleSpec("RUS", "home", odds_bucket="[2.2,2.8)") in rus
    assert AnchoredRuleSpec("DNK", "draw", odds_bucket="[2.8,3.5)") in dnk
    assert AnchoredRuleSpec("CHN", "draw", market_prob_bucket="[0.28,0.34)") in chn


def test_run_research_can_filter_rule_labels(monkeypatch) -> None:
    rows = []
    for index in range(160):
        month = f"2024-{index % 12 + 1:02d}"
        rows.append({
            "date": f"{month}-01",
            "month": month,
            "league": "DNK",
            "home_team": f"H{index}",
            "away_team": f"A{index}",
            "outcome": "draw" if index % 2 == 0 else "away",
            "actual_result": "draw",
            "odds": 3.1 if index % 2 == 0 else 2.5,
            "odds_bucket": "[2.8,3.5)" if index % 2 == 0 else "[2.2,2.8)",
            "market_probability": 0.30,
            "market_prob_bucket": "[0.28,0.34)",
            "favorite_relation": "market_non_favorite" if index % 2 == 0 else "market_favorite",
            "odds_source": "AVG_CLOSE",
            "won": index % 2 == 0,
            "unit_profit": 2.1 if index % 2 == 0 else -1.0,
        })
    market = pd.DataFrame(rows)
    features = pd.DataFrame([{
        "match_date": pd.Timestamp(row["date"]),
        "league": row["league"],
        "home_team": row["home_team"],
        "away_team": row["away_team"],
        "league_prior_matches": 100,
        "league_draw_rate": 0.30,
        "form_points_diff": 0.0,
        "form_goal_diff_delta": 0.0,
        "season_points_per_match_delta": 0.0,
        "season_goal_diff_per_match_delta": 0.0,
        "rest_days_delta": 0.0,
        "lambda_total": 2.4,
        "lambda_diff": 0.0,
    } for row in rows])

    monkeypatch.setattr("official_pool_market_anchored_research.build_market_frame", lambda *_args: market)
    monkeypatch.setattr("official_pool_market_anchored_research.build_feature_history", lambda *_args: features)
    report = run_official_pool_market_anchored_research(
        leagues=("DNK",),
        odds_sources=("AVG_CLOSE",),
        first_month="2024-01",
        last_month="2024-12",
        fast=True,
        rule_labels=("DNK_draw_odds2p8_3p5",),
    )

    assert report["results"]
    assert {row.get("rule_spec") for row in report["results"]} == {"DNK_draw_odds2p8_3p5"}
