from __future__ import annotations

import pandas as pd

from scripts.multi_horizon_clv_replay import (
    freeze_multi_horizon_positions,
    settle_multi_horizon_positions,
)


def _row(candidate: str, outcome: str, stake: float, won: bool) -> dict:
    return {
        "candidate_id": candidate, "outcome": outcome, "test_month": "2026-01",
        "date": "2026-01-10", "league": "E0", "stake": stake, "odds": 2.0,
        "execution_bookmaker": "Book", "closing_probability": 0.55,
        "closing_edge_pct": 10.0, "positive_clv": True,
        "closing_fair_odds": 1.818, "actual_outcome": outcome if won else "draw",
        "won": won, "profit": stake if won else -stake,
    }


def test_multi_horizon_freeze_ignores_future_results_and_rejects_conflicts() -> None:
    core = pd.DataFrame([_row("core", "home", 12.0, True)])
    satellite = pd.DataFrame([
        _row("core", "away", 8.0, True),
        _row("satellite", "away", 8.0, False),
    ])

    first = freeze_multi_horizon_positions(core, satellite)
    changed = freeze_multi_horizon_positions(
        core.assign(won=False, profit=-12.0, actual_outcome="away"),
        satellite.assign(won=True, profit=8.0, actual_outcome="away"),
    )

    assert first[["candidate_id", "outcome", "stake"]].equals(
        changed[["candidate_id", "outcome", "stake"]]
    )
    assert first["candidate_id"].tolist() == ["core", "satellite"]
    assert first["stake"].sum() == 15.0
    assert first.loc[first["candidate_id"] == "satellite", "stake"].item() == 3.75


def test_multi_horizon_settlement_recomputes_profit_after_joint_cap() -> None:
    core = pd.DataFrame([_row("core", "home", 12.0, True)])
    satellite = pd.DataFrame([_row("satellite", "away", 8.0, False)])
    frozen = freeze_multi_horizon_positions(core, satellite)

    settled = settle_multi_horizon_positions(frozen, core, satellite)

    assert settled.loc[settled["candidate_id"] == "core", "profit"].item() == 11.25
    assert settled.loc[settled["candidate_id"] == "satellite", "profit"].item() == -3.75
