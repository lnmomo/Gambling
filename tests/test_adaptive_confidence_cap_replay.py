from __future__ import annotations

import pandas as pd
import pytest

from scripts.adaptive_confidence_cap_replay import select_walk_forward_caps


def _portfolios() -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    for index in range(12):
        month = "2025-01" if index < 10 else "2025-02"
        rows.append({
            "candidate_id": f"c{index}", "outcome": "home",
            "test_month": month, "date": f"{month}-01", "odds": 2.0,
            "stake": 1.0, "closing_probability": 0.55,
            "won": index % 2 == 0, "profit": 0.0,
        })
    conservative = pd.DataFrame(rows)
    growth = conservative.copy()
    growth["stake"] = 1.2
    return conservative, growth


def test_cap_for_month_uses_only_prior_closing_evidence() -> None:
    conservative, growth = _portfolios()
    selected, audit = select_walk_forward_caps(conservative, growth, 10)
    assert audit.loc[audit["month"] == "2025-01", "decision"].item() == "CONSERVATIVE"
    assert audit.loc[audit["month"] == "2025-02", "decision"].item() == "GROWTH"
    assert set(selected.loc[selected["test_month"] == "2025-02", "stake"]) == {1.2}

    changed = growth.copy()
    changed.loc[changed["test_month"] == "2025-02", "closing_probability"] = 0.01
    changed.loc[changed["test_month"] == "2025-02", "won"] = False
    _, changed_audit = select_walk_forward_caps(conservative, changed, 10)
    pd.testing.assert_frame_equal(audit, changed_audit)


def test_cap_replay_rejects_direction_or_candidate_mismatch() -> None:
    conservative, growth = _portfolios()
    growth.loc[0, "outcome"] = "away"
    with pytest.raises(ValueError, match="identical decisions"):
        select_walk_forward_caps(conservative, growth, 10)
