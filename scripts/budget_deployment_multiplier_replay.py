"""Select and validate a no-lookahead stake multiplier under a CNY risk budget."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from scripts.clv_model_agreement_replay import cap_daily_group_exposure
from scripts.frozen_portfolio_report import write_frozen_portfolio_report
from scripts.multi_horizon_clv_replay import cap_daily_exposure


DEFAULT_MULTIPLIERS = (1.0, 1.25, 1.5, 2.0, 3.0, 5.0, 10.0, 20.0)


def apply_budget_multiplier(
    positions: pd.DataFrame,
    multiplier: float,
    daily_budget: float = 100.0,
    maximum_daily_league_stake: float = 15.0,
) -> pd.DataFrame:
    required = {
        "candidate_id", "date", "league", "stake", "odds", "won",
        "decision_frozen_before_closing_and_result",
    }
    missing = required - set(positions.columns)
    if missing:
        raise ValueError(f"positions are missing columns: {sorted(missing)}")
    if multiplier <= 0:
        raise ValueError("multiplier must be positive")
    if not positions["decision_frozen_before_closing_and_result"].astype(bool).all():
        raise ValueError("all positions must be frozen before closing and result")

    selected = positions.copy()
    selected["base_stake_before_budget_multiplier"] = selected["stake"].astype(float)
    selected["budget_deployment_multiplier"] = float(multiplier)
    selected["stake"] = (selected["stake"].astype(float) * multiplier).round(2)
    selected = cap_daily_group_exposure(
        selected, "league", maximum_daily_league_stake
    )
    selected = cap_daily_exposure(selected, daily_budget)
    selected["profit"] = selected.apply(
        lambda row: (
            float(row["stake"]) * (float(row["odds"]) - 1.0)
            if bool(row["won"]) else -float(row["stake"])
        ), axis=1,
    ).round(2)
    return selected


def maximum_drawdown(positions: pd.DataFrame) -> float:
    daily = positions.groupby("date", sort=True)["profit"].sum().round(2)
    equity = daily.cumsum().round(2)
    peaks = equity.cummax().clip(lower=0.0)
    return round(float((peaks - equity).max()), 2) if not equity.empty else 0.0


def select_discovery_multiplier(
    portfolios: list[pd.DataFrame],
    discovery_end: str = "2024-05-31",
    multipliers: tuple[float, ...] = DEFAULT_MULTIPLIERS,
    maximum_discovery_drawdown: float = 100.0,
) -> dict[str, Any]:
    if not portfolios:
        raise ValueError("at least one portfolio is required")
    if maximum_discovery_drawdown <= 0:
        raise ValueError("maximum discovery drawdown must be positive")
    grid: list[dict[str, Any]] = []
    for multiplier in sorted(set(float(value) for value in multipliers)):
        cost_drawdowns = []
        cost_expected_profit = []
        for positions in portfolios:
            frozen = apply_budget_multiplier(positions, multiplier)
            discovery = frozen.loc[
                pd.to_datetime(frozen["date"]).le(pd.Timestamp(discovery_end))
            ].copy()
            cost_drawdowns.append(maximum_drawdown(discovery))
            cost_expected_profit.append(round(float(
                (discovery["stake"] * discovery["closing_edge_pct"] / 100.0).sum()
            ), 4))
        grid.append({
            "multiplier": multiplier,
            "maximum_cross_cost_drawdown": max(cost_drawdowns),
            "minimum_cross_cost_closing_expected_profit": min(cost_expected_profit),
            "eligible": max(cost_drawdowns) <= maximum_discovery_drawdown,
        })
    eligible = [row for row in grid if row["eligible"]]
    if not eligible:
        raise ValueError("no multiplier satisfies the discovery drawdown budget")
    selected = max(eligible, key=lambda row: row["multiplier"])
    return {
        "selected_multiplier": selected["multiplier"],
        "discovery_end": discovery_end,
        "maximum_discovery_drawdown": maximum_discovery_drawdown,
        "selection_rule": "largest fixed-grid multiplier within cross-cost drawdown budget",
        "grid": grid,
    }


def replay_budget_deployment(
    source_dir: Path,
    output_dir: Path,
    selection: dict[str, Any],
    validation_start: str = "2024-08-01",
) -> dict[str, Any]:
    positions = pd.read_csv(source_dir / "positions.csv")
    source_summary = json.loads(
        (source_dir / "summary.json").read_text(encoding="utf-8-sig")
    )
    multiplier = float(selection["selected_multiplier"])
    selected = apply_budget_multiplier(positions, multiplier)
    validation = selected.loc[
        pd.to_datetime(selected["date"]).ge(pd.Timestamp(validation_start))
    ]
    validation_expected_profit = float(
        (validation["stake"] * validation["closing_edge_pct"] / 100.0).sum()
    )
    report = write_frozen_portfolio_report(
        selected,
        source_summary,
        output_dir,
        "v8.61 discovery-selected budget deployment multiplier",
        "The multiplier is selected from a fixed grid using only matches through "
        f"{selection['discovery_end']}. Later closing prices and results are attached "
        "only after the multiplier and all opening selections are frozen.",
        {
            "source_policy": "v8.60 cross-cost direct-only core tier",
            "budget_deployment_multiplier": multiplier,
            "multiplier_selection": selection,
            "validation_start": validation_start,
            "validation_positions": int(len(validation)),
            "validation_closing_expected_profit": round(validation_expected_profit, 4),
            "validation_maximum_drawdown": maximum_drawdown(validation),
            "maximum_active_day_stake": round(
                float(selected.groupby("date")["stake"].sum().max()), 2
            ),
        },
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-2-5", type=Path, required=True)
    parser.add_argument("--source-5", type=Path, required=True)
    parser.add_argument("--output-2-5", type=Path, required=True)
    parser.add_argument("--output-5", type=Path, required=True)
    parser.add_argument("--discovery-end", default="2024-05-31")
    parser.add_argument("--validation-start", default="2024-08-01")
    parser.add_argument("--maximum-discovery-drawdown", type=float, default=100.0)
    args = parser.parse_args()
    source_dirs = [args.source_2_5, args.source_5]
    portfolios = [pd.read_csv(path / "positions.csv") for path in source_dirs]
    selection = select_discovery_multiplier(
        portfolios, args.discovery_end,
        maximum_discovery_drawdown=args.maximum_discovery_drawdown,
    )
    reports = {
        "selection": selection,
        "2_5pct": replay_budget_deployment(
            args.source_2_5, args.output_2_5, selection, args.validation_start
        ),
        "5pct": replay_budget_deployment(
            args.source_5, args.output_5, selection, args.validation_start
        ),
    }
    print(json.dumps({
        "selection": selection,
        "2_5pct": {
            key: reports["2_5pct"][key] for key in (
                "positions", "staked", "profit", "maximum_drawdown",
                "validation_closing_expected_profit", "validation_maximum_drawdown",
                "maximum_active_day_stake",
            )
        },
        "5pct": {
            key: reports["5pct"][key] for key in (
                "positions", "staked", "profit", "maximum_drawdown",
                "validation_closing_expected_profit", "validation_maximum_drawdown",
                "maximum_active_day_stake",
            )
        },
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
