"""Walk-forward selection between frozen confidence stake caps."""
from __future__ import annotations

import argparse
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


KEY_COLUMNS = ["candidate_id", "outcome"]
DECISION_COLUMNS = ["test_month", "date", "odds"]


def select_walk_forward_caps(
    conservative: pd.DataFrame,
    growth: pd.DataFrame,
    minimum_prior_uplifted_positions: int = 10,
    conservative_cap: float = 1.05,
    growth_cap: float = 1.25,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Choose each month's cap using closing evidence available before that month."""
    if minimum_prior_uplifted_positions < 1:
        raise ValueError("minimum prior uplifted positions must be positive")
    required = {
        *KEY_COLUMNS, *DECISION_COLUMNS, "stake", "closing_probability", "won",
    }
    for label, frame in (("conservative", conservative), ("growth", growth)):
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(f"{label} portfolio is missing columns: {sorted(missing)}")
        if frame.duplicated(KEY_COLUMNS).any():
            raise ValueError(f"{label} portfolio contains duplicate decisions")

    base = conservative.set_index(KEY_COLUMNS, drop=False).sort_index()
    aggressive = growth.set_index(KEY_COLUMNS, drop=False).sort_index()
    if not base.index.equals(aggressive.index):
        raise ValueError("confidence-cap portfolios must contain identical decisions")
    for column in DECISION_COLUMNS:
        if not base[column].astype(str).equals(aggressive[column].astype(str)):
            raise ValueError(f"confidence-cap portfolios disagree on {column}")

    comparison = base[[*DECISION_COLUMNS, "stake", "closing_probability"]].copy()
    comparison = comparison.rename(columns={"stake": "conservative_stake"})
    comparison["growth_stake"] = aggressive["stake"].astype(float)
    comparison["stake_delta"] = (
        comparison["growth_stake"] - comparison["conservative_stake"].astype(float)
    )
    comparison["prior_closing_expected_delta"] = comparison["stake_delta"] * (
        comparison["closing_probability"].astype(float)
        * comparison["odds"].astype(float)
        - 1.0
    )

    selected_frames: list[pd.DataFrame] = []
    audits: list[dict[str, Any]] = []
    months = sorted(comparison["test_month"].astype(str).unique())
    for month in months:
        prior = comparison.loc[comparison["test_month"].astype(str) < month]
        prior_uplifted = int((prior["stake_delta"] > 1e-9).sum())
        prior_expected_delta = float(prior["prior_closing_expected_delta"].sum())
        use_growth = (
            prior_uplifted >= minimum_prior_uplifted_positions
            and prior_expected_delta > 0.0
        )
        source = aggressive if use_growth else base
        selected = source.loc[source["test_month"].astype(str) == month].copy()
        selected["adaptive_confidence_cap"] = (
            growth_cap if use_growth else conservative_cap
        )
        selected["cap_selected_from_prior_closing_only"] = True
        selected_frames.append(selected)
        audits.append({
            "month": month,
            "selected_cap": growth_cap if use_growth else conservative_cap,
            "prior_uplifted_positions": prior_uplifted,
            "prior_closing_expected_profit_delta": round(prior_expected_delta, 6),
            "decision": "GROWTH" if use_growth else "CONSERVATIVE",
        })

    selected = pd.concat(selected_frames, ignore_index=True)
    selected["profit"] = selected.apply(
        lambda row: (
            float(row["stake"]) * (float(row["odds"]) - 1.0)
            if bool(row["won"]) else -float(row["stake"])
        ), axis=1,
    ).round(2)
    return selected, pd.DataFrame(audits)


def replay_adaptive_cap(
    conservative_dir: Path,
    growth_dir: Path,
    output_dir: Path,
    minimum_prior_uplifted_positions: int = 10,
) -> dict[str, Any]:
    conservative = pd.read_csv(conservative_dir / "positions.csv")
    growth = pd.read_csv(growth_dir / "positions.csv")
    source_summary = json.loads(
        (conservative_dir / "summary.json").read_text(encoding="utf-8-sig")
    )
    selected, cap_audit = select_walk_forward_caps(
        conservative, growth, minimum_prior_uplifted_positions
    )
    month_names = [str(row["month"]) for row in source_summary["monthly"]]
    monthly: list[dict[str, Any]] = []
    for month in month_names:
        frame = selected.loc[selected["test_month"].astype(str) == month]
        stake = float(frame["stake"].sum())
        profit = float(frame["profit"].sum())
        monthly.append({
            "month": month,
            "bets": int(len(frame)),
            "staked": round(stake, 2),
            "profit": round(profit, 2),
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
    source = leave_one_source_out_diagnostics(selected, month_names)
    groups = {
        column: leave_one_group_out_diagnostics(selected, month_names, column)
        for column in ("league", "outcome", "odds_band")
    }
    team = leave_one_team_out_diagnostics(selected, month_names)
    stake = float(selected["stake"].sum())
    profit = float(selected["profit"].sum())
    active = [row for row in monthly if row["bets"] > 0]
    payload = {
        "method": "expanding walk-forward confidence-cap selection",
        "anti_leakage": (
            "The cap for a test month uses only closing evidence from strictly prior "
            "months. Match results are never read by the cap decision."
        ),
        "daily_budget_limit": 100.0,
        "maximum_daily_league_stake": 15.0,
        "minimum_prior_uplifted_positions": minimum_prior_uplifted_positions,
        "positions": int(len(selected)),
        "active_months": len(active),
        "growth_cap_months": int((cap_audit["decision"] == "GROWTH").sum()),
        "staked": round(stake, 2),
        "profit": round(profit, 2),
        "roi_pct": round(profit / stake * 100.0, 2) if stake else 0.0,
        "maximum_drawdown": round(maximum_drawdown, 2),
        "monthly_bootstrap_roi": _monthly_bootstrap(monthly),
        "moving_block_bootstrap_roi": moving_block_bootstrap_roi(monthly),
        "leave_one_execution_source_out": source,
        "leave_one_group_out": groups,
        "leave_one_team_out": team,
        "closing_value": closing,
        "closing_expected_monthly_stability": closing_monthly,
        "horizon_role_attribution": horizon_role_attribution(selected),
        "decision": "ROLLING_RESEARCH_SURVIVOR",
        "monthly": monthly,
        "live_promotion_allowed": False,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    selected.to_csv(output_dir / "positions.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(monthly).to_csv(
        output_dir / "monthly.csv", index=False, encoding="utf-8-sig"
    )
    pd.DataFrame(daily_rows).to_csv(
        output_dir / "daily.csv", index=False, encoding="utf-8-sig"
    )
    cap_audit.to_csv(
        output_dir / "cap_decisions.csv", index=False, encoding="utf-8-sig"
    )
    (output_dir / "summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--conservative-dir", type=Path, required=True)
    parser.add_argument("--growth-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--minimum-prior-uplifted-positions", type=int, default=10)
    args = parser.parse_args()
    report = replay_adaptive_cap(
        args.conservative_dir, args.growth_dir, args.output_dir,
        args.minimum_prior_uplifted_positions,
    )
    print(json.dumps(
        {key: value for key, value in report.items() if key != "monthly"},
        ensure_ascii=False, indent=2,
    ))


if __name__ == "__main__":
    main()
