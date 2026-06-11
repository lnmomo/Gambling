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

