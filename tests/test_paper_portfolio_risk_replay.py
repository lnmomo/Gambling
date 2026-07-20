from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.paper_portfolio_risk_replay import run as replay_run


def _write_frame(tmp_path: Path, rows: list[dict]) -> Path:
    source = tmp_path / "replay_source.csv"
    pd.DataFrame(rows).to_csv(source, index=False, encoding="utf-8-sig")
    return source


def test_replay_promotes_when_dynamic_retains_profit_and_drawdown_compatible(tmp_path: Path) -> None:
    # A clean positive sequence: dynamic risk never trips a pause, so profit is
    # retained (>=65%) and the drawdown ratio stays <=1.0 in every window.
    rows = [
        {"date": f"2022-08-{day:02d}", "unit_profit": 1.0}
        for day in range(1, 16)
    ] + [
        {"date": f"2023-08-{day:02d}", "unit_profit": 1.0}
        for day in range(1, 16)
    ] + [
        {"date": f"2024-07-{day:02d}", "unit_profit": 1.0}
        for day in range(1, 16)
    ] + [
        {"date": f"2025-07-{day:02d}", "unit_profit": 1.0}
        for day in range(1, 16)
    ]
    source = _write_frame(tmp_path, rows)
    output = tmp_path / "replay_out"

    report = replay_run(source, output, unit_stake=10.0, daily_budget=100.0)

    assert report["promotion_decision"] == "PROMOTE_DYNAMIC_RISK_CANDIDATE"
    assert (output / "summary.json").exists()
    assert (output / "daily_replay.csv").exists()
    for window in report["multi_window"]:
        assert window["profit_retention"] is not None
        assert float(window["profit_retention"]) >= 0.65
        # drawdown_ratio is None when both fixed and dynamic have zero drawdown
        # (a clean positive run); that satisfies the <=1.0 gate.
        if window["drawdown_ratio"] is not None:
            assert float(window["drawdown_ratio"]) <= 1.0


def test_replay_rejects_when_deep_drawdown_trips_pause_across_windows(tmp_path: Path) -> None:
    # Six consecutive losing settlement days per window trip PAUSED (multiplier
    # 0.0), skipping most stakes; profit retention collapses below 0.65.
    rows: list[dict] = []
    day = 1
    for year, month in (("2022", "08"), ("2023", "08"), ("2024", "07"), ("2025", "07")):
        # six losses then a small win each window
        for _ in range(6):
            rows.append({"date": f"{year}-{month}-{day:02d}", "unit_profit": -1.0})
            day = day % 28 + 1
        rows.append({"date": f"{year}-{month}-{day:02d}", "unit_profit": 5.0})
        day = day % 28 + 1
    source = _write_frame(tmp_path, rows)
    output = tmp_path / "replay_out"

    report = replay_run(source, output, unit_stake=10.0, daily_budget=100.0)

    assert report["promotion_decision"] == "REJECT_DYNAMIC_RISK_PROMOTION"
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert summary["dynamic_risk"]["paused_decisions"] > 0


def test_replay_records_tiered_states_in_daily_rows(tmp_path: Path) -> None:
    # Three losing days trip CAUTION (>=2), four trip DEFENSIVE (>=4); confirm
    # the daily replay rows surface the v3 state names.
    rows = [{"date": f"2022-08-{day:02d}", "unit_profit": -1.0} for day in range(1, 5)]
    rows.append({"date": "2022-08-06", "unit_profit": 2.0})
    rows = rows + [
        {"date": f"2023-08-{day:02d}", "unit_profit": 1.0} for day in range(1, 16)
    ] + [
        {"date": f"2024-07-{day:02d}", "unit_profit": 1.0} for day in range(1, 16)
    ] + [
        {"date": f"2025-07-{day:02d}", "unit_profit": 1.0} for day in range(1, 16)
    ]
    source = _write_frame(tmp_path, rows)
    output = tmp_path / "replay_out"

    report = replay_run(source, output, unit_stake=10.0, daily_budget=100.0)
    daily = pd.read_csv(output / "daily_replay.csv")
    state_set = set(daily["risk_status"].dropna().unique())
    assert "CAUTION" in state_set or "DEFENSIVE" in state_set or "PAUSED" in state_set
    assert "applied_stake_multiplier" in daily.columns
    assert "current_drawdown_fraction" in daily.columns
