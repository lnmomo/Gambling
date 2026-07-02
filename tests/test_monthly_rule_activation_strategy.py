from __future__ import annotations

import pandas as pd

from scripts.monthly_rule_activation_strategy import (
    ActivationConfig,
    apply_monthly_activation,
    rule_enabled,
)


def test_rule_activation_uses_only_prior_month_history():
    rows = [
        {
            "date": "2026-01-01",
            "league": "L",
            "home_team": "A",
            "away_team": "B",
            "outcome": "home",
            "actual_result": "away",
            "odds": 2.0,
            "won": False,
            "unit_profit": -1.0,
            "rule_label": "rule",
        },
        {
            "date": "2026-02-01",
            "league": "L",
            "home_team": "C",
            "away_team": "D",
            "outcome": "home",
            "actual_result": "home",
            "odds": 2.0,
            "won": True,
            "unit_profit": 1.0,
            "rule_label": "rule",
        },
    ]
    config = ActivationConfig(
        lookback_months=1,
        min_history_bets=1,
        min_history_roi=0.0,
        min_positive_month_edge=0,
        cold_start="enabled",
    )

    selected, states = apply_monthly_activation(pd.DataFrame(rows), config)

    assert selected["date"].tolist() == ["2026-01-01"]
    assert states.loc[states["month"] == "2026-01", "reason"].iloc[0] == "cold_start"
    assert bool(states.loc[states["month"] == "2026-02", "enabled"].iloc[0]) is False


def test_rule_enabled_can_reenable_after_positive_prior_state():
    history = pd.DataFrame([
        {"month": "2026-01", "rule_label": "rule", "profit": 1.0, "stake": 1.0},
        {"month": "2026-01", "rule_label": "rule", "profit": 1.0, "stake": 1.0},
    ])
    config = ActivationConfig(
        lookback_months=3,
        min_history_bets=1,
        min_history_roi=0.0,
        min_positive_month_edge=0,
        cold_start="disabled",
    )

    enabled, state = rule_enabled(history, "rule", config)

    assert enabled is True
    assert state["profit"] == 2.0
