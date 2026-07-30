from __future__ import annotations

import pandas as pd

from scripts.profit_concentration_gate_power import (
    _remove_largest_winners,
    simulate_gate_power,
)


def test_remove_largest_winners_never_removes_losses() -> None:
    profit = pd.Series([5.0, -3.0, 2.0]).to_numpy()
    stake = pd.Series([2.0, 3.0, 1.0]).to_numpy()

    retained_profit, retained_stake = _remove_largest_winners(
        profit, stake, 5
    )

    assert retained_profit.tolist() == [0.0, -3.0, 0.0]
    assert retained_stake.tolist() == [0.0, 3.0, 0.0]


def test_gate_power_simulation_is_deterministic_and_bounded() -> None:
    positions = pd.DataFrame([
        {
            "test_month": f"2026-{month:02d}", "stake": 2.0,
            "odds": 2.2, "closing_probability": 0.55,
        }
        for month in range(1, 7)
        for _index in range(3)
    ])
    months = [f"2026-{month:02d}" for month in range(1, 7)]

    first = simulate_gate_power(
        positions, months, simulations=50, bootstrap_iterations=50, seed=7
    )
    second = simulate_gate_power(
        positions, months, simulations=50, bootstrap_iterations=50, seed=7
    )

    assert first == second
    assert 0.0 <= first["joint_current_concentration_gate_pass_rate"] <= 1.0
