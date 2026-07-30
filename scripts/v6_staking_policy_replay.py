"""Replay stake sizing on already frozen v6.2 decisions without result leakage."""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from scripts.portfolio_algorithm_optimization import PROJECT_ROOT
from scripts.robust_consensus_latest_month_holdout import _monthly_bootstrap


@dataclass(frozen=True)
class StakePolicy:
    name: str
    mode: str
    amount: float
    maximum_single_stake: float
    daily_budget: float = 100.0


POLICIES = (
    StakePolicy("existing_one_tenth_kelly", "kelly", 0.10, 5.0),
    StakePolicy("quarter_kelly", "kelly", 0.25, 10.0),
    StakePolicy("half_kelly", "kelly", 0.50, 15.0),
    StakePolicy("flat_1", "flat", 1.0, 1.0),
    StakePolicy("flat_2", "flat", 2.0, 2.0),
    StakePolicy("flat_5", "flat", 5.0, 5.0),
)
MAXIMUM_DRAWDOWN_FRACTION_OF_DAILY_BUDGET = 0.10


def freeze_stakes(decisions: pd.DataFrame, policy: StakePolicy) -> pd.DataFrame:
    forbidden = {"actual_outcome", "won", "profit", "closing_edge_pct", "positive_clv"}
    opening = decisions.drop(columns=[name for name in forbidden if name in decisions], errors="ignore").copy()
    opening.sort_values(
        ["date", "lower_closing_edge_pct", "candidate_id"],
        ascending=[True, False, True], inplace=True,
    )
    frozen: list[dict[str, Any]] = []
    for _day, daily in opening.groupby("date", sort=True):
        remaining = policy.daily_budget
        for row in daily.to_dict("records"):
            odds = float(row["odds"])
            if policy.mode == "flat":
                requested = policy.amount
            else:
                lower_edge = float(row["lower_closing_edge_pct"]) / 100.0
                probability = min(0.999, (1.0 + lower_edge) / odds)
                full_kelly = max(0.0, (probability * odds - 1.0) / max(odds - 1.0, 1e-9))
                requested = policy.daily_budget * policy.amount * full_kelly
            stake = round(min(policy.maximum_single_stake, remaining, requested), 2)
            if stake < 0.10:
                continue
            remaining = round(remaining - stake, 2)
            frozen.append({**row, "stake": stake, "stake_policy": policy.name})
    return pd.DataFrame(frozen)


def settle_frozen(frozen: pd.DataFrame, outcomes: pd.DataFrame) -> pd.DataFrame:
    post_event_columns = [
        name for name in (
            "candidate_id", "actual_outcome", "closing_edge_pct", "positive_clv",
            "closing_probability", "closing_fair_odds",
        ) if name in outcomes
    ]
    settlement = outcomes[post_event_columns].copy()
    settled = frozen.merge(settlement, on="candidate_id", how="left", validate="one_to_one")
    settled["won"] = settled["outcome"] == settled["actual_outcome"]
    settled["profit"] = settled.apply(
        lambda row: round(float(row["stake"]) * (float(row["odds"]) - 1.0), 2)
        if bool(row["won"]) else -round(float(row["stake"]), 2), axis=1,
    )
    return settled


def _daily_ledger(settled: pd.DataFrame, all_dates: list[str], daily_budget: float) -> pd.DataFrame:
    grouped = {
        str(day): frame for day, frame in settled.groupby("date", sort=True)
    } if not settled.empty else {}
    rows = []
    cumulative = peak = max_drawdown = 0.0
    for day in all_dates:
        frame = grouped.get(day)
        staked = round(float(frame["stake"].sum()), 2) if frame is not None else 0.0
        profit = round(float(frame["profit"].sum()), 2) if frame is not None else 0.0
        bets = len(frame) if frame is not None else 0
        cumulative = round(cumulative + profit, 2)
        peak = max(peak, cumulative)
        max_drawdown = max(max_drawdown, peak - cumulative)
        rows.append({
            "date": day, "bets": bets, "staked": staked, "profit": profit,
            "cumulative_profit": cumulative, "drawdown": round(peak - cumulative, 2),
            "cash_reserved": round(daily_budget - staked, 2),
        })
    ledger = pd.DataFrame(rows)
    ledger.attrs["max_drawdown"] = round(max_drawdown, 2)
    return ledger


def replay_policies(input_dir: Path, output_dir: Path) -> dict[str, Any]:
    input_dir = input_dir.resolve()
    output_dir = output_dir.resolve()
    decisions = pd.read_csv(input_dir / "positions.csv")
    base_monthly = pd.read_csv(input_dir / "monthly.csv")
    base_daily = pd.read_csv(input_dir / "daily.csv")
    all_dates = sorted(base_daily["date"].astype(str).unique())
    months = base_monthly["month"].astype(str).tolist()
    results = []
    ledgers: dict[str, pd.DataFrame] = {}
    positions: dict[str, pd.DataFrame] = {}

    for policy in POLICIES:
        frozen = freeze_stakes(decisions, policy)
        settled = settle_frozen(frozen, decisions)
        ledger = _daily_ledger(settled, all_dates, policy.daily_budget)
        ledgers[policy.name] = ledger
        positions[policy.name] = settled
        monthly = []
        for month in months:
            frame = settled.loc[settled["test_month"].astype(str) == month]
            staked = round(float(frame["stake"].sum()), 2)
            profit = round(float(frame["profit"].sum()), 2)
            monthly.append({
                "month": month, "bets": len(frame), "staked": staked, "profit": profit,
                "roi_pct": round(profit / staked * 100.0, 2) if staked else 0.0,
            })
        staked = round(float(settled["stake"].sum()), 2)
        profit = round(float(settled["profit"].sum()), 2)
        bootstrap = _monthly_bootstrap(monthly)
        active_months = [row for row in monthly if row["bets"] > 0]
        max_drawdown = float(ledger.attrs["max_drawdown"])
        results.append({
            "policy": policy.name, "configuration": policy.__dict__,
            "bets": len(settled), "staked": staked, "profit": profit,
            "roi_pct": round(profit / staked * 100.0, 2) if staked else 0.0,
            "active_months": len(active_months),
            "positive_active_months": sum(row["profit"] > 0 for row in active_months),
            "maximum_drawdown": max_drawdown,
            "profit_to_drawdown": round(profit / max(max_drawdown, 0.01), 4),
            "maximum_daily_stake": round(float(ledger["staked"].max()), 2),
            "monthly_bootstrap_roi": bootstrap,
            "monthly": monthly,
        })

    eligible = [row for row in results if (
        row["bets"] >= 100
        and row["profit"] > 0
        and row["monthly_bootstrap_roi"]["lower_95_pct"] is not None
        and float(row["monthly_bootstrap_roi"]["lower_95_pct"]) > 0
        and row["maximum_daily_stake"] <= 100.0
        and row["maximum_drawdown"] <= (
            row["configuration"]["daily_budget"]
            * MAXIMUM_DRAWDOWN_FRACTION_OF_DAILY_BUDGET
        )
    )]
    selected = max(
        eligible, key=lambda row: (row["profit"], row["profit_to_drawdown"], row["roi_pct"])
    ) if eligible else None
    payload = {
        "method": "stake-only replay on immutable v6.2 selections; results excluded until stakes are frozen",
        "input": str(input_dir.relative_to(PROJECT_ROOT)),
        "daily_budget_limit": 100.0,
        "selection_rule": "among policies with >=100 bets, positive profit, positive monthly bootstrap lower 95%, daily stake<=100 and max drawdown<=10% of one daily budget, maximize profit",
        "selected_policy": selected["policy"] if selected else "ABSTAIN",
        "research_stage": "POST_HOC_EXPLORATORY",
        "live_promotion_allowed": False,
        "results": results,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if selected:
        ledgers[selected["policy"]].to_csv(output_dir / "selected_daily.csv", index=False, encoding="utf-8-sig")
        positions[selected["policy"]].to_csv(output_dir / "selected_positions.csv", index=False, encoding="utf-8-sig")
        latest_month = months[-1]
        latest_positions = positions[selected["policy"]].loc[
            positions[selected["policy"]]["test_month"].astype(str) == latest_month
        ].copy()
        period = pd.Period(latest_month, freq="M")
        latest_dates = pd.date_range(
            period.start_time, period.end_time.normalize(), freq="D"
        ).strftime("%Y-%m-%d").tolist()
        latest_daily = _daily_ledger(latest_positions, latest_dates, selected["configuration"]["daily_budget"])
        latest_daily.to_csv(output_dir / "selected_latest_month_daily.csv", index=False, encoding="utf-8-sig")
        latest_staked = round(float(latest_positions["stake"].sum()), 2)
        latest_profit = round(float(latest_positions["profit"].sum()), 2)
        payload["selected_latest_month"] = {
            "month": latest_month, "bets": len(latest_positions),
            "active_days": int((latest_daily["bets"] > 0).sum()),
            "staked": latest_staked, "profit": latest_profit,
            "roi_pct": round(latest_profit / latest_staked * 100.0, 2) if latest_staked else 0.0,
            "maximum_daily_stake": round(float(latest_daily["staked"].max()), 2),
            "maximum_drawdown": float(latest_daily.attrs["max_drawdown"]),
        }
        (output_dir / "summary.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    pd.DataFrame([{key: value for key, value in row.items() if key not in {"monthly", "configuration", "monthly_bootstrap_roi"}}
                  for row in results]).to_csv(output_dir / "comparison.csv", index=False, encoding="utf-8-sig")
    return payload


def replay_sealed_month(
    input_dir: Path, output_dir: Path, policy_name: str,
) -> dict[str, Any]:
    policy = next((row for row in POLICIES if row.name == policy_name), None)
    if policy is None:
        raise ValueError(f"unknown stake policy: {policy_name}")
    input_dir = input_dir.resolve()
    decisions = pd.read_csv(input_dir / "positions.csv")
    daily_source = pd.read_csv(input_dir / "daily.csv")
    all_dates = daily_source["date"].astype(str).tolist()
    frozen = freeze_stakes(decisions, policy)
    settled = settle_frozen(frozen, decisions)
    ledger = _daily_ledger(settled, all_dates, policy.daily_budget)
    staked = round(float(settled["stake"].sum()), 2) if not settled.empty else 0.0
    profit = round(float(settled["profit"].sum()), 2) if not settled.empty else 0.0
    payload = {
        "method": "stake policy selected on prior rolling folds, then frozen on sealed month before settlement",
        "policy": policy.__dict__, "bets": len(settled), "staked": staked, "profit": profit,
        "roi_pct": round(profit / staked * 100.0, 2) if staked else 0.0,
        "maximum_daily_stake": round(float(ledger["staked"].max()), 2),
        "maximum_drawdown": float(ledger.attrs["max_drawdown"]),
        "ending_equity_change": profit,
        "selection_used_sealed_month_results": False,
        "daily": ledger.to_dict("records"),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "sealed_month_summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    ledger.to_csv(output_dir / "sealed_month_daily.csv", index=False, encoding="utf-8-sig")
    settled.to_csv(output_dir / "sealed_month_positions.csv", index=False, encoding="utf-8-sig")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input-dir", type=Path,
        default=PROJECT_ROOT / "reports" / "clv_ridge_walk_forward_v6_2_fixed_cap5_5pct",
    )
    parser.add_argument(
        "--output-dir", type=Path,
        default=PROJECT_ROOT / "reports" / "v6_staking_policy_replay_v1",
    )
    parser.add_argument("--sealed-input-dir", type=Path)
    args = parser.parse_args()
    report = replay_policies(args.input_dir, args.output_dir)
    if args.sealed_input_dir and report["selected_policy"] != "ABSTAIN":
        report["sealed_month"] = replay_sealed_month(
            args.sealed_input_dir, args.output_dir, report["selected_policy"]
        )
    print(json.dumps({
        "selected_policy": report["selected_policy"],
        "results": [{key: value for key, value in row.items() if key not in {"monthly", "configuration"}}
                    for row in report["results"]],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
