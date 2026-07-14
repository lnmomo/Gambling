from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .config import settings
from .profit_strategy_registry import list_profit_strategy_packages


REQUIRED_OFFICIAL_SETTLED_SELECTED = 200
REQUIRED_ACTIVE_MONTHS = 6


def _is_historically_supported(strategy: dict[str, Any]) -> bool:
    status = str(strategy.get("status") or "")
    if status.startswith("RESEARCH_ONLY") or strategy.get("recommended_for_shadow") is False:
        return False
    audit = strategy.get("audit") or {}
    calibration = strategy.get("calibration") or {}
    return (
        audit.get("decision") == "STATISTICALLY_SUPPORTED_RESEARCH_CANDIDATE"
        and calibration.get("decision") == "CALIBRATED_EDGE_CONFIRMED"
    )


def _official_selected_count(strategy: dict[str, Any]) -> int:
    official = strategy.get("official_validation") or {}
    for key in ("settled_selected_snapshots", "selected_snapshots", "pool_passed_scorer"):
        try:
            value = int(official.get(key) or 0)
        except (TypeError, ValueError):
            value = 0
        if key == "settled_selected_snapshots":
            return value
    return 0


def _official_pool_passed(strategy: dict[str, Any]) -> int:
    official = strategy.get("official_validation") or {}
    try:
        return int(official.get("pool_passed_scorer") or 0)
    except (TypeError, ValueError):
        return 0


def _strategy_status(strategy: dict[str, Any]) -> dict[str, Any]:
    official = strategy.get("official_validation") or {}
    historical_supported = _is_historically_supported(strategy)
    settled_selected = _official_selected_count(strategy)
    pool_passed = _official_pool_passed(strategy)
    official_decision = str(official.get("decision") or "PENDING_OFFICIAL_SP_VALIDATION")
    blockers = list(strategy.get("deployment_blockers") or [])
    top_blockers = list(official.get("top_pool_blockers") or official.get("top_snapshot_blockers") or [])

    official_ready = (
        official_decision == "OFFICIAL_SP_PROSPECTIVE_PASS"
        and settled_selected >= REQUIRED_OFFICIAL_SETTLED_SELECTED
    )
    if official_ready:
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
        "action": action,
        "reason": reason,
        "top_blockers": top_blockers[:5],
        "deployment_blockers": blockers,
        "selection": strategy.get("selection") or {},
        "risk_control": strategy.get("risk_control") or {},
    }


def build_profit_allocation_readiness(daily_budget: float | None = None) -> dict[str, Any]:
    budget = float(settings.profit_daily_budget if daily_budget is None else daily_budget)
    strategies = [_strategy_status(strategy) for strategy in list_profit_strategy_packages()]
    ready = [row for row in strategies if row["action"] == "PAPER_ALLOCATION_READY"]

    allocations: list[dict[str, Any]] = []
    if ready and budget > 0:
        per_strategy = round(budget / len(ready), 2)
        for row in ready:
            allocations.append({
                "strategy_id": row["strategy_id"],
                "paper_budget": per_strategy,
                "mode": "shadow_or_paper_only",
                "reason": "Allocation readiness passed; still no automatic real-money order placement.",
            })

    allocated_budget = round(sum(float(item["paper_budget"]) for item in allocations), 2)
    if allocations:
        decision = "PAPER_ALLOCATION_READY"
        reason = f"{len(allocations)} strategy package(s) passed historical and official-SP readiness gates."
    elif any(row["action"] == "WAIT_FOR_ELIGIBLE_OFFICIAL_POOL" for row in strategies):
        decision = "WAIT_FOR_VALIDATED_OFFICIAL_SP_COVERAGE"
        reason = "At least one strategy is historically supported, but none covers the current official pool."
    elif any(row["action"] == "WAIT_FOR_OFFICIAL_SP_SETTLEMENT" for row in strategies):
        decision = "WAIT_FOR_OFFICIAL_SP_SETTLEMENT"
        reason = "Eligible official selections exist, but settled official-SP sample size is still below the promotion gate."
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
            "min_settled_selected_snapshots": REQUIRED_OFFICIAL_SETTLED_SELECTED,
            "min_active_months": REQUIRED_ACTIVE_MONTHS,
        },
        "allocations": allocations,
        "strategies": strategies,
        "guardrail": (
            "This report never places real bets. It only decides whether the daily budget may enter "
            "shadow/paper allocation under validated strategy coverage."
        ),
    }
