from __future__ import annotations

import pandas as pd
import pytest

from scripts.adaptive_budget_deployment_replay import (
    apply_monthly_budget_multipliers,
    matched_cross_cost_evidence,
    select_adaptive_rule,
    select_monthly_multipliers,
)


def _portfolio() -> pd.DataFrame:
    rows = []
    for month, won, edge in (
        ("2024-01", True, 5.0),
        ("2024-02", True, 5.0),
        ("2024-03", True, 5.0),
        ("2024-04", False, -50.0),
    ):
        rows.append({
            "candidate_id": month,
            "date": f"{month}-01",
            "league": "L1",
            "stake": 1.0,
            "odds": 2.0,
            "won": won,
            "profit": 1.0 if won else -1.0,
            "closing_edge_pct": edge,
            "decision_frozen_before_closing_and_result": True,
        })
    return pd.DataFrame(rows)


def test_monthly_multiplier_uses_only_strictly_prior_active_months() -> None:
    portfolio = _portfolio()

    multipliers = select_monthly_multipliers(
        [portfolio], prior_active_months=3, minimum_prior_positions=3,
    )
    changed_current = portfolio.copy()
    changed_current.loc[changed_current["candidate_id"] == "2024-04", [
        "won", "profit", "closing_edge_pct",
    ]] = [True, 1000.0, 1000.0]
    changed = select_monthly_multipliers(
        [changed_current], prior_active_months=3, minimum_prior_positions=3,
    )

    assert multipliers["2024-04"] == 20.0
    assert changed["2024-04"] == multipliers["2024-04"]


def test_monthly_multiplier_reapplies_exposure_caps() -> None:
    portfolio = pd.concat([_portfolio().iloc[[0]]] * 2, ignore_index=True)
    portfolio.loc[1, "candidate_id"] = "second"

    selected = apply_monthly_budget_multipliers(
        portfolio, {"2024-01": 20.0}
    )

    assert selected["stake"].sum() == pytest.approx(15.0)
    assert selected["budget_deployment_multiplier"].eq(20.0).all()


def test_adaptive_rule_is_selected_by_discovery_objective() -> None:
    portfolio = _portfolio().iloc[:2].copy()
    portfolio["stake"] = 0.5

    result = select_adaptive_rule(
        [portfolio], discovery_end="2024-02-29",
        prior_active_months_grid=(1,), minimum_prior_positions_grid=(1,),
        growth_multiplier_grid=(15.0, 20.0,),
    )

    assert result["selected"]["growth_multiplier"] == 20.0
    assert result["selected"]["minimum_cross_cost_closing_expected_profit"] > 0


def test_cross_cost_evidence_requires_same_candidate_and_direction() -> None:
    first = _portfolio().iloc[:2].copy()
    second = first.copy()
    second.loc[1, "outcome"] = "away"
    first["outcome"] = "home"
    second.loc[0, "outcome"] = "home"

    matched = matched_cross_cost_evidence([first, second])

    assert [frame["candidate_id"].tolist() for frame in matched] == [
        ["2024-01"], ["2024-01"],
    ]


def test_unmatched_deployment_month_still_receives_frozen_multiplier() -> None:
    first = _portfolio().iloc[:2].copy()
    second = first.iloc[:1].copy()
    first["outcome"] = "home"
    second["outcome"] = "home"

    multipliers = select_monthly_multipliers(
        [first, second], prior_active_months=1, minimum_prior_positions=1,
        matched_evidence_only=True,
    )

    assert set(multipliers) == {"2024-01", "2024-02"}


def test_explicit_new_tier_month_receives_prior_only_multiplier() -> None:
    portfolios = [_portfolio(), _portfolio()]
    for portfolio in portfolios:
        portfolio["outcome"] = "home"

    multipliers = select_monthly_multipliers(
        portfolios, prior_active_months=3, minimum_prior_positions=20,
        matched_evidence_only=True, deployment_months=["2026-02"],
    )

    assert multipliers == {"2026-02": 10.0}
