"""No-lookahead agreement replay for two independently frozen CLV models."""
from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path
from typing import Any

import pandas as pd

from scripts.portfolio_algorithm_optimization import PROJECT_ROOT
from scripts.profit_concentration_gate_power import simulate_gate_power
from scripts.robust_consensus_latest_month_holdout import _monthly_bootstrap
from scripts.v6_staking_policy_replay import StakePolicy, _daily_ledger, freeze_stakes, settle_frozen


FUTURE_COLUMNS = {
    "actual_outcome", "won", "profit", "closing_probability", "closing_fair_odds",
    "closing_edge_pct", "positive_clv", "stake", "stake_policy",
}
HALF_KELLY = StakePolicy("model_agreement_half_kelly", "kelly", 0.50, 15.0)


def monthly_reset_ledger(daily: pd.DataFrame) -> pd.DataFrame:
    frame = daily.copy()
    if frame.empty:
        for column in ("month", "monthly_cumulative_profit", "monthly_drawdown"):
            frame[column] = pd.Series(dtype=str if column == "month" else float)
        return frame
    frame["month"] = frame["date"].astype(str).str[:7]
    frame["monthly_cumulative_profit"] = frame.groupby("month")["profit"].cumsum().round(2)
    monthly_peaks = (
        frame.groupby("month")["monthly_cumulative_profit"].cummax().clip(lower=0.0)
    )
    frame["monthly_drawdown"] = (
        monthly_peaks - frame["monthly_cumulative_profit"]
    ).round(2)
    return frame


def moving_block_bootstrap_roi(
    monthly: list[dict[str, Any]], block_size: int = 3,
    iterations: int = 5000, seed: int = 42,
) -> dict[str, Any]:
    if not monthly or block_size < 1:
        return {"status": "NO_MONTHS", "lower_95_pct": None}
    if not any(float(row["staked"]) > 0 for row in monthly):
        return {"status": "NO_STAKED_POSITIONS", "lower_95_pct": None}
    if len(monthly) < block_size:
        return {
            "status": "INSUFFICIENT_MONTHS", "months": len(monthly),
            "required_months": block_size, "block_size": block_size,
            "lower_95_pct": None,
        }
    rng = random.Random(seed)
    estimates: list[float] = []
    count = len(monthly)
    for _ in range(iterations):
        sample: list[dict[str, Any]] = []
        while len(sample) < count:
            start = rng.randrange(count)
            sample.extend(monthly[(start + offset) % count] for offset in range(block_size))
        sample = sample[:count]
        staked = sum(float(row["staked"]) for row in sample)
        if staked > 0:
            estimates.append(sum(float(row["profit"]) for row in sample) / staked * 100.0)
    if not estimates:
        return {"status": "NO_STAKED_POSITIONS", "lower_95_pct": None}
    estimates.sort()
    def percentile(probability: float) -> float:
        index = min(len(estimates) - 1, math.floor((len(estimates) - 1) * probability))
        return round(estimates[index], 4)
    return {
        "status": "READY", "months": count, "block_size": block_size,
        "iterations": iterations, "seed": seed,
        "lower_95_pct": percentile(0.025), "median_pct": percentile(0.50),
        "upper_95_pct": percentile(0.975),
    }


def leave_one_group_out_diagnostics(
    settled: pd.DataFrame, month_names: list[str], group_column: str,
    block_size: int = 3,
) -> dict[str, Any]:
    if settled.empty or group_column not in settled:
        return {
            "status": "NO_GROUPS", "group_column": group_column, "groups": [],
            "minimum_lower_95_pct": None,
        }
    groups = []
    group_values = settled[group_column].astype(str)
    for group_value in sorted(group_values.unique()):
        retained = settled.loc[group_values != group_value]
        retained_months = retained["test_month"].astype(str)
        monthly = []
        for month in month_names:
            frame = retained.loc[retained_months == month]
            monthly.append({
                "month": month,
                "staked": float(frame["stake"].sum()),
                "profit": float(frame["profit"].sum()),
            })
        bootstrap = moving_block_bootstrap_roi(monthly, block_size=block_size)
        staked = float(retained["stake"].sum())
        profit = float(retained["profit"].sum())
        groups.append({
            "excluded_group": group_value,
            "retained_bets": len(retained),
            "retained_staked": round(staked, 2),
            "retained_profit": round(profit, 2),
            "retained_roi_pct": round(profit / staked * 100.0, 2) if staked else None,
            "moving_block_lower_95_pct": bootstrap.get("lower_95_pct"),
        })
    usable = [
        float(row["moving_block_lower_95_pct"])
        for row in groups if row["moving_block_lower_95_pct"] is not None
    ]
    return {
        "status": "READY" if usable else "NO_USABLE_BOOTSTRAPS",
        "group_column": group_column, "groups": groups,
        "minimum_lower_95_pct": round(min(usable), 4) if usable else None,
    }


def leave_one_source_out_diagnostics(
    settled: pd.DataFrame, month_names: list[str], block_size: int = 3,
) -> dict[str, Any]:
    report = leave_one_group_out_diagnostics(
        settled, month_names, "execution_bookmaker", block_size
    )
    return {
        "status": report["status"],
        "sources": [
            {
                "excluded_bookmaker": row["excluded_group"],
                **{key: value for key, value in row.items() if key != "excluded_group"},
            }
            for row in report["groups"]
        ],
        "minimum_lower_95_pct": report["minimum_lower_95_pct"],
    }


def leave_one_team_out_diagnostics(
    settled: pd.DataFrame, month_names: list[str], block_size: int = 3,
    minimum_exposures: int = 2,
) -> dict[str, Any]:
    if settled.empty or not {"home_team", "away_team"}.issubset(settled):
        return {"status": "NO_TEAMS", "teams": [], "minimum_lower_95_pct": None}
    exposure = pd.concat([
        settled["home_team"].astype(str), settled["away_team"].astype(str)
    ]).value_counts()
    teams = []
    for team in sorted(exposure.loc[exposure >= minimum_exposures].index):
        retained = settled.loc[
            (settled["home_team"].astype(str) != team)
            & (settled["away_team"].astype(str) != team)
        ]
        retained_months = retained["test_month"].astype(str)
        monthly = [{
            "month": month,
            "staked": float(retained.loc[retained_months == month, "stake"].sum()),
            "profit": float(retained.loc[retained_months == month, "profit"].sum()),
        } for month in month_names]
        bootstrap = moving_block_bootstrap_roi(monthly, block_size=block_size)
        staked = float(retained["stake"].sum())
        profit = float(retained["profit"].sum())
        teams.append({
            "excluded_team": team, "historical_exposures": int(exposure[team]),
            "retained_bets": len(retained), "retained_staked": round(staked, 2),
            "retained_profit": round(profit, 2),
            "retained_roi_pct": round(profit / staked * 100.0, 2) if staked else None,
            "moving_block_lower_95_pct": bootstrap.get("lower_95_pct"),
        })
    usable = [
        float(row["moving_block_lower_95_pct"])
        for row in teams if row["moving_block_lower_95_pct"] is not None
    ]
    return {
        "status": "READY" if usable else "NO_REPEATED_TEAMS",
        "minimum_exposures": minimum_exposures, "teams": teams,
        "minimum_lower_95_pct": round(min(usable), 4) if usable else None,
    }


def top_winner_removal_diagnostics(
    settled: pd.DataFrame, month_names: list[str],
    removal_counts: tuple[int, ...] = (1, 3, 5, 10), block_size: int = 3,
) -> dict[str, Any]:
    if settled.empty:
        return {"status": "NO_POSITIONS", "scenarios": []}
    ordered_winners = settled.loc[settled["profit"] > 0].sort_values(
        ["profit", "candidate_id"], ascending=[False, True]
    )
    scenarios = []
    for count in removal_counts:
        removed_index = ordered_winners.head(count).index
        retained = settled.drop(index=removed_index)
        retained_months = retained["test_month"].astype(str)
        monthly = [{
            "month": month,
            "staked": float(retained.loc[retained_months == month, "stake"].sum()),
            "profit": float(retained.loc[retained_months == month, "profit"].sum()),
        } for month in month_names]
        bootstrap = moving_block_bootstrap_roi(monthly, block_size=block_size)
        staked = float(retained["stake"].sum())
        profit = float(retained["profit"].sum())
        scenarios.append({
            "removed_winners": count,
            "actual_removed_winners": len(removed_index),
            "retained_bets": len(retained),
            "retained_staked": round(staked, 2), "retained_profit": round(profit, 2),
            "retained_roi_pct": round(profit / staked * 100.0, 2) if staked else None,
            "moving_block_lower_95_pct": bootstrap.get("lower_95_pct"),
        })
    return {"status": "READY", "scenarios": scenarios}


def closing_value_diagnostics(
    settled: pd.DataFrame, late_start: str = "2023-08-01",
) -> dict[str, Any]:
    required = {"stake", "odds", "closing_probability", "closing_edge_pct", "profit", "date"}
    if settled.empty or not required.issubset(settled.columns):
        return {"status": "UNAVAILABLE", "required_columns": sorted(required)}
    frame = settled.copy()
    for column in ("stake", "odds", "closing_probability", "closing_edge_pct", "profit"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=list(required - {"date"}))
    if frame.empty:
        return {"status": "UNAVAILABLE", "required_columns": sorted(required)}
    frame["closing_expected_profit"] = (
        frame["stake"] * (frame["closing_probability"] * frame["odds"] - 1.0)
    )
    late = frame.loc[frame["date"].astype(str) >= late_start]

    def period_metrics(period: pd.DataFrame) -> dict[str, Any]:
        stake = float(period["stake"].sum())
        expected = float(period["closing_expected_profit"].sum())
        return {
            "positions": len(period),
            "staked": round(stake, 2),
            "closing_expected_profit": round(expected, 4),
            "closing_expected_roi_pct": (
                round(expected / stake * 100.0, 4) if stake else None
            ),
            "positive_clv_rate": (
                round(float((period["closing_edge_pct"] > 0).mean()), 4)
                if len(period) else None
            ),
        }

    realized = float(frame["profit"].sum())
    expected = float(frame["closing_expected_profit"].sum())
    return {
        "status": "READY",
        "benchmark": "position closing fair probability",
        "all": period_metrics(frame),
        "late": {"starts_on": late_start, **period_metrics(late)},
        "realized_profit": round(realized, 4),
        "realized_minus_closing_expected_profit": round(realized - expected, 4),
        "guardrail": (
            "Post-settlement attribution only; closing prices and outcomes never alter "
            "eligibility, direction, or stake."
        ),
    }


def closing_expected_monthly_stability(
    settled: pd.DataFrame, month_names: list[str], block_size: int = 3,
) -> dict[str, Any]:
    """Measure temporal stability with closing value instead of match outcomes."""
    required = {"test_month", "stake", "odds", "closing_probability"}
    if settled.empty or not required.issubset(settled.columns):
        return {
            "status": "UNAVAILABLE",
            "required_columns": sorted(required),
            "monthly": [],
        }
    frame = settled.copy()
    for column in ("stake", "odds", "closing_probability"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(
        subset=["test_month", "stake", "odds", "closing_probability"]
    )
    if frame.empty:
        return {
            "status": "UNAVAILABLE",
            "required_columns": sorted(required),
            "monthly": [],
        }
    frame["closing_expected_profit"] = (
        frame["stake"] * (frame["closing_probability"] * frame["odds"] - 1.0)
    )
    month_values = frame["test_month"].astype(str)
    monthly: list[dict[str, Any]] = []
    for month in month_names:
        period = frame.loc[month_values == str(month)]
        stake = float(period["stake"].sum())
        expected_profit = float(period["closing_expected_profit"].sum())
        monthly.append({
            "month": str(month),
            "bets": len(period),
            "staked": round(stake, 4),
            "profit": round(expected_profit, 6),
            "closing_expected_profit": round(expected_profit, 6),
            "closing_expected_roi_pct": (
                round(expected_profit / stake * 100.0, 4) if stake else 0.0
            ),
        })
    active = [row for row in monthly if int(row["bets"]) > 0]
    iid = _monthly_bootstrap(monthly)
    block = moving_block_bootstrap_roi(monthly, block_size=block_size)
    positive = sum(
        float(row["closing_expected_profit"]) > 0 for row in active
    )
    return {
        "status": (
            "READY"
            if iid.get("lower_95_pct") is not None
            and block.get("lower_95_pct") is not None
            else "INSUFFICIENT_SAMPLE"
        ),
        "benchmark": "position closing fair probability",
        "active_months": len(active),
        "positive_expected_active_months": positive,
        "positive_expected_active_month_rate": (
            round(positive / len(active), 4) if active else None
        ),
        "monthly_bootstrap_roi": iid,
        "moving_block_bootstrap_roi": block,
        "monthly": monthly,
        "guardrail": (
            "Closing prices are attribution-only and cannot change frozen eligibility, "
            "direction or stake. Match outcomes are not used by this diagnostic."
        ),
    }


def agreement_opening(
    direct: pd.DataFrame, movement: pd.DataFrame, disagreement_penalty: float = 0.0,
    minimum_lower_clv_pct: float = 1.0,
    staking_probability_profile: str = "minimum_lower_clv",
) -> pd.DataFrame:
    direct_opening = direct.drop(
        columns=[name for name in FUTURE_COLUMNS if name in direct], errors="ignore"
    ).copy()
    direct_opening.rename(columns={
        "predicted_closing_edge_pct": "direct_predicted_clv_pct",
        "lower_closing_edge_pct": "direct_lower_clv_pct",
        "estimated_probability_from_lower_clv": "direct_staking_probability",
        "estimated_probability_from_training_market": "direct_market_staking_probability",
        "estimated_probability_from_training_market_logistic": (
            "direct_market_logistic_staking_probability"
        ),
        "estimated_probability_from_validated_market_residual": (
            "direct_validated_market_residual_staking_probability"
        ),
        "estimated_probability_from_unshrunk_training_market": (
            "direct_unshrunk_market_staking_probability"
        ),
        "market_calibration_weight": "direct_market_calibration_weight",
    }, inplace=True)
    movement_columns = [
        "candidate_id", "test_month", "outcome",
        "predicted_closing_edge_pct", "lower_closing_edge_pct",
        "estimated_probability_from_lower_clv",
    ]
    if "estimated_probability_from_training_market" in movement:
        movement_columns.append("estimated_probability_from_training_market")
    if "estimated_probability_from_training_market_logistic" in movement:
        movement_columns.append("estimated_probability_from_training_market_logistic")
    if "estimated_probability_from_validated_market_residual" in movement:
        movement_columns.append("estimated_probability_from_validated_market_residual")
    if "estimated_probability_from_unshrunk_training_market" in movement:
        movement_columns.append("estimated_probability_from_unshrunk_training_market")
    if "market_calibration_weight" in movement:
        movement_columns.append("market_calibration_weight")
    movement_opening = movement[movement_columns].copy()
    movement_opening.rename(columns={
        "predicted_closing_edge_pct": "movement_predicted_clv_pct",
        "lower_closing_edge_pct": "movement_lower_clv_pct",
        "estimated_probability_from_lower_clv": "movement_staking_probability",
        "estimated_probability_from_training_market": "movement_market_staking_probability",
        "estimated_probability_from_training_market_logistic": (
            "movement_market_logistic_staking_probability"
        ),
        "estimated_probability_from_validated_market_residual": (
            "movement_validated_market_residual_staking_probability"
        ),
        "estimated_probability_from_unshrunk_training_market": (
            "movement_unshrunk_market_staking_probability"
        ),
        "market_calibration_weight": "movement_market_calibration_weight",
    }, inplace=True)
    agreed = direct_opening.merge(
        movement_opening, on=["candidate_id", "test_month", "outcome"],
        how="inner", validate="one_to_one",
    )
    agreed["predicted_closing_edge_pct"] = agreed[[
        "direct_predicted_clv_pct", "movement_predicted_clv_pct",
    ]].mean(axis=1)
    agreed["model_disagreement_pct"] = (
        agreed["direct_predicted_clv_pct"] - agreed["movement_predicted_clv_pct"]
    ).abs()
    agreed["lower_closing_edge_pct"] = agreed[[
        "direct_lower_clv_pct", "movement_lower_clv_pct",
    ]].min(axis=1) - disagreement_penalty * agreed["model_disagreement_pct"]
    if {
        "direct_staking_probability", "movement_staking_probability",
    }.issubset(agreed.columns):
        agreed["staking_probability"] = agreed[[
            "direct_staking_probability", "movement_staking_probability",
        ]].min(axis=1)
        agreed["minimum_lower_clv_staking_probability"] = agreed[
            "staking_probability"
        ]
    if staking_probability_profile == "training_market_platt":
        required = {
            "direct_market_staking_probability", "movement_market_staking_probability",
        }
        if not required.issubset(agreed.columns):
            raise ValueError("training market probability is missing from component positions")
        agreed["staking_probability"] = agreed[list(sorted(required))].min(axis=1)
    elif staking_probability_profile == "training_market_logistic":
        required = {
            "direct_market_logistic_staking_probability",
            "movement_market_logistic_staking_probability",
        }
        if not required.issubset(agreed.columns):
            raise ValueError(
                "training market logistic probability is missing from component positions"
            )
        agreed["staking_probability"] = agreed[list(sorted(required))].min(axis=1)
    elif staking_probability_profile == "validated_market_residual_blend":
        required = {
            "direct_validated_market_residual_staking_probability",
            "movement_validated_market_residual_staking_probability",
        }
        if not required.issubset(agreed.columns):
            raise ValueError(
                "validated market residual probability is missing from component positions"
            )
        agreed["staking_probability"] = agreed[list(sorted(required))].min(axis=1)
    elif staking_probability_profile == "validated_market_risk_scaling":
        probability_columns = {
            "direct_unshrunk_market_staking_probability",
            "movement_unshrunk_market_staking_probability",
        }
        weight_columns = {
            "direct_market_calibration_weight", "movement_market_calibration_weight",
        }
        if not probability_columns.issubset(agreed) or not weight_columns.issubset(agreed):
            raise ValueError("validated market reliability fields are missing")
        agreed["staking_probability"] = agreed[
            list(sorted(probability_columns))
        ].min(axis=1)
        agreed["calibration_reliability_multiplier"] = agreed[
            list(sorted(weight_columns))
        ].min(axis=1)
    elif staking_probability_profile != "minimum_lower_clv":
        raise ValueError(
            f"unknown agreement staking probability profile: {staking_probability_profile}"
        )
    return agreed.loc[
        agreed["lower_closing_edge_pct"] >= minimum_lower_clv_pct
    ].copy()


def apply_stake_adjustments(
    opening: pd.DataFrame, minimum_depth: int | None,
    minimum_depth_stake_multiplier: float,
    short_odds_threshold: float = 0.0,
    short_odds_stake_multiplier: float = 1.0,
    low_clv_upper_pct: float = 0.0,
    low_clv_stake_multiplier: float = 1.0,
    positive_clv_probability_soft_cap: float = 0.0,
    positive_clv_probability_minimum_multiplier: float = 0.5,
    positive_clv_probability_maximum_multiplier: float = 1.0,
) -> pd.DataFrame:
    if not 0.0 <= minimum_depth_stake_multiplier <= 1.0:
        raise ValueError("minimum_depth_stake_multiplier must be between 0 and 1")
    if not 0.0 <= short_odds_stake_multiplier <= 1.0:
        raise ValueError("short_odds_stake_multiplier must be between 0 and 1")
    if not 0.0 <= low_clv_stake_multiplier <= 1.0:
        raise ValueError("low_clv_stake_multiplier must be between 0 and 1")
    if positive_clv_probability_soft_cap < 0.0:
        raise ValueError("positive_clv_probability_soft_cap cannot be negative")
    if not 0.0 <= positive_clv_probability_minimum_multiplier <= 1.0:
        raise ValueError(
            "positive_clv_probability_minimum_multiplier must be between 0 and 1"
        )
    if not 1.0 <= positive_clv_probability_maximum_multiplier <= 2.0:
        raise ValueError(
            "positive_clv_probability_maximum_multiplier must be between 1 and 2"
        )
    adjusted = opening.copy()
    adjusted["stake_multiplier"] = 1.0
    if "calibration_reliability_multiplier" in adjusted:
        adjusted["stake_multiplier"] *= adjusted[
            "calibration_reliability_multiplier"
        ].clip(0.0, 1.0)
    if short_odds_threshold > 0:
        adjusted.loc[
            adjusted["odds"] < short_odds_threshold, "stake_multiplier"
        ] *= short_odds_stake_multiplier
    if low_clv_upper_pct > 0:
        if "lower_closing_edge_pct" not in adjusted:
            raise ValueError("missing lower_closing_edge_pct for CLV tier sizing")
        adjusted.loc[
            adjusted["lower_closing_edge_pct"] < low_clv_upper_pct,
            "stake_multiplier",
        ] *= low_clv_stake_multiplier
    if positive_clv_probability_soft_cap > 0.0:
        field = "predicted_positive_clv_probability"
        if field not in adjusted:
            raise ValueError("positive-CLV probability is missing from direct positions")
        probability_multiplier = (
            adjusted[field].astype(float) / positive_clv_probability_soft_cap
        ).clip(
            lower=positive_clv_probability_minimum_multiplier,
            upper=positive_clv_probability_maximum_multiplier,
        )
        adjusted["stake_multiplier"] *= probability_multiplier
    if minimum_depth is not None:
        adjusted.loc[
            adjusted["reference_bookmakers"] == minimum_depth, "stake_multiplier"
        ] *= minimum_depth_stake_multiplier
    return adjusted


def prior_only_market_probability_blend(
    opening: pd.DataFrame, settlements: pd.DataFrame,
    minimum_prior_positions: int = 30, prior_strength: float = 50.0,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Blend Kelly probability toward consensus using only earlier settled months."""
    if minimum_prior_positions < 1:
        raise ValueError("minimum_prior_positions must be positive")
    if prior_strength < 0:
        raise ValueError("prior_strength cannot be negative")
    adjusted = opening.copy()
    evidence = adjusted[[
        "candidate_id", "test_month", "probability", "staking_probability",
    ]].merge(
        settlements[["candidate_id", "test_month", "won"]],
        on=["candidate_id", "test_month"], how="left", validate="one_to_one",
    )
    diagnostics: list[dict[str, Any]] = []
    months = sorted(adjusted["test_month"].astype(str).unique())
    evidence_months = evidence["test_month"].astype(str)
    adjusted_months = adjusted["test_month"].astype(str)
    for month in months:
        prior = evidence.loc[(evidence_months < month) & evidence["won"].notna()]
        raw_weight = shrunk_weight = 1.0
        status = "INSUFFICIENT_PRIOR_SETTLEMENTS"
        if len(prior) >= minimum_prior_positions:
            delta = (
                prior["staking_probability"].astype(float)
                - prior["probability"].astype(float)
            )
            denominator = float((delta * delta).sum())
            if denominator > 0:
                won = prior["won"].astype(float)
                numerator = float((delta * (won - prior["probability"])).sum())
                raw_weight = min(1.0, max(0.0, numerator / denominator))
                shrunk_weight = raw_weight * len(prior) / (len(prior) + prior_strength)
                status = "PRIOR_ONLY_BLEND_FITTED"
        current = adjusted_months == month
        reference = adjusted.loc[current, "probability"].astype(float)
        raw = adjusted.loc[current, "staking_probability"].astype(float)
        adjusted.loc[current, "staking_probability"] = (
            reference + shrunk_weight * (raw - reference)
        ).clip(0.001, 0.999)
        diagnostics.append({
            "month": month, "prior_positions": len(prior), "status": status,
            "raw_model_weight": round(raw_weight, 6),
            "shrunk_model_weight": round(shrunk_weight, 6),
        })
    return adjusted, diagnostics


def cap_daily_group_exposure(
    frozen: pd.DataFrame, group_column: str, maximum_group_stake: float,
) -> pd.DataFrame:
    if maximum_group_stake <= 0 or frozen.empty:
        return frozen.copy()
    if group_column not in frozen:
        raise ValueError(f"missing group exposure column: {group_column}")
    adjusted = frozen.copy()
    totals = adjusted.groupby(["date", group_column])["stake"].transform("sum")
    scale = (maximum_group_stake / totals).clip(upper=1.0)
    adjusted["stake"] = (adjusted["stake"] * scale).round(2)
    return adjusted.loc[adjusted["stake"] >= 0.10].copy()


def filter_opening_by_eligibility_keys(
    opening: pd.DataFrame,
    eligible_candidate_keys: set[tuple[str, str]] | None,
) -> pd.DataFrame:
    if eligible_candidate_keys is None:
        return opening.copy()
    keys = pd.Series(
        zip(opening["candidate_id"].astype(str), opening["outcome"].astype(str)),
        index=opening.index,
    )
    return opening.loc[keys.isin(eligible_candidate_keys)].copy()


def apply_cross_cost_positive_clv_consensus(
    opening: pd.DataFrame, peer_positions: pd.DataFrame,
) -> pd.DataFrame:
    """Use the lower decision-time CLV probability from two cost models."""
    probability_field = "predicted_positive_clv_probability"
    required = {"candidate_id", "outcome", probability_field}
    if not required.issubset(opening.columns):
        raise ValueError("local positive-CLV probability is missing")
    if not required.issubset(peer_positions.columns):
        raise ValueError("peer positive-CLV probability is missing")
    peer = peer_positions[list(sorted(required))].copy()
    peer.rename(columns={probability_field: "peer_positive_clv_probability"}, inplace=True)
    peer.drop_duplicates(["candidate_id", "outcome"], inplace=True)
    adjusted = opening.merge(
        peer, on=["candidate_id", "outcome"], how="left", validate="one_to_one"
    )
    adjusted["local_positive_clv_probability"] = adjusted[probability_field]
    adjusted["peer_positive_clv_probability"] = adjusted[
        "peer_positive_clv_probability"
    ].fillna(0.0)
    adjusted[probability_field] = adjusted[[
        "local_positive_clv_probability", "peer_positive_clv_probability",
    ]].min(axis=1)
    return adjusted


def replay_agreement(
    direct_dir: Path, movement_dir: Path, output_dir: Path,
    disagreement_penalty: float = 0.0,
    minimum_depth_stake_multiplier: float = 1.0,
    minimum_staking_probability: float = 0.0,
    kelly_fraction: float = 0.50,
    maximum_single_stake: float = 15.0,
    minimum_lower_clv_pct: float = 1.0,
    minimum_execution_odds: float = 0.0,
    short_odds_threshold: float = 0.0,
    short_odds_stake_multiplier: float = 1.0,
    staking_probability_profile: str = "minimum_lower_clv",
    calibration_minimum_prior_positions: int = 30,
    calibration_prior_strength: float = 50.0,
    maximum_daily_league_stake: float = 0.0,
    staking_mode: str = "kelly",
    flat_stake: float = 3.0,
    eligibility_file: Path | None = None,
    governance_gate_profile: str = "absolute_winner_deletion",
    low_clv_upper_pct: float = 0.0,
    low_clv_stake_multiplier: float = 1.0,
    positive_clv_probability_soft_cap: float = 0.0,
    positive_clv_probability_minimum_multiplier: float = 0.5,
    positive_clv_probability_maximum_multiplier: float = 1.0,
    positive_clv_probability_peer_file: Path | None = None,
) -> dict[str, Any]:
    direct = pd.read_csv(direct_dir / "positions.csv")
    movement = pd.read_csv(movement_dir / "positions.csv")
    monthly_source = pd.read_csv(direct_dir / "monthly.csv")
    daily_source = pd.read_csv(direct_dir / "daily.csv")
    agreement_probability_profile = (
        staking_probability_profile
        if staking_probability_profile in {
            "training_market_platt", "training_market_logistic",
            "validated_market_residual_blend", "validated_market_risk_scaling",
        }
        else "minimum_lower_clv"
    )
    opening = agreement_opening(
        direct, movement, disagreement_penalty, minimum_lower_clv_pct,
        agreement_probability_profile,
    )
    if positive_clv_probability_peer_file is not None:
        peer_positions = pd.read_csv(positive_clv_probability_peer_file)
        opening = apply_cross_cost_positive_clv_consensus(
            opening, peer_positions
        )
    if "staking_probability" not in opening:
        opening["staking_probability"] = (
            (1.0 + opening["lower_closing_edge_pct"] / 100.0) / opening["odds"]
        ).clip(0.001, 0.999)
    selection_probability = (
        opening["minimum_lower_clv_staking_probability"]
        if "minimum_lower_clv_staking_probability" in opening
        else opening["staking_probability"]
    )
    opening = opening.loc[selection_probability >= minimum_staking_probability].copy()
    opening = opening.loc[opening["odds"] >= minimum_execution_odds].copy()
    eligible_candidate_keys = None
    if eligibility_file is not None:
        eligibility = pd.read_csv(
            eligibility_file, usecols=["candidate_id", "outcome"]
        )
        eligible_candidate_keys = set(zip(
            eligibility["candidate_id"].astype(str),
            eligibility["outcome"].astype(str),
        ))
        opening = filter_opening_by_eligibility_keys(
            opening, eligible_candidate_keys
        )
    calibration_diagnostics: list[dict[str, Any]] = []
    if staking_probability_profile == "prior_only_market_blend":
        opening, calibration_diagnostics = prior_only_market_probability_blend(
            opening, direct, calibration_minimum_prior_positions,
            calibration_prior_strength,
        )
    elif staking_probability_profile not in {
        "minimum_lower_clv", "training_market_platt", "training_market_logistic",
        "validated_market_residual_blend", "validated_market_risk_scaling",
    }:
        raise ValueError(
            f"unknown staking_probability_profile: {staking_probability_profile}"
        )
    minimum_depth = int(opening["reference_bookmakers"].min()) if not opening.empty else None
    opening = apply_stake_adjustments(
        opening, minimum_depth, minimum_depth_stake_multiplier,
        short_odds_threshold, short_odds_stake_multiplier,
        low_clv_upper_pct, low_clv_stake_multiplier,
        positive_clv_probability_soft_cap,
        positive_clv_probability_minimum_multiplier,
        positive_clv_probability_maximum_multiplier,
    )
    if staking_mode not in {"kelly", "flat"}:
        raise ValueError(f"unknown staking mode: {staking_mode}")
    if flat_stake <= 0:
        raise ValueError("flat_stake must be positive")
    stake_policy = (
        StakePolicy(
            f"model_agreement_flat_{flat_stake:g}", "flat", flat_stake,
            min(maximum_single_stake, flat_stake),
        )
        if staking_mode == "flat"
        else StakePolicy(
            f"model_agreement_{kelly_fraction:g}_kelly", "kelly", kelly_fraction,
            maximum_single_stake,
        )
    )
    if staking_mode == "flat":
        eligibility_policy = StakePolicy(
            f"model_agreement_{kelly_fraction:g}_kelly_eligibility",
            "kelly", kelly_fraction, maximum_single_stake,
        )
        eligibility_positions = freeze_stakes(opening, eligibility_policy)
        eligible_ids = (
            set(eligibility_positions["candidate_id"].astype(str))
            if "candidate_id" in eligibility_positions else set()
        )
        opening = opening.loc[
            opening["candidate_id"].astype(str).isin(eligible_ids)
        ].copy()
    frozen = freeze_stakes(opening, stake_policy)
    frozen = cap_daily_group_exposure(
        frozen, "league", maximum_daily_league_stake
    )
    settled = settle_frozen(frozen, direct)
    dates = sorted(daily_source["date"].astype(str).unique())
    daily = _daily_ledger(settled, dates, stake_policy.daily_budget)
    monthly_daily = monthly_reset_ledger(daily)

    monthly = []
    for month in monthly_source["month"].astype(str):
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
    block_bootstrap = moving_block_bootstrap_roi(monthly)
    source_robustness = leave_one_source_out_diagnostics(
        settled, [str(row["month"]) for row in monthly]
    )
    group_robustness = {
        column: leave_one_group_out_diagnostics(
            settled, [str(row["month"]) for row in monthly], column
        )
        for column in ("league", "outcome", "odds_band")
    }
    month_names = [str(row["month"]) for row in monthly]
    team_robustness = leave_one_team_out_diagnostics(settled, month_names)
    winner_robustness = top_winner_removal_diagnostics(settled, month_names)
    closing_value = closing_value_diagnostics(settled)
    closing_monthly_stability = closing_expected_monthly_stability(
        settled, month_names
    )
    if governance_gate_profile not in {
        "absolute_winner_deletion", "closing_probability_calibrated",
    }:
        raise ValueError(f"unknown governance gate profile: {governance_gate_profile}")
    calibrated_concentration = (
        simulate_gate_power(settled, month_names)
        if governance_gate_profile == "closing_probability_calibrated" else None
    )
    active = [row for row in monthly if row["bets"] > 0]
    reasons = []
    if len(settled) < 100:
        reasons.append("bets<100")
    if len(active) < 8:
        reasons.append("active_months<8")
    if (
        governance_gate_profile == "absolute_winner_deletion"
        and active and sum(row["profit"] > 0 for row in active) / len(active) < 0.60
    ):
        reasons.append("positive_active_month_rate<60pct")
    if profit <= 0:
        reasons.append("aggregate_profit<=0")
    if closing_value["status"] != "READY":
        reasons.append("closing_value_diagnostics_unavailable")
    else:
        if float(closing_value["all"]["closing_expected_profit"]) <= 0:
            reasons.append("closing_expected_profit<=0")
        late_expected_roi = closing_value["late"]["closing_expected_roi_pct"]
        if late_expected_roi is None or float(late_expected_roi) <= 0:
            reasons.append("late_closing_expected_roi<=0")
    closing_iid_lower = (
        closing_monthly_stability.get("monthly_bootstrap_roi", {})
        .get("lower_95_pct")
    )
    if closing_iid_lower is None or float(closing_iid_lower) <= 0:
        reasons.append("closing_expected_monthly_bootstrap_roi_lower_95<=0")
    closing_block_lower = (
        closing_monthly_stability.get("moving_block_bootstrap_roi", {})
        .get("lower_95_pct")
    )
    if closing_block_lower is None or float(closing_block_lower) <= 0:
        reasons.append("closing_expected_moving_block_roi_lower_95<=0")
    if bootstrap["lower_95_pct"] is None or float(bootstrap["lower_95_pct"]) <= 0:
        reasons.append("monthly_bootstrap_roi_lower_95<=0")
    if (
        block_bootstrap["lower_95_pct"] is None
        or float(block_bootstrap["lower_95_pct"]) <= 0
    ):
        reasons.append("moving_block_bootstrap_roi_lower_95<=0")
    if (
        source_robustness["minimum_lower_95_pct"] is None
        or float(source_robustness["minimum_lower_95_pct"]) <= 0
    ):
        reasons.append("leave_one_source_out_block_lower_95<=0")
    league_robustness = group_robustness["league"]
    if (
        league_robustness["minimum_lower_95_pct"] is None
        or float(league_robustness["minimum_lower_95_pct"]) <= 0
    ):
        reasons.append("leave_one_league_out_block_lower_95<=0")
    for column in ("outcome", "odds_band"):
        diagnostic = group_robustness[column]
        retained_profits = [float(row["retained_profit"]) for row in diagnostic["groups"]]
        if not retained_profits or min(retained_profits) <= 0:
            reasons.append(f"leave_one_{column}_out_profit<=0")
    if (
        team_robustness["minimum_lower_95_pct"] is None
        or float(team_robustness["minimum_lower_95_pct"]) <= 0
    ):
        reasons.append("leave_one_team_out_block_lower_95<=0")
    winner_scenarios = {
        int(row["removed_winners"]): row
        for row in winner_robustness.get("scenarios", [])
    }
    if governance_gate_profile == "absolute_winner_deletion":
        remove_five = winner_scenarios.get(5)
        if (
            not remove_five
            or remove_five["moving_block_lower_95_pct"] is None
            or float(remove_five["moving_block_lower_95_pct"]) <= 0
        ):
            reasons.append("remove_top_5_winners_block_lower_95<=0")
        remove_ten = winner_scenarios.get(10)
        if not remove_ten or float(remove_ten["retained_profit"]) <= 0:
            reasons.append("remove_top_10_winners_profit<=0")
    elif not bool(
        (calibrated_concentration or {})
        .get("observed_calibrated_diagnostics", {})
        .get("calibrated_concentration_gate_passed")
    ):
        reasons.append("closing_probability_calibrated_concentration_gate_failed")
    payload = {
        "method": "intersection of frozen direct-CLV and probability-movement selections",
        "anti_leakage": "future columns removed before agreement and stake sizing; outcomes merged only for settlement",
        "staking": stake_policy.__dict__, "daily_budget_limit": 100.0,
        "disagreement_penalty": disagreement_penalty,
        "minimum_reference_depth": minimum_depth,
        "minimum_depth_stake_multiplier": minimum_depth_stake_multiplier,
        "minimum_staking_probability": minimum_staking_probability,
        "minimum_lower_clv_pct": minimum_lower_clv_pct,
        "minimum_execution_odds": minimum_execution_odds,
        "short_odds_threshold": short_odds_threshold,
        "short_odds_stake_multiplier": short_odds_stake_multiplier,
        "low_clv_upper_pct": low_clv_upper_pct,
        "low_clv_stake_multiplier": low_clv_stake_multiplier,
        "positive_clv_probability_soft_cap": (
            positive_clv_probability_soft_cap
        ),
        "positive_clv_probability_minimum_multiplier": (
            positive_clv_probability_minimum_multiplier
        ),
        "positive_clv_probability_maximum_multiplier": (
            positive_clv_probability_maximum_multiplier
        ),
        "positive_clv_probability_peer_file": (
            str(positive_clv_probability_peer_file)
            if positive_clv_probability_peer_file is not None else None
        ),
        "staking_probability_profile": staking_probability_profile,
        "calibration_minimum_prior_positions": calibration_minimum_prior_positions,
        "calibration_prior_strength": calibration_prior_strength,
        "calibration_diagnostics": calibration_diagnostics,
        "maximum_daily_league_stake": maximum_daily_league_stake,
        "staking_mode": staking_mode,
        "flat_stake": flat_stake if staking_mode == "flat" else None,
        "flat_eligibility_policy": (
            f"{kelly_fraction:g}_kelly_minimum_0.10_stake"
            if staking_mode == "flat" else None
        ),
        "external_eligibility_file": (
            str(eligibility_file) if eligibility_file is not None else None
        ),
        "external_eligible_candidate_keys": (
            len(eligible_candidate_keys) if eligible_candidate_keys is not None else None
        ),
        "governance_gate_profile": governance_gate_profile,
        "direct_positions": len(direct), "movement_positions": len(movement),
        "agreement_positions": len(settled), "active_months": len(active),
        "positive_active_months": sum(row["profit"] > 0 for row in active),
        "staked": staked, "profit": profit,
        "roi_pct": round(profit / staked * 100.0, 2) if staked else 0.0,
        "maximum_daily_stake": round(float(daily["staked"].max()), 2),
        "maximum_drawdown": float(daily.attrs["max_drawdown"]),
        "monthly_bootstrap_roi": bootstrap,
        "moving_block_bootstrap_roi": block_bootstrap,
        "leave_one_execution_source_out": source_robustness,
        "leave_one_group_out": group_robustness,
        "leave_one_team_out": team_robustness,
        "top_winner_removal": winner_robustness,
        "closing_value": closing_value,
        "closing_expected_monthly_stability": closing_monthly_stability,
        "calibrated_concentration_gate": calibrated_concentration,
        "decision": "ROLLING_RESEARCH_SURVIVOR" if not reasons else "ROLLING_REJECTED",
        "decision_reasons": reasons, "monthly": monthly,
        "live_promotion_allowed": False,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    daily.to_csv(output_dir / "daily.csv", index=False, encoding="utf-8-sig")
    monthly_daily.to_csv(
        output_dir / "monthly_daily.csv", index=False, encoding="utf-8-sig"
    )
    settled.to_csv(output_dir / "positions.csv", index=False, encoding="utf-8-sig")
    eligibility_output = (
        frozen[["candidate_id", "outcome"]].drop_duplicates()
        if "candidate_id" in frozen else pd.DataFrame(columns=["candidate_id"])
    )
    if "outcome" not in eligibility_output:
        eligibility_output["outcome"] = pd.Series(dtype=str)
    eligibility_output.to_csv(
        output_dir / "eligibility.csv", index=False, encoding="utf-8-sig"
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--direct-dir", type=Path, required=True)
    parser.add_argument("--movement-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--disagreement-penalty", type=float, default=0.0)
    parser.add_argument("--minimum-depth-stake-multiplier", type=float, default=1.0)
    parser.add_argument("--minimum-staking-probability", type=float, default=0.0)
    parser.add_argument("--kelly-fraction", type=float, default=0.50)
    parser.add_argument("--maximum-single-stake", type=float, default=15.0)
    parser.add_argument("--minimum-lower-clv-pct", type=float, default=1.0)
    parser.add_argument("--minimum-execution-odds", type=float, default=0.0)
    parser.add_argument("--short-odds-threshold", type=float, default=0.0)
    parser.add_argument("--short-odds-stake-multiplier", type=float, default=1.0)
    parser.add_argument("--low-clv-upper-pct", type=float, default=0.0)
    parser.add_argument("--low-clv-stake-multiplier", type=float, default=1.0)
    parser.add_argument("--positive-clv-probability-soft-cap", type=float, default=0.0)
    parser.add_argument(
        "--positive-clv-probability-minimum-multiplier", type=float, default=0.5
    )
    parser.add_argument(
        "--positive-clv-probability-maximum-multiplier", type=float, default=1.0
    )
    parser.add_argument("--positive-clv-probability-peer-file", type=Path)
    parser.add_argument(
        "--staking-probability-profile",
        choices=(
            "minimum_lower_clv", "prior_only_market_blend", "training_market_platt",
            "training_market_logistic", "validated_market_risk_scaling",
            "validated_market_residual_blend",
        ),
        default="minimum_lower_clv",
    )
    parser.add_argument("--calibration-minimum-prior-positions", type=int, default=30)
    parser.add_argument("--calibration-prior-strength", type=float, default=50.0)
    parser.add_argument("--maximum-daily-league-stake", type=float, default=0.0)
    parser.add_argument("--staking-mode", choices=("kelly", "flat"), default="kelly")
    parser.add_argument("--flat-stake", type=float, default=3.0)
    parser.add_argument("--eligibility-file", type=Path)
    parser.add_argument(
        "--governance-gate-profile",
        choices=("absolute_winner_deletion", "closing_probability_calibrated"),
        default="absolute_winner_deletion",
    )
    args = parser.parse_args()
    report = replay_agreement(
        args.direct_dir, args.movement_dir, args.output_dir, args.disagreement_penalty,
        args.minimum_depth_stake_multiplier,
        args.minimum_staking_probability,
        args.kelly_fraction,
        args.maximum_single_stake,
        args.minimum_lower_clv_pct,
        args.minimum_execution_odds,
        args.short_odds_threshold,
        args.short_odds_stake_multiplier,
        args.staking_probability_profile,
        args.calibration_minimum_prior_positions,
        args.calibration_prior_strength,
        args.maximum_daily_league_stake,
        args.staking_mode,
        args.flat_stake,
        args.eligibility_file,
        args.governance_gate_profile,
        args.low_clv_upper_pct,
        args.low_clv_stake_multiplier,
        args.positive_clv_probability_soft_cap,
        args.positive_clv_probability_minimum_multiplier,
        args.positive_clv_probability_maximum_multiplier,
        args.positive_clv_probability_peer_file,
    )
    print(json.dumps({key: value for key, value in report.items() if key != "monthly"}, indent=2))


if __name__ == "__main__":
    main()
