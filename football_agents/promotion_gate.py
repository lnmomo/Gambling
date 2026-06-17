from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from .shadow_evaluator import ShadowValidationMetrics
from .db import db
from .shadow_prediction_store import DATABASE_REGISTRY, ShadowPredictionStore, TrueOddsConfigVersion, dumps


@dataclass
class PromotionGateRule:
    rule_id: str
    description: str
    passed: bool
    value: float | int | str | None
    threshold: float | int | str | None
    severity: str
    message: str


@dataclass
class PromotionGateResult:
    config_version_id: str
    evaluated_at: str
    decision: str
    rules: list[PromotionGateRule]
    recommended_for_production: bool
    requires_human_confirmation: bool
    summary: list[str]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _val(value: float | None, fallback: float = 0.0) -> float:
    return fallback if value is None else value


def evaluate_promotion_gate(metrics: ShadowValidationMetrics, config_version: TrueOddsConfigVersion,
                            options: dict[str, Any] | None = None) -> PromotionGateResult:
    options = options or {}
    min_evaluated = int(options.get("min_evaluated", 200))
    rules = [
        PromotionGateRule("sample", "evaluated_count >= minimum", metrics.evaluated_count >= min_evaluated, metrics.evaluated_count, min_evaluated, "BLOCKING", "sample size"),
        PromotionGateRule("recommendations", "shadow_recommendation_count >= 30", metrics.shadow_recommendation_count >= 30, metrics.shadow_recommendation_count, 30, "BLOCKING", "recommendation count"),
        PromotionGateRule("positive_clv", "positive CLV rate improves by 5pp", _val(metrics.shadow_positive_clv_rate) >= _val(metrics.baseline_positive_clv_rate) + 0.05, metrics.shadow_positive_clv_rate, (_val(metrics.baseline_positive_clv_rate) + 0.05), "BLOCKING", "positive CLV improvement"),
        PromotionGateRule("avg_clv", "average CLV improves", _val(metrics.shadow_average_clv) > _val(metrics.baseline_average_clv), metrics.shadow_average_clv, metrics.baseline_average_clv, "BLOCKING", "average CLV improvement"),
        PromotionGateRule("drawdown", "max drawdown not worse than 110%", _val(metrics.shadow_max_drawdown) <= _val(metrics.baseline_max_drawdown) * 1.10 + 1e-12, metrics.shadow_max_drawdown, _val(metrics.baseline_max_drawdown) * 1.10, "WARNING", "drawdown guard"),
        PromotionGateRule("retention", "recommendation retention >= 40%", _val(metrics.recommendation_retention_rate, 1) >= 0.40, metrics.recommendation_retention_rate, 0.40, "WARNING", "retention guard"),
        PromotionGateRule("blocked", "blocked recommendation count >= 20", metrics.blocked_recommendation_count >= 20, metrics.blocked_recommendation_count, 20, "WARNING", "blocked sample"),
        PromotionGateRule("blocked_clv", "blocked average CLV is negative", _val(metrics.blocked_average_clv, -1) < 0, metrics.blocked_average_clv, 0, "WARNING", "blocked CLV"),
        PromotionGateRule("mode", "config mode is SHADOW or FILTER_ONLY", config_version.config.mode in {"SHADOW", "FILTER_ONLY"}, config_version.config.mode, "SHADOW/FILTER_ONLY", "BLOCKING", "mode guard"),
    ]
    blocking_failed = [rule for rule in rules if rule.severity == "BLOCKING" and not rule.passed]
    warnings: list[str] = []
    if config_version.config.mode == "ADJUST_PROBABILITY":
        warnings.append("ADJUST_PROBABILITY cannot be recommended")
    if metrics.evaluated_count < min_evaluated:
        decision = "NEED_MORE_DATA"
    elif blocking_failed:
        worse = _val(metrics.shadow_average_clv) < _val(metrics.baseline_average_clv) and _val(metrics.shadow_roi) < _val(metrics.baseline_roi)
        decision = "REJECT_CONFIG" if worse else "KEEP_SHADOW"
    else:
        decision = "ENABLE_FILTER_ONLY_RECOMMENDED"
    recommended = decision == "ENABLE_FILTER_ONLY_RECOMMENDED" and config_version.config.mode != "ADJUST_PROBABILITY"
    summary = [f"Decision: {decision}", "Human confirmation is required before production activation."]
    return PromotionGateResult(config_version.config_version_id, datetime.now(timezone.utc).isoformat(), decision,
                               rules, recommended, True, summary, warnings)


def save_promotion_gate_result(result: PromotionGateResult, metrics: ShadowValidationMetrics | None = None) -> dict[str, Any]:
    store = ShadowPredictionStore(DATABASE_REGISTRY.get(result.config_version_id, db))
    version = store.get_config_version(result.config_version_id)
    if version:
        before = version.to_dict()
        version.promotion_status = result.decision
        if result.decision == "ENABLE_FILTER_ONLY_RECOMMENDED":
            version.status = "RECOMMENDED_FOR_FILTER_ONLY"
        store.save_config_version(version)
        store._audit("evaluate_promotion_gate", result.config_version_id, before=before, after=result.to_dict())
    run = store.save_validation_run({
        "config_version_id": result.config_version_id,
        "from_date": None,
        "to_date": None,
        "metrics_json": dumps(metrics.to_dict() if metrics else {}),
        "promotion_gate_result_json": dumps(result.to_dict()),
        "decision": result.decision,
        "recommended_for_production": int(result.recommended_for_production),
        "warnings_json": dumps(result.warnings),
    })
    return run
