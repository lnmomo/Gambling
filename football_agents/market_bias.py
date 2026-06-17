from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .multi_devig import OUTCOMES, Probability, _normalize, calculate_multi_devig_probabilities


@dataclass
class MarketBiasBucket:
    bucket_id: str
    league: str | None
    outcome: str
    odds_bucket: str
    market_quality: str | None
    official_external_deviation_bucket: str | None
    sample_count: int
    official_prob_avg: float
    closing_prob_avg: float
    result_frequency: float
    bias_vs_closing: float
    bias_vs_result: float
    log_loss_delta: float
    recommended_correction: float
    confidence: float
    warnings: list[str] = field(default_factory=list)


def _bucket(odds: float) -> str:
    if odds < 1.3:
        return "1.01-1.30"
    if odds < 1.6:
        return "1.30-1.60"
    if odds < 2:
        return "1.60-2.00"
    if odds < 3:
        return "2.00-3.00"
    if odds < 5:
        return "3.00-5.00"
    return "5.00+"


def build_market_bias_buckets(historical_records: list[dict[str, Any]], options: dict[str, Any] | None = None) -> list[MarketBiasBucket]:
    groups: dict[tuple, list[tuple[float, float, float]]] = {}
    for row in historical_records:
        odds = row.get("official_sp") or row.get("odds")
        if not odds:
            continue
        official = calculate_multi_devig_probabilities(odds).recommended_probability
        closing = calculate_multi_devig_probabilities(row.get("closing_sp") or odds).recommended_probability
        actual = str(row.get("actual_result") or "").lower()
        for outcome in OUTCOMES:
            key = (row.get("league"), outcome.upper(), _bucket(float(odds[outcome])), row.get("external_market_quality"), None)
            groups.setdefault(key, []).append((official[outcome], closing[outcome], 1.0 if actual == outcome else 0.0))
    buckets: list[MarketBiasBucket] = []
    for (league, outcome, odds_bucket, quality, deviation), rows in groups.items():
        n = len(rows)
        off = sum(r[0] for r in rows) / n
        close = sum(r[1] for r in rows) / n
        result = sum(r[2] for r in rows) / n
        bias_close = close - off
        bias_result = result - off
        shrink = 0 if n < 50 else 0.25 if n < 100 else 0.50 if n < 300 else 0.75
        correction = max(-0.03, min(0.03, bias_close * shrink))
        confidence = min(1.0, n / 300) * (0.8 if quality == "LOW" else 1.0)
        buckets.append(MarketBiasBucket(f"{league or 'GLOBAL'}:{outcome}:{odds_bucket}:{quality or 'ANY'}", league, outcome, odds_bucket, quality, deviation, n, off, close, result, bias_close, bias_result, abs(bias_close) - abs(bias_result), correction, confidence, [] if n >= 50 else ["sample too small; no correction recommended"]))
    return buckets


def apply_market_bias_correction(base_probability: Probability, match_context: dict[str, Any], bias_buckets: list[MarketBiasBucket]) -> tuple[Probability, MarketBiasBucket | None, list[str]]:
    probability = _normalize(base_probability) or {"home": 1 / 3, "draw": 1 / 3, "away": 1 / 3}
    league = match_context.get("league")
    outcome = str(match_context.get("outcome") or "ANY").upper()
    odds = float(match_context.get("odds") or 2)
    odds_bucket = _bucket(odds)
    candidates = [bucket for bucket in bias_buckets if bucket.sample_count >= 50 and bucket.odds_bucket == odds_bucket and bucket.outcome in {outcome, "ANY"} and (bucket.league == league or bucket.league is None)]
    if not candidates:
        return probability, None, ["no reliable market bias bucket"]
    selected = sorted(candidates, key=lambda item: (item.league == league, item.confidence), reverse=True)[0]
    key = outcome.lower()
    if key not in OUTCOMES:
        return probability, selected, ["no selected outcome for bias correction"]
    correction = selected.recommended_correction * (0.5 if key == "draw" else 1.0)
    adjusted = dict(probability)
    adjusted[key] = max(0.01, adjusted[key] + correction)
    return _normalize(adjusted) or probability, selected, []
