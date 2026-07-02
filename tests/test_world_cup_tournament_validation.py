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
