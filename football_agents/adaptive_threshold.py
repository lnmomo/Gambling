from __future__ import annotations

from typing import Any


def calculate_adaptive_ev_threshold(match_context: dict[str, Any] | None = None, risk_context: dict[str, Any] | None = None, market_context: dict[str, Any] | None = None) -> float:
    match_context = match_context or {}
    risk_context = risk_context or {}
    market_context = market_context or {}
    threshold = 0.03
    quality = str(market_context.get("externalMarketQuality") or market_context.get("external_market_quality") or "UNAVAILABLE").upper()
    if quality == "HIGH":
        threshold -= 0.005
    elif quality == "LOW":
        threshold += 0.015
    elif quality == "UNAVAILABLE":
        threshold += 0.025
    disagreement = str(risk_context.get("modelDisagreement") or risk_context.get("model_disagreement") or "").upper()
    if disagreement == "MEDIUM":
        threshold += 0.010
    elif disagreement == "HIGH":
        threshold += 0.025
    if str(risk_context.get("pureModelReliability") or "").upper() == "LOW":
        threshold += 0.015
    if str(risk_context.get("lineupRisk") or "").upper() == "HIGH":
        threshold += 0.015
    if str(risk_context.get("fatigueRisk") or "").upper() == "HIGH":
        threshold += 0.010
    if str(match_context.get("outcome") or "").upper() == "DRAW":
        threshold += 0.010
    odds = float(match_context.get("odds") or 2)
    if odds < 1.30:
        threshold += 0.015
    if odds > 5.00:
        threshold += 0.020
    if str(match_context.get("leagueSample") or match_context.get("league_sample") or "").upper() == "LOW":
        threshold += 0.015
    clv = str(market_context.get("clvHistory") or market_context.get("clv_history") or "").upper()
    if clv == "POSITIVE":
        threshold -= 0.005
    elif clv == "NEGATIVE":
        threshold += 0.015
    return max(0.02, min(0.10, threshold))
