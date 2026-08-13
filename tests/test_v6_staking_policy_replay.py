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


def test_opening_evidence_stake_multiplier_scales_frozen_kelly_stake() -> None:
    policy = StakePolicy("half_kelly", "kelly", 0.5, 15.0)
    baseline = _decisions("home").head(1)
    discounted = baseline.assign(stake_multiplier=0.5)

    baseline_stake = float(freeze_stakes(baseline, policy).iloc[0]["stake"])
    discounted_stake = float(freeze_stakes(discounted, policy).iloc[0]["stake"])

    assert discounted_stake == round(baseline_stake * 0.5, 2)


def test_opening_evidence_can_uplift_stake_within_policy_caps() -> None:
    policy = StakePolicy("half_kelly", "kelly", 0.5, 15.0)
    baseline = _decisions("home").head(1)
    uplifted = baseline.assign(stake_multiplier=1.25)

    baseline_stake = float(freeze_stakes(baseline, policy).iloc[0]["stake"])
    uplifted_stake = float(freeze_stakes(uplifted, policy).iloc[0]["stake"])

    assert baseline_stake == 1.67
    assert uplifted_stake == 2.08
