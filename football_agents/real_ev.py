from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .multi_devig import OUTCOMES, Probability, _normalize


@dataclass
class RealProbabilityDiagnostics:
    market_anchor: bool
    reliability: float
    residual_retention: float
    max_deviation_before: dict[str, float]
    max_deviation_after: dict[str, float]
    residual_caps: dict[str, float]
    relative_caps: dict[str, float]
    longshot_penalties: dict[str, float]
    underdog_penalties: dict[str, float]
    favorite_downside_caps: dict[str, float]
    warnings: list[str] = field(default_factory=list)


def _odds_for(key: str, odds: dict[str, float] | None) -> float:
    if not odds:
        return 0.0
    try:
        return float(odds.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _cap_for_odds(odds: float, outcome: str) -> tuple[float, float]:
    if outcome == "draw" and 2.4 <= odds < 4.0:
        return 0.034, 0.12
    if odds <= 0:
        return 0.012, 0.05
    if odds < 1.60:
        return 0.052, 0.16
    if odds < 2.20:
        return 0.046, 0.14
    if odds < 3.00:
        return 0.034, 0.11
    if odds < 5.00:
        return 0.014, 0.055
    return 0.006, 0.030


def _longshot_penalty(outcome: str, odds: float, reliability: float) -> float:
    if outcome == "draw" and odds < 4.0:
        return 0.0
    if odds < 3.0:
        return 0.0
    if odds < 5.0:
        base = 0.006
    elif odds < 8.0:
        base = 0.012
    else:
        base = 0.018
    return base * (1.0 - 0.35 * reliability)


def _underdog_positive_residual_penalty(outcome: str, odds: float, reliability: float, is_market_favorite: bool) -> float:
    if outcome == "draw" or is_market_favorite or odds < 2.20:
        return 0.0
    if odds < 3.00:
        base = 0.006
    elif odds < 5.00:
        base = 0.010
    else:
        base = 0.014
    return base * (1.0 - 0.25 * reliability)


def _favorite_downside_cap(odds: float, cap: float, is_market_favorite: bool) -> float:
    if not is_market_favorite:
        return cap
    if odds < 1.60:
        return min(cap, 0.014)
    if odds < 2.20:
        return min(cap, 0.018)
    return min(cap, 0.024)


def anchor_real_probability(
    model_probability: Probability,
    market_probability: Probability,
    odds: dict[str, float] | None,
    *,
    reliability: float = 0.5,
) -> tuple[Probability, RealProbabilityDiagnostics]:
    """Estimate bettable probability from a market prior plus a tiny model residual.

    This is deliberately not a model-confidence display probability. It is the
    probability used for EV and staking. The market is treated as the prior; the
    model may only move away from it when data reliability is good, and high-odds
    outcomes receive tighter caps because small probability errors dominate EV.
    """
    market = _normalize(market_probability) or {key: 1 / 3 for key in OUTCOMES}
    model = _normalize(model_probability) or market
    reliability = max(0.0, min(1.0, float(reliability)))
    residual_retention = 0.08 + 0.28 * reliability
    market_favorite = max(market, key=market.get)

    adjusted: dict[str, float] = {}
    before: dict[str, float] = {}
    after: dict[str, float] = {}
    caps: dict[str, float] = {}
    relative_caps: dict[str, float] = {}
    penalties: dict[str, float] = {}
    underdog_penalties: dict[str, float] = {}
    favorite_downside_caps: dict[str, float] = {}
    warnings: list[str] = []

    for key in OUTCOMES:
        price = _odds_for(key, odds)
        absolute_cap, relative_cap = _cap_for_odds(price, key)
        cap = min(absolute_cap, max(0.004, market[key] * relative_cap))
        downside_cap = _favorite_downside_cap(price, cap, key == market_favorite)
        raw_residual = model[key] - market[key]
        retained = max(-downside_cap, min(cap, raw_residual * residual_retention))
        penalty = _longshot_penalty(key, price, reliability) if retained > 0 else 0.0
        underdog_penalty = _underdog_positive_residual_penalty(key, price, reliability, key == market_favorite) if retained > 0 else 0.0
        adjusted[key] = max(0.001, market[key] + retained - penalty - underdog_penalty)
        before[key] = raw_residual
        after[key] = retained - penalty - underdog_penalty
        caps[key] = cap
        relative_caps[key] = relative_cap
        penalties[key] = penalty
        underdog_penalties[key] = underdog_penalty
        favorite_downside_caps[key] = downside_cap
        if penalty > 0:
            warnings.append(f"{key} longshot positive residual discounted")
        if underdog_penalty > 0:
            warnings.append(f"{key} underdog positive residual discounted")
        if key == market_favorite and raw_residual < 0 and downside_cap < cap:
            warnings.append(f"{key} market favorite downside residual capped")

    normalized = _normalize(adjusted) or market
    diagnostics = RealProbabilityDiagnostics(
        market_anchor=True,
        reliability=reliability,
        residual_retention=residual_retention,
        max_deviation_before=before,
        max_deviation_after={key: normalized[key] - market[key] for key in OUTCOMES},
        residual_caps=caps,
        relative_caps=relative_caps,
        longshot_penalties=penalties,
        underdog_penalties=underdog_penalties,
        favorite_downside_caps=favorite_downside_caps,
        warnings=list(dict.fromkeys(warnings)),
    )
    return normalized, diagnostics


def expected_value(probability: float, odds: float) -> float:
    return probability * odds - 1.0


def real_ev_by_outcome(probability: Probability, odds: dict[str, float]) -> dict[str, float]:
    return {key: expected_value(probability[key], _odds_for(key, odds)) for key in OUTCOMES}


def diagnostics_to_dict(diagnostics: RealProbabilityDiagnostics) -> dict[str, Any]:
    return {
        "market_anchor": diagnostics.market_anchor,
        "reliability": diagnostics.reliability,
        "residual_retention": diagnostics.residual_retention,
        "max_deviation_before": diagnostics.max_deviation_before,
        "max_deviation_after": diagnostics.max_deviation_after,
        "residual_caps": diagnostics.residual_caps,
        "relative_caps": diagnostics.relative_caps,
        "longshot_penalties": diagnostics.longshot_penalties,
        "underdog_penalties": diagnostics.underdog_penalties,
        "favorite_downside_caps": diagnostics.favorite_downside_caps,
        "warnings": diagnostics.warnings,
    }
