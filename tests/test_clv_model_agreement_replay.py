from __future__ import annotations

import pandas as pd

from scripts.clv_model_agreement_replay import (
    HALF_KELLY,
    agreement_opening,
    apply_stake_adjustments,
    apply_cross_cost_positive_clv_consensus,
    leave_one_source_out_diagnostics,
    leave_one_group_out_diagnostics,
    moving_block_bootstrap_roi,
    monthly_reset_ledger,
    prior_only_market_probability_blend,
    cap_daily_group_exposure,
    leave_one_team_out_diagnostics,
    top_winner_removal_diagnostics,
    filter_opening_by_eligibility_keys,
    closing_expected_monthly_stability,
    closing_value_diagnostics,
)
from scripts.v6_staking_policy_replay import freeze_stakes


def _positions(actual: str, offset: float) -> pd.DataFrame:
    return pd.DataFrame([{
        "candidate_id": f"candidate-{index}", "test_month": "2026-03",
        "date": "2026-03-08", "outcome": "home", "actual_outcome": actual,
        "odds": 2.5, "predicted_closing_edge_pct": 4.0 + offset,
        "lower_closing_edge_pct": 2.0 + offset, "closing_edge_pct": 3.0,
        "estimated_probability_from_lower_clv": 0.42 + offset / 100.0,
        "won": actual == "home", "profit": 1.0 if actual == "home" else -1.0,
    } for index in range(5)])


def test_agreement_and_stakes_do_not_change_with_future_results() -> None:
    direct_winners = _positions("home", 0.0)
    direct_losers = _positions("away", 0.0)
    movement_winners = _positions("home", 0.5)
    movement_losers = _positions("away", 0.5)
    winning = freeze_stakes(agreement_opening(direct_winners, movement_winners), HALF_KELLY)
    losing = freeze_stakes(agreement_opening(direct_losers, movement_losers), HALF_KELLY)
    assert winning[["candidate_id", "stake"]].equals(losing[["candidate_id", "stake"]])
    assert winning["stake"].sum() <= 100.0


def test_model_disagreement_reduces_conservative_edge() -> None:
    direct = _positions("home", 0.0)
    movement = _positions("away", 0.5)
    unpenalized = agreement_opening(direct, movement, 0.0)
    penalized = agreement_opening(direct, movement, 1.0)
    assert (
        penalized["lower_closing_edge_pct"].to_numpy()
        < unpenalized["lower_closing_edge_pct"].to_numpy()
    ).all()


def test_agreement_minimum_lower_clv_margin_is_applied_before_staking() -> None:
    direct = _positions("home", 0.0)
    movement = _positions("away", 0.5)

    one_percent = agreement_opening(direct, movement, minimum_lower_clv_pct=1.0)
    three_percent = agreement_opening(direct, movement, minimum_lower_clv_pct=3.0)

    assert len(one_percent) == 5
    assert three_percent.empty


def test_agreement_uses_lower_frozen_staking_probability() -> None:
    direct = _positions("home", 0.0)
    movement = _positions("away", 0.5)

    agreed = agreement_opening(direct, movement)

    assert (agreed["staking_probability"] == 0.42).all()


def test_agreement_can_size_from_side_channel_market_calibration() -> None:
    direct = _positions("home", 0.0)
    movement = _positions("away", 0.5)
    direct["estimated_probability_from_training_market"] = 0.38
    movement["estimated_probability_from_training_market"] = 0.36

    agreed = agreement_opening(
        direct, movement, staking_probability_profile="training_market_platt"
    )

    assert (agreed["staking_probability"] == 0.36).all()
    assert (agreed["minimum_lower_clv_staking_probability"] == 0.42).all()


def test_agreement_can_size_from_conservative_market_logistic_probability() -> None:
    direct = _positions("home", 0.0)
    movement = _positions("away", 0.5)
    direct["estimated_probability_from_training_market_logistic"] = 0.41
    movement["estimated_probability_from_training_market_logistic"] = 0.39

    agreed = agreement_opening(
        direct, movement, staking_probability_profile="training_market_logistic"
    )

    assert (agreed["staking_probability"] == 0.39).all()
    assert (agreed["minimum_lower_clv_staking_probability"] == 0.42).all()


def test_agreement_can_size_from_validated_market_residual_probability() -> None:
    direct = _positions("home", 0.0)
    movement = _positions("away", 0.5)
    direct["estimated_probability_from_validated_market_residual"] = 0.44
    movement["estimated_probability_from_validated_market_residual"] = 0.40

    agreed = agreement_opening(
        direct, movement,
        staking_probability_profile="validated_market_residual_blend",
    )

    assert (agreed["staking_probability"] == 0.40).all()


def test_external_eligibility_filter_requires_candidate_and_outcome() -> None:
    opening = _positions("home", 0.0)

    filtered = filter_opening_by_eligibility_keys(
        opening, {("candidate-1", "home"), ("candidate-3", "away")}
    )

    assert filtered["candidate_id"].tolist() == ["candidate-1"]


def test_validated_market_profile_separates_probability_and_risk_weight() -> None:
    direct = _positions("home", 0.0)
    movement = _positions("away", 0.5)
    direct["estimated_probability_from_unshrunk_training_market"] = 0.45
    movement["estimated_probability_from_unshrunk_training_market"] = 0.43
    direct["market_calibration_weight"] = 0.8
    movement["market_calibration_weight"] = 0.6

    agreed = agreement_opening(
        direct, movement, staking_probability_profile="validated_market_risk_scaling"
    )
    adjusted = apply_stake_adjustments(agreed, None, 1.0)

    assert (agreed["staking_probability"] == 0.43).all()
    assert (adjusted["stake_multiplier"] == 0.6).all()


def test_short_odds_and_reference_depth_stake_multipliers_compose() -> None:
    opening = pd.DataFrame([
        {"odds": 1.8, "reference_bookmakers": 4},
        {"odds": 2.2, "reference_bookmakers": 4},
        {"odds": 1.8, "reference_bookmakers": 5},
    ])

    adjusted = apply_stake_adjustments(opening, 4, 0.5, 2.0, 0.25)

    assert adjusted["stake_multiplier"].tolist() == [0.125, 0.5, 0.25]


def test_positive_clv_probability_soft_scaling_never_increases_stake() -> None:
    opening = pd.DataFrame({
        "reference_bookmakers": [4, 4, 4],
        "odds": [2.0, 2.0, 2.0],
        "lower_closing_edge_pct": [3.0, 3.0, 3.0],
        "predicted_positive_clv_probability": [0.30, 0.45, 0.70],
    })

    adjusted = apply_stake_adjustments(
        opening, minimum_depth=None, minimum_depth_stake_multiplier=1.0,
        positive_clv_probability_soft_cap=0.60,
        positive_clv_probability_minimum_multiplier=0.50,
    )

    assert adjusted["stake_multiplier"].tolist() == [0.5, 0.75, 1.0]


def test_positive_clv_probability_can_reallocate_with_a_bounded_uplift() -> None:
    opening = pd.DataFrame({
        "reference_bookmakers": [4, 4, 4],
        "odds": [2.0, 2.0, 2.0],
        "lower_closing_edge_pct": [3.0, 3.0, 3.0],
        "predicted_positive_clv_probability": [0.30, 0.75, 0.95],
    })

    adjusted = apply_stake_adjustments(
        opening, minimum_depth=None, minimum_depth_stake_multiplier=1.0,
        positive_clv_probability_soft_cap=0.75,
        positive_clv_probability_minimum_multiplier=0.50,
        positive_clv_probability_maximum_multiplier=1.25,
    )

    assert adjusted["stake_multiplier"].tolist() == [0.5, 1.0, 1.25]


def test_cross_cost_positive_clv_consensus_uses_lower_probability_only() -> None:
    opening = pd.DataFrame({
        "candidate_id": ["a", "b"], "outcome": ["home", "away"],
        "predicted_positive_clv_probability": [0.80, 0.90],
    })
    peer = pd.DataFrame({
        "candidate_id": ["a"], "outcome": ["home"],
        "predicted_positive_clv_probability": [0.70],
        "actual_outcome": ["away"], "profit": [999.0],
    })

    result = apply_cross_cost_positive_clv_consensus(opening, peer)
    changed_future = apply_cross_cost_positive_clv_consensus(
        opening, peer.assign(actual_outcome="home", profit=-999.0)
    )

    assert result["predicted_positive_clv_probability"].tolist() == [0.70, 0.0]
    assert changed_future["predicted_positive_clv_probability"].equals(
        result["predicted_positive_clv_probability"]
    )


def test_low_clv_confidence_tier_composes_without_future_results() -> None:
    opening = pd.DataFrame([
        {"odds": 2.0, "reference_bookmakers": 4, "lower_closing_edge_pct": 1.5},
        {"odds": 2.0, "reference_bookmakers": 5, "lower_closing_edge_pct": 2.0},
    ])

    adjusted = apply_stake_adjustments(
        opening, 4, 0.5, low_clv_upper_pct=2.0,
        low_clv_stake_multiplier=0.5,
    )

    assert adjusted["stake_multiplier"].tolist() == [0.25, 1.0]


def test_probability_blend_uses_only_strictly_earlier_settlements() -> None:
    opening = pd.DataFrame([
        {"candidate_id": "jan", "test_month": "2026-01", "probability": 0.40, "staking_probability": 0.50},
        {"candidate_id": "feb", "test_month": "2026-02", "probability": 0.40, "staking_probability": 0.50},
        {"candidate_id": "mar", "test_month": "2026-03", "probability": 0.40, "staking_probability": 0.50},
    ])
    settlements = pd.DataFrame([
        {"candidate_id": "jan", "test_month": "2026-01", "won": False},
        {"candidate_id": "feb", "test_month": "2026-02", "won": True},
        {"candidate_id": "mar", "test_month": "2026-03", "won": True},
    ])

    baseline, diagnostics = prior_only_market_probability_blend(
        opening, settlements, minimum_prior_positions=1, prior_strength=0
    )
    future_changed = settlements.copy()
    future_changed.loc[future_changed["candidate_id"] == "mar", "won"] = False
    changed, _ = prior_only_market_probability_blend(
        opening, future_changed, minimum_prior_positions=1, prior_strength=0
    )

    assert baseline.loc[baseline["candidate_id"] == "feb", "staking_probability"].item() == 0.40
    assert changed.loc[changed["candidate_id"] == "feb", "staking_probability"].item() == 0.40
    assert diagnostics[0]["status"] == "INSUFFICIENT_PRIOR_SETTLEMENTS"


def test_daily_league_cap_scales_frozen_stakes_without_results() -> None:
    frozen = pd.DataFrame([
        {"candidate_id": "a", "date": "2026-01-01", "league": "E0", "stake": 12.0},
        {"candidate_id": "b", "date": "2026-01-01", "league": "E0", "stake": 8.0},
        {"candidate_id": "c", "date": "2026-01-01", "league": "D1", "stake": 9.0},
    ])

    capped = cap_daily_group_exposure(frozen, "league", 15.0)

    assert capped.loc[capped["league"] == "E0", "stake"].sum() == 15.0
    assert capped.loc[capped["league"] == "D1", "stake"].sum() == 9.0


def test_team_and_winner_removal_diagnostics_preserve_positive_diverse_sample() -> None:
    settled = pd.DataFrame([
        {
            "candidate_id": f"c-{index}", "test_month": f"2026-{index + 1:02d}",
            "home_team": "Shared" if index < 2 else f"H-{index}",
            "away_team": f"A-{index}", "stake": 10.0, "profit": 1.0,
        }
        for index in range(12)
    ])
    months = settled["test_month"].tolist()

    teams = leave_one_team_out_diagnostics(settled, months)
    winners = top_winner_removal_diagnostics(settled, months)

    assert teams["minimum_lower_95_pct"] == 10.0
    assert winners["scenarios"][-1]["removed_winners"] == 10
    assert winners["scenarios"][-1]["retained_profit"] == 2.0


def test_closing_value_diagnostics_separates_expected_edge_from_result_luck() -> None:
    settled = pd.DataFrame([
        {
            "date": "2022-01-01", "stake": 10.0, "odds": 2.0,
            "closing_probability": 0.55, "closing_edge_pct": 10.0,
            "profit": 10.0,
        },
        {
            "date": "2024-01-01", "stake": 10.0, "odds": 2.0,
            "closing_probability": 0.60, "closing_edge_pct": 20.0,
            "profit": -10.0,
        },
    ])

    report = closing_value_diagnostics(settled)

    assert report["status"] == "READY"
    assert report["all"]["closing_expected_profit"] == 3.0
    assert report["all"]["closing_expected_roi_pct"] == 15.0
    assert report["late"]["closing_expected_profit"] == 2.0
    assert report["realized_profit"] == 0.0
    assert report["realized_minus_closing_expected_profit"] == -3.0


def test_closing_expected_monthly_stability_ignores_match_result_profit() -> None:
    settled = pd.DataFrame([
        {
            "test_month": f"2025-{month:02d}", "stake": 10.0,
            "odds": 2.0, "closing_probability": 0.55,
            "profit": 10.0 if month % 2 else -10.0,
        }
        for month in range(1, 13)
    ])
    months = [f"2025-{month:02d}" for month in range(1, 13)]

    baseline = closing_expected_monthly_stability(settled, months)
    changed = closing_expected_monthly_stability(
        settled.assign(profit=-settled["profit"]), months
    )

    assert baseline == changed
    assert baseline["status"] == "READY"
    assert baseline["positive_expected_active_months"] == 12
    assert baseline["monthly_bootstrap_roi"]["lower_95_pct"] == 10.0
    assert baseline["moving_block_bootstrap_roi"]["lower_95_pct"] == 10.0


def test_moving_block_bootstrap_requires_staked_months_and_preserves_positive_series() -> None:
    empty = moving_block_bootstrap_roi([
        {"month": "2026-01", "staked": 0.0, "profit": 0.0},
    ], iterations=100)
    positive = moving_block_bootstrap_roi([
        {"month": f"2026-{month:02d}", "staked": 10.0, "profit": 1.0}
        for month in range(1, 7)
    ], block_size=3, iterations=100)
    short = moving_block_bootstrap_roi([
        {"month": "2026-01", "staked": 10.0, "profit": 5.0},
    ], block_size=3, iterations=100)

    assert empty["status"] == "NO_STAKED_POSITIONS"
    assert short["status"] == "INSUFFICIENT_MONTHS"
    assert short["lower_95_pct"] is None
    assert positive["lower_95_pct"] == 10.0


def test_leave_one_source_out_removes_each_bookmaker_before_bootstrap() -> None:
    settled = pd.DataFrame([
        {"test_month": "2026-01", "execution_bookmaker": "A", "stake": 1.0, "profit": 1.0},
        {"test_month": "2026-02", "execution_bookmaker": "B", "stake": 1.0, "profit": 1.0},
        {"test_month": "2026-03", "execution_bookmaker": "A", "stake": 1.0, "profit": 1.0},
    ])

    report = leave_one_source_out_diagnostics(
        settled, ["2026-01", "2026-02", "2026-03"]
    )

    assert report["status"] == "READY"
    by_source = {row["excluded_bookmaker"]: row for row in report["sources"]}
    assert by_source["A"]["retained_bets"] == 1
    assert by_source["B"]["retained_bets"] == 2
    assert report["minimum_lower_95_pct"] == 100.0


def test_leave_one_group_out_supports_league_and_outcome_dimensions() -> None:
    settled = pd.DataFrame([
        {"test_month": "2026-01", "league": "E0", "outcome": "home", "stake": 1.0, "profit": 1.0},
        {"test_month": "2026-02", "league": "D1", "outcome": "away", "stake": 1.0, "profit": 1.0},
        {"test_month": "2026-03", "league": "E0", "outcome": "draw", "stake": 1.0, "profit": 1.0},
    ])

    report = leave_one_group_out_diagnostics(
        settled, ["2026-01", "2026-02", "2026-03"], "league"
    )

    assert report["group_column"] == "league"
    assert {row["excluded_group"] for row in report["groups"]} == {"D1", "E0"}
    assert report["minimum_lower_95_pct"] == 100.0


def test_monthly_reset_ledger_starts_each_month_from_zero() -> None:
    daily = pd.DataFrame([
        {"date": "2026-04-30", "profit": 5.0},
        {"date": "2026-05-01", "profit": -2.0},
        {"date": "2026-05-02", "profit": 3.0},
    ])

    result = monthly_reset_ledger(daily)

    assert result["monthly_cumulative_profit"].tolist() == [5.0, -2.0, 1.0]
    assert result["monthly_drawdown"].tolist() == [0.0, 2.0, 0.0]
