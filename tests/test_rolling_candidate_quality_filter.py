from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.rolling_candidate_quality_filter import (  # noqa: E402
    RollingQualityConfig,
    add_quality_buckets,
    rolling_quality_filter,
    select_allowed_buckets,
)


def _row(date: str, form_gap: float, won: bool) -> dict:
    return {
        "date": date,
        "month": date[:7],
        "league": "DNK",
        "home_team": f"H{date}",
        "away_team": f"A{date}",
        "outcome": "draw",
        "actual_result": "draw" if won else "home",
        "odds": 3.2,
        "odds_bucket": "[2.8,3.5)",
        "market_probability": 0.29,
        "market_prob_bucket": "[0.28,0.34)",
        "favorite_relation": "market_non_favorite",
        "odds_source": "AVG_CLOSE",
        "won": won,
        "unit_profit": 2.2 if won else -1.0,
        "rule_label": "DNK_draw_odds2p8_3p5",
        "league_prior_matches": 100,
        "league_draw_rate": 0.26,
        "form_points_diff": form_gap,
        "form_goal_diff_delta": 0.0,
        "season_points_per_match_delta": 0.0,
        "season_goal_diff_per_match_delta": 0.0,
        "rest_days_delta": 0.0,
        "lambda_total": 2.4,
        "lambda_diff": 0.2,
        "bet_date": date,
        "season": "2023-24",
        "log_odds": 1.1,
        "is_draw": 1.0,
        "is_home": 0.0,
        "league_prior_matches_scaled": 0.1,
        "abs_form_points_diff": abs(form_gap),
        "abs_form_goal_diff_delta": 0.0,
        "abs_season_points_per_match_delta": 0.0,
        "abs_season_goal_diff_per_match_delta": 0.0,
        "predicted_probability": 0.34,
        "predicted_ev": 0.08,
    }


def test_select_allowed_buckets_uses_prior_profitability() -> None:
    frame = add_quality_buckets(pd.DataFrame([
        _row("2024-01-01", 0.8, True),
        _row("2024-02-01", 0.9, True),
        _row("2024-03-01", 0.1, False),
    ]))
    config = RollingQualityConfig(12, ("abs_form_points_bucket",), 2, 1.0, 0.05, 1, 0.02)

    allowed = select_allowed_buckets(frame, config)

    assert ("form_gap_mid",) in allowed
    assert ("form_gap_tiny",) not in allowed


def test_rolling_quality_filter_does_not_use_current_month_to_select_bucket() -> None:
    rows = [
        _row("2024-01-01", 0.8, True),
        _row("2024-02-01", 0.9, True),
        _row("2024-03-01", 0.1, True),
        _row("2024-04-01", 0.1, True),
    ]
    config = RollingQualityConfig(12, ("abs_form_points_bucket",), 2, 1.0, 0.05, 1, 0.02)

    summary, selected = rolling_quality_filter(pd.DataFrame(rows), config, "2024-03", "2024-04")

    assert summary["months"][0]["selected"] == 0
    assert selected.empty
