"""No-lookahead monthly walk-forward experiment for a train-only CLV ranker.

The model learns closing-line value from opening information in the prior six
months. It never uses match results as a feature or model-selection target. The
immediate next month is scored with a frozen model, all daily stakes are frozen,
and only then are closing prices and results attached for evaluation.
"""
from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import math
import sys
from collections import Counter
from dataclasses import asdict, dataclass, replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import ExtraTreesRegressor
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from scripts.robust_consensus_latest_month_holdout import (
    HistoricalMatch,
    Strategy,
    _candidate_buckets,
    _closing_price_quality,
    _monthly_bootstrap,
    _months_before,
    build_candidate_cache,
    complete_months,
    latest_complete_month,
    load_matches,
)
from scripts.portfolio_algorithm_optimization import PROJECT_ROOT


NUMERIC_FEATURES = (
    "probability",
    "conservative_probability",
    "odds",
    "raw_odds",
    "conservative_ev_pct",
    "reference_dispersion",
    "reference_bookmakers",
    "execution_cost_rate",
)
MARKET_STRUCTURE_NUMERIC_FEATURES = NUMERIC_FEATURES + (
    "implied_probability",
    "price_ratio",
    "probability_uncertainty",
    "relative_dispersion",
    "log_odds",
    "probability_squared",
    "odds_probability_interaction",
    "reference_depth_inverse",
    "raw_net_odds_gap_pct",
)
CATEGORICAL_FEATURES = (
    "outcome",
    "odds_band",
    "source_type",
    "execution_bookmaker",
    "league",
)
CATEGORICAL_FEATURES_PORTABLE = tuple(
    field for field in CATEGORICAL_FEATURES if field != "league"
)
MARKET_STRUCTURE_CATEGORICAL_FEATURES = CATEGORICAL_FEATURES_PORTABLE + (
    "outcome_odds_band",
    "outcome_source_type",
    "source_odds_band",
)
ALPHAS = (1.0, 10.0, 100.0)
SAFETY_MARGINS = (0.0, 0.25, 0.5)
MAXIMUM_ODDS_CAPS = (4.0, 5.0, 6.0, 8.0)
MINIMUM_LOWER_CLV_PCT = 1.0


@dataclass(frozen=True)
class RankerPolicy:
    daily_budget: float = 100.0
    maximum_single_stake: float = 5.0
    kelly_fraction: float = 0.10
    minimum_inner_validation_positions: int = 30
    minimum_inner_positive_clv_rate: float = 0.55
    minimum_inner_positive_month_rate: float = 0.0


@dataclass
class FittedRanker:
    model: Pipeline
    alpha: float
    safety_margin: float
    maximum_odds: float
    validation_rmse_pct: float
    validation_diagnostics: list[dict[str, Any]]
    numeric_features: tuple[str, ...]
    categorical_features: tuple[str, ...]
    estimator_profile: str = "ridge"
    target_profile: str = "closing_edge_pct"
    staking_probability_profile: str = "lower_clv"
    calibration_intercept: float = 0.0
    calibration_slope: float = 1.0
    market_calibration_intercept: float = 0.0
    market_calibration_slope: float = 1.0
    market_calibration_weight: float = 1.0
    outcome_probability_profile: str = "none"
    outcome_probability_model: Pipeline | None = None
    outcome_probability_validation_brier: float | None = None
    market_probability_validation_brier: float | None = None
    outcome_probability_weight: float = 0.0


def _feature_contract(feature_profile: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if feature_profile == "full":
        return NUMERIC_FEATURES, CATEGORICAL_FEATURES
    if feature_profile == "portable":
        return NUMERIC_FEATURES, CATEGORICAL_FEATURES_PORTABLE
    if feature_profile == "market_structure":
        return MARKET_STRUCTURE_NUMERIC_FEATURES, MARKET_STRUCTURE_CATEGORICAL_FEATURES
    raise ValueError(f"unknown feature profile: {feature_profile}")


def market_structure_features(row: dict[str, Any]) -> dict[str, Any]:
    """Derive portable nonlinear basis terms using opening information only."""
    probability = float(row["probability"])
    conservative_probability = float(row["conservative_probability"])
    odds = float(row["odds"])
    raw_odds = float(row["raw_odds"])
    dispersion = float(row["reference_dispersion"])
    depth = max(1.0, float(row["reference_bookmakers"]))
    odds_band_value = str(row["odds_band"])
    source_type = str(row["source_type"])
    outcome = str(row["outcome"])
    return {
        "implied_probability": 1.0 / odds,
        "price_ratio": odds * probability,
        "probability_uncertainty": probability - conservative_probability,
        "relative_dispersion": dispersion / max(probability, 1e-9),
        "log_odds": math.log(odds),
        "probability_squared": probability * probability,
        "odds_probability_interaction": math.log(odds) * probability,
        "reference_depth_inverse": 1.0 / depth,
        "raw_net_odds_gap_pct": (raw_odds / odds - 1.0) * 100.0,
        "outcome_odds_band": f"{outcome}:{odds_band_value}",
        "outcome_source_type": f"{outcome}:{source_type}",
        "source_odds_band": f"{source_type}:{odds_band_value}",
    }


def archived_complete_months(
    rows: list[HistoricalMatch], minimum_rows: int,
) -> list[tuple[date, date]]:
    """Treat inactive calendar edges as complete in immutable historical archives."""
    grouped: dict[tuple[int, int], list[date]] = {}
    for row in rows:
        grouped.setdefault((row.match_date.year, row.match_date.month), []).append(row.match_date)
    if not grouped:
        return []
    latest_key = max(grouped)
    windows = []
    for (year, month), dates in sorted(grouped.items()):
        last_day = calendar.monthrange(year, month)[1]
        archive_closed = (year, month) < latest_key or max(dates).day == last_day
        if len(dates) >= minimum_rows and archive_closed:
            windows.append((date(year, month, 1), date(year, month, last_day)))
    return windows


def broad_strategy(
    exchange_commission_rate: float, minimum_reference_bookmakers: int = 4,
    exchange_bookmaker_keys: tuple[str, ...] = ("BFE",),
    maximum_price_ratio: float | None = None,
) -> Strategy:
    return Strategy(
        name="RC-F-v6-clv-ridge-broad",
        minimum_price_ratio=0.97,
        minimum_conservative_ev=-0.05,
        dispersion_multiplier=1.0,
        minimum_probability=0.12,
        maximum_odds=8.0,
        minimum_reference_bookmakers=minimum_reference_bookmakers,
        uncertainty_floor=0.002,
        slippage_rate=0.02,
        exchange_commission_rate=exchange_commission_rate,
        daily_budget=100.0,
        maximum_single_stake=5.0,
        kelly_fraction=0.10,
        exchange_bookmaker_keys=exchange_bookmaker_keys,
        maximum_price_ratio=maximum_price_ratio,
    )


def _opening_rows(
    matches: list[HistoricalMatch], strategy: Strategy,
    candidate_cache: dict[tuple[str, int], dict[str, Any] | None],
    start: date, end: date, include_closing_target: bool,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for match in matches:
        if not start <= match.match_date <= end:
            continue
        key = (match.source_file, match.source_row)
        candidate = candidate_cache.get(key)
        if candidate is None:
            continue
        buckets = _candidate_buckets(candidate)
        row = {
            "candidate_id": f"{match.source_file}:{match.source_row}",
            "source_file": match.source_file,
            "source_row": match.source_row,
            "date": match.match_date.isoformat(),
            "league": match.league,
            "home_team": match.home_team,
            "away_team": match.away_team,
            "outcome": candidate["outcome"],
            "probability": float(candidate["probability"]),
            "conservative_probability": float(candidate["conservative_probability"]),
            "odds": float(candidate["odds"]),
            "raw_odds": float(candidate["raw_odds"]),
            "conservative_ev_pct": float(candidate["conservative_ev"]) * 100.0,
            "reference_dispersion": float(candidate["reference_dispersion"]),
            "reference_bookmakers": len(candidate["reference_bookmakers"]),
            "execution_cost_rate": float(candidate["execution_cost_rate"]),
            "execution_bookmaker": candidate["execution_bookmaker"],
            "odds_band": buckets[1].split(":", 1)[1],
            "source_type": buckets[2].split(":", 1)[1],
        }
        row.update(market_structure_features(row))
        if include_closing_target:
            quality = _closing_price_quality(match, candidate, strategy)
            if quality["closing_edge_pct"] is None:
                continue
            row["closing_edge_pct"] = float(quality["closing_edge_pct"])
            row["closing_probability"] = float(quality["closing_probability"])
            row["closing_probability_delta"] = (
                float(quality["closing_probability"]) - float(row["probability"])
            )
            row["actual_outcome"] = match.actual_outcome
            row["unit_profit"] = (
                float(candidate["odds"]) - 1.0
                if match.actual_outcome == candidate["outcome"] else -1.0
            )
        rows.append(row)
    return pd.DataFrame(rows)


def _pipeline(
    alpha: float, numeric_features: tuple[str, ...], categorical_features: tuple[str, ...],
    estimator_profile: str = "ridge",
) -> Pipeline:
    transform = ColumnTransformer((
        ("numeric", StandardScaler(), list(numeric_features)),
        ("categorical", OneHotEncoder(handle_unknown="ignore"), list(categorical_features)),
    ))
    if estimator_profile == "ridge":
        estimator = Ridge(alpha=alpha)
    elif estimator_profile == "extra_trees":
        estimator = ExtraTreesRegressor(
            n_estimators=120, min_samples_leaf=20, max_features=0.7,
            random_state=42, n_jobs=-1,
        )
    else:
        raise ValueError(f"unknown estimator profile: {estimator_profile}")
    return Pipeline((("features", transform), (estimator_profile, estimator)))


def _outcome_probability_pipeline(
    numeric_features: tuple[str, ...], categorical_features: tuple[str, ...],
) -> Pipeline:
    transform = ColumnTransformer((
        ("numeric", StandardScaler(), list(numeric_features)),
        ("categorical", OneHotEncoder(handle_unknown="ignore"), list(categorical_features)),
    ))
    return Pipeline((
        ("features", transform),
        ("logistic", LogisticRegression(C=0.1, solver="lbfgs", max_iter=1000)),
    ))


def _rmse(actual: pd.Series, predicted: Any) -> float:
    errors = actual.to_numpy(dtype=float) - predicted
    return math.sqrt(float((errors * errors).mean()))


def _validation_month_stability(selected: pd.DataFrame) -> tuple[int, float | None]:
    if selected.empty:
        return 0, None
    monthly_mean_clv = (
        selected.assign(_month=pd.to_datetime(selected["date"]).dt.to_period("M"))
        .groupby("_month")["closing_edge_pct"].mean()
    )
    return len(monthly_mean_clv), float((monthly_mean_clv > 0).mean())


def _logit(probability: Any) -> Any:
    clipped = pd.Series(probability, dtype=float).clip(0.001, 0.999)
    return (clipped / (1.0 - clipped)).map(math.log)


def _fit_staking_calibration(
    training: pd.DataFrame, validation: pd.DataFrame, lower_edge: Any, profile: str,
) -> tuple[float, float]:
    if profile == "lower_clv":
        return 0.0, 1.0
    if profile == "validation_platt":
        calibration_frame = validation
        raw_probability = (
            (1.0 + pd.Series(lower_edge, index=validation.index, dtype=float) / 100.0)
            / validation["odds"].astype(float)
        ).clip(0.001, 0.999)
    elif profile == "training_market_platt":
        calibration_frame = training
        raw_probability = training["probability"].astype(float).clip(0.001, 0.999)
    else:
        raise ValueError(f"unknown staking probability profile: {profile}")
    won = (calibration_frame["unit_profit"].astype(float) > 0).astype(int)
    if won.nunique() < 2:
        return 0.0, 1.0
    calibrator = LogisticRegression(C=1.0, solver="lbfgs")
    calibrator.fit(_logit(raw_probability).to_numpy().reshape(-1, 1), won)
    return float(calibrator.intercept_[0]), float(calibrator.coef_[0][0])


def _calibrate_probability(probability: float, intercept: float, slope: float) -> float:
    clipped = min(0.999, max(0.001, probability))
    value = intercept + slope * math.log(clipped / (1.0 - clipped))
    return 1.0 / (1.0 + math.exp(-value))


def _fit_market_calibration_weight(
    validation: pd.DataFrame, lower_edge: Any, intercept: float, slope: float,
    prior_strength: float = 50.0,
) -> float:
    lower_probability = (
        (1.0 + pd.Series(lower_edge, index=validation.index, dtype=float) / 100.0)
        / validation["odds"].astype(float)
    ).clip(0.001, 0.999)
    market_probability = validation["probability"].astype(float).map(
        lambda value: _calibrate_probability(value, intercept, slope)
    )
    delta = market_probability - lower_probability
    denominator = float((delta * delta).sum())
    if denominator <= 0 or validation.empty:
        return 0.0
    won = (validation["unit_profit"].astype(float) > 0).astype(float)
    raw_weight = min(
        1.0, max(0.0, float((delta * (won - lower_probability)).sum()) / denominator)
    )
    return raw_weight * len(validation) / (len(validation) + prior_strength)


def _fit_validated_market_residual_weight(
    market_probability: Any, challenger_probability: Any, won: Any,
    prior_strength: float = 50.0, minimum_brier_improvement: float = 0.001,
) -> tuple[float, float, float]:
    market = pd.Series(market_probability, dtype=float).clip(0.001, 0.999)
    challenger = pd.Series(challenger_probability, dtype=float).clip(0.001, 0.999)
    target = pd.Series(won, dtype=float)
    market_brier = float(((market - target) ** 2).mean())
    delta = challenger - market
    denominator = float((delta * delta).sum())
    if denominator <= 0 or market.empty:
        return 0.0, market_brier, market_brier
    raw_weight = min(
        1.0, max(0.0, float((delta * (target - market)).sum()) / denominator)
    )
    weight = raw_weight * len(market) / (len(market) + prior_strength)
    blended = (market + weight * delta).clip(0.001, 0.999)
    blended_brier = float(((blended - target) ** 2).mean())
    if market_brier - blended_brier < minimum_brier_improvement:
        return 0.0, market_brier, market_brier
    return weight, blended_brier, market_brier


def _predicted_edges(
    predicted: Any, odds: pd.Series, opening_probability: pd.Series,
    rmse: float, margin: float, target_profile: str,
) -> tuple[Any, Any, Any | None]:
    if target_profile == "closing_edge_pct":
        return predicted, predicted - margin * rmse, None
    if target_profile not in {"closing_probability", "closing_probability_delta"}:
        raise ValueError(f"unknown target profile: {target_profile}")
    probabilities = pd.Series(predicted, index=odds.index, dtype=float)
    if target_profile == "closing_probability_delta":
        probabilities = probabilities + opening_probability.astype(float)
    probabilities = probabilities.clip(0.001, 0.999)
    conservative = (probabilities - margin * rmse).clip(0.001, 0.999)
    predicted_edge = (probabilities * odds.astype(float) - 1.0) * 100.0
    lower_edge = (conservative * odds.astype(float) - 1.0) * 100.0
    return predicted_edge, lower_edge, probabilities


def fit_ranker(
    training: pd.DataFrame, validation_start: date, policy: RankerPolicy,
    selection_objective: str = "profit_tuned_cap", fixed_maximum_odds: float = 5.0,
    numeric_features: tuple[str, ...] = NUMERIC_FEATURES,
    categorical_features: tuple[str, ...] = CATEGORICAL_FEATURES,
    target_profile: str = "closing_edge_pct",
    uncertainty_profile: str = "rmse_grid",
    staking_probability_profile: str = "lower_clv",
    outcome_probability_profile: str = "none",
    diagnostics_sink: list[dict[str, Any]] | None = None,
    estimator_profile: str = "ridge",
) -> FittedRanker | None:
    dates = pd.to_datetime(training["date"]).dt.date
    inner_train = training.loc[dates < validation_start].copy()
    validation = training.loc[dates >= validation_start].copy()
    if len(inner_train) < 100 or len(validation) < policy.minimum_inner_validation_positions:
        return None

    diagnostics: list[dict[str, Any]] = []
    eligible: list[tuple[tuple[float, float, int, float], float, float, float, float]] = []
    odds_caps = MAXIMUM_ODDS_CAPS if selection_objective == "profit_tuned_cap" else (fixed_maximum_odds,)
    estimator_parameters = ALPHAS if estimator_profile == "ridge" else (0.0,)
    for alpha in estimator_parameters:
        model = _pipeline(
            alpha, numeric_features, categorical_features, estimator_profile
        )
        model.fit(inner_train, inner_train[target_profile])
        predicted = model.predict(validation)
        rmse = _rmse(validation[target_profile], predicted)
        if uncertainty_profile == "rmse_grid":
            margins = SAFETY_MARGINS
        elif uncertainty_profile == "residual_quantile_25":
            residual_q25 = float(
                (validation[target_profile] - predicted).quantile(0.25)
            )
            margins = (max(0.0, -residual_q25 / rmse) if rmse else 0.0,)
        else:
            raise ValueError(f"unknown uncertainty profile: {uncertainty_profile}")
        for margin in margins:
            _predicted_edge, lower, _probability = _predicted_edges(
                predicted, validation["odds"], validation["probability"],
                rmse, margin, target_profile
            )
            for maximum_odds in odds_caps:
                selected = validation.loc[
                    (lower >= MINIMUM_LOWER_CLV_PCT)
                    & (validation["odds"].to_numpy(dtype=float) <= maximum_odds)
                ]
                mean_clv = float(selected["closing_edge_pct"].mean()) if len(selected) else None
                positive_rate = float((selected["closing_edge_pct"] > 0).mean()) if len(selected) else None
                validation_months, positive_month_rate = _validation_month_stability(selected)
                flat_profit = float(selected["unit_profit"].sum()) if len(selected) else 0.0
                payoff_scale = math.sqrt(float((selected["unit_profit"] ** 2).sum())) if len(selected) else 0.0
                risk_adjusted_profit = flat_profit / payoff_scale if payoff_scale else 0.0
                clv_passed = (
                    len(selected) >= policy.minimum_inner_validation_positions
                    and mean_clv is not None and mean_clv > 0
                    and positive_rate is not None
                    and positive_rate >= policy.minimum_inner_positive_clv_rate
                    and positive_month_rate is not None
                    and positive_month_rate >= policy.minimum_inner_positive_month_rate
                )
                passed = clv_passed and (
                    selection_objective not in {"profit_tuned_cap", "profit_gated_fixed_cap"}
                    or (flat_profit > 0 and risk_adjusted_profit > 0)
                )
                diagnostics.append({
                    "alpha": alpha,
                    "estimator_profile": estimator_profile,
                    "safety_margin": margin,
                    "maximum_odds": maximum_odds,
                    "validation_candidates": len(validation),
                    "selected": len(selected),
                    "target_profile": target_profile,
                    "uncertainty_profile": uncertainty_profile,
                    "rmse": round(rmse, 6),
                    "average_closing_edge_pct": round(mean_clv, 4) if mean_clv is not None else None,
                    "positive_clv_rate": round(positive_rate, 4) if positive_rate is not None else None,
                    "validation_months": validation_months,
                    "positive_month_rate": (
                        round(positive_month_rate, 4) if positive_month_rate is not None else None
                    ),
                    "flat_unit_profit": round(flat_profit, 4),
                    "risk_adjusted_profit": round(risk_adjusted_profit, 4),
                    "eligible": passed,
                })
                if passed:
                    clv_score = float(mean_clv) * math.sqrt(len(selected))
                    score = (
                        (risk_adjusted_profit, clv_score, len(selected), -rmse)
                        if selection_objective in {"profit_tuned_cap", "profit_gated_fixed_cap"}
                        else (clv_score, float(mean_clv), len(selected), -rmse)
                    )
                    eligible.append((
                        score,
                        alpha, margin, maximum_odds, rmse,
                    ))
    if diagnostics_sink is not None:
        diagnostics_sink.extend(diagnostics)
    if not eligible:
        return None

    _score, alpha, margin, maximum_odds, validation_rmse = max(eligible, key=lambda row: row[0])
    final_model = _pipeline(
        alpha, numeric_features, categorical_features, estimator_profile
    )
    final_model.fit(training, training[target_profile])
    calibration_model = _pipeline(
        alpha, numeric_features, categorical_features, estimator_profile
    )
    calibration_model.fit(inner_train, inner_train[target_profile])
    calibration_prediction = calibration_model.predict(validation)
    _edge, calibration_lower, _probability = _predicted_edges(
        calibration_prediction, validation["odds"], validation["probability"],
        validation_rmse, margin, target_profile,
    )
    calibration_intercept, calibration_slope = _fit_staking_calibration(
        training, validation, calibration_lower, staking_probability_profile
    )
    inner_market_intercept, inner_market_slope = _fit_staking_calibration(
        inner_train, validation, calibration_lower, "training_market_platt"
    )
    market_calibration_weight = _fit_market_calibration_weight(
        validation, calibration_lower, inner_market_intercept, inner_market_slope
    )
    market_calibration_intercept, market_calibration_slope = _fit_staking_calibration(
        training, validation, calibration_lower, "training_market_platt"
    )
    outcome_probability_model = None
    outcome_probability_validation_brier = None
    market_probability_validation_brier = None
    outcome_probability_weight = 0.0
    if outcome_probability_profile in {
        "training_market_logistic", "validated_market_residual_blend",
    }:
        inner_won = (inner_train["unit_profit"].astype(float) > 0).astype(int)
        validation_won = (validation["unit_profit"].astype(float) > 0).astype(int)
        if inner_won.nunique() < 2:
            return None
        validation_model = _outcome_probability_pipeline(
            numeric_features, categorical_features
        )
        validation_model.fit(inner_train, inner_won)
        validation_probability = validation_model.predict_proba(validation)[:, 1]
        if outcome_probability_profile == "validated_market_residual_blend":
            (
                outcome_probability_weight,
                outcome_probability_validation_brier,
                market_probability_validation_brier,
            ) = _fit_validated_market_residual_weight(
                validation["probability"], validation_probability, validation_won
            )
        else:
            outcome_probability_validation_brier = float(
                ((validation_probability - validation_won.to_numpy(dtype=float)) ** 2).mean()
            )
            market_probability_validation_brier = float(
                ((validation["probability"].to_numpy(dtype=float)
                  - validation_won.to_numpy(dtype=float)) ** 2).mean()
            )
        training_won = (training["unit_profit"].astype(float) > 0).astype(int)
        outcome_probability_model = _outcome_probability_pipeline(
            numeric_features, categorical_features
        )
        outcome_probability_model.fit(training, training_won)
    elif outcome_probability_profile != "none":
        raise ValueError(
            f"unknown outcome probability profile: {outcome_probability_profile}"
        )
    return FittedRanker(
        final_model, alpha, margin, maximum_odds, validation_rmse, diagnostics,
        numeric_features, categorical_features, estimator_profile, target_profile,
        staking_probability_profile, calibration_intercept, calibration_slope,
        market_calibration_intercept, market_calibration_slope,
        market_calibration_weight,
        outcome_probability_profile, outcome_probability_model,
        outcome_probability_validation_brier, market_probability_validation_brier,
        outcome_probability_weight,
    )


def freeze_decisions(
    opening_candidates: pd.DataFrame, fitted: FittedRanker, policy: RankerPolicy,
) -> list[dict[str, Any]]:
    if opening_candidates.empty:
        return []
    frame = opening_candidates.copy()
    raw_prediction = fitted.model.predict(frame)
    predicted_edge, lower_edge, predicted_probability = _predicted_edges(
        raw_prediction, frame["odds"], frame["probability"], fitted.validation_rmse_pct,
        fitted.safety_margin, fitted.target_profile,
    )
    frame["predicted_closing_edge_pct"] = predicted_edge
    frame["lower_closing_edge_pct"] = lower_edge
    if predicted_probability is not None:
        frame["predicted_closing_probability"] = predicted_probability
    frame = frame.loc[
        (frame["lower_closing_edge_pct"] >= MINIMUM_LOWER_CLV_PCT)
        & (frame["odds"] <= fitted.maximum_odds)
    ].copy()
    frame.sort_values(
        ["date", "lower_closing_edge_pct", "candidate_id"],
        ascending=[True, False, True], inplace=True,
    )

    frozen: list[dict[str, Any]] = []
    for match_date, daily in frame.groupby("date", sort=True):
        remaining = policy.daily_budget
        for row in daily.to_dict("records"):
            odds = float(row["odds"])
            lower_edge = float(row["lower_closing_edge_pct"]) / 100.0
            probability = min(0.99, (1.0 + lower_edge) / odds)
            lower_clv_probability = probability
            if fitted.staking_probability_profile == "validation_platt":
                probability = _calibrate_probability(
                    probability, fitted.calibration_intercept, fitted.calibration_slope
                )
            elif fitted.staking_probability_profile == "training_market_platt":
                probability = _calibrate_probability(
                    float(row["probability"]), fitted.calibration_intercept,
                    fitted.calibration_slope,
                )
            full_kelly = max(0.0, (probability * odds - 1.0) / max(odds - 1.0, 1e-9))
            stake = round(min(
                policy.maximum_single_stake,
                remaining,
                policy.daily_budget * policy.kelly_fraction * full_kelly,
            ), 2)
            if stake < 0.10:
                continue
            unshrunk_market_probability = _calibrate_probability(
                float(row["probability"]), fitted.market_calibration_intercept,
                fitted.market_calibration_slope,
            )
            market_logistic_probability = None
            validated_market_residual_probability = None
            if fitted.outcome_probability_model is not None:
                market_logistic_probability = float(
                    fitted.outcome_probability_model.predict_proba(
                        pd.DataFrame([row])
                    )[0, 1]
                )
                validated_market_residual_probability = min(0.999, max(
                    0.001,
                    float(row["probability"]) + fitted.outcome_probability_weight
                    * (market_logistic_probability - float(row["probability"])),
                ))
            remaining = round(remaining - stake, 2)
            frozen.append({
                **row,
                "stake": stake,
                "estimated_probability_from_lower_clv": probability,
                "estimated_probability_from_unshrunk_training_market": (
                    unshrunk_market_probability
                ),
                "estimated_probability_from_training_market": (
                    unshrunk_market_probability * fitted.market_calibration_weight
                )
                + lower_clv_probability * (1.0 - fitted.market_calibration_weight),
                "market_calibration_weight": fitted.market_calibration_weight,
                "estimated_probability_from_training_market_logistic": (
                    market_logistic_probability
                ),
                "estimated_probability_from_validated_market_residual": (
                    validated_market_residual_probability
                ),
                "outcome_probability_weight": fitted.outcome_probability_weight,
                "staking_probability_profile": fitted.staking_probability_profile,
                "decision_frozen_before_closing_and_result": True,
            })
    return frozen


def settle_frozen_decisions(
    frozen: list[dict[str, Any]], matches_by_id: dict[str, HistoricalMatch], strategy: Strategy,
) -> list[dict[str, Any]]:
    settled: list[dict[str, Any]] = []
    for decision in frozen:
        match = matches_by_id[decision["candidate_id"]]
        candidate = {
            "outcome": decision["outcome"],
            "odds": decision["odds"],
        }
        quality = _closing_price_quality(match, candidate, strategy)
        won = match.actual_outcome == decision["outcome"]
        stake, odds = float(decision["stake"]), float(decision["odds"])
        profit = round(stake * (odds - 1.0) if won else -stake, 2)
        settled.append({
            **decision,
            **quality,
            "actual_outcome": match.actual_outcome,
            "won": won,
            "profit": profit,
        })
    return settled


def _daily_ledger(start: date, end: date, positions: list[dict[str, Any]], budget: float) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in positions:
        grouped.setdefault(str(row["date"]), []).append(row)
    ledger = []
    cumulative = peak = 0.0
    current = start
    while current <= end:
        rows = grouped.get(current.isoformat(), [])
        staked = round(sum(float(row["stake"]) for row in rows), 2)
        profit = round(sum(float(row["profit"]) for row in rows), 2)
        cumulative = round(cumulative + profit, 2)
        peak = max(peak, cumulative)
        ledger.append({
            "date": current.isoformat(), "bets": len(rows), "staked": staked,
            "profit": profit, "cumulative_profit": cumulative,
            "drawdown": round(peak - cumulative, 2),
            "cash_reserved": round(budget - staked, 2),
        })
        current += timedelta(days=1)
    return ledger


def rolling_v6(
    output_dir: Path, fold_count: int = 18, exchange_commission_rate: float = 0.025,
    minimum_month_rows: int = 300, matches: list[HistoricalMatch] | None = None,
    selection_objective: str = "profit_tuned_cap", fixed_maximum_odds: float = 5.0,
    feature_profile: str = "full",
    training_months: int = 6, validation_months: int = 2,
    prediction_profile: str = "aligned",
    target_profile: str = "closing_edge_pct",
    uncertainty_profile: str = "rmse_grid",
    month_completeness_profile: str = "calendar_boundary",
    include_latest_month: bool = False,
    minimum_reference_bookmakers: int = 4,
    minimum_inner_positive_month_rate: float = 0.0,
    staking_probability_profile: str = "lower_clv",
    outcome_probability_profile: str = "none",
    exchange_bookmaker_keys: tuple[str, ...] = ("BFE",),
    maximum_price_ratio: float | None = None,
    estimator_profile: str = "ridge",
) -> dict[str, Any]:
    rows = matches if matches is not None else load_matches()
    if month_completeness_profile == "calendar_boundary":
        windows = complete_months(rows, minimum_month_rows)
    elif month_completeness_profile == "archived_count":
        windows = archived_complete_months(rows, minimum_month_rows)
    else:
        raise ValueError(f"unknown month completeness profile: {month_completeness_profile}")
    if not windows:
        raise ValueError("no complete historical months satisfy the configured profile")
    latest_start, _latest_end = windows[-1]
    eligible_windows = windows if include_latest_month else [
        window for window in windows if window[0] < latest_start
    ]
    folds = eligible_windows[-max(1, fold_count):]
    strategy = broad_strategy(
        exchange_commission_rate, minimum_reference_bookmakers, exchange_bookmaker_keys,
        maximum_price_ratio,
    )
    policy = RankerPolicy(
        minimum_inner_positive_month_rate=minimum_inner_positive_month_rate
    )
    numeric_features, categorical_features = _feature_contract(feature_profile)
    cache = build_candidate_cache(rows, strategy)
    matches_by_id = {f"{row.source_file}:{row.source_row}": row for row in rows}
    monthly: list[dict[str, Any]] = []
    all_positions: list[dict[str, Any]] = []
    all_daily: list[dict[str, Any]] = []

    for test_start, test_end in folds:
        train_start = _months_before(test_start, training_months)
        train_end = test_start - timedelta(days=1)
        validation_start = _months_before(test_start, validation_months)
        training = _opening_rows(rows, strategy, cache, train_start, train_end, True)
        fitted = fit_ranker(
            training, validation_start, policy, selection_objective, fixed_maximum_odds,
            numeric_features, categorical_features, target_profile, uncertainty_profile,
            staking_probability_profile, outcome_probability_profile,
            estimator_profile=estimator_profile,
        )
        if fitted is None:
            monthly.append({
                "month": test_start.strftime("%Y-%m"),
                "train_window": f"{train_start}..{train_end}",
                "status": "ABSTAIN_INNER_VALIDATION", "training_candidates": len(training),
                "bets": 0, "active_days": 0, "staked": 0.0, "profit": 0.0,
                "roi_pct": 0.0, "available_capacity": (test_end - test_start).days * 100.0 + 100.0,
            })
            continue

        # The test-month frame deliberately has no closing target or result column.
        opening_test = _opening_rows(rows, strategy, cache, test_start, test_end, False)
        if prediction_profile == "unknown_league" and "league" in opening_test:
            opening_test["league"] = "__UNKNOWN_LIVE_LEAGUE__"
        frozen = freeze_decisions(opening_test, fitted, policy)
        settled = settle_frozen_decisions(frozen, matches_by_id, strategy)
        ledger = _daily_ledger(test_start, test_end, settled, policy.daily_budget)
        all_positions.extend({"test_month": test_start.strftime("%Y-%m"), **row} for row in settled)
        all_daily.extend({"test_month": test_start.strftime("%Y-%m"), **row} for row in ledger)
        staked = round(sum(float(row["stake"]) for row in settled), 2)
        profit = round(sum(float(row["profit"]) for row in settled), 2)
        clv = [float(row["closing_edge_pct"]) for row in settled if row["closing_edge_pct"] is not None]
        monthly.append({
            "month": test_start.strftime("%Y-%m"),
            "train_window": f"{train_start}..{train_end}", "status": "FROZEN_MODEL_EVALUATED",
            "training_candidates": len(training), "test_candidates": len(opening_test),
            "alpha": fitted.alpha, "safety_margin": fitted.safety_margin,
            "estimator_profile": fitted.estimator_profile,
            "maximum_odds": fitted.maximum_odds,
            "validation_rmse_pct": round(fitted.validation_rmse_pct, 4),
            "outcome_probability_validation_brier": (
                round(fitted.outcome_probability_validation_brier, 6)
                if fitted.outcome_probability_validation_brier is not None else None
            ),
            "market_probability_validation_brier": (
                round(fitted.market_probability_validation_brier, 6)
                if fitted.market_probability_validation_brier is not None else None
            ),
            "outcome_probability_weight": round(fitted.outcome_probability_weight, 6),
            "inner_validation": fitted.validation_diagnostics,
            "bets": len(settled), "active_days": sum(row["bets"] > 0 for row in ledger),
            "staked": staked, "profit": profit,
            "roi_pct": round(profit / staked * 100.0, 2) if staked else 0.0,
            "average_closing_edge_pct": round(sum(clv) / len(clv), 4) if clv else None,
            "positive_clv_rate": round(sum(value > 0 for value in clv) / len(clv), 4) if clv else None,
            "outcome_counts": dict(Counter(row["outcome"] for row in settled)),
            "available_capacity": len(ledger) * policy.daily_budget,
        })

    staked = round(sum(float(row["staked"]) for row in monthly), 2)
    profit = round(sum(float(row["profit"]) for row in monthly), 2)
    capacity = round(sum(float(row["available_capacity"]) for row in monthly), 2)
    active = [row for row in monthly if int(row["bets"]) > 0]
    outcomes = Counter(str(row["outcome"]) for row in all_positions)
    concentration = max(outcomes.values(), default=0) / len(all_positions) if all_positions else 0.0
    clv = [float(row["closing_edge_pct"]) for row in all_positions if row["closing_edge_pct"] is not None]
    average_clv = sum(clv) / len(clv) if clv else None
    positive_clv = sum(value > 0 for value in clv) / len(clv) if clv else None
    bootstrap = _monthly_bootstrap(monthly)
    utilization = staked / capacity * 100.0 if capacity else 0.0
    active_days = sum(int(row.get("active_days") or 0) for row in monthly)
    active_capacity = active_days * policy.daily_budget
    active_day_utilization = staked / active_capacity * 100.0 if active_capacity else 0.0
    probability_validation = [
        row for row in monthly
        if row.get("outcome_probability_validation_brier") is not None
    ]
    probability_validation_summary = {
        "folds": len(probability_validation),
        "outcome_model_mean_brier": (
            round(sum(float(row["outcome_probability_validation_brier"])
                      for row in probability_validation) / len(probability_validation), 6)
            if probability_validation else None
        ),
        "market_mean_brier": (
            round(sum(float(row["market_probability_validation_brier"])
                      for row in probability_validation) / len(probability_validation), 6)
            if probability_validation else None
        ),
        "mean_residual_weight": (
            round(sum(float(row.get("outcome_probability_weight") or 0.0)
                      for row in probability_validation) / len(probability_validation), 6)
            if probability_validation else None
        ),
        "nonzero_weight_folds": sum(
            float(row.get("outcome_probability_weight") or 0.0) > 0
            for row in probability_validation
        ),
    }
    reasons = []
    warnings = []
    if len(monthly) < 12: reasons.append("monthly_folds<12")
    if len(active) < 8: reasons.append("active_months<8")
    if len(all_positions) < 100: reasons.append("bets<100")
    if active and sum(float(row["profit"]) > 0 for row in active) / len(active) < 0.60:
        reasons.append("positive_active_month_rate<60pct")
    if profit <= 0: reasons.append("aggregate_profit<=0")
    if bootstrap["lower_95_pct"] is None or float(bootstrap["lower_95_pct"]) <= 0:
        reasons.append("monthly_bootstrap_roi_lower_95<=0")
    if average_clv is None or average_clv <= 0: reasons.append("average_closing_edge<=0")
    if positive_clv is None or positive_clv < 0.55: reasons.append("positive_clv_rate<55pct")
    if concentration > 0.75: reasons.append("selected_outcome_concentration>75pct")
    if utilization < 0.50: warnings.append("calendar_capacity_utilization<0.5pct")
    if active_day_utilization < 0.50: warnings.append("active_day_capacity_utilization<0.5pct")

    payload = {
        "method": (
            f"{estimator_profile} CLV ranker; trailing train window, trailing inner "
            "validation, immediate next month evaluate"
        ),
        "estimator_profile": estimator_profile,
        "training_months": training_months,
        "validation_months": validation_months,
        "prediction_profile": prediction_profile,
        "target_profile": target_profile,
        "uncertainty_profile": uncertainty_profile,
        "staking_probability_profile": staking_probability_profile,
        "outcome_probability_profile": outcome_probability_profile,
        "outcome_probability_validation": probability_validation_summary,
        "month_completeness_profile": month_completeness_profile,
        "feature_contract": {
            "profile": feature_profile,
            "numeric": list(numeric_features), "categorical": list(categorical_features),
            "ridge_model_forbidden": ["actual_outcome", "unit_profit", "won", "profit"],
            "test_decision_frame_forbidden": [
                "actual_outcome", "unit_profit", "closing_edge_pct", "closing_probability",
                "closing_probability_delta",
            ],
        },
        "strategy": asdict(strategy), "policy": asdict(policy),
        "selection_objective": selection_objective,
        "fixed_maximum_odds": (
            fixed_maximum_odds if selection_objective != "profit_tuned_cap" else None
        ),
        "exchange_commission_rate": exchange_commission_rate,
        "exchange_bookmaker_keys": list(exchange_bookmaker_keys),
        "maximum_price_ratio": maximum_price_ratio,
        "latest_sealed_month_excluded": (
            None if include_latest_month else latest_start.strftime("%Y-%m")
        ),
        "latest_archived_month_included": (
            latest_start.strftime("%Y-%m") if include_latest_month else None
        ),
        "folds": len(monthly), "active_months": len(active),
        "positive_active_months": sum(float(row["profit"]) > 0 for row in active),
        "bets": len(all_positions), "staked": staked, "profit": profit,
        "roi_pct": round(profit / staked * 100.0, 2) if staked else 0.0,
        "available_capacity": capacity, "capital_utilization_pct": round(utilization, 4),
        "active_days": active_days, "active_day_capacity": active_capacity,
        "active_day_capital_utilization_pct": round(active_day_utilization, 4),
        "outcome_counts": dict(outcomes),
        "maximum_outcome_concentration_pct": round(concentration * 100.0, 2),
        "average_closing_edge_pct": round(average_clv, 4) if average_clv is not None else None,
        "positive_clv_rate": round(positive_clv, 4) if positive_clv is not None else None,
        "monthly_bootstrap_roi": bootstrap,
        "decision": "ROLLING_RESEARCH_SURVIVOR" if not reasons else "ROLLING_REJECTED",
        "decision_reasons": reasons, "warnings": warnings,
        "research_stage": "POST_HOC_EXPLORATORY",
        "live_promotion_allowed": False,
        "live_promotion_blocker": "The algorithm was developed after inspecting these historical folds; prospective T-1 confirmation is required.",
        "monthly": monthly,
        "guardrail": "Exploratory historical evidence only. No live order or automatic promotion is possible.",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(monthly).drop(columns=["inner_validation"], errors="ignore").to_csv(
        output_dir / "monthly.csv", index=False, encoding="utf-8-sig"
    )
    pd.DataFrame(all_daily).to_csv(output_dir / "daily.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(all_positions).to_csv(output_dir / "positions.csv", index=False, encoding="utf-8-sig")
    return payload


def sealed_latest_month_v6(
    output_dir: Path, exchange_commission_rate: float = 0.025,
    minimum_month_rows: int = 300, matches: list[HistoricalMatch] | None = None,
    fixed_maximum_odds: float = 5.0, feature_profile: str = "market_structure",
    training_months: int = 6, validation_months: int = 2,
) -> dict[str, Any]:
    """Evaluate the latest complete month once, after freezing all test decisions."""
    rows = matches if matches is not None else load_matches()
    test_start, test_end = latest_complete_month(rows, minimum_month_rows)
    train_start = _months_before(test_start, training_months)
    train_end = test_start - timedelta(days=1)
    validation_start = _months_before(test_start, validation_months)
    strategy = broad_strategy(exchange_commission_rate)
    policy = RankerPolicy()
    numeric_features, categorical_features = _feature_contract(feature_profile)
    cache = build_candidate_cache(rows, strategy)
    training = _opening_rows(rows, strategy, cache, train_start, train_end, True)
    fitted = fit_ranker(
        training, validation_start, policy, "clv_fixed_cap", fixed_maximum_odds,
        numeric_features, categorical_features,
    )
    opening_test = _opening_rows(rows, strategy, cache, test_start, test_end, False)
    forbidden_present = sorted(
        {
            "actual_outcome", "unit_profit", "closing_edge_pct", "closing_probability",
            "closing_probability_delta", "won", "profit",
        }
        & set(opening_test.columns)
    )
    if forbidden_present:
        raise ValueError(f"sealed test decision frame contains future fields: {forbidden_present}")

    frozen = freeze_decisions(opening_test, fitted, policy) if fitted is not None else []
    frozen_signature = hashlib.sha256(json.dumps([
        {
            "candidate_id": row["candidate_id"], "date": row["date"],
            "outcome": row["outcome"], "odds": row["odds"], "stake": row["stake"],
            "predicted_closing_edge_pct": row["predicted_closing_edge_pct"],
            "lower_closing_edge_pct": row["lower_closing_edge_pct"],
        }
        for row in frozen
    ], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    matches_by_id = {f"{row.source_file}:{row.source_row}": row for row in rows}
    settled = settle_frozen_decisions(frozen, matches_by_id, strategy)
    ledger = _daily_ledger(test_start, test_end, settled, policy.daily_budget)
    staked = round(sum(float(row["stake"]) for row in settled), 2)
    profit = round(sum(float(row["profit"]) for row in settled), 2)
    clv = [float(row["closing_edge_pct"]) for row in settled if row["closing_edge_pct"] is not None]
    payload = {
        "method": "single sealed latest-complete-calendar-month holdout",
        "research_stage": "SEALED_HOLDOUT_EVALUATED",
        "feature_profile": feature_profile,
        "exchange_commission_rate": exchange_commission_rate,
        "period_start": test_start.isoformat(), "period_end": test_end.isoformat(),
        "training_window": f"{train_start}..{train_end}",
        "inner_validation_start": validation_start.isoformat(),
        "inner_gate_passed": fitted is not None,
        "training_candidates": len(training), "test_candidates": len(opening_test),
        "bets": len(settled), "active_days": sum(row["bets"] > 0 for row in ledger),
        "daily_budget_limit": policy.daily_budget,
        "maximum_daily_stake": max((float(row["staked"]) for row in ledger), default=0.0),
        "staked": staked, "profit": profit,
        "roi_pct": round(profit / staked * 100.0, 2) if staked else 0.0,
        "ending_equity_change": profit,
        "maximum_drawdown": max((float(row["drawdown"]) for row in ledger), default=0.0),
        "average_closing_edge_pct": round(sum(clv) / len(clv), 4) if clv else None,
        "positive_clv_rate": round(sum(value > 0 for value in clv) / len(clv), 4) if clv else None,
        "outcome_counts": dict(Counter(row["outcome"] for row in settled)),
        "frozen_decision_sha256": frozen_signature,
        "anti_leakage": {
            "test_decision_frame_forbidden_fields": [
                "actual_outcome", "unit_profit", "closing_edge_pct", "won", "profit"
            ],
            "forbidden_fields_present": forbidden_present,
            "decisions_and_stakes_frozen_before_settlement": True,
            "test_month_used_for_model_or_policy_selection": False,
        },
        "daily": ledger,
        "guardrail": "Historical sealed holdout only; this result cannot authorize real orders.",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    pd.DataFrame(ledger).to_csv(output_dir / "daily.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(settled).to_csv(output_dir / "positions.csv", index=False, encoding="utf-8-sig")
    return payload


def export_live_ranker(
    output_path: Path, exchange_commission_rate: float = 0.05,
    fixed_maximum_odds: float = 5.0, matches: list[HistoricalMatch] | None = None,
    training_end: date | None = None,
    feature_profile: str = "full",
    training_months: int = 6, validation_months: int = 2,
    target_profile: str = "closing_edge_pct",
    uncertainty_profile: str = "rmse_grid",
    model_version: str | None = None,
    minimum_reference_bookmakers: int = 4,
    minimum_inner_positive_month_rate: float = 0.0,
    staking_probability_profile: str = "lower_clv",
    outcome_probability_profile: str = "none",
    exchange_bookmaker_keys: tuple[str, ...] = ("BFE",),
    maximum_price_ratio: float | None = None,
) -> dict[str, Any]:
    if outcome_probability_profile != "none":
        raise ValueError(
            "research outcome probability profiles cannot be exported before promotion"
        )
    numeric_features, categorical_features = _feature_contract(feature_profile)
    rows = matches if matches is not None else load_matches()
    strategy = broad_strategy(
        exchange_commission_rate, minimum_reference_bookmakers,
        exchange_bookmaker_keys, maximum_price_ratio,
    )
    cache = build_candidate_cache(rows, strategy)
    training_end = training_end or max(row.match_date for row in rows)
    next_month = training_end.replace(day=1) + timedelta(days=32)
    training_start = _months_before(next_month, training_months)
    validation_start = _months_before(next_month, validation_months)
    training = _opening_rows(rows, strategy, cache, training_start, training_end, True)
    policy = RankerPolicy(
        minimum_inner_positive_month_rate=minimum_inner_positive_month_rate
    )
    fitted = fit_ranker(
        training, validation_start, policy, "clv_fixed_cap", fixed_maximum_odds,
        numeric_features, categorical_features, target_profile, uncertainty_profile,
        staking_probability_profile, outcome_probability_profile,
    )
    if fitted is None:
        raise ValueError("latest six-month window did not pass the frozen inner CLV gate")

    transform = fitted.model.named_steps["features"]
    ridge = fitted.model.named_steps["ridge"]
    scaler = transform.named_transformers_["numeric"]
    encoder = transform.named_transformers_["categorical"]
    coefficients = ridge.coef_.tolist()
    numeric_count = len(fitted.numeric_features)
    numeric_scaled = coefficients[:numeric_count]
    numeric_coefficients = {
        name: float(coefficient) / float(scale)
        for name, coefficient, scale in zip(fitted.numeric_features, numeric_scaled, scaler.scale_)
    }
    intercept = float(ridge.intercept_) - sum(
        float(coefficient) * float(mean) / float(scale)
        for coefficient, mean, scale in zip(numeric_scaled, scaler.mean_, scaler.scale_)
    )
    categorical_coefficients: dict[str, dict[str, float]] = {}
    offset = numeric_count
    for field, categories in zip(fitted.categorical_features, encoder.categories_):
        values = coefficients[offset:offset + len(categories)]
        categorical_coefficients[field] = {
            str(category): float(coefficient) for category, coefficient in zip(categories, values)
        }
        offset += len(categories)

    parity_sample = training.head(200)
    pipeline_scores = fitted.model.predict(parity_sample)
    json_scores = []
    for row in parity_sample.to_dict("records"):
        score = intercept + sum(
            numeric_coefficients[field] * float(row[field]) for field in fitted.numeric_features
        )
        score += sum(
            categorical_coefficients[field].get(str(row[field]), 0.0)
            for field in fitted.categorical_features
        )
        json_scores.append(score)
    parity_error = max(
        (abs(float(expected) - actual) for expected, actual in zip(pipeline_scores, json_scores)),
        default=0.0,
    )
    if parity_error > 1e-8:
        raise ValueError(f"JSON model export parity failed: {parity_error}")

    default_model_version = (
        "clv-ridge-v7.1-probability-movement-fixed-cap5-prospective-shadow"
        if target_profile == "closing_probability_delta" else {
            "full": "clv-ridge-v6.2-fixed-cap5-prospective-shadow",
            "portable": "clv-ridge-v6.4-portable-fixed-cap5-prospective-shadow",
            "market_structure": "clv-ridge-v6.6-market-structure-fixed-cap5-prospective-shadow",
        }[feature_profile]
    )
    payload = {
        "model_version": model_version or default_model_version,
        "created_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "training_window": f"{training_start}..{training_end}",
        "training_months": training_months,
        "validation_months": validation_months,
        "training_candidates": len(training),
        "training_result_used_as_feature": False,
        "target": target_profile,
        "uncertainty_profile": uncertainty_profile,
        "alpha": fitted.alpha,
        "safety_margin": fitted.safety_margin,
        "validation_rmse_pct": fitted.validation_rmse_pct,
        "minimum_lower_clv_pct": MINIMUM_LOWER_CLV_PCT,
        "minimum_reference_bookmakers": minimum_reference_bookmakers,
        "minimum_inner_positive_month_rate": minimum_inner_positive_month_rate,
        "staking_probability_profile": staking_probability_profile,
        "outcome_probability_profile": outcome_probability_profile,
        "calibration_intercept": fitted.calibration_intercept,
        "calibration_slope": fitted.calibration_slope,
        "market_calibration_intercept": fitted.market_calibration_intercept,
        "market_calibration_slope": fitted.market_calibration_slope,
        "market_calibration_weight": fitted.market_calibration_weight,
        "maximum_odds": fitted.maximum_odds,
        "exchange_commission_rate": exchange_commission_rate,
        "exchange_bookmaker_keys": list(exchange_bookmaker_keys),
        "maximum_price_ratio": maximum_price_ratio,
        "slippage_rate": strategy.slippage_rate,
        "intercept": intercept,
        "numeric_features": list(fitted.numeric_features),
        "feature_profile": feature_profile,
        "categorical_features": list(fitted.categorical_features),
        "numeric_coefficients": numeric_coefficients,
        "categorical_coefficients": categorical_coefficients,
        "unknown_category_policy": "zero_coefficient",
        "export_parity_sample": len(parity_sample),
        "export_parity_max_abs_error": parity_error,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    payload["model_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "reports" / "clv_ridge_walk_forward_v6")
    parser.add_argument("--fold-count", type=int, default=18)
    parser.add_argument("--minimum-month-rows", type=int, default=300)
    parser.add_argument("--minimum-reference-bookmakers", type=int, default=4)
    parser.add_argument("--minimum-inner-positive-month-rate", type=float, default=0.0)
    parser.add_argument(
        "--staking-probability-profile",
        choices=("lower_clv", "validation_platt", "training_market_platt"),
        default="lower_clv",
    )
    parser.add_argument(
        "--outcome-probability-profile",
        choices=(
            "none", "training_market_logistic", "validated_market_residual_blend",
        ),
        default="none",
    )
    parser.add_argument(
        "--month-completeness-profile",
        choices=("calendar_boundary", "archived_count"), default="calendar_boundary",
    )
    parser.add_argument("--exchange-commission-rate", type=float, default=0.025)
    parser.add_argument(
        "--exchange-bookmaker-keys", default="BFE",
        help="Comma-separated bookmaker prefixes charged exchange commission (default: BFE).",
    )
    parser.add_argument(
        "--maximum-price-ratio", type=float,
        help="Reject execution quotes above this multiple of leave-one-out consensus fair value.",
    )
    parser.add_argument(
        "--selection-objective",
        choices=("profit_tuned_cap", "clv_fixed_cap", "profit_gated_fixed_cap"),
        default="profit_tuned_cap",
    )
    parser.add_argument("--fixed-maximum-odds", type=float, default=5.0)
    parser.add_argument("--export-live-model", type=Path)
    parser.add_argument("--model-version")
    parser.add_argument("--sealed-latest-month", action="store_true")
    parser.add_argument("--include-latest-month", action="store_true")
    parser.add_argument("--model-training-end", type=date.fromisoformat)
    parser.add_argument(
        "--feature-profile", choices=("full", "portable", "market_structure"), default="full"
    )
    parser.add_argument("--training-months", type=int, default=6)
    parser.add_argument("--validation-months", type=int, default=2)
    parser.add_argument(
        "--prediction-profile", choices=("aligned", "unknown_league"), default="aligned"
    )
    parser.add_argument(
        "--target-profile",
        choices=("closing_edge_pct", "closing_probability", "closing_probability_delta"),
        default="closing_edge_pct",
    )
    parser.add_argument(
        "--uncertainty-profile", choices=("rmse_grid", "residual_quantile_25"),
        default="rmse_grid",
    )
    parser.add_argument(
        "--estimator-profile", choices=("ridge", "extra_trees"), default="ridge",
    )
    args = parser.parse_args()
    exchange_bookmaker_keys = tuple(
        key.strip().upper() for key in args.exchange_bookmaker_keys.split(",") if key.strip()
    )
    if not exchange_bookmaker_keys:
        parser.error("--exchange-bookmaker-keys must contain at least one bookmaker prefix")
    if args.estimator_profile != "ridge" and (
        args.export_live_model or args.sealed_latest_month
    ):
        parser.error(
            "extra_trees is research-only and cannot be exported or used for sealed live scoring"
        )
    report = (
        sealed_latest_month_v6(
            args.output_dir, args.exchange_commission_rate,
            fixed_maximum_odds=args.fixed_maximum_odds,
            feature_profile=args.feature_profile,
            training_months=args.training_months, validation_months=args.validation_months,
        ) if args.sealed_latest_month else
        export_live_ranker(
            args.export_live_model, args.exchange_commission_rate, args.fixed_maximum_odds,
            training_end=args.model_training_end, feature_profile=args.feature_profile,
            training_months=args.training_months, validation_months=args.validation_months,
            target_profile=args.target_profile, uncertainty_profile=args.uncertainty_profile,
            model_version=args.model_version,
            minimum_reference_bookmakers=args.minimum_reference_bookmakers,
            minimum_inner_positive_month_rate=args.minimum_inner_positive_month_rate,
            staking_probability_profile=args.staking_probability_profile,
            outcome_probability_profile=args.outcome_probability_profile,
            exchange_bookmaker_keys=exchange_bookmaker_keys,
            maximum_price_ratio=args.maximum_price_ratio,
        ) if args.export_live_model else
        rolling_v6(
            args.output_dir, args.fold_count, args.exchange_commission_rate,
            minimum_month_rows=args.minimum_month_rows,
            selection_objective=args.selection_objective,
            fixed_maximum_odds=args.fixed_maximum_odds,
            feature_profile=args.feature_profile,
            training_months=args.training_months,
            validation_months=args.validation_months,
            prediction_profile=args.prediction_profile,
            target_profile=args.target_profile,
            uncertainty_profile=args.uncertainty_profile,
            month_completeness_profile=args.month_completeness_profile,
            include_latest_month=args.include_latest_month,
            minimum_reference_bookmakers=args.minimum_reference_bookmakers,
            minimum_inner_positive_month_rate=args.minimum_inner_positive_month_rate,
            staking_probability_profile=args.staking_probability_profile,
            outcome_probability_profile=args.outcome_probability_profile,
            exchange_bookmaker_keys=exchange_bookmaker_keys,
            maximum_price_ratio=args.maximum_price_ratio,
            estimator_profile=args.estimator_profile,
        )
    )
    print(json.dumps({key: value for key, value in report.items() if key != "monthly"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
