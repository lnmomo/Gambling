from __future__ import annotations

import calendar
from dataclasses import replace
from datetime import date

import pytest
import pandas as pd

from scripts.clv_ridge_walk_forward import (
    _pipeline,
    _outcome_probability_pipeline,
    _fit_staking_calibration,
    _fit_validated_market_residual_weight,
    _fit_market_calibration_weight,
    _validation_month_stability,
    archived_complete_months,
    export_live_ranker,
    market_structure_features,
    rolling_v6,
    sealed_latest_month_v6,
)


def test_extra_trees_ranker_is_deterministic_and_ignores_future_columns() -> None:
    frame = pd.DataFrame({
        "probability": [0.2, 0.3, 0.7, 0.8] * 30,
        "odds": [4.0, 3.0, 1.5, 1.3] * 30,
        "outcome": ["away", "draw", "home", "home"] * 30,
        "actual_outcome": ["home"] * 120,
        "profit": [999.0] * 120,
    })
    target = pd.Series([4.0, 2.0, 1.0, 3.0] * 30)
    first = _pipeline(0.0, ("probability", "odds"), ("outcome",), "extra_trees")
    second = _pipeline(0.0, ("probability", "odds"), ("outcome",), "extra_trees")
    first.fit(frame, target)
    second.fit(frame.assign(actual_outcome="away", profit=-999.0), target)

    assert (first.predict(frame) == second.predict(frame)).all()


def test_validated_market_residual_weight_improves_or_falls_back() -> None:
    market = [0.5, 0.5, 0.5, 0.5] * 30
    won = [0.0, 0.0, 1.0, 1.0] * 30
    useful = [0.2, 0.3, 0.7, 0.8] * 30
    harmful = [0.8, 0.7, 0.3, 0.2] * 30

    weight, blended_brier, market_brier = _fit_validated_market_residual_weight(
        market, useful, won
    )
    fallback_weight, fallback_brier, fallback_market_brier = (
        _fit_validated_market_residual_weight(market, harmful, won)
    )

    assert 0.0 < weight <= 1.0
    assert blended_brier < market_brier
    assert fallback_weight == 0.0
    assert fallback_brier == fallback_market_brier


def test_outcome_probability_model_ignores_future_columns() -> None:
    frame = pd.DataFrame({
        "probability": [0.2, 0.3, 0.7, 0.8] * 30,
        "odds": [4.0, 3.0, 1.5, 1.3] * 30,
        "outcome": ["away", "draw", "home", "home"] * 30,
        "actual_outcome": ["home"] * 120,
        "profit": [999.0] * 120,
    })
    won = pd.Series([0, 0, 1, 1] * 30)
    model = _outcome_probability_pipeline(
        ("probability", "odds"), ("outcome",)
    )
    model.fit(frame, won)
    before = model.predict_proba(frame)[:, 1]
    changed = frame.assign(actual_outcome="away", profit=-999.0)
    after = model.predict_proba(changed)[:, 1]

    assert (before == after).all()
    assert ((before > 0.0) & (before < 1.0)).all()


def test_unpromoted_outcome_probability_model_cannot_be_exported(tmp_path) -> None:
    with pytest.raises(ValueError, match="cannot be exported before promotion"):
        export_live_ranker(
            tmp_path / "candidate.json",
            outcome_probability_profile="training_market_logistic",
        )


def test_training_market_calibration_uses_broad_training_probabilities() -> None:
    training = pd.DataFrame({
        "probability": [0.2, 0.3, 0.7, 0.8] * 30,
        "unit_profit": [-1.0, -1.0, 1.0, 1.0] * 30,
    })
    validation = pd.DataFrame({
        "probability": [0.5, 0.5], "odds": [2.0, 2.0],
        "unit_profit": [1.0, -1.0],
    })

    intercept, slope = _fit_staking_calibration(
        training, validation, [0.0, 0.0], "training_market_platt"
    )

    assert abs(intercept) < 0.1
    assert slope > 1.0


def test_market_calibration_weight_is_shrunk_from_validation_only() -> None:
    validation = pd.DataFrame({
        "probability": [0.7, 0.7, 0.3, 0.3],
        "odds": [2.0, 2.0, 3.0, 3.0],
        "unit_profit": [1.0, 1.0, -1.0, -1.0],
    })

    weight = _fit_market_calibration_weight(
        validation, [0.0, 0.0, 0.0, 0.0], 0.0, 1.0, prior_strength=4.0
    )

    assert 0.0 <= weight <= 0.5


def test_validation_month_stability_weights_months_not_row_counts() -> None:
    frame = pd.DataFrame([
        *[{"date": "2026-01-10", "closing_edge_pct": 2.0} for _ in range(20)],
        {"date": "2026-02-10", "closing_edge_pct": -1.0},
    ])

    months, positive_rate = _validation_month_stability(frame)

    assert months == 2
    assert positive_rate == 0.5


def test_archived_complete_months_do_not_require_matches_on_first_day() -> None:
    rows = [
        HistoricalMatch(date(2026, month, day), "E0", "H", "A", "home", (), "x", day)
        for month, day in ((1, 5), (1, 20), (2, 8), (2, 24), (3, 31))
    ]
    assert archived_complete_months(rows, 2) == [
        (date(2026, 1, 1), date(2026, 1, 31)),
        (date(2026, 2, 1), date(2026, 2, 28)),
    ]


def test_include_latest_month_evaluates_latest_archive_after_prior_training(tmp_path) -> None:
    matches = []
    for month in range(1, 9):
        last_day = calendar.monthrange(2026, month)[1]
        for index in range(30):
            matches.append(HistoricalMatch(
                date(2026, month, last_day), "E0", f"H-{month}-{index}",
                f"A-{month}-{index}", "home", _opening_books(),
                f"month-{month}.csv", index + 2, _closing_books(),
            ))

    report = rolling_v6(
        tmp_path / "latest", fold_count=1, minimum_month_rows=1, matches=matches,
        month_completeness_profile="archived_count", include_latest_month=True,
    )

    assert report["latest_sealed_month_excluded"] is None
    assert report["latest_archived_month_included"] == "2026-08"
    assert report["monthly"][0]["month"] == "2026-08"
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


@pytest.mark.parametrize(
    ("target_profile", "uncertainty_profile", "selection_objective"),
    [
        ("closing_edge_pct", "rmse_grid", "profit_tuned_cap"),
        ("closing_probability", "rmse_grid", "profit_tuned_cap"),
        ("closing_probability_delta", "rmse_grid", "profit_tuned_cap"),
        ("closing_probability_delta", "residual_quantile_25", "profit_tuned_cap"),
        ("closing_edge_pct", "rmse_grid", "profit_gated_fixed_cap"),
    ],
)
def test_v6_test_month_results_cannot_change_model_or_frozen_stakes(
    tmp_path, target_profile: str, uncertainty_profile: str, selection_objective: str,
) -> None:
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
        tmp_path / f"positive-{target_profile}", fold_count=1,
        minimum_month_rows=1, matches=winners, target_profile=target_profile,
        uncertainty_profile=uncertainty_profile,
        selection_objective=selection_objective,
    )
    negative = rolling_v6(
        tmp_path / f"negative-{target_profile}", fold_count=1,
        minimum_month_rows=1, matches=losers, target_profile=target_profile,
        uncertainty_profile=uncertainty_profile,
        selection_objective=selection_objective,
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
