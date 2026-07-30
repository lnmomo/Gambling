from __future__ import annotations

import json

import pytest

from football_agents.clv_ridge_shadow import load_frozen_model, score_opening_features


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
