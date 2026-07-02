import sys
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from market_bias_candidate_screen import _summarize_rules, load_candidate_rules  # noqa: E402
from market_bias_robustness_gate import DEFAULT_RULE  # noqa: E402


def test_load_candidate_rules_filters_recent_negative_and_keeps_baseline(tmp_path):
    csv_path = tmp_path / "market_bias.csv"
    pd.DataFrame([
        {"columns": "league|outcome|odds_bucket", "key": "P1|away|[1.0,1.8)", "score": 10, "profit": 20, "bets": 200, "latest_profit": -1.0},
        {"columns": "league|outcome|odds_bucket", "key": "T1|away|[1.0,1.8)", "score": 9, "profit": 15, "bets": 150, "latest_profit": 0.5},
        {"columns": "outcome", "key": "draw", "score": 8, "profit": 30, "bets": 500, "latest_profit": 2.0},
    ]).to_csv(csv_path, index=False)
    rules = load_candidate_rules(csv_path, top_n=3)
    assert rules[0] == DEFAULT_RULE
    assert "league|outcome|odds_bucket=T1|away|[1.0,1.8)" in rules
    assert "league|outcome|odds_bucket=P1|away|[1.0,1.8)" not in rules
    assert "outcome=draw" not in rules


def test_load_candidate_rules_can_require_multi_source_overlap(tmp_path):
    first = tmp_path / "avg.csv"
    second = tmp_path / "ps.csv"
    pd.DataFrame([
        {"columns": "league|outcome|market_prob_bucket", "key": "JPN|away|[0.28,0.34)", "score": 20, "profit": 20, "bets": 200, "latest_profit": 1.0},
        {"columns": "league|outcome|odds_bucket", "key": "RUS|home|[2.2,2.8)", "score": 30, "profit": 60, "bets": 250, "latest_profit": 1.0},
    ]).to_csv(first, index=False)
    pd.DataFrame([
        {"columns": "league|outcome|market_prob_bucket", "key": "JPN|away|[0.28,0.34)", "score": 10, "profit": 10, "bets": 180, "latest_profit": 2.0},
        {"columns": "league|outcome|odds_bucket", "key": "AUT|away|[4.0,5.0)", "score": 40, "profit": 80, "bets": 300, "latest_profit": 2.0},
    ]).to_csv(second, index=False)

    rules = load_candidate_rules([first, second], top_n=3, include_rule=None, min_source_count=2)

    assert rules == ["league|outcome|market_prob_bucket=JPN|away|[0.28,0.34)"]


def test_load_candidate_rules_can_skip_default_baseline(tmp_path):
    csv_path = tmp_path / "market_bias.csv"
    pd.DataFrame([
        {"columns": "league|outcome|odds_bucket", "key": "T1|away|[1.0,1.8)", "score": 9, "profit": 15, "bets": 150, "latest_profit": 0.5},
    ]).to_csv(csv_path, index=False)

    rules = load_candidate_rules(csv_path, top_n=2, include_rule=None)

    assert DEFAULT_RULE not in rules
    assert rules == ["league|outcome|odds_bucket=T1|away|[1.0,1.8)"]


def test_summarize_rules_requires_every_validation_source_to_pass():
    summary = _summarize_rules([
        {
            "rule": "r1",
            "odds_source": "AVG_CLOSE",
            "passes_screen": True,
            "portfolio_bets": 100,
            "portfolio_staked": 1000.0,
            "portfolio_profit": 60.0,
            "portfolio_roi_pct": 6.0,
            "portfolio_max_drawdown": 50.0,
            "fail_reasons": [],
        },
        {
            "rule": "r1",
            "odds_source": "PS_CLOSE",
            "passes_screen": False,
            "portfolio_bets": 100,
            "portfolio_staked": 1000.0,
            "portfolio_profit": 10.0,
            "portfolio_roi_pct": 1.0,
            "portfolio_max_drawdown": 80.0,
            "fail_reasons": ["roi<3%"],
        },
        {
            "rule": "r2",
            "odds_source": "AVG_CLOSE",
            "passes_screen": True,
            "portfolio_bets": 120,
            "portfolio_staked": 1200.0,
            "portfolio_profit": 72.0,
            "portfolio_roi_pct": 6.0,
            "portfolio_max_drawdown": 40.0,
            "fail_reasons": [],
        },
        {
            "rule": "r2",
            "odds_source": "PS_CLOSE",
            "passes_screen": True,
            "portfolio_bets": 130,
            "portfolio_staked": 1300.0,
            "portfolio_profit": 65.0,
            "portfolio_roi_pct": 5.0,
            "portfolio_max_drawdown": 45.0,
            "fail_reasons": [],
        },
    ])

    by_rule = {row["rule"]: row for row in summary}
    assert by_rule["r1"]["passed_validation_sources"] == 1
    assert not by_rule["r1"]["passes_all_validation_sources"]
    assert by_rule["r2"]["passed_validation_sources"] == 2
    assert by_rule["r2"]["passes_all_validation_sources"]
    assert by_rule["r2"]["combined_roi_pct"] == 5.48
