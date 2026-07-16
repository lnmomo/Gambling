from __future__ import annotations

import pytest

from football_agents.profit_allocation_readiness import build_profit_allocation_readiness


@pytest.fixture(autouse=True)
def _ready_official_sp_evidence(monkeypatch):
    monkeypatch.setattr(
        "football_agents.profit_allocation_readiness.build_official_sp_evidence_quality",
        lambda: {"decision": "EVIDENCE_READY", "research_usable": True, "summary": {}},
    )


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
            "active_months": 0,
            "profit": 0,
            "roi_pct": 0,
            "max_drawdown": 0,
            "closing_sp_coverage": 0,
            "average_clv": None,
            "positive_clv_rate": None,
            "positive_months": 0,
            "negative_months": 0,
            "monthly": [],
            "top_pool_blockers": [{"reason": "league_not_i2", "matches": 100}],
        },
        "selection": {"league_family": "I2", "outcome": "DRAW"},
        "risk_control": {"cooldown_days": 14},
        "deployment_blockers": ["official-SP validation required"],
    }
    base.update(overrides)
    official = base.get("official_validation") or {}
    if (
        official.get("decision") == "OFFICIAL_SP_PROSPECTIVE_PASS"
        and "statistical_evidence" not in official
    ):
        official["statistical_evidence"] = {
            "point_estimates": {
                "brier_improvement": 0.01,
                "log_loss_improvement": 0.01,
            },
            "bootstrap": {
                "settlement_days": 120,
                "roi_ci_pct": {"p05": 1.0},
                "average_clv_ci": {"p05": 0.005},
                "brier_improvement_ci": {"p05": 0.001},
                "log_loss_improvement_ci": {"p05": 0.001},
            },
        }
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
    assert report["strategies"][0]["portfolio_risk_control"]["state"] == "WAITING_FOR_EVIDENCE"
    assert report["strategies"][0]["portfolio_risk_control"]["multiplier"] == 0.0


def test_allocation_readiness_allocates_paper_budget_after_official_sp_pass(monkeypatch):
    monkeypatch.setattr(
        "football_agents.profit_allocation_readiness.list_profit_strategy_packages",
        lambda: [
            _strategy(official_validation={
                "decision": "OFFICIAL_SP_PROSPECTIVE_PASS",
                "pool_passed_scorer": 12,
                "settled_selected_snapshots": 240,
                "active_months": 6,
                "profit": 28.0,
                "roi_pct": 5.0,
                "max_drawdown": 8.0,
                "closing_sp_coverage": 0.95,
                "average_clv": 0.02,
                "positive_clv_rate": 0.58,
                "positive_months": 4,
                "negative_months": 2,
                "monthly": [
                    {"month": "2026-01", "profit": 4.0},
                    {"month": "2026-02", "profit": -2.0},
                    {"month": "2026-03", "profit": 8.0},
                    {"month": "2026-04", "profit": 5.0},
                    {"month": "2026-05", "profit": -1.0},
                    {"month": "2026-06", "profit": 14.0},
                ],
            })
        ],
    )

    report = build_profit_allocation_readiness(100)

    assert report["decision"] == "PAPER_ALLOCATION_READY"
    assert report["allocated_budget"] == 100
    assert report["cash_reserved"] == 0
    assert report["allocations"][0]["strategy_id"] == "profit-i2-test"
    assert report["allocations"][0]["paper_budget"] == 100
    assert report["allocations"][0]["risk_multiplier"] == 1.0


def test_allocation_readiness_rejects_legacy_pass_without_uncertainty_evidence(monkeypatch):
    official = {
        "decision": "OFFICIAL_SP_PROSPECTIVE_PASS",
        "pool_passed_scorer": 12,
        "settled_selected_snapshots": 240,
        "profit": 28.0,
        "roi_pct": 5.0,
        "max_drawdown": 8.0,
        "closing_sp_coverage": 0.95,
        "average_clv": 0.02,
        "positive_clv_rate": 0.58,
        "positive_months": 4,
        "negative_months": 2,
        "monthly": [
            {"month": "2026-01", "profit": 4.0}, {"month": "2026-02", "profit": -2.0},
            {"month": "2026-03", "profit": 8.0}, {"month": "2026-04", "profit": 5.0},
            {"month": "2026-05", "profit": -1.0}, {"month": "2026-06", "profit": 14.0},
        ],
        "statistical_evidence": {},
    }
    monkeypatch.setattr(
        "football_agents.profit_allocation_readiness.list_profit_strategy_packages",
        lambda: [_strategy(official_validation=official)],
    )

    report = build_profit_allocation_readiness(100)

    assert report["allocated_budget"] == 0
    failures = report["strategies"][0]["official_evidence_failures"]
    assert "bootstrap_roi_p05<=0" in failures
    assert "bootstrap_clv_p05<=0" in failures
    assert "relative_calibration_confidence_not_positive" in failures


def test_allocation_readiness_rejects_model_that_is_worse_than_market(monkeypatch):
    official = {
        "decision": "OFFICIAL_SP_PROSPECTIVE_PASS",
        "pool_passed_scorer": 12,
        "settled_selected_snapshots": 240,
        "profit": 28.0,
        "roi_pct": 5.0,
        "max_drawdown": 8.0,
        "closing_sp_coverage": 0.95,
        "average_clv": 0.02,
        "positive_clv_rate": 0.58,
        "positive_months": 4,
        "negative_months": 2,
        "monthly": [
            {"month": "2026-01", "profit": 4.0}, {"month": "2026-02", "profit": -2.0},
            {"month": "2026-03", "profit": 8.0}, {"month": "2026-04", "profit": 5.0},
            {"month": "2026-05", "profit": -1.0}, {"month": "2026-06", "profit": 14.0},
        ],
        "statistical_evidence": {
            "point_estimates": {"brier_improvement": -0.01, "log_loss_improvement": -0.02},
            "bootstrap": {
                "settlement_days": 120,
                "roi_ci_pct": {"p05": 1.0},
                "average_clv_ci": {"p05": 0.005},
                "brier_improvement_ci": {"p05": -0.02},
                "log_loss_improvement_ci": {"p05": -0.03},
            },
        },
    }
    monkeypatch.setattr(
        "football_agents.profit_allocation_readiness.list_profit_strategy_packages",
        lambda: [_strategy(official_validation=official)],
    )

    report = build_profit_allocation_readiness(100)

    failures = report["strategies"][0]["official_evidence_failures"]
    assert "model_brier_worse_than_market" in failures
    assert "model_log_loss_worse_than_market" in failures
    assert report["allocated_budget"] == 0


def test_allocation_readiness_holds_cash_when_official_sp_evidence_is_degraded(monkeypatch):
    official = {
        "decision": "OFFICIAL_SP_PROSPECTIVE_PASS",
        "pool_passed_scorer": 12,
        "settled_selected_snapshots": 240,
        "active_months": 6,
        "profit": 28.0,
        "roi_pct": 5.0,
        "max_drawdown": 8.0,
        "closing_sp_coverage": 0.95,
        "average_clv": 0.02,
        "positive_clv_rate": 0.58,
        "positive_months": 4,
        "negative_months": 2,
        "monthly": [
            {"month": "2026-01", "profit": 4.0}, {"month": "2026-02", "profit": -2.0},
            {"month": "2026-03", "profit": 8.0}, {"month": "2026-04", "profit": 5.0},
            {"month": "2026-05", "profit": -1.0}, {"month": "2026-06", "profit": 14.0},
        ],
    }
    monkeypatch.setattr(
        "football_agents.profit_allocation_readiness.list_profit_strategy_packages",
        lambda: [_strategy(official_validation=official)],
    )
    monkeypatch.setattr(
        "football_agents.profit_allocation_readiness.build_official_sp_evidence_quality",
        lambda: {
            "decision": "EVIDENCE_CRITICAL", "research_usable": False,
            "failed_checks": 2, "critical_checks": 1, "summary": {"freshness_hours": 30.0},
        },
    )

    report = build_profit_allocation_readiness(100)

    assert report["decision"] == "WAIT_FOR_OFFICIAL_SP_EVIDENCE_QUALITY"
    assert report["allocated_budget"] == 0
    assert report["cash_reserved"] == 100


def test_allocation_readiness_rejects_weak_historical_strategy(monkeypatch):
    monkeypatch.setattr(
        "football_agents.profit_allocation_readiness.list_profit_strategy_packages",
        lambda: [_strategy(audit={"decision": "REJECTED"})],
    )

    report = build_profit_allocation_readiness(100)

    assert report["decision"] == "RESEARCH_ONLY_NO_DAILY_ALLOCATION"
    assert report["strategies"][0]["action"] == "RESEARCH_ONLY"


def test_allocation_readiness_rejects_scorecard_blocked_strategy(monkeypatch):
    monkeypatch.setattr(
        "football_agents.profit_allocation_readiness.list_profit_strategy_packages",
        lambda: [_strategy(
            status="RESEARCH_ONLY_UNSTABLE_WINDOWS",
            recommended_for_shadow=False,
            deployment_blockers=["latest scorecard blocked shadow promotion"],
        )],
    )

    report = build_profit_allocation_readiness(100)

    assert report["decision"] == "RESEARCH_ONLY_NO_DAILY_ALLOCATION"
    assert report["allocated_budget"] == 0
    assert report["cash_reserved"] == 100
    assert report["strategies"][0]["historically_supported"] is False
    assert report["strategies"][0]["action"] == "RESEARCH_ONLY"


def test_allocation_readiness_enforces_active_months_even_when_report_claims_pass(monkeypatch):
    official = {
        "decision": "OFFICIAL_SP_PROSPECTIVE_PASS",
        "pool_passed_scorer": 20,
        "settled_selected_snapshots": 240,
        "active_months": 5,
        "profit": 30.0,
        "roi_pct": 6.0,
        "max_drawdown": 8.0,
        "closing_sp_coverage": 0.95,
        "average_clv": 0.02,
        "positive_clv_rate": 0.60,
        "positive_months": 4,
        "negative_months": 1,
        "monthly": [{"month": f"2026-0{month}", "profit": 6.0} for month in range(1, 6)],
    }
    monkeypatch.setattr(
        "football_agents.profit_allocation_readiness.list_profit_strategy_packages",
        lambda: [_strategy(official_validation=official)],
    )

    report = build_profit_allocation_readiness(100)

    assert report["allocated_budget"] == 0
    assert "active_months<6" in report["strategies"][0]["official_evidence_failures"]


def test_allocation_readiness_does_not_trust_claimed_month_count(monkeypatch):
    official = {
        "decision": "OFFICIAL_SP_PROSPECTIVE_PASS",
        "pool_passed_scorer": 20,
        "settled_selected_snapshots": 240,
        "active_months": 6,
        "profit": 30.0,
        "roi_pct": 6.0,
        "max_drawdown": 8.0,
        "closing_sp_coverage": 0.95,
        "average_clv": 0.02,
        "positive_clv_rate": 0.60,
        "positive_months": 1,
        "negative_months": 0,
        "monthly": [{"month": "2026-06", "profit": 30.0}],
    }
    monkeypatch.setattr(
        "football_agents.profit_allocation_readiness.list_profit_strategy_packages",
        lambda: [_strategy(official_validation=official)],
    )

    report = build_profit_allocation_readiness(100)

    assert report["allocated_budget"] == 0
    assert report["strategies"][0]["active_months"] == 1
    assert "active_months<6" in report["strategies"][0]["official_evidence_failures"]


def test_allocation_readiness_uses_daily_path_for_intra_month_drawdown(monkeypatch):
    monthly = [{"month": f"2026-0{month}", "profit": 5.0} for month in range(1, 7)]
    official = {
        "decision": "OFFICIAL_SP_PROSPECTIVE_PASS",
        "pool_passed_scorer": 20,
        "settled_selected_snapshots": 240,
        "active_months": 6,
        "profit": 30.0,
        "roi_pct": 6.0,
        "max_drawdown": 12.0,
        "closing_sp_coverage": 0.95,
        "average_clv": 0.02,
        "positive_clv_rate": 0.60,
        "positive_months": 6,
        "negative_months": 0,
        "monthly": monthly,
        "daily": [
            {"date": "2026-06-01", "profit": 30.0},
            {"date": "2026-06-02", "profit": -6.0},
            {"date": "2026-06-03", "profit": -6.0},
        ],
    }
    monkeypatch.setattr(
        "football_agents.profit_allocation_readiness.list_profit_strategy_packages",
        lambda: [_strategy(official_validation=official)],
    )

    report = build_profit_allocation_readiness(100)

    control = report["strategies"][0]["portfolio_risk_control"]
    assert control["path_grain"] == "daily"
    assert control["current_drawdown"] == 12.0
    assert control["current_drawdown_to_peak"] == 0.4
    assert report["allocated_budget"] == 75.0


def test_allocation_readiness_enters_cooldown_after_two_losing_months(monkeypatch):
    monthly = [
        {"month": "2026-01", "profit": 20.0},
        {"month": "2026-02", "profit": 10.0},
        {"month": "2026-03", "profit": 8.0},
        {"month": "2026-04", "profit": 6.0},
        {"month": "2026-05", "profit": -2.0},
        {"month": "2026-06", "profit": -1.0},
    ]
    official = {
        "decision": "OFFICIAL_SP_PROSPECTIVE_PASS",
        "pool_passed_scorer": 20,
        "settled_selected_snapshots": 240,
        "active_months": 6,
        "profit": 41.0,
        "roi_pct": 6.0,
        "max_drawdown": 3.0,
        "closing_sp_coverage": 0.95,
        "average_clv": 0.02,
        "positive_clv_rate": 0.60,
        "positive_months": 4,
        "negative_months": 2,
        "monthly": monthly,
    }
    monkeypatch.setattr(
        "football_agents.profit_allocation_readiness.list_profit_strategy_packages",
        lambda: [_strategy(official_validation=official)],
    )

    report = build_profit_allocation_readiness(100)

    assert report["decision"] == "PORTFOLIO_RISK_COOLDOWN"
    assert report["allocated_budget"] == 0
    assert report["strategies"][0]["action"] == "RISK_COOLDOWN"


def test_allocation_readiness_caps_multi_strategy_concentration(monkeypatch):
    common = {
        "decision": "OFFICIAL_SP_PROSPECTIVE_PASS",
        "pool_passed_scorer": 20,
        "settled_selected_snapshots": 300,
        "active_months": 6,
        "profit": 40.0,
        "roi_pct": 8.0,
        "max_drawdown": 5.0,
        "closing_sp_coverage": 1.0,
        "average_clv": 0.03,
        "positive_clv_rate": 0.60,
        "positive_months": 5,
        "negative_months": 1,
        "monthly": [
            {"month": "2026-01", "profit": 10.0},
            {"month": "2026-02", "profit": -1.0},
            {"month": "2026-03", "profit": 8.0},
            {"month": "2026-04", "profit": 7.0},
            {"month": "2026-05", "profit": 6.0},
            {"month": "2026-06", "profit": 10.0},
        ],
    }
    weaker = {
        **common,
        "profit": 10.0,
        "roi_pct": 1.0,
        "average_clv": 0.001,
        "monthly": [
            {"month": "2026-01", "profit": 3.0},
            {"month": "2026-02", "profit": -1.0},
            {"month": "2026-03", "profit": 2.0},
            {"month": "2026-04", "profit": 2.0},
            {"month": "2026-05", "profit": 2.0},
            {"month": "2026-06", "profit": 2.0},
        ],
    }
    monkeypatch.setattr(
        "football_agents.profit_allocation_readiness.list_profit_strategy_packages",
        lambda: [
            _strategy(strategy_id="strong", official_validation=common),
            _strategy(strategy_id="weak", official_validation=weaker),
        ],
    )

    report = build_profit_allocation_readiness(100)

    assert report["allocated_budget"] == 100
    assert max(item["portfolio_weight"] for item in report["allocations"]) <= 0.60
    assert sorted(item["paper_budget"] for item in report["allocations"]) == [40.0, 60.0]


def test_allocation_readiness_reserves_cash_after_one_losing_month(monkeypatch):
    monthly = [
        {"month": "2026-01", "profit": 10.0},
        {"month": "2026-02", "profit": 8.0},
        {"month": "2026-03", "profit": 7.0},
        {"month": "2026-04", "profit": 6.0},
        {"month": "2026-05", "profit": 5.0},
        {"month": "2026-06", "profit": -1.0},
    ]
    official = {
        "decision": "OFFICIAL_SP_PROSPECTIVE_PASS",
        "pool_passed_scorer": 20,
        "settled_selected_snapshots": 240,
        "active_months": 6,
        "profit": 35.0,
        "roi_pct": 6.0,
        "max_drawdown": 1.0,
        "closing_sp_coverage": 0.95,
        "average_clv": 0.02,
        "positive_clv_rate": 0.60,
        "positive_months": 5,
        "negative_months": 1,
        "monthly": monthly,
    }
    monkeypatch.setattr(
        "football_agents.profit_allocation_readiness.list_profit_strategy_packages",
        lambda: [_strategy(official_validation=official)],
    )

    report = build_profit_allocation_readiness(100)

    assert report["decision"] == "PAPER_ALLOCATION_READY"
    assert report["allocated_budget"] == 75
    assert report["cash_reserved"] == 25
    assert report["allocations"][0]["risk_multiplier"] == 0.75
