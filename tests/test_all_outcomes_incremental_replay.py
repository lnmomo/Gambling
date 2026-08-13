from __future__ import annotations

import pandas as pd

from scripts.all_outcomes_incremental_replay import (
    combine_incremental_tier,
    cross_cost_incremental_tiers,
)


def _base(candidate_id: str) -> pd.DataFrame:
    return pd.DataFrame([{
        "candidate_id": candidate_id, "outcome": "home", "date": "2026-01-01",
        "league": "E0", "stake": 1.0, "odds": 2.0, "won": True,
        "profit": 1.0, "decision_frozen_before_closing_and_result": True,
    }])


def _candidates(second_outcome: str = "away") -> pd.DataFrame:
    return pd.DataFrame([
        {"candidate_id": "old:away", "match_key": "old", "outcome": "away",
         "date": "2026-01-02", "league": "E0", "stake": 1.0, "odds": 3.0,
         "won": False, "profit": -1.0,
         "decision_frozen_before_closing_and_result": True},
        {"candidate_id": f"new:{second_outcome}", "match_key": "new",
         "outcome": second_outcome, "date": "2026-01-02", "league": "E1",
         "stake": 2.0, "odds": 2.5, "won": True, "profit": 3.0,
         "decision_frozen_before_closing_and_result": True},
    ])


def test_cross_cost_tier_requires_same_new_match_and_direction() -> None:
    tiers = cross_cost_incremental_tiers(
        [_base("old"), _base("old")], [_candidates(), _candidates()]
    )

    assert [frame["candidate_id"].tolist() for frame in tiers] == [["new"], ["new"]]
    assert all(frame.iloc[0]["horizon_role"] == "9m3m_all_outcomes_incremental"
               for frame in tiers)


def test_cross_cost_tier_rejects_direction_disagreement() -> None:
    tiers = cross_cost_incremental_tiers(
        [_base("old"), _base("old")], [_candidates("home"), _candidates("away")]
    )

    assert all(frame.empty for frame in tiers)


def test_cross_model_confirmation_requires_same_direction() -> None:
    tiers = cross_cost_incremental_tiers(
        [_base("old"), _base("old")],
        [_candidates("away"), _candidates("away")],
        [_candidates("away"), _candidates("home")],
    )

    assert all(frame.empty for frame in tiers)


def test_cross_model_confirmation_preserves_fully_agreed_candidate() -> None:
    tiers = cross_cost_incremental_tiers(
        [_base("old"), _base("old")],
        [_candidates("away"), _candidates("away")],
        [_candidates("away"), _candidates("away")],
    )

    assert [frame["candidate_id"].tolist() for frame in tiers] == [
        ["new"], ["new"]
    ]


def test_fallback_is_used_only_for_months_absent_from_primary() -> None:
    primary = _candidates("away").assign(test_month="2026-01")
    ignored_fallback = _candidates("home").assign(test_month="2026-01")
    used_fallback = _candidates("home").assign(
        test_month="2026-02", match_key=["old-2", "new-2"],
        candidate_id=["old-2:home", "new-2:home"],
    )
    fallback = pd.concat([ignored_fallback, used_fallback], ignore_index=True)

    tiers = cross_cost_incremental_tiers(
        [_base("old"), _base("old")], [primary, primary],
        fallback_candidates=[fallback, fallback],
    )

    assert tiers[0][["match_key", "outcome"]].values.tolist() == [
        ["new", "away"], ["old-2", "away"], ["new-2", "home"]
    ]


def test_supplemental_model_adds_only_matches_absent_from_primary() -> None:
    primary = _candidates("away")
    supplemental = _candidates("home").copy()
    extra = _candidates("home").iloc[[1]].assign(
        match_key="extra", candidate_id="extra:home"
    )
    supplemental = pd.concat([supplemental, extra], ignore_index=True)

    tiers = cross_cost_incremental_tiers(
        [_base("old"), _base("old")], [primary, primary],
        supplemental_candidates=[supplemental, supplemental],
    )

    assert tiers[0][["match_key", "outcome"]].values.tolist() == [
        ["new", "away"], ["extra", "home"]
    ]


def test_combined_tier_recomputes_profit_after_caps() -> None:
    combined = combine_incremental_tier(_base("old"), _candidates().iloc[[1]])

    assert len(combined) == 2
    assert combined["profit"].sum() == 4.0


def test_combined_tier_can_apply_fixed_fractional_kelly_multiplier() -> None:
    combined = combine_incremental_tier(
        _base("old"), _candidates().iloc[[1]], tier_stake_multiplier=2.5
    )

    incremental = combined.loc[combined["candidate_id"] == "new:away"].iloc[0]
    assert incremental["base_stake_before_tier_multiplier"] == 2.0
    assert incremental["stake"] == 5.0
    assert incremental["profit"] == 7.5


def test_cross_cost_confidence_uses_minimum_probability_and_fixed_cap() -> None:
    first = _candidates().assign(
        predicted_positive_clv_probability=[0.90, 0.90]
    )
    second = _candidates().assign(
        predicted_positive_clv_probability=[0.80, 0.80]
    )
    tiers = cross_cost_incremental_tiers(
        [_base("old"), _base("old")], [first, second]
    )

    combined = combine_incremental_tier(
        _base("old"), tiers[0], confidence_anchor=0.75,
        confidence_maximum_multiplier=1.25,
    )

    incremental = combined.loc[combined["candidate_id"] == "new"].iloc[0]
    assert incremental["cross_cost_positive_clv_probability"] == 0.80
    assert incremental["tier_confidence_multiplier"] == 0.80 / 0.75
    assert incremental["stake"] == 2.13
