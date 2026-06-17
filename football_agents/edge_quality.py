from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .closing_line_proxy import ClosingLineProxy
from .probability_uncertainty import ProbabilityUncertainty


@dataclass
class EdgeQualityOutput:
    outcome: str
    official_sp: float
    break_even_probability: float
    estimated_probability: float
    lower_bound_probability: float
    upper_bound_probability: float
    expected_ev: float
    lower_bound_ev: float
    upper_bound_ev: float
    expected_closing_edge: float | None
    clv_win_probability: float | None
    edge_quality_score: float
    edge_quality_level: str
    edge_noise_risk: str
    adaptive_threshold: float
    passes_true_odds_filter: bool
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def calculate_edge_quality(outcome: str, official_sp: float, estimated_probability: dict[str, float], uncertainty: ProbabilityUncertainty, closing_proxy: ClosingLineProxy | None, context: dict[str, Any] | None, adaptive_threshold: float) -> EdgeQualityOutput:
    context = context or {}
    key = outcome.lower()
    p = estimated_probability[key]
    lower = uncertainty.lower[key]
    upper = uncertainty.upper[key]
    expected_ev = p * official_sp - 1
    lower_ev = lower * official_sp - 1
    upper_ev = upper * official_sp - 1
    score = 50.0
    reasons: list[str] = []
    warnings: list[str] = []
    if expected_ev > adaptive_threshold + 0.03:
        score += 15
    elif expected_ev > adaptive_threshold:
        score += 8
    if lower_ev > 0:
        score += 20
    else:
        score -= 25
        reasons.append("lowerBoundEV <= 0")
    clv_prob = closing_proxy.clv_win_probability if closing_proxy and closing_proxy.available else None
    closing_edge = closing_proxy.expected_closing_edge if closing_proxy and closing_proxy.available else None
    if clv_prob is not None and clv_prob > 0.55:
        score += 10
    if closing_edge is not None:
        score += 10 if closing_edge > 0 else -20
    score += 10 * float(context.get("method_agreement_score", 0))
    if str(context.get("external_market_quality") or "").upper() == "HIGH":
        score += 10
    if str(context.get("historical_bucket") or "").upper() == "POSITIVE":
        score += 10
    if str(context.get("model_disagreement") or "").upper() == "HIGH":
        score -= 20
        reasons.append("model disagreement high")
    if str(context.get("market_deviation") or "").upper() == "SUSPICIOUS":
        score -= 15
    if str(context.get("pure_model_reliability") or "").upper() == "LOW":
        score -= 15
    if str(context.get("lineup_risk") or "").upper() == "HIGH":
        score -= 10
    if str(context.get("fatigue_risk") or "").upper() == "HIGH":
        score -= 10
    if key == "draw" and not context.get("draw_calibrator_support"):
        score -= 8
    if official_sp > 5 or official_sp < 1.30:
        score -= 10
    if str(context.get("sample_size") or "").upper() == "LOW":
        score -= 15
    score = max(0, min(100, score))
    level = "HIGH" if score >= 75 else "MEDIUM" if score >= 55 else "LOW" if score >= 35 else "NO_EDGE"
    noise = "HIGH" if uncertainty.overall_uncertainty >= 0.75 or str(context.get("model_disagreement") or "").upper() == "HIGH" else "MEDIUM" if uncertainty.overall_uncertainty >= 0.5 else "LOW"
    if expected_ev <= adaptive_threshold:
        reasons.append("expected EV below adaptive threshold")
    if noise == "HIGH":
        reasons.append("edge noise risk high")
    passes = expected_ev > adaptive_threshold and lower_ev > 0 and level in {"HIGH", "MEDIUM"} and noise != "HIGH" and not context.get("critic_blocked", False)
    return EdgeQualityOutput(key.upper(), official_sp, 1 / official_sp, p, lower, upper, expected_ev, lower_ev, upper_ev, closing_edge, clv_prob, score, level, noise, adaptive_threshold, passes, list(dict.fromkeys(reasons)), warnings)
