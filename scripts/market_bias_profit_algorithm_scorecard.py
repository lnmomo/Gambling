from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _candidate_screen_row(candidate_screen: dict[str, Any] | None, rule: str | None) -> dict[str, Any] | None:
    if not candidate_screen or not rule:
        return None
    for row in candidate_screen.get("rule_summary") or []:
        if row.get("rule") == rule:
            return row
    for row in candidate_screen.get("rows") or []:
        if row.get("rule") == rule:
            return row
    return None


def _historical_score(robustness: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    total_runs = float(robustness.get("total_runs") or 0)
    passed_runs = float(robustness.get("passed_runs") or 0)
    pass_rate = _ratio(passed_runs, total_runs)
    source_passes = float(robustness.get("source_passes") or 0)
    profile_passes = float(robustness.get("profile_passes") or 0)
    decision_bonus = 1.0 if robustness.get("decision") == "RESEARCH_CANDIDATE_SHADOW_VALIDATION" else 0.0
    score = (
        12.0 * _clamp(pass_rate / 0.75)
        + 8.0 * _clamp(source_passes / 4.0)
        + 6.0 * _clamp(profile_passes / 2.0)
        + 4.0 * decision_bonus
    )
    return round(score, 2), {
        "passed_runs": int(passed_runs),
        "total_runs": int(total_runs),
        "pass_rate": round(pass_rate, 4),
        "source_passes": int(source_passes),
        "profile_passes": int(profile_passes),
        "decision": robustness.get("decision"),
    }


def _portfolio_score(portfolio: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    overall = portfolio.get("overall") or {}
    profit = float(overall.get("profit") or 0)
    roi_pct = float(overall.get("roi_pct") or 0)
    max_drawdown = float(overall.get("max_drawdown") or 0)
    positive_months = int(portfolio.get("positive_months") or 0)
    negative_months = int(portfolio.get("negative_months") or 0)
    positive_seasons = int(portfolio.get("positive_seasons") or 0)
    negative_seasons = int(portfolio.get("negative_seasons") or 0)
    drawdown_to_profit = _ratio(max_drawdown, profit) if profit > 0 else 999.0
    score = (
        8.0 * _clamp(roi_pct / 5.0)
        + 5.0 * (1.0 if profit > 0 else 0.0)
        + 5.0 * _clamp((positive_months - negative_months) / 4.0)
        + 4.0 * (1.0 if positive_seasons > negative_seasons else 0.0)
        + 3.0 * _clamp(1.0 - drawdown_to_profit)
    )
    return round(score, 2), {
        "profit": round(profit, 2),
        "roi_pct": round(roi_pct, 2),
        "max_drawdown": round(max_drawdown, 2),
        "drawdown_to_profit": round(drawdown_to_profit, 4) if profit > 0 else None,
        "positive_months": positive_months,
        "negative_months": negative_months,
        "positive_seasons": positive_seasons,
        "negative_seasons": negative_seasons,
    }


def _cross_source_score(candidate_screen_row: dict[str, Any] | None) -> tuple[float, dict[str, Any]]:
    if not candidate_screen_row:
        return 0.0, {"available": False}
    validation_source_count = int(candidate_screen_row.get("validation_source_count") or 0)
    passed_validation_sources = int(candidate_screen_row.get("passed_validation_sources") or 0)
    combined_roi_pct = float(candidate_screen_row.get("combined_roi_pct") or 0)
    worst_source_roi_pct = float(candidate_screen_row.get("worst_source_roi_pct") or 0)
    total_bets = int(candidate_screen_row.get("total_portfolio_bets") or 0)
    score = (
        7.0 * _clamp(_ratio(passed_validation_sources, validation_source_count or 1))
        + 5.0 * _clamp(combined_roi_pct / 5.0)
        + 5.0 * _clamp(worst_source_roi_pct / 3.0)
        + 3.0 * _clamp(total_bets / 300.0)
    )
    return round(score, 2), {
        "available": True,
        "validation_source_count": validation_source_count,
        "passed_validation_sources": passed_validation_sources,
        "combined_roi_pct": round(combined_roi_pct, 2),
        "worst_source_roi_pct": round(worst_source_roi_pct, 2),
        "total_portfolio_bets": total_bets,
        "passes_all_validation_sources": bool(candidate_screen_row.get("passes_all_validation_sources")),
    }


def _official_score(official_sp: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    if "official_sp" in official_sp and isinstance(official_sp["official_sp"], dict):
        official_sp = official_sp["official_sp"]
    settled = int(official_sp.get("settled_candidate_count") or 0)
    roi_pct = float(official_sp.get("roi_pct") or 0)
    positive_months = int(official_sp.get("positive_months") or 0)
    negative_months = int(official_sp.get("negative_months") or 0)
    month_count = len(official_sp.get("monthly") or [])
    score = (
        6.0 * _clamp(settled / 100.0)
        + 5.0 * _clamp(month_count / 12.0)
        + 6.0 * _clamp(roi_pct / 3.0)
        + 3.0 * (1.0 if positive_months > negative_months and month_count > 0 else 0.0)
    )
    return round(score, 2), {
        "settled_candidate_count": settled,
        "roi_pct": round(roi_pct, 2),
        "active_months": month_count,
        "positive_months": positive_months,
        "negative_months": negative_months,
    }


def _governance_score(portfolio: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    config = portfolio.get("config") or {}
    walk_forward = portfolio.get("walk_forward_config") or {}
    settlement_safe = bool(config.get("same_day_results_hidden_until_settlement", True))
    walk_forward_safe = bool(walk_forward or portfolio.get("method"))
    score = 2.5 * settlement_safe + 2.5 * walk_forward_safe
    return round(score, 2), {
        "same_day_results_hidden_until_settlement": settlement_safe,
        "walk_forward_evidence_present": walk_forward_safe,
    }


def _statistical_audit_component(statistical_audit: dict[str, Any] | None) -> dict[str, Any]:
    if not statistical_audit:
        return {"available": False}
    overall = statistical_audit.get("overall") or {}
    bootstrap = statistical_audit.get("bootstrap") or {}
    sign_flip = statistical_audit.get("sign_flip_test") or {}
    return {
        "available": True,
        "decision": statistical_audit.get("decision"),
        "bets": int(overall.get("bets") or 0),
        "active_months": int(overall.get("active_months") or 0),
        "roi_pct": float(overall.get("roi_pct") or 0),
        "bootstrap_roi_p05": float((bootstrap.get("roi_ci_pct") or {}).get("p05") or 0),
        "bootstrap_probability_roi_positive": float(bootstrap.get("probability_roi_positive") or 0),
        "sign_flip_p_value": float(sign_flip.get("one_sided_p_value") or 1.0),
        "decision_reasons": list(statistical_audit.get("decision_reasons") or []),
    }


def _edge_calibration_component(edge_calibration: dict[str, Any] | None) -> dict[str, Any]:
    if not edge_calibration:
        return {"available": False}
    overall = edge_calibration.get("overall") or {}
    return {
        "available": True,
        "decision": edge_calibration.get("decision") or overall.get("decision"),
        "bets": int(overall.get("bets") or 0),
        "hit_rate": float(overall.get("hit_rate") or 0),
        "wilson_hit_rate_lower_95": float(overall.get("wilson_hit_rate_lower_95") or 0),
        "avg_implied_probability": float(overall.get("avg_implied_probability") or 0),
        "edge_vs_implied_probability": float(overall.get("edge_vs_implied_probability") or 0),
        "conservative_edge_vs_implied": float(overall.get("conservative_edge_vs_implied") or 0),
        "roi_pct": float(overall.get("roi_pct") or 0),
        "decision_reasons": list(edge_calibration.get("decision_reasons") or overall.get("decision_reasons") or []),
    }


def _deployment_tier(score: float, promotion: dict[str, Any], official_component: dict[str, Any],
                     cross_source_component: dict[str, Any]) -> str:
    if promotion.get("recommended_for_production") and score >= 85:
        return "PRODUCTION_REVIEW"
    if promotion.get("recommended_for_shadow") and score >= 55:
        return "SHADOW_READY_PRODUCTION_BLOCKED"
    if cross_source_component.get("passes_all_validation_sources") and score >= 55:
        return "RESEARCH_WATCH_ONLY"
    if official_component.get("settled_candidate_count", 0) == 0 and score >= 50:
        return "HISTORICAL_ONLY_NEEDS_OFFICIAL_SP"
    return "REJECT_OR_KEEP_RESEARCH_BACKLOG"


def _multi_window_row(multi_window: dict[str, Any] | None, strategy_id: str) -> dict[str, Any] | None:
    if not multi_window:
        return None
    for row in multi_window.get("candidate_summaries") or []:
        if row.get("candidate_id") == strategy_id:
            return row
        candidate_id = str(row.get("candidate_id") or "")
        if strategy_id.startswith(candidate_id) or candidate_id.startswith(strategy_id):
            return row
    for row in multi_window.get("summaries") or []:
        if row.get("candidate_id") == strategy_id:
            return row
        candidate_id = str(row.get("candidate_id") or "")
        if strategy_id.startswith(candidate_id) or candidate_id.startswith(strategy_id):
            return row
    return None


def _apply_multi_window_gate(tier: str, multi_window_row: dict[str, Any] | None) -> tuple[str, dict[str, Any]]:
    if not multi_window_row:
        return tier, {"available": False}
    decision = multi_window_row.get("decision")
    validation = {
        "available": True,
        "decision": decision,
        "passed_windows": int(multi_window_row.get("passed_windows") or 0),
        "window_count": int(multi_window_row.get("window_count") or 0),
        "pass_rate": float(multi_window_row.get("pass_rate") or 0),
        "source_passes": int(multi_window_row.get("source_passes") or 0),
        "source_count": int(multi_window_row.get("source_count") or 0),
        "combined_roi_pct": float(multi_window_row.get("combined_roi_pct") or 0),
        "worst_window_roi_pct": float(multi_window_row.get("worst_window_roi_pct") or 0),
    }
    if decision == "MULTI_WINDOW_SHADOW_CANDIDATE":
        return tier, validation
    if tier in {"SHADOW_READY_PRODUCTION_BLOCKED", "PRODUCTION_REVIEW"}:
        return "RESEARCH_ONLY_UNSTABLE_WINDOWS", validation
    return tier, validation


def _apply_statistical_audit_gate(tier: str, component: dict[str, Any]) -> str:
    if not component.get("available"):
        return tier
    if component.get("decision") == "STATISTICALLY_SUPPORTED_RESEARCH_CANDIDATE":
        return tier
    if tier in {"SHADOW_READY_PRODUCTION_BLOCKED", "PRODUCTION_REVIEW"}:
        return "RESEARCH_ONLY_STATISTICALLY_WEAK"
    return tier


def _apply_edge_calibration_gate(tier: str, component: dict[str, Any]) -> str:
    if not component.get("available"):
        return tier
    if component.get("decision") == "CALIBRATED_EDGE_CONFIRMED":
        return tier
    if tier in {"SHADOW_READY_PRODUCTION_BLOCKED", "PRODUCTION_REVIEW"}:
        return "RESEARCH_ONLY_CALIBRATION_WEAK"
    return tier


def evaluate_profit_algorithm_scorecard(
    *,
    strategy_id: str,
    rule: str | None,
    robustness: dict[str, Any],
    portfolio: dict[str, Any],
    official_sp: dict[str, Any],
    promotion: dict[str, Any],
    candidate_screen: dict[str, Any] | None = None,
    multi_window: dict[str, Any] | None = None,
    statistical_audit: dict[str, Any] | None = None,
    edge_calibration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    screen_row = _candidate_screen_row(candidate_screen, rule)
    historical_score, historical_component = _historical_score(robustness)
    portfolio_score, portfolio_component = _portfolio_score(portfolio)
    cross_source_score, cross_source_component = _cross_source_score(screen_row)
    official_score, official_component = _official_score(official_sp)
    governance_score, governance_component = _governance_score(portfolio)
    statistical_component = _statistical_audit_component(statistical_audit)
    edge_calibration_component = _edge_calibration_component(edge_calibration)
    total_score = round(
        historical_score
        + portfolio_score
        + cross_source_score
        + official_score
        + governance_score,
        2,
    )
    initial_tier = _deployment_tier(total_score, promotion, official_component, cross_source_component)
    tier, multi_window_component = _apply_multi_window_gate(initial_tier, _multi_window_row(multi_window, strategy_id))
    tier = _apply_statistical_audit_gate(tier, statistical_component)
    tier = _apply_edge_calibration_gate(tier, edge_calibration_component)
    blockers = list(promotion.get("failed_blocking_checks") or [])
    production_blockers = list(promotion.get("failed_production_checks") or [])
    return {
        "method": "market-bias profit algorithm scorecard",
        "strategy_id": strategy_id,
        "rule": rule,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "score": total_score,
        "max_score": 100.0,
        "deployment_tier": tier,
        "pre_multi_window_tier": initial_tier,
        "promotion_decision": promotion.get("decision") or promotion.get("promotion_decision"),
        "recommended_for_shadow": tier in {"SHADOW_READY_PRODUCTION_BLOCKED", "PRODUCTION_REVIEW"},
        "recommended_for_production": tier == "PRODUCTION_REVIEW",
        "components": {
            "historical_robustness": {"score": historical_score, "max_score": 30.0, **historical_component},
            "settlement_portfolio": {"score": portfolio_score, "max_score": 25.0, **portfolio_component},
            "cross_source_validation": {"score": cross_source_score, "max_score": 20.0, **cross_source_component},
            "official_sp_prospective": {"score": official_score, "max_score": 20.0, **official_component},
            "multi_window_validation": multi_window_component,
            "statistical_audit": statistical_component,
            "edge_calibration": edge_calibration_component,
            "governance": {"score": governance_score, "max_score": 5.0, **governance_component},
        },
        "blocking_checks_failed": blockers,
        "production_checks_failed": production_blockers,
        "interpretation": (
            "Historical edge is strong enough for shadow monitoring, but official-SP prospective samples still block production."
            if tier == "SHADOW_READY_PRODUCTION_BLOCKED"
            else "Historical edge is positive, but multi-window validation is not stable enough for shadow promotion."
            if tier == "RESEARCH_ONLY_UNSTABLE_WINDOWS"
            else "Historical edge is positive, but statistical audit is not strong enough for shadow promotion."
            if tier == "RESEARCH_ONLY_STATISTICALLY_WEAK"
            else "Historical edge is positive, but selected-odds calibration is not conservative enough for shadow promotion."
            if tier == "RESEARCH_ONLY_CALIBRATION_WEAK"
            else "Keep collecting evidence before this strategy can influence betting decisions."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy-id", required=True)
    parser.add_argument("--rule", default="")
    parser.add_argument("--robustness", type=Path, required=True)
    parser.add_argument("--portfolio", type=Path, required=True)
    parser.add_argument("--official-sp", type=Path, required=True)
    parser.add_argument("--promotion", type=Path, required=True)
    parser.add_argument("--candidate-screen", type=Path)
    parser.add_argument("--multi-window", type=Path)
    parser.add_argument("--statistical-audit", type=Path)
    parser.add_argument("--edge-calibration", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate_profit_algorithm_scorecard(
        strategy_id=args.strategy_id,
        rule=args.rule or None,
        robustness=_load(args.robustness),
        portfolio=_load(args.portfolio),
        official_sp=_load(args.official_sp),
        promotion=_load(args.promotion),
        candidate_screen=_load(args.candidate_screen) if args.candidate_screen else None,
        multi_window=_load(args.multi_window) if args.multi_window else None,
        statistical_audit=_load(args.statistical_audit) if args.statistical_audit else None,
        edge_calibration=_load(args.edge_calibration) if args.edge_calibration else None,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
