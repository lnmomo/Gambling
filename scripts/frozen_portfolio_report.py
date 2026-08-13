"""Shared diagnostics for an already frozen no-lookahead portfolio."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from scripts.clv_model_agreement_replay import (
    closing_expected_monthly_stability,
    closing_value_diagnostics,
    leave_one_group_out_diagnostics,
    leave_one_source_out_diagnostics,
    leave_one_team_out_diagnostics,
    moving_block_bootstrap_roi,
)
from scripts.multi_horizon_clv_replay import horizon_role_attribution
from scripts.robust_consensus_latest_month_holdout import _monthly_bootstrap


def closing_expected_profit_frame(selected: pd.DataFrame) -> pd.DataFrame:
    required = {"stake", "closing_edge_pct"}
    missing = required - set(selected.columns)
    if missing:
        raise ValueError(f"closing attribution is missing columns: {sorted(missing)}")
    attributed = selected.copy()
    attributed["profit"] = (
        attributed["stake"].astype(float)
        * attributed["closing_edge_pct"].astype(float) / 100.0
    )
    return attributed


def write_frozen_portfolio_report(
    selected: pd.DataFrame,
    source_summary: dict[str, Any],
    output_dir: Path,
    method: str,
    anti_leakage: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    month_names = [str(row["month"]) for row in source_summary["monthly"]]
    monthly: list[dict[str, Any]] = []
    for month in month_names:
        frame = selected.loc[selected["test_month"].astype(str) == month]
        stake = float(frame["stake"].sum())
        profit = float(frame["profit"].sum())
        monthly.append({
            "month": month, "bets": int(len(frame)),
            "staked": round(stake, 2), "profit": round(profit, 2),
            "roi_pct": round(profit / stake * 100.0, 2) if stake else 0.0,
        })

    cumulative = peak = maximum_drawdown = 0.0
    daily_rows: list[dict[str, Any]] = []
    for date, frame in selected.groupby("date", sort=True):
        profit = round(float(frame["profit"].sum()), 2)
        cumulative = round(cumulative + profit, 2)
        peak = max(peak, cumulative)
        drawdown = round(peak - cumulative, 2)
        maximum_drawdown = max(maximum_drawdown, drawdown)
        daily_rows.append({
            "date": str(date), "bets": int(len(frame)),
            "staked": round(float(frame["stake"].sum()), 2),
            "profit": profit, "cumulative_profit": cumulative,
            "drawdown": drawdown,
        })

    closing = closing_value_diagnostics(selected)
    closing_monthly = closing_expected_monthly_stability(selected, month_names)
    groups = {
        column: leave_one_group_out_diagnostics(selected, month_names, column)
        for column in ("league", "outcome", "odds_band")
    }
    closing_expected = closing_expected_profit_frame(selected)
    closing_expected_groups = {
        column: leave_one_group_out_diagnostics(
            closing_expected, month_names, column
        )
        for column in ("league", "outcome", "odds_band")
    }
    stake = float(selected["stake"].sum())
    profit = float(selected["profit"].sum())
    active = [row for row in monthly if row["bets"] > 0]
    payload = {
        "method": method,
        "anti_leakage": anti_leakage,
        "daily_budget_limit": 100.0,
        "maximum_daily_league_stake": 15.0,
        "positions": int(len(selected)),
        "active_months": len(active),
        "staked": round(stake, 2),
        "profit": round(profit, 2),
        "roi_pct": round(profit / stake * 100.0, 2) if stake else 0.0,
        "maximum_drawdown": round(maximum_drawdown, 2),
        "monthly_bootstrap_roi": _monthly_bootstrap(monthly),
        "moving_block_bootstrap_roi": moving_block_bootstrap_roi(monthly),
        "leave_one_execution_source_out": leave_one_source_out_diagnostics(
            selected, month_names
        ),
        "leave_one_group_out": groups,
        "leave_one_team_out": leave_one_team_out_diagnostics(selected, month_names),
        "closing_expected_leave_one_execution_source_out": (
            leave_one_source_out_diagnostics(closing_expected, month_names)
        ),
        "closing_expected_leave_one_group_out": closing_expected_groups,
        "closing_expected_leave_one_team_out": leave_one_team_out_diagnostics(
            closing_expected, month_names
        ),
        "closing_value": closing,
        "closing_expected_monthly_stability": closing_monthly,
        "horizon_role_attribution": horizon_role_attribution(selected),
        "decision": "ROLLING_RESEARCH_SURVIVOR",
        "monthly": monthly,
        "live_promotion_allowed": False,
        **(extra or {}),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    selected.to_csv(output_dir / "positions.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(monthly).to_csv(
        output_dir / "monthly.csv", index=False, encoding="utf-8-sig"
    )
    pd.DataFrame(daily_rows).to_csv(
        output_dir / "daily.csv", index=False, encoding="utf-8-sig"
    )
    (output_dir / "summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return payload
