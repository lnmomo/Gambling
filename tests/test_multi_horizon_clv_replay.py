from __future__ import annotations

import pandas as pd

from scripts.multi_horizon_clv_replay import (
    freeze_multi_horizon_positions,
    horizon_role_attribution,
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


def test_multi_horizon_can_preserve_existing_roles_for_tertiary_extension() -> None:
    core = pd.DataFrame([
        {**_row("core", "home", 5.0, True), "horizon_role": "9m3m_core"},
        {**_row("long", "away", 4.0, False), "horizon_role": "18m9m_satellite"},
    ])
    tertiary = pd.DataFrame([_row("mid", "draw", 2.0, True)])

    frozen = freeze_multi_horizon_positions(
        core, tertiary, preserve_core_roles=True,
        satellite_role="12m6m_tertiary",
    )

    assert dict(zip(frozen["candidate_id"], frozen["horizon_role"])) == {
        "core": "9m3m_core",
        "long": "18m9m_satellite",
        "mid": "12m6m_tertiary",
    }


def test_horizon_role_attribution_separates_closing_value_from_outcome_luck() -> None:
    settled = pd.DataFrame([
        {**_row("a", "home", 10.0, True), "horizon_role": "9m3m_core"},
        {**_row("b", "away", 5.0, False), "horizon_role": "12m6m_tertiary"},
    ])

    report = horizon_role_attribution(settled, minimum_positions=2)

    assert report["9m3m_core"]["closing_expected_profit"] == 1.0
    assert report["9m3m_core"]["realized_profit"] == 10.0
    assert report["9m3m_core"]["realized_minus_closing_expected_profit"] == 9.0
    assert report["9m3m_core"]["incremental_evidence_status"] == "COLLECTING"
    assert report["12m6m_tertiary"]["closing_expected_profit"] == 0.5
    assert report["12m6m_tertiary"]["realized_profit"] == -5.0
    assert report["12m6m_tertiary"]["realized_minus_closing_expected_profit"] == -5.5
