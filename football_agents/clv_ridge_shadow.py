"""Frozen, JSON-only scoring for the v6.2 prospective CLV shadow policy."""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any


MODEL_PATH = Path(__file__).with_name("model_artifacts") / "clv_ridge_v6_2.json"


def _canonical_without_hash(payload: dict[str, Any]) -> str:
    value = {key: item for key, item in payload.items() if key != "model_sha256"}
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


@lru_cache(maxsize=4)
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
    lower = score - float(model["safety_margin"]) * float(model["validation_rmse_pct"])
    return {
        "model_version": model["model_version"],
        "model_sha256": model["model_sha256"],
        "predicted_closing_edge_pct": score,
        "lower_predicted_closing_edge_pct": lower,
        "minimum_lower_clv_pct": float(model["minimum_lower_clv_pct"]),
        "maximum_odds": float(model["maximum_odds"]),
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

