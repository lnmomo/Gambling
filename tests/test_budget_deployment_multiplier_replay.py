from __future__ import annotations

import pandas as pd
import pytest

from scripts.budget_deployment_multiplier_replay import (
    apply_budget_multiplier,
    select_discovery_multiplier,
)
from scripts.frozen_portfolio_report import closing_expected_profit_frame


def _positions() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "candidate_id": "discovery-win",
            "date": "2024-05-01",
            "league": "L1",
            "stake": 8.0,
            "odds": 2.0,
            "won": True,
            "closing_edge_pct": 5.0,
            "decision_frozen_before_closing_and_result": True,
        },
        {
            "candidate_id": "discovery-loss",
            "date": "2024-05-02",
            "league": "L1",
            "stake": 8.0,
            "odds": 2.0,
            "won": False,
            "closing_edge_pct": 5.0,
            "decision_frozen_before_closing_and_result": True,
        },
        {
            "candidate_id": "future-loss",
            "date": "2025-01-01",
            "league": "L1",
            "stake": 8.0,
            "odds": 2.0,
            "won": False,
            "closing_edge_pct": -50.0,
            "decision_frozen_before_closing_and_result": True,
        },
    ])


def test_budget_multiplier_respects_daily_and_league_caps() -> None:
    positions = pd.concat([_positions().iloc[[0]]] * 2, ignore_index=True)
    positions.loc[1, "candidate_id"] = "second"

    selected = apply_budget_multiplier(positions, 20.0)

    assert selected["stake"].sum() == pytest.approx(15.0)
    assert selected["base_stake_before_budget_multiplier"].tolist() == [8.0, 8.0]
    assert selected["budget_deployment_multiplier"].eq(20.0).all()


def test_multiplier_selection_excludes_future_results() -> None:
    positions = _positions()

    first = select_discovery_multiplier(
        [positions], multipliers=(1.0, 2.0, 3.0),
        maximum_discovery_drawdown=10.0,
    )
    changed_future = positions.copy()
    changed_future.loc[changed_future["candidate_id"] == "future-loss", "won"] = True
    changed_future.loc[
        changed_future["candidate_id"] == "future-loss", "closing_edge_pct"
    ] = 500.0
    second = select_discovery_multiplier(
        [changed_future], multipliers=(1.0, 2.0, 3.0),
        maximum_discovery_drawdown=10.0,
    )

    assert first == second
    assert first["selected_multiplier"] == 1.0


def test_budget_multiplier_rejects_unfrozen_positions() -> None:
    positions = _positions()
    positions.loc[0, "decision_frozen_before_closing_and_result"] = False

    with pytest.raises(ValueError, match="frozen before closing"):
        apply_budget_multiplier(positions, 2.0)


def test_closing_expected_attribution_does_not_use_match_result() -> None:
    positions = _positions().iloc[[0, 1]].copy()

    attributed = closing_expected_profit_frame(positions)

    assert attributed["profit"].tolist() == pytest.approx([0.4, 0.4])
    assert attributed["won"].tolist() == [True, False]
