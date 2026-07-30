from __future__ import annotations

import json

import pytest

from football_agents.clv_ridge_shadow import (
    MARKET_STRUCTURE_MODEL_PATH,
    PROBABILITY_MOVEMENT_MODEL_PATH,
    QUOTE_SANITY_MARKET_STRUCTURE_MODEL_PATH,
    QUOTE_SANITY_PROBABILITY_MOVEMENT_MODEL_PATH,
    MARKET_CALIBRATED_MODEL_PATH,
    load_frozen_model,
    market_structure_features,
    score_opening_features,
)


def _features() -> dict:
    return {
        "probability": 0.40,
        "conservative_probability": 0.38,
        "odds": 2.80,
        "raw_odds": 2.90,
        "conservative_ev_pct": 6.4,
        "reference_dispersion": 0.01,
        "reference_bookmakers": 5,
        "execution_cost_rate": 0.0,
        "outcome": "home",
        "odds_band": "2.0-3.0",
        "source_type": "sportsbook",
        "execution_bookmaker": "B365",
        "league": "E0",
    }


def test_frozen_json_score_matches_explicit_linear_sum() -> None:
    model = load_frozen_model()
    features = _features()
    expected = float(model["intercept"])
    expected += sum(
        float(model["numeric_coefficients"][field]) * float(features[field])
        for field in model["numeric_features"]
    )
    expected += sum(
        float(model["categorical_coefficients"][field].get(features[field], 0.0))
        for field in model["categorical_features"]
    )

    result = score_opening_features(features)

    assert result["predicted_closing_edge_pct"] == pytest.approx(expected)
    assert result["model_sha256"] == model["model_sha256"]


def test_tampered_model_is_rejected(tmp_path) -> None:
    model = dict(load_frozen_model())
    model["intercept"] = float(model["intercept"]) + 1.0
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(model), encoding="utf-8")

    with pytest.raises(ValueError, match="hash mismatch"):
        load_frozen_model(str(path))


def test_market_structure_json_score_matches_explicit_linear_sum() -> None:
    model = load_frozen_model(str(MARKET_STRUCTURE_MODEL_PATH))
    features = _features()
    features.update(market_structure_features(features))
    expected = float(model["intercept"])
    expected += sum(
        float(model["numeric_coefficients"][field]) * float(features[field])
        for field in model["numeric_features"]
    )
    expected += sum(
        float(model["categorical_coefficients"][field].get(features[field], 0.0))
        for field in model["categorical_features"]
    )
    result = score_opening_features(features, MARKET_STRUCTURE_MODEL_PATH)
    assert result["predicted_closing_edge_pct"] == pytest.approx(expected)
    assert result["model_sha256"] == model["model_sha256"]


def test_probability_movement_model_converts_delta_to_executable_clv() -> None:
    model = load_frozen_model(str(PROBABILITY_MOVEMENT_MODEL_PATH))
    features = _features()
    features.update(market_structure_features(features))
    delta = float(model["intercept"])
    delta += sum(
        float(model["numeric_coefficients"][field]) * float(features[field])
        for field in model["numeric_features"]
    )
    delta += sum(
        float(model["categorical_coefficients"][field].get(features[field], 0.0))
        for field in model["categorical_features"]
    )
    expected_probability = min(0.999, max(0.001, features["probability"] + delta))
    result = score_opening_features(features, PROBABILITY_MOVEMENT_MODEL_PATH)
    assert result["predicted_closing_probability"] == pytest.approx(expected_probability)
    assert result["predicted_closing_edge_pct"] == pytest.approx(
        (expected_probability * features["odds"] - 1.0) * 100.0
    )


def test_quote_sanity_models_preserve_training_guard_metadata() -> None:
    for path in (
        QUOTE_SANITY_MARKET_STRUCTURE_MODEL_PATH,
        QUOTE_SANITY_PROBABILITY_MOVEMENT_MODEL_PATH,
    ):
        model = load_frozen_model(str(path))
        assert model["maximum_price_ratio"] == 1.15
        assert model["exchange_bookmaker_keys"] == ["BFE", "BF"]
        assert model["training_window"].endswith("2026-04-30")
        assert model["export_parity_max_abs_error"] < 1e-8


def test_market_calibrated_model_exports_probability_for_kelly_sizing() -> None:
    features = _features()
    features.update(market_structure_features(features))

    result = score_opening_features(features, MARKET_CALIBRATED_MODEL_PATH)

    assert result["estimated_probability_from_training_market"] is not None
    assert 0 < result["estimated_probability_from_training_market"] < 1
