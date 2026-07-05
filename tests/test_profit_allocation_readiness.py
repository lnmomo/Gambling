from __future__ import annotations

from football_agents.profit_allocation_readiness import build_profit_allocation_readiness


def _strategy(**overrides):
    base = {
        "strategy_id": "profit-i2-test",
        "name": "I2 test",
        "status": "STATISTICALLY_CALIBRATED_RESEARCH_LEAD_WAITING_OFFICIAL_SP_SHADOW",
        "audit": {"decision": "STATISTICALLY_SUPPORTED_RESEARCH_CANDIDATE"},
        "calibration": {"decision": "CALIBRATED_EDGE_CONFIRMED"},
        "official_validation": {
            "decision": "OFFICIAL_SP_PROSPECTIVE_BLOCKED",
            "pool_passed_scorer": 0,
            "settled_selected_snapshots": 0,
            "top_pool_blockers": [{"reason": "league_not_i2", "matches": 100}],
        },
        "selection": {"league_family": "I2", "outcome": "DRAW"},
        "risk_control": {"cooldown_days": 14},
        "deployment_blockers": ["official-SP validation required"],
    }
    base.update(overrides)
    return base


def test_allocation_readiness_holds_cash_when_official_pool_has_no_coverage(monkeypatch):
    monkeypatch.setattr(
        "football_agents.profit_allocation_readiness.list_profit_strategy_packages",
        lambda: [_strategy()],
    )

    report = build_profit_allocation_readiness(100)

    assert report["decision"] == "WAIT_FOR_VALIDATED_OFFICIAL_SP_COVERAGE"
    assert report["allocated_budget"] == 0
    assert report["cash_reserved"] == 100
    assert report["allocations"] == []
    assert report["strategies"][0]["action"] == "WAIT_FOR_ELIGIBLE_OFFICIAL_POOL"
    assert report["strategies"][0]["top_blockers"][0]["reason"] == "league_not_i2"


def test_allocation_readiness_allocates_paper_budget_after_official_sp_pass(monkeypatch):
    monkeypatch.setattr(
        "football_agents.profit_allocation_readiness.list_profit_strategy_packages",
        lambda: [
            _strategy(official_validation={
                "decision": "OFFICIAL_SP_PROSPECTIVE_PASS",
                "pool_passed_scorer": 12,
                "settled_selected_snapshots": 240,
            })
        ],
    )

    report = build_profit_allocation_readiness(100)

    assert report["decision"] == "PAPER_ALLOCATION_READY"
    assert report["allocated_budget"] == 100
    assert report["cash_reserved"] == 0
    assert report["allocations"][0]["strategy_id"] == "profit-i2-test"
    assert report["allocations"][0]["paper_budget"] == 100


def test_allocation_readiness_rejects_weak_historical_strategy(monkeypatch):
    monkeypatch.setattr(
        "football_agents.profit_allocation_readiness.list_profit_strategy_packages",
        lambda: [_strategy(audit={"decision": "REJECTED"})],
    )

    report = build_profit_allocation_readiness(100)

    assert report["decision"] == "RESEARCH_ONLY_NO_DAILY_ALLOCATION"
    assert report["strategies"][0]["action"] == "RESEARCH_ONLY"
