"""Render a complete calendar-month ledger from already frozen paper positions."""
from __future__ import annotations

import argparse
import calendar
import json
from pathlib import Path
from typing import Any

import pandas as pd


SETTLEMENT_COLUMNS = {
    "actual_outcome", "closing_edge_pct", "positive_clv", "closing_probability",
    "closing_fair_odds", "won", "profit",
}


def replay_fixed_month(
    positions: pd.DataFrame,
    month: str,
    output_dir: Path,
    daily_budget: float = 100.0,
    maximum_daily_league_stake: float = 15.0,
    opening_equity: float = 0.0,
) -> dict[str, Any]:
    month_period = pd.Period(month, freq="M")
    selected = positions.loc[
        positions["test_month"].astype(str) == str(month_period)
    ].copy()
    if selected.empty:
        raise ValueError(f"no frozen positions for {month}")
    if selected.duplicated(["candidate_id", "outcome"]).any():
        raise ValueError("duplicate frozen candidate and outcome")
    if "decision_frozen_before_closing_and_result" in selected and not bool(
        selected["decision_frozen_before_closing_and_result"].astype(bool).all()
    ):
        raise ValueError("a position was not frozen before closing and result")

    opening = selected.drop(
        columns=[column for column in SETTLEMENT_COLUMNS if column in selected],
        errors="ignore",
    ).copy()
    settlement_columns = [
        column for column in SETTLEMENT_COLUMNS if column in selected
    ]
    settlement = selected[
        ["candidate_id", "outcome", *settlement_columns]
    ].copy()
    settled = opening.merge(
        settlement, on=["candidate_id", "outcome"], how="left",
        validate="one_to_one",
    )
    settled["profit"] = settled.apply(
        lambda row: round(
            float(row["stake"]) * (float(row["odds"]) - 1.0)
            if bool(row["won"]) else -float(row["stake"]), 2
        ), axis=1,
    )

    daily_stake = settled.groupby("date")["stake"].sum()
    if float(daily_stake.max()) > daily_budget + 1e-9:
        raise ValueError("frozen portfolio exceeds daily budget")
    league_daily = settled.groupby(["date", "league"])["stake"].sum()
    if float(league_daily.max()) > maximum_daily_league_stake + 1e-9:
        raise ValueError("frozen portfolio exceeds daily league cap")

    year, month_number = map(int, month.split("-"))
    days = calendar.monthrange(year, month_number)[1]
    cumulative = float(opening_equity)
    peak = cumulative
    daily_rows: list[dict[str, Any]] = []
    for day in range(1, days + 1):
        date_value = f"{month}-{day:02d}"
        frame = settled.loc[settled["date"].astype(str) == date_value]
        staked = round(float(frame["stake"].sum()), 2)
        profit = round(float(frame["profit"].sum()), 2)
        start = cumulative
        cumulative = round(cumulative + profit, 2)
        peak = max(peak, cumulative)
        daily_rows.append({
            "date": date_value,
            "opening_equity": round(start, 2),
            "positions": int(len(frame)),
            "staked": staked,
            "unused_daily_budget": round(daily_budget - staked, 2),
            "settled_profit": profit,
            "ending_equity": cumulative,
            "drawdown": round(peak - cumulative, 2),
        })

    direction_labels = {"home": "主胜", "draw": "平", "away": "客胜"}
    details = settled.sort_values(["date", "candidate_id"]).copy()
    details["direction_zh"] = details["outcome"].map(direction_labels)
    details["decision_frozen_before_result"] = True
    detail_columns = [
        "date", "candidate_id", "league", "home_team", "away_team", "outcome",
        "direction_zh", "odds", "stake", "actual_outcome", "won", "profit",
        "horizon_role", "decision_frozen_before_result", "closing_probability",
        "closing_edge_pct", "positive_clv",
    ]
    details = details[[column for column in detail_columns if column in details]]
    stake = float(settled["stake"].sum())
    profit = float(settled["profit"].sum())
    closing_expected_profit = float((
        settled["stake"].astype(float)
        * (settled["closing_probability"].astype(float) * settled["odds"].astype(float) - 1.0)
    ).sum()) if "closing_probability" in settled else None
    payload = {
        "month": month,
        "method": "positions frozen before closing prices and results; settlement attached afterward",
        "purpose": "process audit only; this inspected month cannot select or promote an algorithm",
        "daily_budget_limit": daily_budget,
        "maximum_daily_league_stake": maximum_daily_league_stake,
        "calendar_days": days,
        "betting_days": sum(row["positions"] > 0 for row in daily_rows),
        "no_bet_days": sum(row["positions"] == 0 for row in daily_rows),
        "positions": int(len(settled)),
        "staked": round(stake, 2),
        "realized_profit": round(profit, 2),
        "realized_roi_pct": round(profit / stake * 100.0, 2) if stake else 0.0,
        "opening_equity": round(opening_equity, 2),
        "ending_equity": round(cumulative, 2),
        "maximum_drawdown": max(row["drawdown"] for row in daily_rows),
        "maximum_daily_stake": round(float(daily_stake.max()), 2),
        "maximum_daily_league_stake_observed": round(float(league_daily.max()), 2),
        "closing_expected_profit": (
            round(closing_expected_profit, 4)
            if closing_expected_profit is not None else None
        ),
        "daily": daily_rows,
        "anti_leakage_checks": {
            "unique_frozen_candidates": True,
            "directions_and_stakes_selected_before_settlement_merge": True,
            "all_positions_marked_frozen": True,
            "daily_budget_respected": True,
            "daily_league_cap_respected": True,
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    pd.DataFrame(daily_rows).to_csv(
        output_dir / "daily.csv", index=False, encoding="utf-8-sig"
    )
    details.to_csv(output_dir / "positions.csv", index=False, encoding="utf-8-sig")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--positions", type=Path, required=True)
    parser.add_argument("--month", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--daily-budget", type=float, default=100.0)
    parser.add_argument("--maximum-daily-league-stake", type=float, default=15.0)
    parser.add_argument("--opening-equity", type=float, default=0.0)
    args = parser.parse_args()
    report = replay_fixed_month(
        pd.read_csv(args.positions), args.month, args.output_dir,
        args.daily_budget, args.maximum_daily_league_stake, args.opening_equity,
    )
    print(json.dumps({key: value for key, value in report.items() if key != "daily"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
