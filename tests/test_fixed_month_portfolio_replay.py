from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from scripts.fixed_month_portfolio_replay import replay_fixed_month


def _position(candidate: str, date: str, stake: float, won: bool) -> dict:
    return {
        "test_month": "2026-05", "date": date, "candidate_id": candidate,
        "league": "E0", "home_team": "Home", "away_team": "Away",
        "outcome": "home", "odds": 2.0, "stake": stake,
        "actual_outcome": "home" if won else "away", "won": won,
        "profit": stake if won else -stake, "horizon_role": "9m3m_core",
        "closing_probability": 0.55, "closing_edge_pct": 10.0,
        "positive_clv": True,
        "decision_frozen_before_closing_and_result": True,
    }


def test_fixed_month_replay_includes_no_bet_days_and_settles_after_freeze(
    tmp_path: Path,
) -> None:
    positions = pd.DataFrame([
        _position("a", "2026-05-02", 10.0, True),
        _position("b", "2026-05-03", 5.0, False),
    ])

    report = replay_fixed_month(positions, "2026-05", tmp_path)

    assert report["calendar_days"] == 31
    assert report["betting_days"] == 2
    assert report["no_bet_days"] == 29
    assert report["staked"] == 15.0
    assert report["realized_profit"] == 5.0
    assert report["ending_equity"] == 5.0
    assert report["daily"][0]["ending_equity"] == 0.0
    assert report["daily"][1]["ending_equity"] == 10.0
    assert report["daily"][2]["ending_equity"] == 5.0
    assert (tmp_path / "daily.csv").exists()
    assert (tmp_path / "positions.csv").exists()


def test_fixed_month_replay_rejects_unfrozen_or_over_budget_positions(
    tmp_path: Path,
) -> None:
    unfrozen = pd.DataFrame([_position("a", "2026-05-02", 10.0, True)])
    unfrozen["decision_frozen_before_closing_and_result"] = False
    with pytest.raises(ValueError, match="not frozen"):
        replay_fixed_month(unfrozen, "2026-05", tmp_path / "unfrozen")

    over_budget = pd.DataFrame([
        _position("a", "2026-05-02", 60.0, True),
        {**_position("b", "2026-05-02", 50.0, False), "league": "E1"},
    ])
    with pytest.raises(ValueError, match="daily budget"):
        replay_fixed_month(over_budget, "2026-05", tmp_path / "over")
