"""Export an immutable JSON positive-CLV classifier for prospective scoring."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from scripts.clv_ridge_walk_forward import (
    _feature_contract,
    _months_before,
    _opening_rows,
    _outcome_probability_pipeline,
    _positive_clv_target,
    broad_strategy,
)
from scripts.portfolio_algorithm_optimization import PROJECT_ROOT
from scripts.robust_consensus_latest_month_holdout import (
    HistoricalMatch,
    build_candidate_cache,
    load_matches,
)


def _score_payload(payload: dict[str, Any], features: dict[str, Any]) -> float:
    logit = float(payload["intercept"])
    logit += sum(
        float(payload["numeric_coefficients"][field]) * float(features[field])
        for field in payload["numeric_features"]
    )
    logit += sum(
        float(payload["categorical_coefficients"][field].get(
            str(features[field]), 0.0
        ))
        for field in payload["categorical_features"]
    )
    return 1.0 / (1.0 + math.exp(-logit))


def serialize_classifier(
    model: Any, numeric_features: tuple[str, ...],
    categorical_features: tuple[str, ...], metadata: dict[str, Any],
    parity_sample: pd.DataFrame,
) -> dict[str, Any]:
    transform = model.named_steps["features"]
    logistic = model.named_steps["logistic"]
    scaler = transform.named_transformers_["numeric"]
    encoder = transform.named_transformers_["categorical"]
    coefficients = logistic.coef_[0].tolist()
    numeric_count = len(numeric_features)
    numeric_scaled = coefficients[:numeric_count]
    numeric_coefficients = {
        name: float(coefficient) / float(scale)
        for name, coefficient, scale in zip(
            numeric_features, numeric_scaled, scaler.scale_
        )
    }
    intercept = float(logistic.intercept_[0]) - sum(
        float(coefficient) * float(mean) / float(scale)
        for coefficient, mean, scale in zip(
            numeric_scaled, scaler.mean_, scaler.scale_
        )
    )
    categorical_coefficients: dict[str, dict[str, float]] = {}
    offset = numeric_count
    for field, categories in zip(categorical_features, encoder.categories_):
        values = coefficients[offset:offset + len(categories)]
        categorical_coefficients[field] = {
            str(category): float(coefficient)
            for category, coefficient in zip(categories, values)
        }
        offset += len(categories)
    payload = {
        **metadata,
        "artifact_type": "positive_clv_logistic_v1",
        "target": "closing_edge_pct>0",
        "result_used_as_feature_or_target": False,
        "intercept": intercept,
        "numeric_features": list(numeric_features),
        "categorical_features": list(categorical_features),
        "numeric_coefficients": numeric_coefficients,
        "categorical_coefficients": categorical_coefficients,
        "unknown_category_policy": "zero_coefficient",
    }
    pipeline_probability = model.predict_proba(parity_sample)[:, 1]
    json_probability = [
        _score_payload(payload, row) for row in parity_sample.to_dict("records")
    ]
    parity_error = max((
        abs(float(expected) - actual)
        for expected, actual in zip(pipeline_probability, json_probability)
    ), default=0.0)
    if parity_error > 1e-8:
        raise ValueError(f"positive-CLV JSON parity failed: {parity_error}")
    payload["export_parity_sample"] = len(parity_sample)
    payload["export_parity_max_abs_error"] = parity_error
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    payload["model_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    return payload


def export_positive_clv_classifier(
    output_path: Path, model_version: str,
    exchange_commission_rate: float = 0.05,
    training_months: int = 9, validation_months: int = 3,
    training_end: date | None = None,
    feature_profile: str = "market_structure",
    minimum_reference_bookmakers: int = 4,
    exchange_bookmaker_keys: tuple[str, ...] = ("BFE", "BF"),
    maximum_price_ratio: float | None = 1.15,
    matches: list[HistoricalMatch] | None = None,
) -> dict[str, Any]:
    rows = matches if matches is not None else load_matches()
    training_end = training_end or max(row.match_date for row in rows)
    next_month = training_end.replace(day=1) + timedelta(days=32)
    training_start = _months_before(next_month, training_months)
    validation_start = _months_before(next_month, validation_months)
    strategy = broad_strategy(
        exchange_commission_rate, minimum_reference_bookmakers,
        exchange_bookmaker_keys, maximum_price_ratio,
    )
    cache = build_candidate_cache(rows, strategy)
    training = _opening_rows(
        rows, strategy, cache, training_start, training_end, True
    )
    dates = pd.to_datetime(training["date"]).dt.date
    inner = training.loc[dates < validation_start].copy()
    validation = training.loc[dates >= validation_start].copy()
    numeric, categorical = _feature_contract(feature_profile)
    inner_target = _positive_clv_target(inner)
    training_target = _positive_clv_target(training)
    if inner_target.nunique() < 2 or training_target.nunique() < 2:
        raise ValueError("positive-CLV classifier requires both target classes")
    validation_model = _outcome_probability_pipeline(numeric, categorical)
    validation_model.fit(inner, inner_target)
    validation_probability = validation_model.predict_proba(validation)[:, 1]
    validation_target = _positive_clv_target(validation).to_numpy(dtype=float)
    validation_brier = float(((validation_probability - validation_target) ** 2).mean())
    model = _outcome_probability_pipeline(numeric, categorical)
    model.fit(training, training_target)
    payload = serialize_classifier(
        model, numeric, categorical, {
            "model_version": model_version,
            "created_at": pd.Timestamp.now(tz="UTC").isoformat(),
            "training_window": f"{training_start}..{training_end}",
            "training_months": training_months,
            "validation_months": validation_months,
            "validation_start": validation_start.isoformat(),
            "training_candidates": len(training),
            "validation_candidates": len(validation),
            "validation_brier": validation_brier,
            "positive_target_rate": float(training_target.mean()),
            "feature_profile": feature_profile,
            "exchange_commission_rate": exchange_commission_rate,
            "exchange_bookmaker_keys": list(exchange_bookmaker_keys),
            "maximum_price_ratio": maximum_price_ratio,
            "minimum_reference_bookmakers": minimum_reference_bookmakers,
            "regularization_c": 0.1,
        },
        training.head(200),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-version", required=True)
    parser.add_argument("--exchange-commission-rate", type=float, default=0.05)
    parser.add_argument("--training-months", type=int, default=9)
    parser.add_argument("--validation-months", type=int, default=3)
    parser.add_argument("--training-end", type=date.fromisoformat)
    parser.add_argument("--minimum-reference-bookmakers", type=int, default=4)
    parser.add_argument("--exchange-bookmaker-keys", default="BFE,BF")
    parser.add_argument("--maximum-price-ratio", type=float, default=1.15)
    args = parser.parse_args()
    keys = tuple(
        key.strip().upper() for key in args.exchange_bookmaker_keys.split(",")
        if key.strip()
    )
    report = export_positive_clv_classifier(
        args.output, args.model_version, args.exchange_commission_rate,
        args.training_months, args.validation_months, args.training_end,
        minimum_reference_bookmakers=args.minimum_reference_bookmakers,
        exchange_bookmaker_keys=keys,
        maximum_price_ratio=args.maximum_price_ratio,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
