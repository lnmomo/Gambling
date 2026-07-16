from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .config import settings
from .official_sp_evidence_quality import build_official_sp_evidence_quality
from .profit_strategy_registry import list_profit_strategy_packages


REQUIRED_OFFICIAL_SETTLED_SELECTED = 200
REQUIRED_ACTIVE_MONTHS = 6
REQUIRED_CLOSING_SP_COVERAGE = 0.80
REQUIRED_POSITIVE_CLV_RATE = 0.50
REQUIRED_SETTLEMENT_DAYS = 30
MAX_STRATEGY_SHARE = 0.60


def _is_historically_supported(strategy: dict[str, Any]) -> bool:
    if strategy.get("evidence_basis") == "PRE_REGISTERED_PROSPECTIVE":
        return True
    status = str(strategy.get("status") or "")
    if status.startswith("RESEARCH_ONLY") or strategy.get("recommended_for_shadow") is False:
        return False
    audit = strategy.get("audit") or {}
    calibration = strategy.get("calibration") or {}
    calibration_confirmed = calibration.get("decision") == "CALIBRATED_EDGE_CONFIRMED"
    cross_source = strategy.get("cross_source_validation") or {}
    cross_source_supported = (
        calibration.get("decision") == "POSITIVE_EDGE_BUT_NOT_CONSERVATIVE"
        and cross_source.get("passes_all_sources") is True
    )
    return audit.get("decision") == "STATISTICALLY_SUPPORTED_RESEARCH_CANDIDATE" and (
        calibration_confirmed or cross_source_supported
    )


def _official_selected_count(strategy: dict[str, Any]) -> int:
    official = strategy.get("official_validation") or {}
    try:
        return int(official.get("settled_selected_snapshots") or 0)
    except (TypeError, ValueError):
        return 0


def _official_pool_passed(strategy: dict[str, Any]) -> int:
    official = strategy.get("official_validation") or {}
    try:
        return int(official.get("pool_passed_scorer") or 0)
    except (TypeError, ValueError):
        return 0


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _official_monthly(official: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [row for row in (official.get("monthly") or []) if isinstance(row, dict)]
    return sorted(rows, key=lambda row: str(row.get("month") or ""))


def _active_months(official: dict[str, Any]) -> int:
    return len({str(row.get("month")) for row in _official_monthly(official) if row.get("month")})


def _official_daily(official: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [row for row in (official.get("daily") or []) if isinstance(row, dict)]
    return sorted(rows, key=lambda row: str(row.get("date") or ""))


def _current_drawdown(rows: list[dict[str, Any]]) -> tuple[float, float, float]:
    equity = peak = 0.0
    for row in rows:
        equity += _number(row.get("profit"))
        peak = max(peak, equity)
    return max(0.0, peak - equity), peak, equity


def _negative_month_streak(monthly: list[dict[str, Any]]) -> int:
    streak = 0
    for row in reversed(monthly):
        if _number(row.get("profit")) < 0:
            streak += 1
        else:
            break
    return streak


def _risk_control(official: dict[str, Any]) -> dict[str, Any]:
    monthly = _official_monthly(official)
    path = _official_daily(official) or monthly
    negative_streak = _negative_month_streak(monthly)
    current_drawdown, peak_equity, current_equity = _current_drawdown(path)
    drawdown_ratio = current_drawdown / max(peak_equity, 1.0) if peak_equity > 0 else 1.0
    if not monthly:
        state = "WAITING_FOR_EVIDENCE"
        multiplier = 0.0
        drawdown_ratio = 0.0
        reason = "No settled official-SP monthly return series is available yet."
    elif negative_streak >= 2:
        state = "COOLDOWN"
        multiplier = 0.0
        reason = "Two consecutive losing active months triggered the strategy cooldown."
    elif drawdown_ratio >= 0.50:
        state = "REDUCED"
        multiplier = 0.50
        reason = "Current daily-path drawdown is at least 50% of peak official-SP profit."
    elif negative_streak == 1 or drawdown_ratio >= 0.25:
        state = "REDUCED"
        multiplier = 0.75
        reason = "Recent loss or drawdown triggered a reduced paper allocation."
    else:
        state = "NORMAL"
        multiplier = 1.0
        reason = "No portfolio drawdown reduction is active."
    return {
        "state": state,
        "multiplier": multiplier,
        "negative_month_streak": negative_streak,
        "current_drawdown": round(current_drawdown, 2),
        "current_drawdown_to_peak": round(drawdown_ratio, 4),
        "peak_equity": round(peak_equity, 2),
        "current_equity": round(current_equity, 2),
        "path_grain": "daily" if _official_daily(official) else "monthly",
        "reason": reason,
    }


def _official_evidence_failures(official: dict[str, Any], settled_selected: int) -> list[str]:
    failures: list[str] = []
    active_months = _active_months(official)
    profit = _number(official.get("profit"))
    max_drawdown = _number(official.get("max_drawdown"))
    positive_months = int(_number(official.get("positive_months")))
    negative_months = int(_number(official.get("negative_months")))
    monthly = _official_monthly(official)
    derived_profit = round(sum(_number(row.get("profit")) for row in monthly), 2)
    derived_positive_months = sum(_number(row.get("profit")) > 0 for row in monthly)
    derived_negative_months = sum(_number(row.get("profit")) < 0 for row in monthly)
    closing_coverage = _number(official.get("closing_sp_coverage"))
    average_clv = _number(official.get("average_clv"), -1.0)
    positive_clv_rate = _number(official.get("positive_clv_rate"), -1.0)
    statistical = official.get("statistical_evidence") or {}
    point = statistical.get("point_estimates") or {}
    bootstrap = statistical.get("bootstrap") or {}
    if settled_selected < REQUIRED_OFFICIAL_SETTLED_SELECTED:
        failures.append("settled_selected<200")
    if active_months < REQUIRED_ACTIVE_MONTHS:
        failures.append("active_months<6")
    if monthly and abs(derived_profit - profit) > 0.01:
        failures.append("official_profit_inconsistent_with_monthly")
    if monthly and (
        derived_positive_months != positive_months or derived_negative_months != negative_months
    ):
        failures.append("month_counts_inconsistent_with_monthly")
    if profit <= 0:
        failures.append("official_profit<=0")
    if max_drawdown > max(profit, 1.0):
        failures.append("official_max_drawdown>profit")
    if positive_months <= negative_months:
        failures.append("positive_months<=negative_months")
    if closing_coverage < REQUIRED_CLOSING_SP_COVERAGE:
        failures.append("closing_sp_coverage<0.8")
    if average_clv <= 0:
        failures.append("average_clv<=0")
    if positive_clv_rate < REQUIRED_POSITIVE_CLV_RATE:
        failures.append("positive_clv_rate<0.5")
    if settled_selected >= REQUIRED_OFFICIAL_SETTLED_SELECTED and active_months >= REQUIRED_ACTIVE_MONTHS:
        if int(_number(bootstrap.get("settlement_days"))) < REQUIRED_SETTLEMENT_DAYS:
            failures.append("settlement_days<30")
        if _number((bootstrap.get("roi_ci_pct") or {}).get("p05"), -1.0) <= 0:
            failures.append("bootstrap_roi_p05<=0")
        if (
            closing_coverage >= REQUIRED_CLOSING_SP_COVERAGE
            and _number((bootstrap.get("average_clv_ci") or {}).get("p05"), -1.0) <= 0
        ):
            failures.append("bootstrap_clv_p05<=0")
        if _number(point.get("brier_improvement"), -1.0) < 0:
            failures.append("model_brier_worse_than_market")
        if _number(point.get("log_loss_improvement"), -1.0) < 0:
            failures.append("model_log_loss_worse_than_market")
        brier_p05 = _number((bootstrap.get("brier_improvement_ci") or {}).get("p05"), -1.0)
        log_loss_p05 = _number((bootstrap.get("log_loss_improvement_ci") or {}).get("p05"), -1.0)
        if brier_p05 <= 0 and log_loss_p05 <= 0:
            failures.append("relative_calibration_confidence_not_positive")
    return failures


def _strategy_status(strategy: dict[str, Any]) -> dict[str, Any]:
    official = strategy.get("official_validation") or {}
    historical_supported = _is_historically_supported(strategy)
    settled_selected = _official_selected_count(strategy)
    pool_passed = _official_pool_passed(strategy)
    official_decision = str(official.get("decision") or "PENDING_OFFICIAL_SP_VALIDATION")
    active_months = _active_months(official)
    evidence_failures = _official_evidence_failures(official, settled_selected)
    risk_control = _risk_control(official)
    blockers = list(strategy.get("deployment_blockers") or [])
    top_blockers = list(official.get("top_pool_blockers") or official.get("top_snapshot_blockers") or [])

    official_ready = (
        official_decision == "OFFICIAL_SP_PROSPECTIVE_PASS"
        and not evidence_failures
    )
    if official_ready and risk_control["state"] == "COOLDOWN":
        action = "RISK_COOLDOWN"
        reason = risk_control["reason"]
    elif official_ready:
        action = "PAPER_ALLOCATION_READY"
        reason = "Historical audit, edge calibration, and official-SP prospective validation have all passed."
    elif not historical_supported:
        action = "RESEARCH_ONLY"
        reason = "Historical statistical audit or calibration is not yet strong enough for daily allocation."
    elif pool_passed <= 0:
        action = "WAIT_FOR_ELIGIBLE_OFFICIAL_POOL"
        reason = "The strategy is historically supported, but the current official pool has no eligible scored selections."
    else:
        action = "WAIT_FOR_OFFICIAL_SP_SETTLEMENT"
        reason = (
            "The strategy has eligible official-pool selections, but not enough settled official-SP "
            "shadow samples for allocation promotion."
        )

    return {
        "strategy_id": strategy.get("strategy_id"),
        "name": strategy.get("name"),
        "status": strategy.get("status"),
        "historically_supported": historical_supported,
        "official_decision": official_decision,
        "pool_passed_scorer": pool_passed,
        "settled_selected_snapshots": settled_selected,
        "required_settled_selected_snapshots": REQUIRED_OFFICIAL_SETTLED_SELECTED,
        "active_months": active_months,
        "required_active_months": REQUIRED_ACTIVE_MONTHS,
        "official_profit": _number(official.get("profit")),
        "official_roi_pct": _number(official.get("roi_pct")),
        "official_max_drawdown": _number(official.get("max_drawdown")),
        "closing_sp_coverage": _number(official.get("closing_sp_coverage")),
        "average_clv": _number(official.get("average_clv"), -1.0),
        "positive_clv_rate": _number(official.get("positive_clv_rate"), -1.0),
        "statistical_evidence": official.get("statistical_evidence") or {},
        "official_evidence_failures": evidence_failures,
        "portfolio_risk_control": risk_control,
        "action": action,
        "reason": reason,
        "top_blockers": top_blockers[:5],
        "deployment_blockers": blockers,
        "selection": strategy.get("selection") or {},
        "risk_control": strategy.get("risk_control") or {},
    }


def _allocation_score(strategy: dict[str, Any]) -> tuple[float, float]:
    roi = max(0.001, _number(strategy.get("official_roi_pct")) / 100.0)
    average_clv = max(0.001, _number(strategy.get("average_clv")))
    profit = max(1.0, _number(strategy.get("official_profit")))
    drawdown_penalty = 1.0 + _number(strategy.get("official_max_drawdown")) / profit
    base_score = (roi + average_clv) / drawdown_penalty
    multiplier = _number((strategy.get("portfolio_risk_control") or {}).get("multiplier"), 1.0)
    return base_score, base_score * multiplier


def _capped_shares(scores: list[float]) -> list[float]:
    if not scores:
        return []
    if len(scores) == 1:
        return [1.0]
    shares = [0.0] * len(scores)
    remaining = set(range(len(scores)))
    remaining_share = 1.0
    while remaining:
        total = sum(max(scores[index], 0.0) for index in remaining)
        proposed = {
            index: remaining_share * (max(scores[index], 0.0) / total if total > 0 else 1.0 / len(remaining))
            for index in remaining
        }
        capped = [index for index, share in proposed.items() if share > MAX_STRATEGY_SHARE]
        if not capped:
            for index, share in proposed.items():
                shares[index] = share
            break
        for index in capped:
            shares[index] = MAX_STRATEGY_SHARE
            remaining_share -= MAX_STRATEGY_SHARE
            remaining.remove(index)
    return shares


def build_profit_allocation_readiness(daily_budget: float | None = None) -> dict[str, Any]:
    budget = float(settings.profit_daily_budget if daily_budget is None else daily_budget)
    strategies = [_strategy_status(strategy) for strategy in list_profit_strategy_packages()]
    ready = [row for row in strategies if row["action"] == "PAPER_ALLOCATION_READY"]
    evidence_quality = build_official_sp_evidence_quality()
    evidence_ready = evidence_quality.get("decision") == "EVIDENCE_READY"

    allocations: list[dict[str, Any]] = []
    if ready and evidence_ready and budget > 0:
        score_pairs = [_allocation_score(row) for row in ready]
        base_total = sum(pair[0] for pair in score_pairs)
        adjusted_total = sum(pair[1] for pair in score_pairs)
        deployment_fraction = min(1.0, adjusted_total / base_total) if base_total > 0 else 0.0
        deployable_budget = round(budget * deployment_fraction, 2)
        shares = _capped_shares([pair[1] for pair in score_pairs])
        assigned = 0.0
        for index, row in enumerate(ready):
            amount = round(deployable_budget * shares[index], 2)
            if index == len(ready) - 1:
                amount = round(deployable_budget - assigned, 2)
            assigned += amount
            allocations.append({
                "strategy_id": row["strategy_id"],
                "paper_budget": amount,
                "portfolio_weight": round(shares[index], 4),
                "risk_multiplier": row["portfolio_risk_control"]["multiplier"],
                "mode": "shadow_or_paper_only",
                "reason": "Evidence-weighted paper allocation after strategy drawdown controls.",
            })

    allocated_budget = round(sum(float(item["paper_budget"]) for item in allocations), 2)
    if ready and not evidence_ready:
        decision = "WAIT_FOR_OFFICIAL_SP_EVIDENCE_QUALITY"
        reason = "Strategy gates passed, but official SP freshness, closing-price, or settlement evidence is incomplete."
    elif allocations:
        decision = "PAPER_ALLOCATION_READY"
        reason = f"{len(allocations)} strategy package(s) passed historical and official-SP readiness gates."
    elif any(row["action"] == "WAIT_FOR_ELIGIBLE_OFFICIAL_POOL" for row in strategies):
        decision = "WAIT_FOR_VALIDATED_OFFICIAL_SP_COVERAGE"
        reason = "At least one strategy is historically supported, but none covers the current official pool."
    elif any(row["action"] == "WAIT_FOR_OFFICIAL_SP_SETTLEMENT" for row in strategies):
        decision = "WAIT_FOR_OFFICIAL_SP_SETTLEMENT"
        reason = "Eligible official selections exist, but settled official-SP sample size is still below the promotion gate."
    elif any(row["action"] == "RISK_COOLDOWN" for row in strategies):
        decision = "PORTFOLIO_RISK_COOLDOWN"
        reason = "Validated strategies are temporarily held in cash after two consecutive losing active months."
    else:
        decision = "RESEARCH_ONLY_NO_DAILY_ALLOCATION"
        reason = "No strategy currently passes the historical plus official-SP allocation gates."

    return {
        "method": "profit daily allocation readiness",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "daily_budget": budget,
        "allocated_budget": allocated_budget,
        "cash_reserved": round(max(0.0, budget - allocated_budget), 2),
        "decision": decision,
        "reason": reason,
        "requirements": {
            "historical_audit": "STATISTICALLY_SUPPORTED_RESEARCH_CANDIDATE",
            "edge_calibration": "CALIBRATED_EDGE_CONFIRMED",
            "official_sp_decision": "OFFICIAL_SP_PROSPECTIVE_PASS",
            "official_sp_evidence_quality": "EVIDENCE_READY",
            "min_settled_selected_snapshots": REQUIRED_OFFICIAL_SETTLED_SELECTED,
            "min_active_months": REQUIRED_ACTIVE_MONTHS,
            "min_closing_sp_coverage": REQUIRED_CLOSING_SP_COVERAGE,
            "min_positive_clv_rate": REQUIRED_POSITIVE_CLV_RATE,
            "average_clv": ">0",
            "min_settlement_days": REQUIRED_SETTLEMENT_DAYS,
            "bootstrap_roi_p05": ">0",
            "bootstrap_average_clv_p05": ">0",
            "relative_market_calibration": (
                "model Brier and log loss no worse than de-vig market; at least one paired bootstrap p05 >0"
            ),
        },
        "allocations": allocations,
        "official_sp_evidence_quality": {
            "decision": evidence_quality.get("decision"),
            "research_usable": evidence_quality.get("research_usable", False),
            "failed_checks": evidence_quality.get("failed_checks", 0),
            "pending_checks": evidence_quality.get("pending_checks", 0),
            "critical_checks": evidence_quality.get("critical_checks", 0),
            "summary": evidence_quality.get("summary", {}),
        },
        "strategies": strategies,
        "guardrail": (
            "This report never places real bets. It only decides whether the daily budget may enter "
            "shadow/paper allocation under validated strategy coverage."
        ),
        "portfolio_controls": {
            "budget_is_a_cap_not_a_quota": True,
            "two_negative_months_trigger_cooldown": True,
            "drawdown_reduces_deployable_budget": True,
            "max_strategy_share_when_multiple_ready": MAX_STRATEGY_SHARE,
        },
    }
