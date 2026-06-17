from __future__ import annotations

from typing import Any

from .multi_devig import OUTCOMES, Probability, _normalize


def calibrate_draw_probability(base_probability: Probability, match_features: dict[str, Any] | None = None, historical_draw_buckets: Any = None) -> tuple[Probability, dict[str, Any]]:
    features = match_features or {}
    probability = _normalize(base_probability) or {"home": 1 / 3, "draw": 1 / 3, "away": 1 / 3}
    delta = 0.0
    lambda_total = features.get("lambda_total")
    if lambda_total is None and features.get("lambda_home") is not None and features.get("lambda_away") is not None:
        lambda_total = float(features["lambda_home"]) + float(features["lambda_away"])
    lambda_diff = features.get("lambda_diff")
    if lambda_diff is None and features.get("lambda_home") is not None and features.get("lambda_away") is not None:
        lambda_diff = abs(float(features["lambda_home"]) - float(features["lambda_away"]))
    if isinstance(lambda_total, (int, float)):
        if lambda_total < 2.2:
            delta += 0.012
        elif lambda_total > 3.0:
            delta -= 0.012
    if isinstance(lambda_diff, (int, float)) and lambda_diff < 0.25:
        delta += 0.010
    league_draw_rate = features.get("league_draw_rate")
    if isinstance(league_draw_rate, (int, float)):
        delta += max(-0.01, min(0.01, (float(league_draw_rate) - 0.27) * 0.25))
    if features.get("high_tempo") or (isinstance(features.get("goal_variance"), (int, float)) and float(features["goal_variance"]) > 1.4):
        delta -= 0.010
    sample_count = int(features.get("sample_count") or 0)
    shrink = 1.0 if sample_count >= 100 else 0.5 if sample_count >= 30 else 0.25
    delta = max(-0.025, min(0.025, delta * shrink))
    draw = max(0.05, min(0.45, probability["draw"] + delta))
    remaining = max(1e-9, 1 - draw)
    home_away_total = probability["home"] + probability["away"]
    adjusted = {
        "home": remaining * probability["home"] / home_away_total,
        "draw": draw,
        "away": remaining * probability["away"] / home_away_total,
    }
    return _normalize(adjusted) or probability, {"applied": abs(delta) > 1e-9, "draw_delta": delta, "sample_count": sample_count}
