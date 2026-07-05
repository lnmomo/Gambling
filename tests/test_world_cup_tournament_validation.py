from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import world_cup_tournament_validation as validation  # noqa: E402


def test_world_cup_holdout_discovers_rules_on_train_only(monkeypatch) -> None:
    frame = pd.DataFrame([
        {
            "date": "2018-06-01",
            "month": "2018-06",
            "year": 2018,
            "home_team": "A",
            "away_team": "B",
            "outcome": "home",
            "odds_bucket": "[2.8,3.5)",
            "market_prob_bucket": "[0.28,0.34)",
            "favorite_relation": "market_non_favorite",
            "league": "WORLD_CUP",
            "unit_profit": 2.0,
        },
        {
            "date": "2018-06-02",
            "month": "2018-06",
            "year": 2018,
            "home_team": "C",
            "away_team": "D",
            "outcome": "home",
            "odds_bucket": "[2.8,3.5)",
            "market_prob_bucket": "[0.28,0.34)",
            "favorite_relation": "market_non_favorite",
            "league": "WORLD_CUP",
            "unit_profit": 1.5,
        },
        {
            "date": "2022-11-01",
            "month": "2022-11",
            "year": 2022,
            "home_team": "E",
            "away_team": "F",
            "outcome": "home",
            "odds_bucket": "[2.8,3.5)",
            "market_prob_bucket": "[0.28,0.34)",
            "favorite_relation": "market_non_favorite",
            "league": "WORLD_CUP",
            "unit_profit": -1.0,
        },
    ])
    diagnostics = pd.DataFrame([{
        "columns": "outcome|odds_bucket",
        "key": "home|[2.8,3.5)",
    }])

    def fake_run_diagnostics(train: pd.DataFrame, *_args):
        assert set(train["year"]) == {2018}
        return diagnostics

    monkeypatch.setattr(validation, "build_market_frame", lambda *_args: frame.drop(columns=["year"]))
    monkeypatch.setattr(validation, "run_diagnostics", fake_run_diagnostics)

    report = validation.validate_world_cup_tournament_holdout(min_test_bets=1)

    assert report["candidate_rules"] == 1
    assert report["rows"][0]["test"]["profit"] == -1.0
    assert report["rows"][0]["decision"] == "REJECT_TOURNAMENT_HOLDOUT_WEAK"
    assert report["promotion_decision"] == "BLOCK_PRODUCTION_WORLD_CUP_SAMPLE_TOO_SMALL"


def test_flatten_rule_rows_keeps_csv_columns_simple() -> None:
    rows = [{
        "rule": "outcome=home",
        "train": {"bets": 2, "profit": 1.0},
        "test": {"bets": 3, "profit": -1.0},
        "decision": "REJECT",
        "decision_reasons": ["a", "b"],
    }]

    flattened = validation._flatten_rule_rows(rows)

    assert flattened == [{
        "rule": "outcome=home",
        "decision": "REJECT",
        "decision_reasons": "a;b",
        "train_bets": 2,
        "train_profit": 1.0,
        "test_bets": 3,
        "test_profit": -1.0,
    }]


def test_rolling_holdout_uses_only_prior_years(monkeypatch) -> None:
    frame = pd.DataFrame([
        {
            "date": "2014-06-01",
            "month": "2014-06",
            "home_team": "A",
            "away_team": "B",
            "outcome": "draw",
            "odds_bucket": "[2.8,3.5)",
            "market_prob_bucket": "[0.28,0.34)",
            "favorite_relation": "market_non_favorite",
            "league": "WORLD_CUP",
            "unit_profit": 2.2,
        },
        {
            "date": "2018-06-01",
            "month": "2018-06",
            "home_team": "C",
            "away_team": "D",
            "outcome": "draw",
            "odds_bucket": "[2.8,3.5)",
            "market_prob_bucket": "[0.28,0.34)",
            "favorite_relation": "market_non_favorite",
            "league": "WORLD_CUP",
            "unit_profit": -1.0,
        },
        {
            "date": "2022-11-01",
            "month": "2022-11",
            "home_team": "E",
            "away_team": "F",
            "outcome": "draw",
            "odds_bucket": "[2.8,3.5)",
            "market_prob_bucket": "[0.28,0.34)",
            "favorite_relation": "market_non_favorite",
            "league": "WORLD_CUP",
            "unit_profit": 2.4,
        },
    ])
    diagnostics = pd.DataFrame([{
        "columns": "outcome|odds_bucket",
        "key": "draw|[2.8,3.5)",
    }])
    seen_train_years = []

    def fake_run_diagnostics(train: pd.DataFrame, *_args):
        seen_train_years.append(set(pd.to_datetime(train["date"]).dt.year))
        return diagnostics

    monkeypatch.setattr(validation, "build_market_frame", lambda *_args: frame)
    monkeypatch.setattr(validation, "run_diagnostics", fake_run_diagnostics)

    report = validation.validate_world_cup_rolling_holdout(
        first_test_year=2018,
        min_train_samples=1,
        min_train_active_months=1,
        min_test_bets=1,
    )

    assert seen_train_years == [{2014}, {2014, 2018}]
    assert report["fold_count"] == 2
    assert report["combined_rows"][0]["test"]["bets"] == 2
    assert report["combined_rows"][0]["test_years_with_bets"] == 2


def test_rolling_portfolio_uses_prior_year_training_edge(monkeypatch) -> None:
    frame = pd.DataFrame([
        {
            "date": "2014-06-01",
            "month": "2014-06",
            "home_team": "A",
            "away_team": "B",
            "outcome": "draw",
            "actual_result": "draw",
            "odds": 3.2,
            "odds_bucket": "[2.8,3.5)",
            "market_probability": 0.31,
            "market_prob_bucket": "[0.28,0.34)",
            "favorite_relation": "market_non_favorite",
            "league": "WORLD_CUP",
            "won": True,
            "unit_profit": 2.2,
        },
        {
            "date": "2014-06-02",
            "month": "2014-06",
            "home_team": "C",
            "away_team": "D",
            "outcome": "draw",
            "actual_result": "home",
            "odds": 3.1,
            "odds_bucket": "[2.8,3.5)",
            "market_probability": 0.32,
            "market_prob_bucket": "[0.28,0.34)",
            "favorite_relation": "market_non_favorite",
            "league": "WORLD_CUP",
            "won": False,
            "unit_profit": -1.0,
        },
        {
            "date": "2018-06-01",
            "month": "2018-06",
            "home_team": "E",
            "away_team": "F",
            "outcome": "draw",
            "actual_result": "draw",
            "odds": 3.0,
            "odds_bucket": "[2.8,3.5)",
            "market_probability": 0.33,
            "market_prob_bucket": "[0.28,0.34)",
            "favorite_relation": "market_non_favorite",
            "league": "WORLD_CUP",
            "won": True,
            "unit_profit": 2.0,
        },
        {
            "date": "2018-06-01",
            "month": "2018-06",
            "home_team": "E",
            "away_team": "F",
            "outcome": "draw",
            "actual_result": "draw",
            "odds": 3.0,
            "odds_bucket": "[2.8,3.5)",
            "market_probability": 0.33,
            "market_prob_bucket": "[0.28,0.34)",
            "favorite_relation": "market_non_favorite",
            "league": "WORLD_CUP",
            "won": True,
            "unit_profit": 2.0,
        },
    ])
    diagnostics = pd.DataFrame([{
        "columns": "outcome|odds_bucket",
        "key": "draw|[2.8,3.5)",
    }])
    seen_train_years = []

    def fake_run_diagnostics(train: pd.DataFrame, *_args):
        seen_train_years.append(set(pd.to_datetime(train["date"]).dt.year))
        return diagnostics

    monkeypatch.setattr(validation, "build_market_frame", lambda *_args: frame)
    monkeypatch.setattr(validation, "run_diagnostics", fake_run_diagnostics)

    report, daily, bets, selected = validation.validate_world_cup_rolling_portfolio(
        first_test_year=2018,
        min_train_samples=1,
        min_train_active_months=1,
        min_test_bets=1,
        daily_limit=100,
        max_single_stake=100,
        shrink_prior_bets=1,
    )

    assert seen_train_years == [{2014}]
    assert report["fold_count"] == 1
    assert report["decision"] == "WORLD_CUP_PORTFOLIO_RESEARCH_ONLY"
    assert len(selected) == 1
    assert len(bets) == 1
    assert bets.iloc[0]["stake"] == 100
    assert daily["staked"].sum() == 100


def test_rolling_portfolio_filters_longshot_candidates(monkeypatch) -> None:
    frame = pd.DataFrame([
        {
            "date": "2014-06-01",
            "month": "2014-06",
            "home_team": "A",
            "away_team": "B",
            "outcome": "home",
            "actual_result": "home",
            "odds": 8.0,
            "odds_bucket": "[7.0,inf)",
            "market_probability": 0.12,
            "market_prob_bucket": "[0.00,0.20)",
            "favorite_relation": "market_non_favorite",
            "league": "WORLD_CUP",
            "won": True,
            "unit_profit": 7.0,
        },
        {
            "date": "2018-06-01",
            "month": "2018-06",
            "home_team": "C",
            "away_team": "D",
            "outcome": "home",
            "actual_result": "away",
            "odds": 8.0,
            "odds_bucket": "[7.0,inf)",
            "market_probability": 0.12,
            "market_prob_bucket": "[0.00,0.20)",
            "favorite_relation": "market_non_favorite",
            "league": "WORLD_CUP",
            "won": False,
            "unit_profit": -1.0,
        },
    ])

    monkeypatch.setattr(validation, "build_market_frame", lambda *_args: frame)

    report, _daily, bets, selected = validation.validate_world_cup_rolling_portfolio(
        first_test_year=2018,
        min_train_samples=1,
        min_train_active_months=1,
        min_test_bets=1,
        max_odds=5.0,
        min_market_probability=0.2,
    )

    assert report["candidate_filters"] == ["odds<=5", "market_probability>=0.2"]
    assert report["decision"] == "REJECT_WORLD_CUP_PORTFOLIO_WEAK"
    assert selected.empty
    assert bets.empty


def test_portfolio_grid_sorts_best_near_miss_without_promoting(monkeypatch) -> None:
    def fake_validate_world_cup_rolling_portfolio(**kwargs):
        profit = 12.0 if kwargs["allowed_outcomes"] == ("draw",) else -5.0
        report = {
            "candidate_filters": ["allowed_outcomes=draw"] if kwargs["allowed_outcomes"] == ("draw",) else [],
            "decision": "REJECT_WORLD_CUP_PORTFOLIO_WEAK",
            "decision_reasons": ["drawdown>profit"] if profit > 0 else ["portfolio_profit<=0"],
            "portfolio": {
                "overall": {
                    "bets": 40,
                    "total_staked": 400.0,
                    "profit": profit,
                    "roi_pct": profit / 400.0 * 100,
                    "max_drawdown": 30.0,
                },
                "positive_months": 2,
                "negative_months": 1,
                "positive_years": 1,
                "negative_years": 1,
            },
        }
        return report, pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    monkeypatch.setattr(validation, "validate_world_cup_rolling_portfolio", fake_validate_world_cup_rolling_portfolio)

    report = validation.run_world_cup_portfolio_grid(
        odds_sources=("AVG_CLOSE",),
        max_rules_values=(1,),
        allowed_outcomes_grid=((), ("draw",)),
        max_odds_values=(None,),
        min_market_probability_values=(None,),
    )

    assert report["config_count"] == 2
    assert report["passed_configs"] == 0
    assert report["decision"] == "REJECT_GRID_BEST_POSITIVE_BUT_UNSTABLE"
    assert report["best"]["allowed_outcomes"] == "draw"
    assert report["best"]["profit"] == 12.0
