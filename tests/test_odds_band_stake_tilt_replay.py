from __future__ import annotations

import pandas as pd
import pytest

from scripts.odds_band_stake_tilt_replay import apply_odds_band_tilt


def _positions() -> pd.DataFrame:
    return pd.DataFrame([
        {"candidate_id": "a", "outcome": "home", "odds": 2.5, "stake": 10.0,
         "date": "2026-01-01", "league": "L",
         "decision_frozen_before_closing_and_result": True,
         "closing_probability": 0.5, "won": True, "profit": 15.0},
        {"candidate_id": "b", "outcome": "away", "odds": 3.5, "stake": 10.0,
         "date": "2026-01-02", "league": "L",
         "decision_frozen_before_closing_and_result": True,
         "closing_probability": 0.4, "won": False, "profit": -10.0},
    ])


def test_odds_tilt_uses_only_frozen_execution_odds() -> None:
    source = _positions()
    selected = apply_odds_band_tilt(source)
    assert selected.set_index("candidate_id")["stake"].to_dict() == {
        "a": 10.5, "b": 9.5,
    }
    changed = source.copy()
    changed["closing_probability"] = [0.01, 0.99]
    changed["won"] = [False, True]
    changed_selected = apply_odds_band_tilt(changed)
    assert selected.set_index("candidate_id")["stake"].to_dict() == (
        changed_selected.set_index("candidate_id")["stake"].to_dict()
    )


def test_odds_tilt_rejects_unfrozen_decision() -> None:
    source = _positions()
    source.loc[0, "decision_frozen_before_closing_and_result"] = False
    with pytest.raises(ValueError, match="not frozen"):
        apply_odds_band_tilt(source)
