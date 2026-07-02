import sys
from argparse import Namespace
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from market_bias_multi_window_optimizer import (  # noqa: E402
    CandidateSpec,
    _evaluate_window,
    _month_windows,
    load_candidates_from_diagnostics,
    summarize_candidate_windows,
)


def test_month_windows_builds_forward_validation_blocks_without_partial_tail():
    assert _month_windows("2024-01", "2024-12", window_months=6, step_months=3) == [
        ("2024-01", "2024-06"),
        ("2024-04", "2024-09"),
        ("2024-07", "2024-12"),
    ]


def test_candidate_summary_requires_stable_windows_not_just_positive_total_profit():
    rows = [
        {
            "odds_source": "AVG_OPEN",
            "bets": 40,
            "total_staked": 400.0,
            "profit": 80.0,
            "roi_pct": 20.0,
            "max_drawdown": 20.0,
            "positive_months": 4,
            "negative_months": 1,
            "passes_window": True,
        },
        {
            "odds_source": "AVG_OPEN",
            "bets": 12,
            "total_staked": 120.0,
            "profit": -20.0,
            "roi_pct": -16.67,
            "max_drawdown": 40.0,
            "positive_months": 1,
            "negative_months": 3,
            "passes_window": False,
        },
        {
            "odds_source": "AVG_CLOSE",
            "bets": 8,
            "total_staked": 80.0,
            "profit": -10.0,
            "roi_pct": -12.5,
            "max_drawdown": 30.0,
            "positive_months": 0,
            "negative_months": 2,
            "passes_window": False,
        },
    ]

    summary = summarize_candidate_windows(rows, min_pass_rate=0.6, min_source_pass_rate=0.5)

    assert summary["total_profit"] == 50.0
    assert summary["pass_rate"] == 0.3333
    assert summary["decision"] == "RESEARCH_ONLY_UNSTABLE_WINDOWS"


def test_candidate_summary_promotes_only_when_windows_and_sources_are_stable():
    rows = []
    for source in ("AVG_OPEN", "AVG_CLOSE"):
        for index in range(3):
            rows.append({
                "odds_source": source,
                "bets": 30,
                "total_staked": 300.0,
                "profit": 24.0 + index,
                "roi_pct": 8.0,
                "max_drawdown": 12.0,
                "positive_months": 4,
                "negative_months": 1,
                "passes_window": index < 2,
            })

    summary = summarize_candidate_windows(rows, min_pass_rate=0.6, min_source_pass_rate=1.0)

    assert summary["pass_rate"] == 0.6667
    assert summary["source_pass_rate"] == 1.0
    assert summary["decision"] == "MULTI_WINDOW_SHADOW_CANDIDATE"


def test_candidate_summary_tracks_active_window_stability_separately():
    rows = []
    for index in range(8):
        rows.append({
            "odds_source": "AVG_OPEN",
            "bets": 30 if index < 4 else 0,
            "total_staked": 300.0 if index < 4 else 0.0,
            "profit": 24.0 if index < 4 else 0.0,
            "roi_pct": 8.0 if index < 4 else 0.0,
            "max_drawdown": 12.0 if index < 4 else 0.0,
            "positive_months": 4 if index < 4 else 0,
            "negative_months": 1 if index < 4 else 0,
            "passes_window": index < 4,
        })
    rows.extend([
        {
            "odds_source": "AVG_CLOSE",
            "bets": 0,
            "total_staked": 0.0,
            "profit": 0.0,
            "roi_pct": 0.0,
            "max_drawdown": 0.0,
            "positive_months": 0,
            "negative_months": 0,
            "passes_window": False,
        }
        for _ in range(8)
    ])

    summary = summarize_candidate_windows(
        rows,
        min_pass_rate=0.6,
        min_source_pass_rate=0.5,
        min_active_windows=4,
    )

    assert summary["pass_rate"] == 0.25
    assert summary["active_pass_rate"] == 1.0
    assert summary["active_window_count"] == 4
    assert summary["decision"] == "MULTI_WINDOW_SHADOW_CANDIDATE"


def test_window_evaluation_slices_existing_walk_forward_bets():
    unit_bets = pd.DataFrame([
        {
            "date": "2024-01-01",
            "month": "2024-01",
            "league": "I2",
            "home_team": "A",
            "away_team": "B",
            "outcome": "draw",
            "actual_result": "draw",
            "odds": 3.0,
            "stake": 10.0,
            "profit": 20.0,
            "won": True,
            "rule_label": "r",
        },
        {
            "date": "2024-07-01",
            "month": "2024-07",
            "league": "I2",
            "home_team": "C",
            "away_team": "D",
            "outcome": "draw",
            "actual_result": "home",
            "odds": 3.0,
            "stake": 10.0,
            "profit": -10.0,
            "won": False,
            "rule_label": "r",
        },
    ])
    args = Namespace(
        daily_limit=100.0,
        max_single_stake=10.0,
        settlement_delay_days=1,
        stop_after_losing_settlement_days=999,
        cooldown_days=0,
        validation_min_bets=1,
        validation_min_roi_pct=1.0,
        min_positive_month_edge=1,
        max_drawdown_to_profit=1.5,
    )

    row = _evaluate_window(
        unit_bets,
        CandidateSpec("c", ("league=I2",), ("2122",), "2024-01", "2024-12"),
        "AVG_OPEN",
        "2024-01",
        "2024-06",
        args,
    )

    assert row["bets"] == 1
    assert row["profit"] == 20.0
    assert row["walk_forward_active_months"] == 1
    assert row["active_rules"] == 1
    assert row["rule_contributions"] == [{"rule_label": "r", "bets": 1, "profit": 20.0, "roi_pct": 200.0}]


def test_load_candidates_from_diagnostics_builds_rule_specs_without_default(tmp_path):
    csv_path = tmp_path / "market_bias.csv"
    pd.DataFrame([
        {
            "columns": "league|outcome|market_prob_bucket",
            "key": "JPN|away|[0.28,0.34)",
            "score": 20,
            "profit": 30,
            "bets": 200,
            "latest_profit": 2,
        },
    ]).to_csv(csv_path, index=False)

    candidates = load_candidates_from_diagnostics(
        [csv_path],
        top_n=3,
        seasons=("JPN",),
        first_month="2024-01",
        last_month="2024-12",
        min_diagnostic_sources=1,
        include_default_rule=False,
    )

    assert len(candidates) == 1
    assert candidates[0].rules == ("league|outcome|market_prob_bucket=JPN|away|[0.28,0.34)",)
    assert candidates[0].seasons == ("JPN",)
    assert candidates[0].first_month == "2024-01"


def test_load_candidates_from_diagnostics_can_build_pair_combos(tmp_path):
    csv_path = tmp_path / "market_bias.csv"
    pd.DataFrame([
        {"columns": "league|outcome|market_prob_bucket", "key": "JPN|away|[0.28,0.34)", "score": 30, "profit": 30, "bets": 200, "latest_profit": 2},
        {"columns": "league|outcome|odds_bucket", "key": "SWE|away|[2.2,2.8)", "score": 20, "profit": 20, "bets": 200, "latest_profit": 2},
        {"columns": "league|outcome|odds_bucket", "key": "RUS|home|[2.2,2.8)", "score": 10, "profit": 10, "bets": 200, "latest_profit": 2},
    ]).to_csv(csv_path, index=False)

    candidates = load_candidates_from_diagnostics(
        [csv_path],
        top_n=3,
        seasons=("JPN", "SWE", "RUS"),
        first_month="2024-01",
        last_month="2024-12",
        min_diagnostic_sources=1,
        include_default_rule=False,
        combo_size=2,
    )

    assert len(candidates) == 3
    assert all(len(candidate.rules) == 2 for candidate in candidates)
    assert candidates[0].candidate_id.startswith("combo-")
