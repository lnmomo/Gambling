from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Any


DEFAULT_BOOTSTRAP_ITERATIONS = 5_000
DEFAULT_BOOTSTRAP_SEED = 42
_PROBABILITY_EPSILON = 1e-12


def _percentiles(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"p05": None, "p50": None, "p95": None}
    ordered = sorted(values)

    def percentile(q: float) -> float:
        position = (len(ordered) - 1) * q
        low = int(position)
        high = min(low + 1, len(ordered) - 1)
        fraction = position - low
        return ordered[low] * (1.0 - fraction) + ordered[high] * fraction

    return {
        "p05": round(percentile(0.05), 6),
        "p50": round(percentile(0.50), 6),
        "p95": round(percentile(0.95), 6),
    }


def _probability(value: Any) -> float:
    probability = float(value)
    return min(1.0 - _PROBABILITY_EPSILON, max(_PROBABILITY_EPSILON, probability))


def _metrics(rows: list[dict[str, Any]]) -> dict[str, float | int | None]:
    profits = [float(row["profit"]) for row in rows if row.get("profit") is not None]
    clv = [float(row["clv"]) for row in rows if row.get("clv") is not None]
    probability_rows = [
        row for row in rows
        if row.get("predicted_probability") is not None and row.get("market_probability") is not None
    ]
    model_brier: list[float] = []
    market_brier: list[float] = []
    model_log_loss: list[float] = []
    market_log_loss: list[float] = []
    for row in probability_rows:
        actual = 1.0 if str(row.get("actual_outcome") or "").upper() == str(
            row.get("selected_outcome") or ""
        ).upper() else 0.0
        model_probability = _probability(row["predicted_probability"])
        market_probability = _probability(row["market_probability"])
        model_brier.append((model_probability - actual) ** 2)
        market_brier.append((market_probability - actual) ** 2)
        model_log_loss.append(-(
            actual * math.log(model_probability)
            + (1.0 - actual) * math.log(1.0 - model_probability)
        ))
        market_log_loss.append(-(
            actual * math.log(market_probability)
            + (1.0 - actual) * math.log(1.0 - market_probability)
        ))

    def average(values: list[float]) -> float | None:
        return sum(values) / len(values) if values else None

    model_brier_mean = average(model_brier)
    market_brier_mean = average(market_brier)
    model_log_loss_mean = average(model_log_loss)
    market_log_loss_mean = average(market_log_loss)
    return {
        "bets": len(profits),
        "clv_samples": len(clv),
        "probability_samples": len(probability_rows),
        "roi_pct": sum(profits) / len(profits) * 100.0 if profits else None,
        "average_clv": average(clv),
        "model_brier": model_brier_mean,
        "market_brier": market_brier_mean,
        "brier_improvement": (
            market_brier_mean - model_brier_mean
            if market_brier_mean is not None and model_brier_mean is not None else None
        ),
        "model_log_loss": model_log_loss_mean,
        "market_log_loss": market_log_loss_mean,
        "log_loss_improvement": (
            market_log_loss_mean - model_log_loss_mean
            if market_log_loss_mean is not None and model_log_loss_mean is not None else None
        ),
    }


def _rounded_metrics(metrics: dict[str, float | int | None]) -> dict[str, float | int | None]:
    return {
        key: round(value, 6) if isinstance(value, float) else value
        for key, value in metrics.items()
    }


def build_prospective_statistical_evidence(
    settled_rows: list[dict[str, Any]],
    iterations: int = DEFAULT_BOOTSTRAP_ITERATIONS,
    seed: int = DEFAULT_BOOTSTRAP_SEED,
) -> dict[str, Any]:
    rows = [row for row in settled_rows if row.get("profit") is not None]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        settlement_day = str(
            row.get("settlement_day") or row.get("settled_at") or row.get("kickoff_time") or "unknown"
        )[:10]
        grouped[settlement_day].append(row)
    groups = [grouped[key] for key in sorted(grouped)]
    point = _metrics(rows)
    bootstrap_values: dict[str, list[float]] = {
        "roi_pct": [],
        "average_clv": [],
        "brier_improvement": [],
        "log_loss_improvement": [],
    }
    if groups and iterations > 0:
        rng = random.Random(seed)
        for _ in range(iterations):
            sampled_rows = [row for _ in groups for row in rng.choice(groups)]
            metrics = _metrics(sampled_rows)
            for key in bootstrap_values:
                value = metrics[key]
                if value is not None:
                    bootstrap_values[key].append(float(value))

    bootstrap = {
        "iterations": max(0, int(iterations)),
        "seed": int(seed),
        "resampling_unit": "settlement_day",
        "settlement_days": len(groups),
        "roi_ci_pct": _percentiles(bootstrap_values["roi_pct"]),
        "average_clv_ci": _percentiles(bootstrap_values["average_clv"]),
        "brier_improvement_ci": _percentiles(bootstrap_values["brier_improvement"]),
        "log_loss_improvement_ci": _percentiles(bootstrap_values["log_loss_improvement"]),
        "probability_roi_positive": round(
            sum(value > 0 for value in bootstrap_values["roi_pct"])
            / len(bootstrap_values["roi_pct"]), 4
        ) if bootstrap_values["roi_pct"] else None,
        "probability_clv_positive": round(
            sum(value > 0 for value in bootstrap_values["average_clv"])
            / len(bootstrap_values["average_clv"]), 4
        ) if bootstrap_values["average_clv"] else None,
        "probability_brier_improvement_positive": round(
            sum(value > 0 for value in bootstrap_values["brier_improvement"])
            / len(bootstrap_values["brier_improvement"]), 4
        ) if bootstrap_values["brier_improvement"] else None,
        "probability_log_loss_improvement_positive": round(
            sum(value > 0 for value in bootstrap_values["log_loss_improvement"])
            / len(bootstrap_values["log_loss_improvement"]), 4
        ) if bootstrap_values["log_loss_improvement"] else None,
    }
    return {
        "method": "deterministic settlement-day block bootstrap with paired market calibration",
        "point_estimates": _rounded_metrics(point),
        "bootstrap": bootstrap,
        "guardrail": (
            "Each resample draws whole settlement-day cohorts. Model and de-vig market losses are paired "
            "on the same immutable selected outcomes."
        ),
    }
