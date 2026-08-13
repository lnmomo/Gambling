"""No-lookahead core plus long-horizon satellite CLV portfolio replay."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from scripts.clv_model_agreement_replay import (
    cap_daily_group_exposure,
    closing_expected_monthly_stability,
    closing_value_diagnostics,
    leave_one_group_out_diagnostics,
    leave_one_source_out_diagnostics,
    leave_one_team_out_diagnostics,
    moving_block_bootstrap_roi,
)
from scripts.profit_concentration_gate_power import simulate_gate_power
from scripts.robust_consensus_latest_month_holdout import _monthly_bootstrap


SETTLEMENT_COLUMNS = {
    "actual_outcome", "closing_edge_pct", "positive_clv", "closing_probability",
    "closing_fair_odds", "won", "profit",
}
MINIMUM_INCREMENTAL_ROLE_POSITIONS = 30


def horizon_role_attribution(
    settled: pd.DataFrame,
    minimum_positions: int = MINIMUM_INCREMENTAL_ROLE_POSITIONS,
) -> dict[str, dict[str, Any]]:
    """Separate closing-value evidence from realized outcome luck by horizon."""
    if settled.empty or "horizon_role" not in settled:
        return {}
    required = {"stake", "profit", "odds", "closing_probability"}
    if not required.issubset(settled.columns):
        return {}
    report: dict[str, dict[str, Any]] = {}
    for role, frame in settled.groupby("horizon_role", sort=True):
        stake = float(frame["stake"].sum())
        realized_profit = float(frame["profit"].sum())
        expected_profit = float((
            frame["stake"].astype(float)
            * (
                frame["closing_probability"].astype(float)
                * frame["odds"].astype(float)
                - 1.0
            )
        ).sum())
        positions = int(len(frame))
        positive_clv_rate = None
        if "positive_clv" in frame:
            positive_clv_rate = float(frame["positive_clv"].astype(bool).mean())
        report[str(role)] = {
            "positions": positions,
            "staked": round(stake, 2),
            "realized_profit": round(realized_profit, 4),
            "realized_roi_pct": round(realized_profit / stake * 100.0, 4) if stake else None,
            "closing_expected_profit": round(expected_profit, 4),
            "closing_expected_roi_pct": round(expected_profit / stake * 100.0, 4) if stake else None,
            "positive_clv_rate": round(positive_clv_rate, 4) if positive_clv_rate is not None else None,
            "realized_minus_closing_expected_profit": round(
                realized_profit - expected_profit, 4
            ),
            "minimum_positions_for_incremental_validation": minimum_positions,
            "incremental_evidence_status": (
                "READY" if positions >= minimum_positions else "COLLECTING"
            ),
        }
    return report


def _opening(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.drop(
        columns=[column for column in SETTLEMENT_COLUMNS if column in frame],
        errors="ignore",
    ).copy()


def cap_daily_exposure(frame: pd.DataFrame, daily_budget: float) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    adjusted = frame.copy()
    totals = adjusted.groupby("date")["stake"].transform("sum")
    adjusted["stake"] = (
        adjusted["stake"] * (daily_budget / totals).clip(upper=1.0)
    ).round(2)
    return adjusted.loc[adjusted["stake"] >= 0.10].copy()


def freeze_multi_horizon_positions(
    core: pd.DataFrame, satellite: pd.DataFrame,
    satellite_stake_multiplier: float = 0.5,
    daily_budget: float = 100.0,
    maximum_daily_league_stake: float = 15.0,
    core_role: str = "9m3m_core",
    satellite_role: str = "18m9m_satellite",
    preserve_core_roles: bool = False,
) -> pd.DataFrame:
    if not 0.0 <= satellite_stake_multiplier <= 1.0:
        raise ValueError("satellite_stake_multiplier must be between 0 and 1")
    core_opening = _opening(core)
    satellite_opening = _opening(satellite)
    key_columns = ["candidate_id", "outcome"]
    core_keys = set(map(tuple, core_opening[key_columns].astype(str).to_numpy()))
    core_outcomes = dict(zip(
        core_opening["candidate_id"].astype(str), core_opening["outcome"].astype(str)
    ))
    satellite_keys = pd.Series(
        map(tuple, satellite_opening[key_columns].astype(str).to_numpy()),
        index=satellite_opening.index,
    )
    satellite_opening = satellite_opening.loc[~satellite_keys.isin(core_keys)].copy()
    conflicts = satellite_opening.apply(
        lambda row: (
            str(row["candidate_id"]) in core_outcomes
            and core_outcomes[str(row["candidate_id"])] != str(row["outcome"])
        ),
        axis=1,
    )
    satellite_opening = satellite_opening.loc[~conflicts].copy()
    satellite_opening["stake"] = (
        satellite_opening["stake"].astype(float) * satellite_stake_multiplier
    ).round(2)
    satellite_opening = satellite_opening.loc[satellite_opening["stake"] >= 0.10]
    if not preserve_core_roles or "horizon_role" not in core_opening:
        core_opening["horizon_role"] = core_role
    satellite_opening["horizon_role"] = satellite_role
    frozen = pd.concat([core_opening, satellite_opening], ignore_index=True)
    frozen = cap_daily_group_exposure(
        frozen, "league", maximum_daily_league_stake
    )
    return cap_daily_exposure(frozen, daily_budget)


def settle_multi_horizon_positions(
    frozen: pd.DataFrame, core: pd.DataFrame, satellite: pd.DataFrame,
) -> pd.DataFrame:
    settlement = pd.concat([core, satellite], ignore_index=True)
    settlement = settlement.drop_duplicates(["candidate_id", "outcome"], keep="first")
    available = [
        column for column in SETTLEMENT_COLUMNS if column in settlement.columns
    ]
    settled = frozen.merge(
        settlement[["candidate_id", "outcome", *available]],
        on=["candidate_id", "outcome"], how="left", validate="one_to_one",
    )
    settled["won"] = settled["won"].astype(bool)
    settled["profit"] = settled.apply(
        lambda row: (
            float(row["stake"]) * (float(row["odds"]) - 1.0)
            if bool(row["won"]) else -float(row["stake"])
        ),
        axis=1,
    ).round(2)
    return settled


def replay_multi_horizon(
    core_dir: Path, satellite_dir: Path, output_dir: Path,
    satellite_stake_multiplier: float = 0.5,
    daily_budget: float = 100.0,
    maximum_daily_league_stake: float = 15.0,
    core_role: str = "9m3m_core",
    satellite_role: str = "18m9m_satellite",
    preserve_core_roles: bool = False,
    method: str = "9m3m core plus non-overlapping 18m9m half-stake satellite",
) -> dict[str, Any]:
    core = pd.read_csv(core_dir / "positions.csv")
    satellite = pd.read_csv(satellite_dir / "positions.csv")
    core_summary = json.loads((core_dir / "summary.json").read_text(encoding="utf-8-sig"))
    frozen = freeze_multi_horizon_positions(
        core, satellite, satellite_stake_multiplier, daily_budget,
        maximum_daily_league_stake, core_role, satellite_role,
        preserve_core_roles,
    )
    settled = settle_multi_horizon_positions(frozen, core, satellite)
    month_names = [str(row["month"]) for row in core_summary["monthly"]]
    monthly = []
    month_values = settled["test_month"].astype(str)
    for month in month_names:
        frame = settled.loc[month_values == month]
        staked = float(frame["stake"].sum())
        profit = float(frame["profit"].sum())
        monthly.append({
            "month": month, "bets": len(frame), "staked": round(staked, 2),
            "profit": round(profit, 2),
            "roi_pct": round(profit / staked * 100.0, 2) if staked else 0.0,
        })
    daily_rows = []
    cumulative = peak = 0.0
    for match_date, frame in settled.groupby("date", sort=True):
        profit = round(float(frame["profit"].sum()), 2)
        cumulative = round(cumulative + profit, 2)
        peak = max(peak, cumulative)
        daily_rows.append({
            "date": str(match_date), "bets": len(frame),
            "staked": round(float(frame["stake"].sum()), 2), "profit": profit,
            "cumulative_profit": cumulative, "drawdown": round(peak - cumulative, 2),
        })
    bootstrap = _monthly_bootstrap(monthly)
    block = moving_block_bootstrap_roi(monthly)
    source = leave_one_source_out_diagnostics(settled, month_names)
    groups = {
        column: leave_one_group_out_diagnostics(settled, month_names, column)
        for column in ("league", "outcome", "odds_band")
    }
    team = leave_one_team_out_diagnostics(settled, month_names)
    closing = closing_value_diagnostics(settled)
    closing_monthly = closing_expected_monthly_stability(settled, month_names)
    role_attribution = horizon_role_attribution(settled)
    calibrated = simulate_gate_power(settled, month_names)
    active = [row for row in monthly if row["bets"] > 0]
    staked = float(settled["stake"].sum())
    profit = float(settled["profit"].sum())
    reasons = []
    if len(settled) < 100: reasons.append("bets<100")
    if len(active) < 8: reasons.append("active_months<8")
    if profit <= 0: reasons.append("aggregate_profit<=0")
    if bootstrap.get("lower_95_pct") is None or bootstrap["lower_95_pct"] <= 0:
        reasons.append("monthly_bootstrap_roi_lower_95<=0")
    if block.get("lower_95_pct") is None or block["lower_95_pct"] <= 0:
        reasons.append("moving_block_bootstrap_roi_lower_95<=0")
    if source.get("minimum_lower_95_pct") is None or source["minimum_lower_95_pct"] <= 0:
        reasons.append("leave_one_source_out_block_lower_95<=0")
    if groups["league"].get("minimum_lower_95_pct") is None or groups["league"]["minimum_lower_95_pct"] <= 0:
        reasons.append("leave_one_league_out_block_lower_95<=0")
    if team.get("minimum_lower_95_pct") is None or team["minimum_lower_95_pct"] <= 0:
        reasons.append("leave_one_team_out_block_lower_95<=0")
    if closing["status"] != "READY" or closing["all"]["closing_expected_profit"] <= 0:
        reasons.append("closing_expected_profit<=0")
    if closing["status"] != "READY" or (closing["late"]["closing_expected_roi_pct"] or 0) <= 0:
        reasons.append("late_closing_expected_roi<=0")
    closing_iid_lower = closing_monthly.get("monthly_bootstrap_roi", {}).get(
        "lower_95_pct"
    )
    if closing_iid_lower is None or float(closing_iid_lower) <= 0:
        reasons.append("closing_expected_monthly_bootstrap_roi_lower_95<=0")
    closing_block_lower = closing_monthly.get("moving_block_bootstrap_roi", {}).get(
        "lower_95_pct"
    )
    if closing_block_lower is None or float(closing_block_lower) <= 0:
        reasons.append("closing_expected_moving_block_roi_lower_95<=0")
    if not calibrated["observed_calibrated_diagnostics"]["calibrated_concentration_gate_passed"]:
        reasons.append("closing_probability_calibrated_concentration_gate_failed")
    payload = {
        "method": method,
        "anti_leakage": (
            "both input portfolios were frozen independently before results; future "
            "columns are removed before deduplication, conflict rejection and exposure caps"
        ),
        "daily_budget_limit": daily_budget,
        "maximum_daily_league_stake": maximum_daily_league_stake,
        "satellite_stake_multiplier": satellite_stake_multiplier,
        "positions": len(settled),
        "core_positions": int((settled["horizon_role"] == "9m3m_core").sum()),
        "satellite_positions": int((settled["horizon_role"] == "18m9m_satellite").sum()),
        "horizon_role_counts": {
            str(key): int(value)
            for key, value in settled["horizon_role"].value_counts().items()
        },
        "horizon_role_attribution": role_attribution,
        "active_months": len(active),
        "positive_active_months": sum(row["profit"] > 0 for row in active),
        "staked": round(staked, 2), "profit": round(profit, 2),
        "roi_pct": round(profit / staked * 100.0, 2) if staked else 0.0,
        "maximum_drawdown": max((row["drawdown"] for row in daily_rows), default=0.0),
        "monthly_bootstrap_roi": bootstrap,
        "moving_block_bootstrap_roi": block,
        "leave_one_execution_source_out": source,
        "leave_one_group_out": groups,
        "leave_one_team_out": team,
        "closing_value": closing,
        "closing_expected_monthly_stability": closing_monthly,
        "calibrated_concentration_gate": calibrated,
        "decision": "ROLLING_RESEARCH_SURVIVOR" if not reasons else "ROLLING_REJECTED",
        "decision_reasons": reasons,
        "monthly": monthly,
        "live_promotion_allowed": False,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    settled.to_csv(output_dir / "positions.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(monthly).to_csv(output_dir / "monthly.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(daily_rows).to_csv(output_dir / "daily.csv", index=False, encoding="utf-8-sig")
    (output_dir / "summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--core-dir", type=Path, required=True)
    parser.add_argument("--satellite-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--satellite-stake-multiplier", type=float, default=0.5)
    parser.add_argument("--core-role", default="9m3m_core")
    parser.add_argument("--satellite-role", default="18m9m_satellite")
    parser.add_argument("--preserve-core-roles", action="store_true")
    parser.add_argument(
        "--method",
        default="9m3m core plus non-overlapping 18m9m half-stake satellite",
    )
    args = parser.parse_args()
    report = replay_multi_horizon(
        args.core_dir, args.satellite_dir, args.output_dir,
        args.satellite_stake_multiplier, core_role=args.core_role,
        satellite_role=args.satellite_role,
        preserve_core_roles=args.preserve_core_roles, method=args.method,
    )
    print(json.dumps({key: value for key, value in report.items() if key != "monthly"}, indent=2))


if __name__ == "__main__":
    main()
