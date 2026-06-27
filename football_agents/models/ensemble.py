from __future__ import annotations

from statistics import pstdev
from typing import Mapping


OPTIONS = ("home", "draw", "away")


def normalize(values: Mapping[str, float]) -> dict[str, float]:
    total = sum(max(0, values.get(key, 0)) for key in OPTIONS)
    if total <= 0:
        raise ValueError("Probabilities must have a positive sum")
    return {key: max(0, values.get(key, 0)) / total for key in OPTIONS}


def market_probabilities(odds: Mapping[str, float]) -> dict[str, float]:
    if any(odds.get(key, 0) <= 1 for key in OPTIONS):
        raise ValueError("All 1X2 odds must be greater than 1")
    return normalize({key: 1 / odds[key] for key in OPTIONS})


def market_residual_anchor(
    probability: Mapping[str, float],
    market: Mapping[str, float],
    *,
    reliability: float = 0.5,
    max_absolute_deviation: float = 0.05,
    max_relative_deviation: float = 0.20,
) -> tuple[dict[str, float], dict[str, float | bool]]:
    """Constrain model output to a small, reliability-scaled residual from market.

    The betting market is the strongest prior. Team models may still express an
    edge, but low-reliability features should not be able to create huge
    long-shot probabilities merely from sparse or mismatched history.
    """
    base = normalize(market)
    raw = normalize(probability)
    reliability = max(0.0, min(1.0, reliability))
    residual_retention = 0.20 + 0.60 * reliability
    anchored: dict[str, float] = {}
    capped = False
    max_before = 0.0
    max_after = 0.0
    for option in OPTIONS:
        diff = raw[option] - base[option]
        max_before = max(max_before, abs(diff))
        cap = min(max_absolute_deviation, max(0.015, base[option] * max_relative_deviation))
        retained = max(-cap, min(cap, diff * residual_retention))
        if abs(retained - diff) > 1e-12:
            capped = True
        anchored[option] = base[option] + retained
        max_after = max(max_after, abs(retained))
    return normalize(anchored), {
        "market_residual_anchor": True,
        "capped": capped,
        "reliability": reliability,
        "residual_retention": residual_retention,
        "max_deviation_before": max_before,
        "max_deviation_after": max_after,
        "max_absolute_deviation": max_absolute_deviation,
        "max_relative_deviation": max_relative_deviation,
    }


class EnsembleModel:
    def __init__(self, weights: Mapping[str, float] | None = None) -> None:
        self.weights = dict(weights or {"elo": 0.20, "poisson": 0.45, "market": 0.35})

    def predict(self, predictions: Mapping[str, Mapping[str, float]]) -> dict[str, float]:
        available = {name: normalize(pred) for name, pred in predictions.items() if name in self.weights}
        weight_sum = sum(self.weights[name] for name in available)
        if not available or weight_sum <= 0:
            raise ValueError("No weighted model predictions supplied")
        return normalize({
            option: sum(self.weights[name] * pred[option] for name, pred in available.items()) / weight_sum
            for option in OPTIONS
        })

    @staticmethod
    def disagreement(predictions: Mapping[str, Mapping[str, float]]) -> float:
        if len(predictions) < 2:
            return 0.0
        return max(pstdev([prediction[option] for prediction in predictions.values()]) for option in OPTIONS)

