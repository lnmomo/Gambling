from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from typing import Any

from .multi_devig import calculate_multi_devig_probabilities
from .db import Database, db
from .market_bias_shadow_strategy import MARKET_BIAS_PORTFOLIO_STRATEGIES
from .shadow_prediction_store import DATABASE_REGISTRY, ShadowPredictionStore, dumps


@dataclass
class MarketBiasStrategyMetrics:
    strategy_id: str
    sample_count: int
    evaluated_count: int
    pending_count: int
    profit: float | None
    roi: float | None
    hit_rate: float | None
    max_drawdown: float | None


@dataclass
class ShadowValidationMetrics:
    config_version_id: str
    created_at: str
    sample_count: int
    evaluated_count: int
    pending_count: int
    void_count: int
    baseline_recommendation_count: int
    shadow_recommendation_count: int
    shadow_blocked_count: int
    shadow_added_count: int
    baseline_roi: float | None
    shadow_roi: float | None
    baseline_average_clv: float | None
    shadow_average_clv: float | None
    baseline_positive_clv_rate: float | None
    shadow_positive_clv_rate: float | None
    baseline_hit_rate: float | None
    shadow_hit_rate: float | None
    baseline_max_drawdown: float | None
    shadow_max_drawdown: float | None
    blocked_recommendation_count: int
    blocked_roi: float | None
    blocked_average_clv: float | None
    blocked_positive_clv_rate: float | None
    passed_recommendation_count: int
    passed_roi: float | None
    passed_average_clv: float | None
    passed_positive_clv_rate: float | None
    high_edge_count: int
    medium_edge_count: int
    low_edge_count: int
    no_edge_count: int
    high_edge_roi: float | None
    medium_edge_roi: float | None
    recommendation_retention_rate: float | None
    no_bet_increase_rate: float | None
    market_bias_strategy_metrics: list[MarketBiasStrategyMetrics] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _profit(action: str, sp: float | None, actual: str | None) -> float:
    if action == "NO_BET" or not sp or not actual:
        return 0.0
    return sp - 1 if action == actual else -1.0


def _clv(action: str, sp: float | None, closing: dict[str, float] | None) -> float | None:
    if action == "NO_BET" or not sp or not closing:
        return None
    key = action.lower()
    if closing.get(key, 0) <= 1:
        return None
    return sp / closing[key] - 1


def _shadow_sp(shadow_prediction: dict[str, Any]) -> float | None:
    action = shadow_prediction.get("shadow_recommendation")
    if action == "NO_BET":
        return None
    if action == shadow_prediction.get("baseline_recommendation"):
        return shadow_prediction.get("baseline_official_sp")
    payload = shadow_prediction.get("true_odds_estimate")
    if not isinstance(payload, dict):
        try:
            payload = json.loads(shadow_prediction.get("true_odds_estimate_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            payload = {}
    candidate = payload.get("market_bias_shadow_candidate") or {}
    if str(candidate.get("outcome") or "").upper() == str(action or "").upper():
        try:
            return float(candidate["selected_sp"])
        except (KeyError, TypeError, ValueError):
            return None
    return None


def evaluate_shadow_prediction(shadow_prediction: dict[str, Any], actual_result: str | None,
                               closing_snapshot: dict[str, float] | None = None) -> dict[str, Any]:
    warnings: list[str] = []
    if not actual_result:
        status = "MISSING_RESULT"
    else:
        status = "EVALUATED"
    if actual_result in {"VOID", "CANCELLED", "POSTPONED"}:
        status = "VOID"
    if not closing_snapshot:
        warnings.append("closing_sp unavailable; CLV not calculated")
    baseline_action = shadow_prediction["baseline_recommendation"]
    shadow_action = shadow_prediction["shadow_recommendation"]
    baseline_sp = shadow_prediction.get("baseline_official_sp")
    shadow_sp = _shadow_sp(shadow_prediction)
    closing_prob = calculate_multi_devig_probabilities(closing_snapshot).recommended_probability if closing_snapshot else None
    result = {
        "shadow_prediction_id": shadow_prediction["id"],
        "match_id": shadow_prediction["match_id"],
        "official_match_id": shadow_prediction["official_match_id"],
        "actual_result": actual_result,
        "closing_sp_json": dumps(closing_snapshot),
        "closing_probability_json": dumps(closing_prob),
        "baseline_profit": None if status == "MISSING_RESULT" else _profit(baseline_action, baseline_sp, actual_result),
        "shadow_profit": None if status == "MISSING_RESULT" else _profit(shadow_action, shadow_sp, actual_result),
        "baseline_clv": _clv(baseline_action, baseline_sp, closing_snapshot),
        "shadow_clv": _clv(shadow_action, shadow_sp, closing_snapshot),
        "baseline_hit": None if baseline_action == "NO_BET" or not actual_result else int(baseline_action == actual_result),
        "shadow_hit": None if shadow_action == "NO_BET" or not actual_result else int(shadow_action == actual_result),
        "baseline_would_have_bet": int(baseline_action != "NO_BET"),
        "shadow_would_have_bet": int(shadow_action != "NO_BET"),
        "shadow_blocked_baseline": int(shadow_prediction["shadow_would_block_baseline"]),
        "shadow_added_new_recommendation": int(shadow_prediction["shadow_would_recommend_new"]),
        "evaluation_status": status,
        "warnings_json": dumps(warnings),
    }
    return ShadowPredictionStore(shadow_prediction.get("_database", db)).save_post_match_result(result)


def _mean(values: list[float | None]) -> float | None:
    clean = [v for v in values if v is not None]
    return sum(clean) / len(clean) if clean else None


def _rate(values: list[bool]) -> float | None:
    return sum(values) / len(values) if values else None


def _drawdown(profits: list[float | None]) -> float | None:
    equity = peak = worst = 0.0
    clean = [p for p in profits if p is not None]
    if not clean:
        return None
    for profit in clean:
        equity += profit
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return worst


def _market_bias_strategy_id(prediction: dict[str, Any]) -> str | None:
    payload = prediction.get("true_odds_estimate")
    if not isinstance(payload, dict):
        try:
            payload = json.loads(prediction.get("true_odds_estimate_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            payload = {}
    candidate = payload.get("market_bias_shadow_candidate") or {}
    value = str(candidate.get("strategy_id") or "").strip()
    return value or None


def _build_market_bias_strategy_metrics(predictions: list[dict[str, Any]],
                                        results: list[dict[str, Any]]) -> list[MarketBiasStrategyMetrics]:
    result_by_prediction_id = {row["shadow_prediction_id"]: row for row in results}
    leaf_predictions: dict[str, list[dict[str, Any]]] = {}
    for prediction in predictions:
        strategy_id = _market_bias_strategy_id(prediction)
        if not strategy_id:
            continue
        leaf_predictions.setdefault(strategy_id, []).append(prediction)
    strategy_groups: dict[str, list[dict[str, Any]]] = {key: list(value) for key, value in leaf_predictions.items()}
    for combo_id, leaf_ids in MARKET_BIAS_PORTFOLIO_STRATEGIES.items():
        combo_predictions = [
            prediction
            for leaf_id in leaf_ids
            for prediction in leaf_predictions.get(leaf_id, [])
        ]
        if combo_predictions:
            strategy_groups[combo_id] = combo_predictions
    output = []
    for strategy_id, rows in sorted(strategy_groups.items()):
        evaluated_results = [
            result_by_prediction_id[row["id"]]
            for row in rows
            if result_by_prediction_id.get(row["id"], {}).get("evaluation_status") == "EVALUATED"
        ]
        profits = [row["shadow_profit"] for row in evaluated_results]
        wins = [row["shadow_hit"] for row in evaluated_results if row["shadow_hit"] is not None]
        profit = sum(profit for profit in profits if profit is not None) if evaluated_results else None
        evaluated_count = len(evaluated_results)
        output.append(MarketBiasStrategyMetrics(
            strategy_id=strategy_id,
            sample_count=len(rows),
            evaluated_count=evaluated_count,
            pending_count=len(rows) - evaluated_count,
            profit=round(profit, 4) if profit is not None else None,
            roi=round(profit / evaluated_count, 4) if profit is not None and evaluated_count else None,
            hit_rate=round(sum(bool(win) for win in wins) / len(wins), 4) if wins else None,
            max_drawdown=_drawdown(profits),
        ))
    return output


def build_shadow_validation_metrics(config_version_id: str, from_date: str | None = None, to_date: str | None = None) -> ShadowValidationMetrics:
    store = ShadowPredictionStore(DATABASE_REGISTRY.get(config_version_id, db))
    predictions = store.list_shadow_predictions(config_version_id)
    results = store.list_post_match_results(config_version_id)
    pred_by_id = {row["id"]: row for row in predictions}
    evaluated = [row for row in results if row["evaluation_status"] == "EVALUATED"]
    blocked = [row for row in evaluated if row["shadow_blocked_baseline"]]
    passed = [row for row in evaluated if row["shadow_would_have_bet"]]
    def roi(rows: list[dict[str, Any]], key: str) -> float | None:
        bets = [row for row in rows if row[f"{key}_would_have_bet"]]
        return _mean([row[f"{key}_profit"] for row in bets])
    warnings = ["shadow evaluated sample is small"] if len(evaluated) < 50 else []
    return ShadowValidationMetrics(
        config_version_id, datetime.now(timezone.utc).isoformat(), len(predictions), len(evaluated),
        sum(row["lifecycle_status"] == "PENDING_RESULT" for row in predictions),
        sum(row["evaluation_status"] == "VOID" for row in results),
        sum(row["baseline_recommendation"] != "NO_BET" for row in predictions),
        sum(row["shadow_recommendation"] != "NO_BET" for row in predictions),
        sum(row["shadow_would_block_baseline"] for row in predictions),
        sum(row["shadow_would_recommend_new"] for row in predictions),
        roi(evaluated, "baseline"), roi(evaluated, "shadow"),
        _mean([row["baseline_clv"] for row in evaluated]), _mean([row["shadow_clv"] for row in evaluated]),
        _rate([row["baseline_clv"] > 0 for row in evaluated if row["baseline_clv"] is not None]),
        _rate([row["shadow_clv"] > 0 for row in evaluated if row["shadow_clv"] is not None]),
        _rate([bool(row["baseline_hit"]) for row in evaluated if row["baseline_hit"] is not None]),
        _rate([bool(row["shadow_hit"]) for row in evaluated if row["shadow_hit"] is not None]),
        _drawdown([row["baseline_profit"] for row in evaluated]), _drawdown([row["shadow_profit"] for row in evaluated]),
        len(blocked), roi(blocked, "baseline"), _mean([row["baseline_clv"] for row in blocked]),
        _rate([row["baseline_clv"] > 0 for row in blocked if row["baseline_clv"] is not None]),
        len(passed), roi(passed, "shadow"), _mean([row["shadow_clv"] for row in passed]),
        _rate([row["shadow_clv"] > 0 for row in passed if row["shadow_clv"] is not None]),
        sum((pred_by_id.get(row["shadow_prediction_id"], {}).get("shadow_edge_quality_level") == "HIGH") for row in results),
        sum((pred_by_id.get(row["shadow_prediction_id"], {}).get("shadow_edge_quality_level") == "MEDIUM") for row in results),
        sum((pred_by_id.get(row["shadow_prediction_id"], {}).get("shadow_edge_quality_level") == "LOW") for row in results),
        sum((pred_by_id.get(row["shadow_prediction_id"], {}).get("shadow_edge_quality_level") == "NO_EDGE") for row in results),
        roi([row for row in evaluated if pred_by_id.get(row["shadow_prediction_id"], {}).get("shadow_edge_quality_level") == "HIGH"], "shadow"),
        roi([row for row in evaluated if pred_by_id.get(row["shadow_prediction_id"], {}).get("shadow_edge_quality_level") == "MEDIUM"], "shadow"),
        (sum(row["shadow_recommendation"] != "NO_BET" for row in predictions) / sum(row["baseline_recommendation"] != "NO_BET" for row in predictions)) if sum(row["baseline_recommendation"] != "NO_BET" for row in predictions) else None,
        (sum(row["shadow_would_block_baseline"] for row in predictions) / len(predictions)) if predictions else None,
        _build_market_bias_strategy_metrics(predictions, results),
        warnings,
    )


def _stored_result(database: Database, match_id: str | int) -> str | None:
    with database.connect() as c:
        row = c.execute("SELECT outcome FROM results WHERE match_id=?", (match_id,)).fetchone()
    return str(row["outcome"]).upper() if row else None


def _closing_sp(database: Database, match_id: str | int) -> dict[str, float] | None:
    with database.connect() as c:
        row = c.execute("""SELECT home_sp,draw_sp,away_sp FROM official_odds_closing_observations
            WHERE match_id=? LIMIT 1""", (match_id,)).fetchone()
    if not row:
        return None
    return {"home": float(row["home_sp"]), "draw": float(row["draw_sp"]), "away": float(row["away_sp"])}


def evaluate_pending_shadow_predictions(config_version_id: str | None = None,
                                        database: Database | None = None) -> dict[str, int]:
    active_db = database or DATABASE_REGISTRY.get(config_version_id or "", db)
    store = ShadowPredictionStore(active_db)
    pending = store.list_shadow_predictions(config_version_id, "PENDING_RESULT")
    evaluated = missing_result = missing_closing = void = errors = 0
    for prediction in pending:
        prediction["_database"] = active_db
        try:
            actual = _stored_result(active_db, prediction["match_id"])
            if not actual:
                missing_result += 1
                continue
            closing = _closing_sp(active_db, prediction["match_id"])
            if closing is None:
                missing_closing += 1
            result = evaluate_shadow_prediction(prediction, actual, closing)
            if result["evaluation_status"] == "VOID":
                void += 1
            elif result["evaluation_status"] == "EVALUATED":
                evaluated += 1
        except Exception:
            errors += 1
    remaining = store.list_shadow_predictions(config_version_id, "PENDING_RESULT")
    return {
        "evaluated": evaluated,
        "pending": len(remaining),
        "missing_result": missing_result,
        "missing_closing": missing_closing,
        "void": void,
        "errors": errors,
    }
