from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .multi_devig import OUTCOMES, MultiDevigResult, Probability, _normalize


@dataclass
class ProbabilityUncertainty:
    mean: Probability
    lower: Probability
    upper: Probability
    std: Probability
    confidence: Probability
    method_spread: Probability
    model_disagreement: Probability
    sample_reliability: float
    overall_uncertainty: float
    warnings: list[str] = field(default_factory=list)


def estimate_probability_uncertainty(probability_sources: dict[str, Probability | None], multi_devig_result: MultiDevigResult, context: dict[str, Any] | None = None) -> ProbabilityUncertainty:
    context = context or {}
    mean = _normalize(probability_sources.get("finalProbability") or probability_sources.get("pureModelProbability") or multi_devig_result.recommended_probability) or multi_devig_result.recommended_probability
    sources = [prob for prob in probability_sources.values() if prob and _normalize(prob)]
    disagreement = {}
    for key in OUTCOMES:
        values = [(_normalize(prob) or mean)[key] for prob in sources]
        disagreement[key] = (max(values) - min(values)) if values else 0
    sample_reliability = max(0.0, min(1.0, float(context.get("sample_reliability", 0.5))))
    risk_penalty = 0.0
    if str(context.get("lineup_risk") or "").upper() == "HIGH":
        risk_penalty += 0.015
    if str(context.get("fatigue_risk") or "").upper() == "HIGH":
        risk_penalty += 0.010
    std = {}
    lower = {}
    upper = {}
    confidence = {}
    for key in OUTCOMES:
        spread = float(multi_devig_result.method_spread.get(key, 0))
        std[key] = max(0.015, min(0.12, spread * 0.45 + disagreement[key] * 0.55 + (1 - sample_reliability) * 0.025 + risk_penalty))
        lower[key] = max(0.0, mean[key] - std[key])
        upper[key] = min(1.0, mean[key] + std[key])
        confidence[key] = max(0.0, min(1.0, 1 - std[key] / 0.12))
    overall = max(std.values()) / 0.12
    warnings = ["probability uncertainty is high"] if overall > 0.75 else []
    return ProbabilityUncertainty(mean, lower, upper, std, confidence, dict(multi_devig_result.method_spread), disagreement, sample_reliability, max(0.0, min(1.0, overall)), warnings)
