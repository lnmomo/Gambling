from __future__ import annotations

import pandas as pd

from scripts.v6_staking_policy_replay import StakePolicy, freeze_stakes, settle_frozen


def _decisions(actual: str) -> pd.DataFrame:
    return pd.DataFrame([{
        "candidate_id": f"candidate-{index}",
        "date": "2026-03-08",
        "test_month": "2026-03",
        "outcome": "home",
        "actual_outcome": actual,
        "odds": 2.50,
        "lower_closing_edge_pct": 5.0 + index / 100.0,
        "closing_edge_pct": 3.0,
        "positive_clv": True,
        "won": actual == "home",
        "profit": 1.0 if actual == "home" else -1.0,
    } for index in range(30)])


def test_results_cannot_change_frozen_stakes_and_daily_limit() -> None:
    policy = StakePolicy("flat_5", "flat", 5.0, 5.0)
    winners = _decisions("home")
    losers = _decisions("away")

    winner_stakes = freeze_stakes(winners, policy)
    loser_stakes = freeze_stakes(losers, policy)

    assert winner_stakes[["candidate_id", "stake"]].equals(
        loser_stakes[["candidate_id", "stake"]]
    )
    assert winner_stakes["stake"].sum() == 100.0
    assert loser_stakes["stake"].sum() == 100.0
    winner_settled = settle_frozen(winner_stakes, winners)
    loser_settled = settle_frozen(loser_stakes, losers)
    assert winner_settled["profit"].sum() > loser_settled["profit"].sum()
    assert winner_settled["closing_edge_pct"].tolist() == winners["closing_edge_pct"].tolist()[:20]
