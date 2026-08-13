"""Frozen, JSON-only scoring for the v6.2 prospective CLV shadow policy."""
from __future__ import annotations

import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any


MODEL_PATH = Path(__file__).with_name("model_artifacts") / "clv_ridge_v6_2.json"
MARKET_STRUCTURE_MODEL_PATH = (
    Path(__file__).with_name("model_artifacts") / "clv_ridge_v6_6.json"
)
PROBABILITY_MOVEMENT_MODEL_PATH = (
    Path(__file__).with_name("model_artifacts") / "clv_ridge_v7_1.json"
)
ADAPTIVE_MARKET_STRUCTURE_MODEL_PATH = (
    Path(__file__).with_name("model_artifacts") / "clv_ridge_v8_1_direct.json"
)
ADAPTIVE_PROBABILITY_MOVEMENT_MODEL_PATH = (
    Path(__file__).with_name("model_artifacts") / "clv_ridge_v8_1_movement.json"
)
MONTH_STABLE_MARKET_STRUCTURE_MODEL_PATH = (
    Path(__file__).with_name("model_artifacts") / "clv_ridge_v8_5_direct.json"
)
MONTH_STABLE_PROBABILITY_MOVEMENT_MODEL_PATH = (
    Path(__file__).with_name("model_artifacts") / "clv_ridge_v8_5_movement.json"
)
QUOTE_SANITY_MARKET_STRUCTURE_MODEL_PATH = (
    Path(__file__).with_name("model_artifacts") / "clv_ridge_v8_10_direct.json"
)
QUOTE_SANITY_PROBABILITY_MOVEMENT_MODEL_PATH = (
    Path(__file__).with_name("model_artifacts") / "clv_ridge_v8_10_movement.json"
)
MARKET_CALIBRATED_MODEL_PATH = (
    Path(__file__).with_name("model_artifacts") / "clv_ridge_v8_18_direct.json"
)
MARKET_CALIBRATED_PROBABILITY_MOVEMENT_MODEL_PATH = (
    Path(__file__).with_name("model_artifacts") / "clv_ridge_v8_18_movement.json"
)
MULTI_HORIZON_LONG_MODEL_PATH = (
    Path(__file__).with_name("model_artifacts") / "clv_ridge_v8_33_long_direct.json"
)
MULTI_HORIZON_LONG_MOVEMENT_MODEL_PATH = (
    Path(__file__).with_name("model_artifacts") / "clv_ridge_v8_33_long_movement.json"
)
MULTI_HORIZON_MID_MODEL_PATH = (
    Path(__file__).with_name("model_artifacts") / "clv_ridge_v8_34_mid_direct.json"
)
MULTI_HORIZON_MID_MOVEMENT_MODEL_PATH = (
    Path(__file__).with_name("model_artifacts") / "clv_ridge_v8_34_mid_movement.json"
)
WIDE_ALL_OUTCOMES_MODEL_PATHS = {
    "2_5pct": Path(__file__).with_name("model_artifacts")
    / "clv_ridge_v8_72_wide_all_outcomes_2_5pct.json",
    "5pct": Path(__file__).with_name("model_artifacts")
    / "clv_ridge_v8_72_wide_all_outcomes_5pct.json",
}
POSITIVE_CLV_MODEL_PATHS = {
    "9m3m_core": {
        "2_5pct": Path(__file__).with_name("model_artifacts")
        / "positive_clv_v8_55_core_2_5pct.json",
        "5pct": Path(__file__).with_name("model_artifacts")
        / "positive_clv_v8_55_core_5pct.json",
    },
    "18m9m_satellite": {
        "2_5pct": Path(__file__).with_name("model_artifacts")
        / "positive_clv_v8_55_long_2_5pct.json",
        "5pct": Path(__file__).with_name("model_artifacts")
        / "positive_clv_v8_55_long_5pct.json",
    },
    "12m6m_tertiary": {
        "2_5pct": Path(__file__).with_name("model_artifacts")
        / "positive_clv_v8_55_mid_2_5pct.json",
        "5pct": Path(__file__).with_name("model_artifacts")
        / "positive_clv_v8_55_mid_5pct.json",
    },
}


def _canonical_without_hash(payload: dict[str, Any]) -> str:
    value = {key: item for key, item in payload.items() if key != "model_sha256"}
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


@lru_cache(maxsize=16)
def load_frozen_model(path_text: str | None = None) -> dict[str, Any]:
    path = Path(path_text) if path_text else MODEL_PATH
    payload = json.loads(path.read_text(encoding="utf-8"))
    actual = hashlib.sha256(_canonical_without_hash(payload).encode()).hexdigest()
    if actual != payload.get("model_sha256"):
        raise ValueError("CLV Ridge model hash mismatch")
    return payload


def score_opening_features(features: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    model = load_frozen_model(str(path) if path else None)
    score = float(model["intercept"])
    for field in model["numeric_features"]:
        score += float(model["numeric_coefficients"][field]) * float(features[field])
    for field in model["categorical_features"]:
        coefficients = model["categorical_coefficients"].get(field, {})
        score += float(coefficients.get(str(features[field]), 0.0))
    lower_target = score - float(model["safety_margin"]) * float(model["validation_rmse_pct"])
    target = str(model.get("target") or "closing_edge_pct")
    predicted_probability = None
    if target == "closing_probability_delta":
        predicted_probability = min(0.999, max(0.001, float(features["probability"]) + score))
        lower_probability = min(
            0.999, max(0.001, float(features["probability"]) + lower_target)
        )
        predicted_edge = (predicted_probability * float(features["odds"]) - 1.0) * 100.0
        lower = (lower_probability * float(features["odds"]) - 1.0) * 100.0
    elif target == "closing_probability":
        predicted_probability = min(0.999, max(0.001, score))
        lower_probability = min(0.999, max(0.001, lower_target))
        predicted_edge = (predicted_probability * float(features["odds"]) - 1.0) * 100.0
        lower = (lower_probability * float(features["odds"]) - 1.0) * 100.0
    else:
        predicted_edge = score
        lower = lower_target
    market_probability = None
    if {
        "market_calibration_intercept", "market_calibration_slope",
    }.issubset(model):
        probability = min(0.999, max(0.001, float(features["probability"])))
        calibrated_logit = (
            float(model["market_calibration_intercept"])
            + float(model["market_calibration_slope"])
            * math.log(probability / (1.0 - probability))
        )
        calibrated_market_probability = 1.0 / (1.0 + math.exp(-calibrated_logit))
        lower_staking_probability = min(
            0.999, max(0.001, (1.0 + lower / 100.0) / float(features["odds"]))
        )
        weight = float(model.get("market_calibration_weight", 1.0))
        market_probability = (
            lower_staking_probability
            + weight * (calibrated_market_probability - lower_staking_probability)
        )
    return {
        "model_version": model["model_version"],
        "model_sha256": model["model_sha256"],
        "predicted_closing_edge_pct": predicted_edge,
        "lower_predicted_closing_edge_pct": lower,
        "predicted_closing_probability": predicted_probability,
        "estimated_probability_from_training_market": market_probability,
        "minimum_lower_clv_pct": float(model["minimum_lower_clv_pct"]),
        "maximum_odds": float(model["maximum_odds"]),
        "training_window": model["training_window"],
    }


def score_positive_clv_probability(
    features: dict[str, Any], path: Path,
) -> dict[str, Any]:
    model = load_frozen_model(str(path))
    if model.get("artifact_type") != "positive_clv_logistic_v1":
        raise ValueError("not a positive-CLV logistic artifact")
    logit = float(model["intercept"])
    for field in model["numeric_features"]:
        logit += float(model["numeric_coefficients"][field]) * float(features[field])
    for field in model["categorical_features"]:
        logit += float(model["categorical_coefficients"].get(field, {}).get(
            str(features[field]), 0.0
        ))
    probability = 1.0 / (1.0 + math.exp(-logit))
    return {
        "model_version": model["model_version"],
        "model_sha256": model["model_sha256"],
        "positive_clv_probability": probability,
        "training_window": model["training_window"],
    }


def odds_band(odds: float) -> str:
    if odds < 2.0:
        return "1.5-2.0"
    if odds < 3.0:
        return "2.0-3.0"
    if odds < 4.0:
        return "3.0-4.0"
    if odds < 5.0:
        return "4.0-5.0"
    return "5.0+"


def market_structure_features(row: dict[str, Any]) -> dict[str, Any]:
    """Derive the frozen v6.6 basis terms from pre-match market data only."""
    probability = float(row["probability"])
    conservative_probability = float(row["conservative_probability"])
    odds = float(row["odds"])
    raw_odds = float(row["raw_odds"])
    dispersion = float(row["reference_dispersion"])
    depth = max(1.0, float(row["reference_bookmakers"]))
    band = str(row["odds_band"])
    source = str(row["source_type"])
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
        "outcome_odds_band": f"{outcome}:{band}",
        "outcome_source_type": f"{outcome}:{source}",
        "source_odds_band": f"{source}:{band}",
    }
