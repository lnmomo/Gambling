"""Walk-forward monthly stake deployment using strictly prior active months."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from scripts.budget_deployment_multiplier_replay import maximum_drawdown
from scripts.clv_model_agreement_replay import cap_daily_group_exposure
from scripts.frozen_portfolio_report import write_frozen_portfolio_report
from scripts.multi_horizon_clv_replay import cap_daily_exposure


DEFAULT_PRIOR_ACTIVE_MONTHS_GRID = (3, 6, 12)
DEFAULT_MINIMUM_PRIOR_POSITIONS_GRID = (3, 5, 10, 20)
DEFAULT_GROWTH_MULTIPLIER_GRID = (15.0, 20.0)


def matched_cross_cost_evidence(
    portfolios: list[pd.DataFrame],
) -> list[pd.DataFrame]:
    if not portfolios:
        raise ValueError("at least one portfolio is required")
    required = {"candidate_id", "outcome"}
    for frame in portfolios:
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(f"cross-cost evidence is missing columns: {sorted(missing)}")
    common = set.intersection(*[
        set(map(tuple, frame[["candidate_id", "outcome"]].astype(str).to_numpy()))
        for frame in portfolios
    ])
    matched = []
    for frame in portfolios:
        keys = pd.Series(
            list(map(tuple, frame[["candidate_id", "outcome"]].astype(str).to_numpy())),
            index=frame.index,
        )
        matched.append(frame.loc[keys.isin(common)].copy())
    return matched


def select_monthly_multipliers(
    portfolios: list[pd.DataFrame],
    prior_active_months: int = 3,
    minimum_prior_positions: int = 20,
    base_multiplier: float = 10.0,
    growth_multiplier: float = 20.0,
    matched_evidence_only: bool = False,
    deployment_months: list[str] | None = None,
) -> dict[str, float]:
    if not portfolios:
        raise ValueError("at least one portfolio is required")
    if prior_active_months < 1 or minimum_prior_positions < 1:
        raise ValueError("prior month and position requirements must be positive")
    selected_deployment_months = (
        sorted({pd.Period(month, freq="M") for month in deployment_months})
        if deployment_months is not None else
        sorted(set().union(*[
            set(pd.to_datetime(frame["date"]).dt.to_period("M").unique())
            for frame in portfolios
        ]))
    )
    evidence_portfolios = (
        matched_cross_cost_evidence(portfolios)
        if matched_evidence_only else portfolios
    )
    prepared = []
    for source in evidence_portfolios:
        frame = source.copy()
        frame["_month"] = pd.to_datetime(frame["date"]).dt.to_period("M")
        prepared.append(frame)
    multipliers: dict[str, float] = {}
    evidence_months = sorted(set().union(*[
        set(frame["_month"].unique()) for frame in prepared
    ]))
    for month in selected_deployment_months:
        prior = [item for item in evidence_months if item < month][-prior_active_months:]
        growth_ready = len(prior) == prior_active_months
        for frame in prepared:
            evidence = frame.loc[frame["_month"].isin(prior)]
            closing_expected_profit = float(
                (evidence["stake"] * evidence["closing_edge_pct"] / 100.0).sum()
            )
            growth_ready = growth_ready and (
                len(evidence) >= minimum_prior_positions
                and closing_expected_profit > 0.0
                and float(evidence["profit"].sum()) > 0.0
            )
        multipliers[str(month)] = (
            float(growth_multiplier) if growth_ready else float(base_multiplier)
        )
    return multipliers


def apply_monthly_budget_multipliers(
    positions: pd.DataFrame,
    monthly_multipliers: dict[str, float],
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
    if not positions["decision_frozen_before_closing_and_result"].astype(bool).all():
        raise ValueError("all positions must be frozen before closing and result")
    selected = positions.copy()
    selected["deployment_month"] = pd.to_datetime(selected["date"]).dt.to_period("M").astype(str)
    selected["budget_deployment_multiplier"] = selected["deployment_month"].map(
        monthly_multipliers
    )
    if selected["budget_deployment_multiplier"].isna().any():
        raise ValueError("a deployment month has no frozen multiplier")
    selected["base_stake_before_budget_multiplier"] = selected["stake"].astype(float)
    selected["stake"] = (
        selected["stake"].astype(float)
        * selected["budget_deployment_multiplier"].astype(float)
    ).round(2)
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


def select_adaptive_rule(
    portfolios: list[pd.DataFrame],
    discovery_end: str = "2024-05-31",
    maximum_discovery_drawdown: float = 100.0,
    prior_active_months_grid: tuple[int, ...] = DEFAULT_PRIOR_ACTIVE_MONTHS_GRID,
    minimum_prior_positions_grid: tuple[int, ...] = DEFAULT_MINIMUM_PRIOR_POSITIONS_GRID,
    growth_multiplier_grid: tuple[float, ...] = DEFAULT_GROWTH_MULTIPLIER_GRID,
    base_multiplier: float = 10.0,
    matched_evidence_only: bool = False,
) -> dict[str, Any]:
    grid: list[dict[str, Any]] = []
    for prior_active_months in prior_active_months_grid:
        for minimum_prior_positions in minimum_prior_positions_grid:
            for growth_multiplier in growth_multiplier_grid:
                monthly = select_monthly_multipliers(
                    portfolios, prior_active_months, minimum_prior_positions,
                    base_multiplier, growth_multiplier, matched_evidence_only,
                )
                expected_profits = []
                drawdowns = []
                for positions in portfolios:
                    deployed = apply_monthly_budget_multipliers(positions, monthly)
                    discovery = deployed.loc[
                        pd.to_datetime(deployed["date"]).le(pd.Timestamp(discovery_end))
                    ]
                    expected_profits.append(float(
                        (discovery["stake"] * discovery["closing_edge_pct"] / 100.0).sum()
                    ))
                    drawdowns.append(maximum_drawdown(discovery))
                maximum_drawdown_value = max(drawdowns)
                grid.append({
                    "prior_active_months": int(prior_active_months),
                    "minimum_prior_positions": int(minimum_prior_positions),
                    "base_multiplier": float(base_multiplier),
                    "growth_multiplier": float(growth_multiplier),
                    "minimum_cross_cost_closing_expected_profit": round(
                        min(expected_profits), 4
                    ),
                    "maximum_cross_cost_drawdown": maximum_drawdown_value,
                    "eligible": maximum_drawdown_value <= maximum_discovery_drawdown,
                    "monthly_multipliers": monthly,
                })
    eligible = [row for row in grid if row["eligible"]]
    if not eligible:
        raise ValueError("no adaptive rule satisfies the discovery drawdown budget")
    selected = max(eligible, key=lambda row: (
        float(row["minimum_cross_cost_closing_expected_profit"]),
        -float(row["maximum_cross_cost_drawdown"]),
    ))
    return {
        "discovery_end": discovery_end,
        "maximum_discovery_drawdown": maximum_discovery_drawdown,
        "selection_rule": (
            "maximum minimum cross-cost discovery closing expected profit "
            "subject to the drawdown budget"
        ),
        "matched_cross_cost_evidence_only": matched_evidence_only,
        "selected": selected,
        "grid": [{key: value for key, value in row.items()
                  if key != "monthly_multipliers"} for row in grid],
    }


def replay_adaptive_budget_deployment(
    source_dir: Path,
    output_dir: Path,
    monthly_multipliers: dict[str, float],
    selection: dict[str, Any],
    validation_start: str = "2024-08-01",
) -> dict[str, Any]:
    positions = pd.read_csv(source_dir / "positions.csv")
    source_summary = json.loads(
        (source_dir / "summary.json").read_text(encoding="utf-8-sig")
    )
    selected = apply_monthly_budget_multipliers(positions, monthly_multipliers)
    validation = selected.loc[
        pd.to_datetime(selected["date"]).ge(pd.Timestamp(validation_start))
    ]
    validation_expected_profit = float(
        (validation["stake"] * validation["closing_edge_pct"] / 100.0).sum()
    )
    return write_frozen_portfolio_report(
        selected, source_summary, output_dir,
        "v8.63 prior-active-month adaptive budget deployment",
        "Each calendar month's multiplier is frozen before that month starts using "
        "only the preceding active portfolio months. Current-month closing prices "
        "and results cannot alter it.",
        {
            "source_policy": "v8.60 cross-cost direct-only core tier",
            "multiplier_selection": selection,
            "monthly_multipliers": monthly_multipliers,
            "growth_multiplier_months": sum(
                value == float(selection["growth_multiplier"])
                for value in monthly_multipliers.values()
            ),
            "validation_start": validation_start,
            "validation_positions": int(len(validation)),
            "validation_closing_expected_profit": round(validation_expected_profit, 4),
            "validation_maximum_drawdown": maximum_drawdown(validation),
            "maximum_active_day_stake": round(
                float(selected.groupby("date")["stake"].sum().max()), 2
            ),
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-2-5", type=Path, required=True)
    parser.add_argument("--source-5", type=Path, required=True)
    parser.add_argument("--output-2-5", type=Path, required=True)
    parser.add_argument("--output-5", type=Path, required=True)
    parser.add_argument("--validation-start", default="2024-08-01")
    parser.add_argument("--matched-evidence-only", action="store_true")
    parser.add_argument(
        "--frozen-rule-summary", type=Path,
        help="Reuse an already selected adaptive rule without rerunning its grid.",
    )
    parser.add_argument("--frozen-evidence-2-5", type=Path)
    parser.add_argument("--frozen-evidence-5", type=Path)
    args = parser.parse_args()
    source_dirs = [args.source_2_5, args.source_5]
    portfolios = [pd.read_csv(path / "positions.csv") for path in source_dirs]
    frozen_evidence_paths = [args.frozen_evidence_2_5, args.frozen_evidence_5]
    if args.frozen_rule_summary:
        if not all(frozen_evidence_paths):
            parser.error(
                "--frozen-rule-summary requires both frozen evidence paths"
            )
        frozen_summary = json.loads(
            args.frozen_rule_summary.read_text(encoding="utf-8-sig")
        )
        selected_rule = dict(frozen_summary["multiplier_selection"])
        evidence = [
            pd.read_csv(path / "positions.csv")
            for path in frozen_evidence_paths
        ]
        deployment_months = sorted(set().union(*[
            set(pd.to_datetime(frame["date"]).dt.to_period("M").astype(str))
            for frame in portfolios
        ]))
        monthly = select_monthly_multipliers(
            evidence,
            int(selected_rule["prior_active_months"]),
            int(selected_rule["minimum_prior_positions"]),
            float(selected_rule["base_multiplier"]),
            float(selected_rule["growth_multiplier"]),
            matched_evidence_only=True,
            deployment_months=deployment_months,
        )
        selection_result = {
            "selection_rule": "reuse frozen rule and frozen evidence portfolio",
            "source_summary": str(args.frozen_rule_summary),
            "selected": selected_rule,
        }
    else:
        selection_result = select_adaptive_rule(
            portfolios, matched_evidence_only=args.matched_evidence_only
        )
        selected_rule = selection_result["selected"]
        monthly = selected_rule["monthly_multipliers"]
    selection = {
        **{key: value for key, value in selection_result.items() if key != "selected"},
        **{key: value for key, value in selected_rule.items()
           if key != "monthly_multipliers"},
    }
    reports = {
        "2_5pct": replay_adaptive_budget_deployment(
            args.source_2_5, args.output_2_5, monthly, selection,
            args.validation_start,
        ),
        "5pct": replay_adaptive_budget_deployment(
            args.source_5, args.output_5, monthly, selection,
            args.validation_start,
        ),
    }
    print(json.dumps({key: {
        field: report[field] for field in (
            "positions", "staked", "profit", "maximum_drawdown",
            "growth_multiplier_months", "validation_closing_expected_profit",
            "validation_maximum_drawdown", "maximum_active_day_stake",
        )
    } for key, report in reports.items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
