from __future__ import annotations

import json

import pandas as pd
import pytest

from football_agents.clv_ridge_shadow import (
    load_frozen_model,
    score_positive_clv_probability,
)
from scripts.clv_ridge_walk_forward import _outcome_probability_pipeline
from scripts.export_positive_clv_classifier import serialize_classifier


def test_positive_clv_classifier_json_matches_pipeline_and_rejects_tampering(
    tmp_path,
) -> None:
    frame = pd.DataFrame({
        "probability": [0.2, 0.3, 0.7, 0.8] * 30,
        "odds": [4.0, 3.0, 1.5, 1.3] * 30,
        "outcome": ["away", "draw", "home", "home"] * 30,
        "actual_outcome": ["home"] * 120,
        "profit": [999.0] * 120,
    })
    target = pd.Series([0, 0, 1, 1] * 30)
    model = _outcome_probability_pipeline(
        ("probability", "odds"), ("outcome",)
    )
    model.fit(frame, target)
    payload = serialize_classifier(
        model, ("probability", "odds"), ("outcome",), {
            "model_version": "test-positive-clv-v1",
            "training_window": "2025-01-01..2025-12-31",
        }, frame,
    )
    path = tmp_path / "classifier.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    load_frozen_model.cache_clear()

    scored = score_positive_clv_probability(frame.iloc[0].to_dict(), path)
    expected = float(model.predict_proba(frame.iloc[[0]])[0, 1])
    assert abs(scored["positive_clv_probability"] - expected) < 1e-10

    payload["intercept"] += 1.0
    path.write_text(json.dumps(payload), encoding="utf-8")
    load_frozen_model.cache_clear()
    with pytest.raises(ValueError, match="hash mismatch"):
        score_positive_clv_probability(frame.iloc[0].to_dict(), path)
