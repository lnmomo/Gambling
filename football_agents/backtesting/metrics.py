from __future__ import annotations

import math
from typing import Iterable


def brier_score(probabilities: list[dict[str, float]], outcomes: list[str]) -> float:
    return sum(sum((p[key] - float(key == outcome)) ** 2 for key in ("home", "draw", "away"))
               for p, outcome in zip(probabilities, outcomes)) / len(outcomes)


def log_loss(probabilities: list[dict[str, float]], outcomes: list[str]) -> float:
    eps = 1e-15
    return -sum(math.log(min(1 - eps, max(eps, p[outcome]))) for p, outcome in zip(probabilities, outcomes)) / len(outcomes)


def expected_calibration_error(probabilities: list[dict[str, float]], outcomes: list[str], bins: int = 10) -> float:
    observations: list[tuple[float, int]] = []
    for prediction, outcome in zip(probabilities, outcomes):
        option = max(prediction, key=prediction.get)
        observations.append((prediction[option], int(option == outcome)))
    error = 0.0
    for index in range(bins):
        lower, upper = index / bins, (index + 1) / bins
        bucket = [(confidence, correct) for confidence, correct in observations
                  if lower <= confidence < upper or (index == bins - 1 and confidence == 1)]
        if bucket:
            confidence = sum(item[0] for item in bucket) / len(bucket)
            accuracy = sum(item[1] for item in bucket) / len(bucket)
            error += len(bucket) / len(observations) * abs(confidence - accuracy)
    return error


def max_drawdown(equity: Iterable[float]) -> float:
    peak = 0.0
    worst = 0.0
    for value in equity:
        peak = max(peak, value)
        if peak:
            worst = max(worst, (peak - value) / peak)
    return worst

