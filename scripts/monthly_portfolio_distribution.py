"""Audit every calendar month and day of a frozen historical portfolio."""
from __future__ import annotations

import argparse
import calendar
import json
from pathlib import Path
from typing import Any

import pandas as pd


def build_monthly_distribution(
    positions: pd.DataFrame,
    daily_budget: float = 100.0,
    month_range: tuple[str, str] | None = None,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    required = {
        "candidate_id", "outcome", "test_month", "date", "stake", "odds",
        "won", "closing_probability", "decision_frozen_before_closing_and_result",
    }
    missing = required - set(positions.columns)
    if missing:
        raise ValueError(f"frozen portfolio is missing columns: {sorted(missing)}")
    frozen = positions["decision_frozen_before_closing_and_result"].astype(str).str.lower()
    if not frozen.isin({"true", "1"}).all():
        raise ValueError("portfolio contains a decision that was not frozen")
    if positions.duplicated(["candidate_id", "outcome"]).any():
        raise ValueError("portfolio contains duplicate candidate directions")

    frame = positions.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="raise")
    frame["settled_profit"] = (
        frame["stake"].astype(float) * (frame["odds"].astype(float) - 1.0)
    ).where(frame["won"].astype(bool), -frame["stake"].astype(float)).round(2)
    frame["closing_expected_profit"] = frame["stake"].astype(float) * (
        frame["closing_probability"].astype(float) * frame["odds"].astype(float)
        - 1.0
    )
    first = pd.Period(
        month_range[0] if month_range else frame["test_month"].astype(str).min(),
        freq="M",
    )
    last = pd.Period(
        month_range[1] if month_range else frame["test_month"].astype(str).max(),
        freq="M",
    )
    months = pd.period_range(first, last, freq="M")

    daily_rows: list[dict[str, Any]] = []
    monthly_rows: list[dict[str, Any]] = []
    cumulative = peak = 0.0
    for month in months:
        month_text = str(month)
        month_frame = frame.loc[frame["test_month"].astype(str) == month_text]
        monthly_cumulative = monthly_peak = monthly_drawdown = 0.0
        year, month_number = month.year, month.month
        for day in range(1, calendar.monthrange(year, month_number)[1] + 1):
            date = pd.Timestamp(year=year, month=month_number, day=day)
            selected = month_frame.loc[month_frame["date"] == date]
            stake = round(float(selected["stake"].sum()), 2)
            profit = round(float(selected["settled_profit"].sum()), 2)
            expected = float(selected["closing_expected_profit"].sum())
            cumulative = round(cumulative + profit, 2)
            peak = max(peak, cumulative)
            monthly_cumulative = round(monthly_cumulative + profit, 2)
            monthly_peak = max(monthly_peak, monthly_cumulative)
            monthly_drawdown = max(
                monthly_drawdown, monthly_peak - monthly_cumulative
            )
            daily_rows.append({
                "date": date.date().isoformat(), "month": month_text,
                "positions": int(len(selected)), "staked": stake,
                "unused_daily_budget": round(daily_budget - stake, 2),
                "settled_profit": profit,
                "closing_expected_profit": round(expected, 6),
                "cumulative_profit": cumulative,
                "drawdown": round(peak - cumulative, 2),
            })
        stake = float(month_frame["stake"].sum())
        profit = float(month_frame["settled_profit"].sum())
        expected = float(month_frame["closing_expected_profit"].sum())
        days = calendar.monthrange(year, month_number)[1]
        monthly_rows.append({
            "month": month_text, "calendar_days": days,
            "positions": int(len(month_frame)),
            "betting_days": int(month_frame["date"].dt.date.nunique()),
            "no_bet_days": days - int(month_frame["date"].dt.date.nunique()),
            "staked": round(stake, 2), "realized_profit": round(profit, 2),
            "realized_roi_pct": round(profit / stake * 100.0, 2) if stake else 0.0,
            "closing_expected_profit": round(expected, 6),
            "closing_expected_roi_pct": (
                round(expected / stake * 100.0, 4) if stake else 0.0
            ),
            "maximum_drawdown": round(monthly_drawdown, 2),
            "budget_utilization_pct": round(
                stake / (days * daily_budget) * 100.0, 4
            ),
        })

    monthly = pd.DataFrame(monthly_rows)
    daily = pd.DataFrame(daily_rows)
    active = monthly.loc[monthly["positions"] > 0]
    profitable = active.loc[active["realized_profit"] > 0]
    losing = active.loc[active["realized_profit"] < 0]
    expected_positive = active.loc[active["closing_expected_profit"] > 0]
    payload = {
        "method": "complete calendar-month distribution from frozen positions",
        "anti_leakage": (
            "Directions and stakes are frozen before settlement. Results affect only "
            "same-day settlement profit; closing probabilities are attribution-only."
        ),
        "period": {"first_month": str(first), "last_month": str(last)},
        "daily_budget_limit": daily_budget,
        "calendar_months": int(len(monthly)),
        "calendar_days": int(monthly["calendar_days"].sum()),
        "active_months": int(len(active)),
        "empty_months": int((monthly["positions"] == 0).sum()),
        "profitable_active_months": int(len(profitable)),
        "losing_active_months": int(len(losing)),
        "realized_profitable_active_month_rate": round(
            len(profitable) / len(active), 4
        ) if len(active) else None,
        "realized_profitable_calendar_month_rate": round(
            len(profitable) / len(monthly), 4
        ) if len(monthly) else None,
        "realized_losing_calendar_month_rate": round(
            len(losing) / len(monthly), 4
        ) if len(monthly) else None,
        "closing_expected_positive_active_months": int(len(expected_positive)),
        "closing_expected_positive_active_month_rate": round(
            len(expected_positive) / len(active), 4
        ) if len(active) else None,
        "closing_expected_positive_calendar_month_rate": round(
            len(expected_positive) / len(monthly), 4
        ) if len(monthly) else None,
        "median_active_month_realized_profit": round(
            float(active["realized_profit"].median()), 4
        ) if len(active) else None,
        "active_month_realized_profit_p10": round(
            float(active["realized_profit"].quantile(0.10)), 4
        ) if len(active) else None,
        "active_month_realized_profit_p90": round(
            float(active["realized_profit"].quantile(0.90)), 4
        ) if len(active) else None,
        "maximum_calendar_month_drawdown": round(
            float(monthly["maximum_drawdown"].max()), 2
        ),
        "positions": int(len(frame)),
        "staked": round(float(frame["stake"].sum()), 2),
        "realized_profit": round(float(frame["settled_profit"].sum()), 2),
        "closing_expected_profit": round(
            float(frame["closing_expected_profit"].sum()), 4
        ),
        "overall_budget_utilization_pct": round(
            float(frame["stake"].sum())
            / (float(monthly["calendar_days"].sum()) * daily_budget) * 100.0,
            4,
        ),
        "best_realized_month": (
            profitable.sort_values("realized_profit").iloc[-1].to_dict()
            if len(profitable) else None
        ),
        "worst_realized_month": (
            losing.sort_values("realized_profit").iloc[0].to_dict()
            if len(losing) else None
        ),
        "worst_closing_expected_month": (
            active.sort_values("closing_expected_profit").iloc[0].to_dict()
            if len(active) else None
        ),
        "guardrail": (
            "All months between the first and last archived test month are included; "
            "the report cannot select an algorithm or a favorable month."
        ),
    }
    return payload, monthly, daily


def replay_monthly_distribution(
    positions_file: Path, output_dir: Path, daily_budget: float = 100.0,
    source_summary_file: Path | None = None,
) -> dict[str, Any]:
    month_range = None
    if source_summary_file is not None:
        source_summary = json.loads(
            source_summary_file.read_text(encoding="utf-8-sig")
        )
        source_months = [str(row["month"]) for row in source_summary["monthly"]]
        month_range = (min(source_months), max(source_months))
    payload, monthly, daily = build_monthly_distribution(
        pd.read_csv(positions_file), daily_budget, month_range
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    monthly.to_csv(
        output_dir / "monthly_scorecard.csv", index=False, encoding="utf-8-sig"
    )
    daily.to_csv(
        output_dir / "daily_full.csv", index=False, encoding="utf-8-sig"
    )
    (output_dir / "summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--positions", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--daily-budget", type=float, default=100.0)
    parser.add_argument("--source-summary", type=Path)
    args = parser.parse_args()
    print(json.dumps(
        replay_monthly_distribution(
            args.positions, args.output_dir, args.daily_budget,
            args.source_summary,
        ), ensure_ascii=False, indent=2, default=str,
    ))


if __name__ == "__main__":
    main()
