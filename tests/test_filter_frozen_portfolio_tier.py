from __future__ import annotations

import pandas as pd
import pytest

from scripts.filter_frozen_portfolio_tier import filter_frozen_confidence_tier


def _positions() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "candidate_id": "low", "outcome": "home",
            "lower_closing_edge_pct": 1.5, "stake": 1.0,
            "decision_frozen_before_closing_and_result": True,
            "actual_outcome": "home", "closing_probability": 0.6,
            "profit": 1.0,
        },
        {
            "candidate_id": "high", "outcome": "away",
            "lower_closing_edge_pct": 2.0, "stake": 2.0,
            "decision_frozen_before_closing_and_result": True,
            "actual_outcome": "home", "closing_probability": 0.2,
            "profit": -2.0,
        },
    ])


def test_frozen_tier_membership_does_not_depend_on_future_columns() -> None:
    positions = _positions()
    baseline = filter_frozen_confidence_tier(positions, 1.0, 2.0)
    changed = positions.assign(
        actual_outcome=["away", "away"], closing_probability=[0.1, 0.9],
        profit=[-1.0, 2.0],
    )
    future_changed = filter_frozen_confidence_tier(changed, 1.0, 2.0)

    assert baseline["candidate_id"].tolist() == ["low"]
    assert future_changed["candidate_id"].tolist() == ["low"]


def test_frozen_tier_rejects_unfrozen_decisions() -> None:
    positions = _positions()
    positions.loc[0, "decision_frozen_before_closing_and_result"] = False

    with pytest.raises(ValueError, match="not frozen"):
        filter_frozen_confidence_tier(positions, 1.0, 2.0)


def test_frozen_tier_can_use_another_decision_time_column() -> None:
    positions = _positions().assign(
        minimum_lower_clv_staking_probability=[0.22, 0.28]
    )

    selected = filter_frozen_confidence_tier(
        positions, 0.20, 0.25,
        column="minimum_lower_clv_staking_probability",
    )

    assert selected["candidate_id"].tolist() == ["low"]
