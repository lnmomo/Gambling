from __future__ import annotations

import pandas as pd

from scripts.monthly_portfolio_distribution import build_monthly_distribution


def test_month_distribution_includes_empty_calendar_month_and_days() -> None:
    positions = pd.DataFrame([
        {"candidate_id": "a", "outcome": "home", "test_month": "2026-01",
         "date": "2026-01-02", "stake": 10.0, "odds": 2.0, "won": True,
         "closing_probability": 0.55,
         "decision_frozen_before_closing_and_result": True},
        {"candidate_id": "b", "outcome": "away", "test_month": "2026-03",
         "date": "2026-03-03", "stake": 5.0, "odds": 3.0, "won": False,
         "closing_probability": 0.40,
         "decision_frozen_before_closing_and_result": True},
    ])

    summary, monthly, daily = build_monthly_distribution(positions)

    assert summary["calendar_months"] == 3
    assert summary["empty_months"] == 1
    assert summary["realized_profitable_calendar_month_rate"] == 0.3333
    assert summary["realized_losing_calendar_month_rate"] == 0.3333
    assert monthly.loc[monthly["month"] == "2026-02", "positions"].item() == 0
    assert len(daily) == 31 + 28 + 31
    assert daily.loc[daily["date"] == "2026-01-02", "settled_profit"].item() == 10.0
    assert daily.loc[daily["date"] == "2026-03-03", "settled_profit"].item() == -5.0

    expanded, expanded_monthly, _ = build_monthly_distribution(
        positions, month_range=("2025-12", "2026-04")
    )
    assert expanded["calendar_months"] == 5
    assert expanded_monthly.iloc[0]["month"] == "2025-12"
    assert expanded_monthly.iloc[-1]["month"] == "2026-04"
