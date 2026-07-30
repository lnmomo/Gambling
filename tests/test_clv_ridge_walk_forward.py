from __future__ import annotations

import calendar
from dataclasses import replace
from datetime import date

from scripts.clv_ridge_walk_forward import (
    market_structure_features,
    rolling_v6,
    sealed_latest_month_v6,
)
from scripts.robust_consensus_latest_month_holdout import HistoricalMatch


def _opening_books() -> tuple[dict, ...]:
    values = [
        ("best", 2.40, 3.10, 3.90),
        ("a", 2.00, 3.20, 4.00),
        ("b", 2.02, 3.15, 3.95),
        ("c", 1.98, 3.25, 4.05),
        ("d", 2.01, 3.18, 4.02),
        ("e", 1.99, 3.22, 3.98),
    ]
    return tuple({
        "bookmaker_key": key, "home_odds": home, "draw_odds": draw, "away_odds": away,
    } for key, home, draw, away in values)


def _closing_books() -> tuple[dict, ...]:
    return tuple({
        "bookmaker_key": f"close-{index}",
        "home_odds": 1.80,
        "draw_odds": 3.60,
        "away_odds": 5.00,
    } for index in range(6))


def test_v6_test_month_results_cannot_change_model_or_frozen_stakes(tmp_path) -> None:
    winners = []
    losers = []
    for month in range(1, 9):
        last_day = calendar.monthrange(2026, month)[1]
        for index in range(30):
            match = HistoricalMatch(
                date(2026, month, last_day), "E0",
                f"Home-{month}-{index}", f"Away-{month}-{index}", "home",
                _opening_books(), f"ridge-month-{month}.csv", index + 2, _closing_books(),
            )
            winners.append(match)
            losers.append(replace(match, actual_outcome="away") if month == 7 else match)

    positive = rolling_v6(
        tmp_path / "positive", fold_count=1, minimum_month_rows=1, matches=winners,
    )
    negative = rolling_v6(
        tmp_path / "negative", fold_count=1, minimum_month_rows=1, matches=losers,
    )

    positive_month = positive["monthly"][0]
    negative_month = negative["monthly"][0]
    assert positive["latest_sealed_month_excluded"] == "2026-08"
    assert positive_month["month"] == negative_month["month"] == "2026-07"
    assert positive_month["alpha"] == negative_month["alpha"]
    assert positive_month["safety_margin"] == negative_month["safety_margin"]
    assert positive_month["maximum_odds"] == negative_month["maximum_odds"]
    assert positive_month["bets"] == negative_month["bets"] > 0
    assert positive_month["staked"] == negative_month["staked"]
    assert positive_month["profit"] > negative_month["profit"]


def test_market_structure_features_use_opening_values_only() -> None:
    row = {
        "probability": 0.40,
        "conservative_probability": 0.38,
        "odds": 2.60,
        "raw_odds": 2.65,
        "reference_dispersion": 0.01,
        "reference_bookmakers": 5,
        "outcome": "home",
        "odds_band": "2.0-3.0",
        "source_type": "sportsbook",
    }
    features = market_structure_features(row)
    assert features["implied_probability"] == 1 / 2.60
    assert features["price_ratio"] == 2.60 * 0.40
    assert abs(features["probability_uncertainty"] - 0.02) < 1e-12
    assert features["outcome_odds_band"] == "home:2.0-3.0"
    assert not {"actual_outcome", "closing_edge_pct", "profit"} & features.keys()


def test_sealed_latest_month_outcomes_cannot_change_frozen_decisions(tmp_path) -> None:
    winners = []
    losers = []
    for month in range(1, 9):
        last_day = calendar.monthrange(2026, month)[1]
        for index in range(30):
            match = HistoricalMatch(
                date(2026, month, last_day), "E0",
                f"Home-{month}-{index}", f"Away-{month}-{index}", "home",
                _opening_books(), f"sealed-month-{month}.csv", index + 2, _closing_books(),
            )
            winners.append(match)
            losers.append(replace(match, actual_outcome="away") if month == 8 else match)

    positive = sealed_latest_month_v6(
        tmp_path / "positive", minimum_month_rows=1, matches=winners,
        feature_profile="market_structure",
    )
    negative = sealed_latest_month_v6(
        tmp_path / "negative", minimum_month_rows=1, matches=losers,
        feature_profile="market_structure",
    )
    assert positive["period_start"] == negative["period_start"] == "2026-08-01"
    assert positive["frozen_decision_sha256"] == negative["frozen_decision_sha256"]
    assert positive["bets"] == negative["bets"] > 0
    assert positive["staked"] == negative["staked"]
    assert positive["profit"] > negative["profit"]
