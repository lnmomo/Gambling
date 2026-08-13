from __future__ import annotations

import pandas as pd

from scripts.direct_only_confidence_tier_replay import (
    add_direct_only_confidence_tier,
)


def _row(candidate: str, probability: float) -> dict[str, object]:
    return {
        "candidate_id": candidate, "outcome": "home", "date": "2026-01-01",
        "league": "L", "odds": 2.0, "stake": 1.0,
        "lower_closing_edge_pct": 2.0,
        "estimated_probability_from_training_market": 0.55,
        "predicted_positive_clv_probability": probability,
        "decision_frozen_before_closing_and_result": True,
        "closing_probability": 0.6, "positive_clv": True,
        "actual_outcome": "home", "won": True, "profit": 1.0,
    }


def test_direct_only_tier_ignores_future_fields_and_existing_matches() -> None:
    base = pd.DataFrame([_row("existing", 0.9)])
    direct = pd.DataFrame([_row("existing", 0.9), _row("new", 0.8)])
    peer = pd.DataFrame([_row("existing", 0.9), _row("new", 0.7)])
    selected = add_direct_only_confidence_tier(base, direct, peer)
    assert set(selected["candidate_id"]) == {"existing", "new"}
    new_stake = selected.loc[selected["candidate_id"] == "new", "stake"].item()

    changed = direct.copy()
    changed["closing_probability"] = 0.01
    changed["actual_outcome"] = "away"
    changed["won"] = False
    changed_selected = add_direct_only_confidence_tier(base, changed, peer)
    assert changed_selected.loc[
        changed_selected["candidate_id"] == "new", "stake"
    ].item() == new_stake
