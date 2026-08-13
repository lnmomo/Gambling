from __future__ import annotations

import calendar
import math
from dataclasses import replace
from datetime import date

import pytest
import pandas as pd

from scripts.clv_ridge_walk_forward import (
    _pipeline,
    _outcome_probability_pipeline,
    _positive_clv_target,
    _fit_staking_calibration,
    _fit_validated_market_residual_weight,
    _fit_market_calibration_weight,
    _fit_prediction_bias_corrections,
    _apply_prediction_bias_corrections,
    _predicted_edges,
    _uncertainty_scale,
    _validation_month_stability,
    FittedRanker,
    RankerPolicy,
    freeze_decisions,
    _training_sample_weights,
    archived_complete_months,
    export_live_ranker,
    market_structure_features,
    market_shape_features,
    rolling_v6,
    sealed_latest_month_v6,
)


def test_validation_bucket_bias_correction_is_shrunk_and_test_result_blind() -> None:
    validation = pd.DataFrame({
        "outcome": ["home", "home", "away"],
        "odds_band": ["2.0-3.0", "2.0-3.0", "3.0-4.0"],
        "source_type": ["sportsbook", "sportsbook", "exchange"],
        "closing_edge_pct": [6.0, 8.0, -2.0],
    })
    corrections = _fit_prediction_bias_corrections(
        validation, pd.Series([2.0, 2.0, -2.0]).to_numpy(),
        "closing_edge_pct", prior_observations=2.0,
    )
    test = pd.DataFrame({
        "outcome": ["home", "draw"],
        "odds_band": ["2.0-3.0", "3.0-4.0"],
        "source_type": ["sportsbook", "exchange"],
        "actual_outcome": ["away", "home"],
        "profit": [-999.0, 999.0],
    })
    changed = test.assign(actual_outcome="draw", profit=0.0)

    first = _apply_prediction_bias_corrections(
        test, pd.Series([1.0, 1.0]).to_numpy(), corrections
    )
    second = _apply_prediction_bias_corrections(
        changed, pd.Series([1.0, 1.0]).to_numpy(), corrections
    )

    assert corrections["home|2.0-3.0|sportsbook"] == pytest.approx(2.5)
    assert first.tolist() == pytest.approx([3.5, 1.0])
    assert second.tolist() == pytest.approx(first.tolist())


def test_bucket_bias_ranking_changes_direction_without_relaxing_base_gate() -> None:
    class FixedModel:
        def predict(self, frame):
            return pd.Series([3.0, 2.0], index=frame.index).to_numpy()

    frame = pd.DataFrame({
        "candidate_id": ["match:home", "match:away"],
        "match_key": ["match", "match"],
        "date": ["2026-01-01", "2026-01-01"],
        "outcome": ["home", "away"],
        "odds_band": ["2.0-3.0", "2.0-3.0"],
        "source_type": ["sportsbook", "sportsbook"],
        "odds": [2.0, 2.0],
        "probability": [0.5, 0.5],
    })
    fitted = FittedRanker(
        model=FixedModel(), alpha=1.0, safety_margin=0.0,
        maximum_odds=5.0, validation_rmse_pct=0.0,
        validation_diagnostics=[], numeric_features=(), categorical_features=(),
        prediction_bias_profile="validation_bucket_ranking_only",
        prediction_bias_corrections={
            "home|2.0-3.0|sportsbook": -3.0,
            "away|2.0-3.0|sportsbook": 3.0,
        },
    )

    frozen = freeze_decisions(frame, fitted, RankerPolicy())

    assert len(frozen) == 1
    assert frozen[0]["outcome"] == "away"
    assert frozen[0]["lower_closing_edge_pct"] == pytest.approx(2.0)
    assert frozen[0]["ranking_lower_closing_edge_pct"] == pytest.approx(5.0)


def test_positive_clv_weighted_ranking_keeps_base_gate_and_changes_direction() -> None:
    class FixedModel:
        def predict(self, frame):
            return pd.Series([3.0, 2.0], index=frame.index).to_numpy()

    class FixedPositiveModel:
        def predict_proba(self, frame):
            probabilities = pd.Series([0.50, 0.90], index=frame.index).to_numpy()
            return pd.DataFrame({0: 1.0 - probabilities, 1: probabilities}).to_numpy()

    frame = pd.DataFrame({
        "candidate_id": ["match:home", "match:away"],
        "match_key": ["match", "match"],
        "date": ["2026-01-01", "2026-01-01"],
        "outcome": ["home", "away"],
        "odds_band": ["2.0-3.0", "2.0-3.0"],
        "source_type": ["sportsbook", "sportsbook"],
        "odds": [2.0, 2.0], "probability": [0.5, 0.5],
    })
    fitted = FittedRanker(
        model=FixedModel(), alpha=1.0, safety_margin=0.0,
        maximum_odds=5.0, validation_rmse_pct=0.0,
        validation_diagnostics=[], numeric_features=(), categorical_features=(),
        positive_clv_model=FixedPositiveModel(),
        selection_ranking_profile="lower_clv_x_positive_probability",
    )

    frozen = freeze_decisions(frame, fitted, RankerPolicy())

    assert len(frozen) == 1
    assert frozen[0]["outcome"] == "away"
    assert frozen[0]["lower_closing_edge_pct"] == pytest.approx(2.0)
    assert frozen[0]["selection_ranking_score"] == pytest.approx(1.8)


def test_research_lower_clv_threshold_is_frozen_in_ranker() -> None:
    class FixedModel:
        def predict(self, frame):
            return pd.Series([0.99], index=frame.index).to_numpy()

    frame = pd.DataFrame({
        "candidate_id": ["match:home"], "match_key": ["match"],
        "date": ["2026-01-01"], "outcome": ["home"],
        "odds_band": ["2.0-3.0"], "source_type": ["sportsbook"],
        "odds": [2.0], "probability": [0.5],
    })
    fitted = FittedRanker(
        model=FixedModel(), alpha=1.0, safety_margin=0.0,
        maximum_odds=5.0, validation_rmse_pct=0.0,
        validation_diagnostics=[], numeric_features=(), categorical_features=(),
    )

    assert freeze_decisions(frame, fitted, RankerPolicy()) == []
    relaxed = freeze_decisions(
        frame, replace(fitted, minimum_lower_clv_pct=0.0), RankerPolicy()
    )
    assert len(relaxed) == 1
    assert relaxed[0]["lower_closing_edge_pct"] == pytest.approx(0.99)


def test_hist_gradient_boosting_pipeline_handles_unknown_category() -> None:
    training = pd.DataFrame({
        "probability": [0.40, 0.45, 0.50, 0.55] * 30,
        "outcome": ["home", "draw", "away", "home"] * 30,
    })
    target = pd.Series([1.0, -1.0, 2.0, 0.5] * 30)
    model = _pipeline(
        0.0, ("probability",), ("outcome",), "hist_gradient_boosting"
    )
    model.fit(training, target)

    prediction = model.predict(pd.DataFrame({
        "probability": [0.47], "outcome": ["unknown_live_outcome"],
    }))

    assert len(prediction) == 1
    assert math.isfinite(float(prediction[0]))


def test_validated_market_residual_probability_drives_kelly_without_test_result() -> None:
    class EdgeModel:
        def predict(self, frame):
            return pd.Series([10.0], index=frame.index).to_numpy()

    class OutcomeModel:
        def predict_proba(self, frame):
            return pd.DataFrame({0: [0.2], 1: [0.8]}).to_numpy()

    frame = pd.DataFrame({
        "candidate_id": ["match:home"], "match_key": ["match"],
        "date": ["2026-01-01"], "outcome": ["home"],
        "odds_band": ["2.0-3.0"], "source_type": ["sportsbook"],
        "odds": [2.0], "probability": [0.5],
        "actual_outcome": ["away"], "profit": [-999.0],
    })
    fitted = FittedRanker(
        model=EdgeModel(), alpha=1.0, safety_margin=0.0,
        maximum_odds=5.0, validation_rmse_pct=0.0,
        validation_diagnostics=[], numeric_features=(), categorical_features=(),
        staking_probability_profile="validated_market_residual",
        outcome_probability_profile="validated_market_residual_blend",
        outcome_probability_model=OutcomeModel(), outcome_probability_weight=0.5,
    )

    frozen = freeze_decisions(frame, fitted, RankerPolicy())
    changed = freeze_decisions(
        frame.assign(actual_outcome="home", profit=999.0), fitted, RankerPolicy()
    )

    assert frozen[0]["estimated_probability_from_validated_market_residual"] == 0.65
    assert frozen[0]["stake"] == 3.0
    assert changed[0]["stake"] == frozen[0]["stake"]


def test_recency_weights_use_dates_only_with_fixed_ninety_day_half_life() -> None:
    frame = pd.DataFrame({
        "date": ["2025-07-04", "2025-10-02", "2025-12-31"],
        "actual_outcome": ["home", "draw", "away"],
        "profit": [-999.0, 999.0, 0.0],
    })
    changed = frame.assign(actual_outcome="away", profit=12345.0)

    first = _training_sample_weights(frame, "recency_half_life_90d")
    second = _training_sample_weights(changed, "recency_half_life_90d")

    assert first.tolist() == pytest.approx([0.25, 0.5, 1.0])
    assert second.tolist() == pytest.approx(first.tolist())


def test_logit_delta_target_restores_probability_and_logit_uncertainty() -> None:
    odds = pd.Series([2.0])
    opening = pd.Series([0.5])

    predicted, lower, probability = _predicted_edges(
        pd.Series([0.4]).to_numpy(), odds, opening,
        rmse=0.2, margin=1.0, target_profile="closing_logit_delta",
    )

    assert probability.iloc[0] == pytest.approx(1.0 / (1.0 + math.exp(-0.4)))
    assert predicted.iloc[0] == pytest.approx(
        (2.0 / (1.0 + math.exp(-0.4)) - 1.0) * 100.0
    )
    assert lower.iloc[0] == pytest.approx(
        (2.0 / (1.0 + math.exp(-0.2)) - 1.0) * 100.0
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


def test_huber_ranker_is_deterministic_and_ignores_future_columns() -> None:
    frame = pd.DataFrame({
        "probability": [0.2, 0.3, 0.7, 0.8] * 30,
        "odds": [4.0, 3.0, 1.5, 1.3] * 30,
        "outcome": ["away", "draw", "home", "home"] * 30,
        "actual_outcome": ["home"] * 120, "profit": [999.0] * 120,
    })
    target = pd.Series([4.0, 2.0, 1.0, 3.0] * 30)
    first = _pipeline(0.0, ("probability", "odds"), ("outcome",), "huber")
    second = _pipeline(0.0, ("probability", "odds"), ("outcome",), "huber")
    first.fit(frame, target)
    second.fit(frame.assign(actual_outcome="away", profit=-999.0), target)

    assert first.predict(frame) == pytest.approx(second.predict(frame))


def test_quantile_ranker_is_deterministic_and_ignores_future_columns() -> None:
    frame = pd.DataFrame({
        "probability": [0.2, 0.3, 0.7, 0.8] * 30,
        "odds": [4.0, 3.0, 1.5, 1.3] * 30,
        "outcome": ["away", "draw", "home", "home"] * 30,
        "actual_outcome": ["home"] * 120,
        "profit": [999.0] * 120,
    })
    target = pd.Series([8.0, -2.0, 3.0, 1.0] * 30)
    first = _pipeline(0.01, ("probability", "odds"), ("outcome",), "quantile_25")
    second = _pipeline(0.01, ("probability", "odds"), ("outcome",), "quantile_25")
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


def test_positive_clv_classifier_target_ignores_match_results_and_profit() -> None:
    frame = pd.DataFrame({
        "closing_edge_pct": [-1.0, 0.0, 0.1, 4.0],
        "actual_outcome": ["home", "draw", "away", "home"],
        "unit_profit": [10.0, -1.0, -1.0, 3.0],
    })

    expected = _positive_clv_target(frame)
    changed = _positive_clv_target(frame.assign(
        actual_outcome=["away"] * 4,
        unit_profit=[-999.0, 999.0, 999.0, -999.0],
    ))

    assert expected.tolist() == [0, 0, 1, 1]
    assert changed.equals(expected)


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
    (
        "target_profile", "uncertainty_profile", "selection_objective",
        "estimator_profile",
    ),
    [
        ("closing_edge_pct", "rmse_grid", "profit_tuned_cap", "ridge"),
        ("closing_probability", "rmse_grid", "profit_tuned_cap", "ridge"),
        ("closing_probability_delta", "rmse_grid", "profit_tuned_cap", "ridge"),
        ("closing_probability_delta", "residual_quantile_25", "profit_tuned_cap", "ridge"),
        ("closing_edge_pct", "rmse_grid", "profit_gated_fixed_cap", "ridge"),
        ("closing_edge_pct", "odds_scaled_rmse_grid", "clv_fixed_cap", "ridge"),
        ("closing_edge_pct", "odds_upscaled_rmse_grid", "clv_fixed_cap", "ridge"),
        ("closing_edge_pct", "odds_upscaled_freeze_only", "clv_fixed_cap", "ridge"),
        ("closing_edge_pct", "direct_quantile_25", "clv_fixed_cap", "quantile_25"),
        ("closing_edge_pct", "direct_quantile_40", "clv_fixed_cap", "quantile_40"),
    ],
)
def test_v6_test_month_results_cannot_change_model_or_frozen_stakes(
    tmp_path, target_profile: str, uncertainty_profile: str,
    selection_objective: str, estimator_profile: str,
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
        estimator_profile=estimator_profile,
    )
    negative = rolling_v6(
        tmp_path / f"negative-{target_profile}", fold_count=1,
        minimum_month_rows=1, matches=losers, target_profile=target_profile,
        uncertainty_profile=uncertainty_profile,
        selection_objective=selection_objective,
        estimator_profile=estimator_profile,
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


def test_market_shape_features_use_complete_opening_consensus() -> None:
    features = market_shape_features({
        "outcome": "away",
        "consensus_probabilities": {"home": 0.50, "draw": 0.30, "away": 0.20},
        "consensus_dispersions": {"home": 0.02, "draw": 0.01, "away": 0.03},
        "execution_quote_advantage_pct": 1.25,
        "execution_book_overround": 0.04,
        "execution_selected_probability_gap": 0.02,
        "execution_nonselected_mean_absolute_gap": 0.01,
        "execution_selection_specificity": 0.01,
    })

    assert features["consensus_favorite_outcome"] == "home"
    assert features["consensus_favorite_probability"] == 0.50
    assert features["selected_vs_favorite_probability"] == -0.30
    assert features["home_away_probability_gap"] == 0.30
    assert features["consensus_max_dispersion"] == 0.03
    assert features["execution_quote_advantage_pct"] == 1.25
    assert features["execution_book_overround"] == 0.04
    assert features["execution_selection_specificity"] == 0.01


def test_odds_scaled_uncertainty_is_stricter_for_high_price_direct_clv() -> None:
    odds = pd.Series([1.5, 3.0, 5.0])
    scale = _uncertainty_scale(
        odds, "closing_edge_pct", "odds_scaled_rmse_grid"
    )
    _, lower, _ = _predicted_edges(
        pd.Series([10.0, 10.0, 10.0]), odds, pd.Series([0.5] * 3),
        rmse=4.0, margin=1.0, target_profile="closing_edge_pct",
        uncertainty_scale=scale,
    )

    assert scale.tolist()[0] == 0.75
    assert scale.tolist()[1] == 1.0
    assert scale.tolist()[2] > 1.0
    assert lower.iloc[0] > lower.iloc[1] > lower.iloc[2]


def test_odds_upscaled_uncertainty_never_relaxes_the_baseline_margin() -> None:
    scale = _uncertainty_scale(
        pd.Series([1.5, 3.0, 5.0]),
        "closing_edge_pct", "odds_upscaled_rmse_grid",
    )

    assert scale.tolist()[0] == 1.0
    assert scale.tolist()[1] == 1.0
    assert scale.tolist()[2] > 1.0

    freeze_only = _uncertainty_scale(
        pd.Series([1.5, 3.0, 5.0]),
        "closing_edge_pct", "odds_upscaled_freeze_only",
    )
    assert freeze_only.tolist() == scale.tolist()


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
