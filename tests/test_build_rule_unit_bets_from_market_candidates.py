import sys
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from build_rule_unit_bets_from_market_candidates import build_unit_bets  # noqa: E402


def test_build_unit_bets_filters_diagnostic_rules(tmp_path):
    diagnostics = tmp_path / "market_bias.csv"
    pd.DataFrame([{
        "columns": "league|outcome|odds_bucket",
        "key": "L|home|[2.2,2.8)",
        "bets": 10,
        "profit": 4.0,
        "roi_pct": 40.0,
        "latest_profit": 1.0,
        "score": 5.0,
    }]).to_csv(diagnostics, index=False)

    candidates = tmp_path / "market_candidates.csv"
    pd.DataFrame([
        {
            "date": "2024-01-01",
            "month": "2024-01",
            "league": "L",
            "home_team": "H",
            "away_team": "A",
            "outcome": "home",
            "actual_result": "home",
            "odds": 2.4,
            "odds_bucket": "[2.2,2.8)",
            "market_prob_bucket": "[0.34,0.42)",
            "favorite_relation": "market_favorite",
            "odds_source": "AVG_CLOSE",
            "won": True,
            "unit_profit": 1.4,
        },
        {
            "date": "2024-01-02",
            "month": "2024-01",
            "league": "X",
            "home_team": "H2",
            "away_team": "A2",
            "outcome": "home",
            "actual_result": "away",
            "odds": 2.4,
            "odds_bucket": "[2.2,2.8)",
            "market_prob_bucket": "[0.34,0.42)",
            "favorite_relation": "market_favorite",
            "odds_source": "AVG_CLOSE",
            "won": False,
            "unit_profit": -1.0,
        },
    ]).to_csv(candidates, index=False)

    unit_bets, rules, summaries = build_unit_bets(
        [candidates],
        [diagnostics],
        top_n=1,
        min_diagnostic_sources=1,
    )

    assert rules == ["league|outcome|odds_bucket=L|home|[2.2,2.8)"]
    assert len(unit_bets) == 1
    assert unit_bets.iloc[0]["profit"] == 1.4
    assert summaries[0]["bets"] == 1
