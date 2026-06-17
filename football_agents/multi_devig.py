from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from math import isfinite
from typing import Any

OUTCOMES = ("home", "draw", "away")
Probability = dict[str, float]
Odds = dict[str, float]


class DevigMethod(StrEnum):
    MULTIPLICATIVE = "MULTIPLICATIVE"
    ADDITIVE = "ADDITIVE"
    POWER = "POWER"
    ODDS_RATIO = "ODDS_RATIO"
    SHIN = "SHIN"
    CONSERVATIVE = "CONSERVATIVE"


@dataclass
class DevigProbabilitySet:
    method: str
    probability: Probability
    fair_odds: Odds
    overround: float
    valid: bool
    warnings: list[str] = field(default_factory=list)


@dataclass
class MultiDevigResult:
    source: str
    odds: Odds
    methods: dict[str, DevigProbabilitySet]
    recommended_method: str
    recommended_probability: Probability
    recommended_fair_odds: Odds
    method_agreement_score: float
    method_spread: dict[str, float]
    warnings: list[str] = field(default_factory=list)


def _invalid(method: DevigMethod | str, odds: Odds, warnings: list[str]) -> DevigProbabilitySet:
    return DevigProbabilitySet(str(method), {}, {}, _overround(odds), False, warnings)


def _overround(odds: Odds) -> float:
    values = []
    for key in OUTCOMES:
        value = float(odds.get(key, 0) or 0)
        if value > 1 and isfinite(value):
            values.append(1 / value)
    return sum(values)


def _valid_odds(odds: Odds) -> bool:
    return all(isfinite(float(odds.get(key, 0) or 0)) and float(odds.get(key, 0) or 0) > 1 for key in OUTCOMES)


def _normalize(values: Probability) -> Probability | None:
    if any((not isfinite(float(values.get(key, 0)))) or float(values.get(key, 0)) <= 0 for key in OUTCOMES):
        return None
    total = sum(float(values[key]) for key in OUTCOMES)
    if not isfinite(total) or total <= 0:
        return None
    return {key: float(values[key]) / total for key in OUTCOMES}


def _fair_odds(probability: Probability) -> Odds:
    return {key: 1 / max(probability[key], 1e-12) for key in OUTCOMES}


def _set(method: DevigMethod, odds: Odds, probability: Probability | None, warnings: list[str] | None = None) -> DevigProbabilitySet:
    normalized = _normalize(probability or {})
    if not normalized:
        return _invalid(method, odds, warnings or ["devig method produced invalid probabilities"])
    return DevigProbabilitySet(method.value, normalized, _fair_odds(normalized), _overround(odds), True, warnings or [])


def _multiplicative(odds: Odds) -> DevigProbabilitySet:
    implied = {key: 1 / float(odds[key]) for key in OUTCOMES}
    return _set(DevigMethod.MULTIPLICATIVE, odds, implied)


def _additive(odds: Odds) -> DevigProbabilitySet:
    implied = {key: 1 / float(odds[key]) for key in OUTCOMES}
    excess = sum(implied.values()) - 1
    probability = {key: implied[key] - excess / 3 for key in OUTCOMES}
    if any(value <= 0 for value in probability.values()):
        fallback = _multiplicative(odds)
        return DevigProbabilitySet(DevigMethod.ADDITIVE.value, fallback.probability, fallback.fair_odds, fallback.overround, True, ["additive invalid; used multiplicative fallback"])
    return _set(DevigMethod.ADDITIVE, odds, probability)


def _bisect(fn, low: float, high: float, target: float = 1.0, iterations: int = 80) -> float | None:
    f_low = fn(low) - target
    f_high = fn(high) - target
    if not isfinite(f_low) or not isfinite(f_high) or f_low * f_high > 0:
        return None
    for _ in range(iterations):
        mid = (low + high) / 2
        f_mid = fn(mid) - target
        if abs(f_mid) < 1e-12:
            return mid
        if f_low * f_mid <= 0:
            high = mid
            f_high = f_mid
        else:
            low = mid
            f_low = f_mid
    return (low + high) / 2


def _power(odds: Odds) -> DevigProbabilitySet:
    implied = {key: 1 / float(odds[key]) for key in OUTCOMES}
    k = _bisect(lambda x: sum(value**x for value in implied.values()), 0.5, 2.5)
    if k is None:
        fallback = _multiplicative(odds)
        return DevigProbabilitySet(DevigMethod.POWER.value, fallback.probability, fallback.fair_odds, fallback.overround, True, ["power solver failed; used multiplicative fallback"])
    return _set(DevigMethod.POWER, odds, {key: implied[key] ** k for key in OUTCOMES})


def _odds_ratio(odds: Odds) -> DevigProbabilitySet:
    implied = {key: 1 / float(odds[key]) for key in OUTCOMES}

    def total(c: float) -> float:
        return sum(value / (c + value - c * value) for value in implied.values())

    c = _bisect(total, 0.01, 100)
    if c is None:
        fallback = _multiplicative(odds)
        return DevigProbabilitySet(DevigMethod.ODDS_RATIO.value, fallback.probability, fallback.fair_odds, fallback.overround, True, ["odds-ratio solver failed; used multiplicative fallback"])
    return _set(DevigMethod.ODDS_RATIO, odds, {key: implied[key] / (c + implied[key] - c * implied[key]) for key in OUTCOMES})


def _shin_like(odds: Odds) -> DevigProbabilitySet:
    power = _power(odds)
    if not power.valid:
        fallback = _multiplicative(odds)
        return DevigProbabilitySet(DevigMethod.SHIN.value, fallback.probability, fallback.fair_odds, fallback.overround, True, ["shin-like approximation fallback used"])
    mean = 1 / 3
    adjusted = {key: max(1e-9, power.probability[key] * 0.97 + mean * 0.03) for key in OUTCOMES}
    return _set(DevigMethod.SHIN, odds, adjusted, ["shin-like approximation used"])


def _conservative(odds: Odds, methods: dict[str, DevigProbabilitySet]) -> DevigProbabilitySet:
    valid = [item.probability for item in methods.values() if item.valid and item.probability]
    if not valid:
        return _invalid(DevigMethod.CONSERVATIVE, odds, ["no valid devig method available"])
    return _set(DevigMethod.CONSERVATIVE, odds, {key: min(prob[key] for prob in valid) for key in OUTCOMES}, ["conservative worst-case estimate"])


def calculate_multi_devig_probabilities(odds: Odds, options: dict[str, Any] | None = None) -> MultiDevigResult:
    options = options or {}
    source = str(options.get("source", "market"))
    clean_odds = {key: float(odds.get(key, 0) or 0) for key in OUTCOMES}
    warnings: list[str] = []
    if not _valid_odds(clean_odds):
        methods = {method.value: _invalid(method, clean_odds, ["odds must be finite and > 1"]) for method in DevigMethod}
        neutral = {key: 1 / 3 for key in OUTCOMES}
        return MultiDevigResult(source, clean_odds, methods, DevigMethod.MULTIPLICATIVE.value, neutral, _fair_odds(neutral), 0.0, {"home": 0, "draw": 0, "away": 0, "max": 0}, ["invalid odds"])

    methods: dict[str, DevigProbabilitySet] = {
        DevigMethod.MULTIPLICATIVE.value: _multiplicative(clean_odds),
        DevigMethod.ADDITIVE.value: _additive(clean_odds),
        DevigMethod.POWER.value: _power(clean_odds),
        DevigMethod.ODDS_RATIO.value: _odds_ratio(clean_odds),
        DevigMethod.SHIN.value: _shin_like(clean_odds),
    }
    methods[DevigMethod.CONSERVATIVE.value] = _conservative(clean_odds, methods)
    preferred = str(options.get("recommended_method") or DevigMethod.POWER.value).upper()
    if preferred not in methods or not methods[preferred].valid:
        preferred = DevigMethod.MULTIPLICATIVE.value
    valid_probs = [item.probability for item in methods.values() if item.valid and item.probability]
    spread = {key: (max(prob[key] for prob in valid_probs) - min(prob[key] for prob in valid_probs)) if valid_probs else 0 for key in OUTCOMES}
    spread["max"] = max(spread.values()) if spread else 0
    agreement = max(0.0, min(1.0, 1 - spread["max"] / 0.08))
    recommended = methods[preferred].probability
    return MultiDevigResult(source, clean_odds, methods, preferred, recommended, _fair_odds(recommended), agreement, spread, warnings)
