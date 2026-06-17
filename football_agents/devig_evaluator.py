from __future__ import annotations

from dataclasses import dataclass, field
from math import log
from typing import Any

from .market_bias import _bucket
from .multi_devig import OUTCOMES, DevigMethod, calculate_multi_devig_probabilities


@dataclass
class DevigMethodPerformance:
    method: str
    league: str | None
    bucket: str
    outcome: str | None
    sample_count: int
    log_loss: float
    brier_score: float
    calibration_error: float
    average_clv: float | None
    positive_clv_rate: float | None
    rank: int
    recommended: bool
    warnings: list[str] = field(default_factory=list)


def evaluate_devig_methods(historical_records: list[dict[str, Any]], options: dict[str, Any] | None = None) -> list[DevigMethodPerformance]:
    groups: dict[tuple, list[tuple[float, float, float | None]]] = {}
    for row in historical_records:
        odds = row.get("official_sp") or row.get("odds")
        actual = str(row.get("actual_result") or "").lower()
        if not odds or actual not in OUTCOMES:
            continue
        result = calculate_multi_devig_probabilities(odds)
        closing = row.get("closing_sp")
        closing_prob = calculate_multi_devig_probabilities(closing).recommended_probability if closing else None
        for method, probability_set in result.methods.items():
            if not probability_set.valid:
                continue
            p = max(1e-15, min(1 - 1e-15, probability_set.probability[actual]))
            brier = sum((probability_set.probability[key] - (1 if actual == key else 0)) ** 2 for key in OUTCOMES) / 3
            clv = probability_set.probability[actual] - closing_prob[actual] if closing_prob else None
            bucket = _bucket(float(odds[actual]))
            groups.setdefault((row.get("league"), bucket, actual.upper(), method), []).append((-log(p), brier, clv))
            groups.setdefault((None, "GLOBAL", None, method), []).append((-log(p), brier, clv))
    rows: list[DevigMethodPerformance] = []
    for (league, bucket, outcome, method), values in groups.items():
        n = len(values)
        log_loss = sum(v[0] for v in values) / n
        brier = sum(v[1] for v in values) / n
        clvs = [v[2] for v in values if v[2] is not None]
        calibration_error = abs(sum(min(1, max(0, 1 - v[0])) for v in values) / n - 1 / 3)
        warnings = [] if n >= 50 else ["sample_count < 50; do not force recommendation"]
        rows.append(DevigMethodPerformance(method, league, bucket, outcome, n, log_loss, brier, calibration_error, sum(clvs) / len(clvs) if clvs else None, sum(1 for v in clvs if v > 0) / len(clvs) if clvs else None, 0, False, warnings))
    for key in {(row.league, row.bucket, row.outcome) for row in rows}:
        group = sorted([row for row in rows if (row.league, row.bucket, row.outcome) == key], key=lambda row: (row.sample_count < 50, row.log_loss, row.brier_score))
        for index, row in enumerate(group, 1):
            row.rank = index
            row.recommended = index == 1 and row.sample_count >= 50
    return rows


def select_best_devig_method_for_context(context: dict[str, Any], performance_records: list[DevigMethodPerformance]) -> str:
    league = context.get("league")
    bucket = context.get("bucket") or context.get("odds_bucket")
    outcome = context.get("outcome")
    outcome = str(outcome).upper() if outcome else None
    tiers = [
        lambda row: row.league == league and row.bucket == bucket and row.outcome == outcome,
        lambda row: row.league == league and row.bucket == bucket,
        lambda row: row.league == league,
        lambda row: row.league is None and row.bucket == "GLOBAL",
    ]
    for predicate in tiers:
        candidates = [row for row in performance_records if predicate(row) and row.sample_count >= 50]
        if candidates:
            return sorted(candidates, key=lambda row: (row.rank or 999, row.log_loss))[0].method
    return DevigMethod.POWER.value
