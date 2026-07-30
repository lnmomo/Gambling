from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def _moving_block_indices(
    month_count: int, block_size: int, iterations: int, seed: int,
) -> np.ndarray:
    rng = random.Random(seed)
    samples: list[list[int]] = []
    for _ in range(iterations):
        sample: list[int] = []
        while len(sample) < month_count:
            start = rng.randrange(month_count)
            sample.extend(
                (start + offset) % month_count for offset in range(block_size)
            )
        samples.append(sample[:month_count])
    return np.asarray(samples, dtype=int)


def _remove_largest_winners(
    profit: np.ndarray, stake: np.ndarray, count: int,
) -> tuple[np.ndarray, np.ndarray]:
    retained_profit = profit.copy()
    retained_stake = stake.copy()
    winner_indices = np.flatnonzero(profit > 0)
    if winner_indices.size:
        order = winner_indices[np.argsort(profit[winner_indices])[::-1]]
        removed = order[:count]
        retained_profit[removed] = 0.0
        retained_stake[removed] = 0.0
    return retained_profit, retained_stake


def simulate_gate_power(
    positions: pd.DataFrame, month_names: list[str], simulations: int = 2000,
    bootstrap_iterations: int = 1000, block_size: int = 3, seed: int = 20260730,
) -> dict[str, Any]:
    required = {
        "test_month", "stake", "odds", "closing_probability",
    }
    missing = sorted(required - set(positions.columns))
    if missing:
        raise ValueError(f"positions missing required columns: {missing}")
    if simulations < 1 or bootstrap_iterations < 1:
        raise ValueError("simulation counts must be positive")
    month_index = {month: index for index, month in enumerate(month_names)}
    position_month = positions["test_month"].astype(str).map(month_index)
    if position_month.isna().any():
        raise ValueError("position month is absent from the monthly ledger")

    stake = positions["stake"].to_numpy(dtype=float)
    odds = positions["odds"].to_numpy(dtype=float)
    probability = positions["closing_probability"].to_numpy(dtype=float)
    probability = np.clip(probability, 0.001, 0.999)
    month_matrix = np.zeros((len(positions), len(month_names)), dtype=float)
    month_matrix[np.arange(len(positions)), position_month.to_numpy(dtype=int)] = 1.0
    block_indices = _moving_block_indices(
        len(month_names), block_size, bootstrap_iterations, seed + 1
    )
    rng = np.random.default_rng(seed)
    wins = rng.random((simulations, len(positions))) < probability
    simulated_profit = np.where(wins, stake * (odds - 1.0), -stake)

    remove_five_lower: list[float] = []
    remove_five_profit: list[float] = []
    remove_ten_profit: list[float] = []
    positive_active_months: list[int] = []
    active_month_mask = (stake @ month_matrix) > 0
    for path_profit in simulated_profit:
        original_monthly_profit = path_profit @ month_matrix
        positive_active_months.append(int((original_monthly_profit[active_month_mask] > 0).sum()))
        profit_five, stake_five = _remove_largest_winners(path_profit, stake, 5)
        monthly_profit = profit_five @ month_matrix
        monthly_stake = stake_five @ month_matrix
        sampled_profit = monthly_profit[block_indices].sum(axis=1)
        sampled_stake = monthly_stake[block_indices].sum(axis=1)
        sampled_roi = np.divide(
            sampled_profit, sampled_stake,
            out=np.zeros_like(sampled_profit), where=sampled_stake > 0,
        ) * 100.0
        remove_five_lower.append(float(np.quantile(sampled_roi, 0.025)))
        remove_five_profit.append(float(profit_five.sum()))
        profit_ten, _stake_ten = _remove_largest_winners(path_profit, stake, 10)
        remove_ten_profit.append(float(profit_ten.sum()))

    lower = np.asarray(remove_five_lower)
    profit_five = np.asarray(remove_five_profit)
    profit_ten = np.asarray(remove_ten_profit)
    simulated_positive_months = np.asarray(positive_active_months)
    expected_profit = float((stake * (probability * odds - 1.0)).sum())
    report = {
        "method": "fixed-position Bernoulli simulation from closing fair probability",
        "simulations": simulations,
        "bootstrap_iterations_per_simulation": bootstrap_iterations,
        "block_size_months": block_size,
        "seed": seed,
        "positions": len(positions),
        "months": len(month_names),
        "closing_probability_expected_profit": round(expected_profit, 4),
        "closing_probability_expected_roi_pct": round(
            expected_profit / float(stake.sum()) * 100.0, 4
        ),
        "remove_top_5": {
            "block_lower_95_positive_rate": round(float((lower > 0).mean()), 6),
            "aggregate_profit_positive_rate": round(float((profit_five > 0).mean()), 6),
            "median_block_lower_95_pct": round(float(np.median(lower)), 4),
            "median_retained_profit": round(float(np.median(profit_five)), 2),
        },
        "remove_top_10": {
            "aggregate_profit_positive_rate": round(float((profit_ten > 0).mean()), 6),
            "median_retained_profit": round(float(np.median(profit_ten)), 2),
        },
        "joint_current_concentration_gate_pass_rate": round(
            float(((lower > 0) & (profit_ten > 0)).mean()), 6
        ),
        "guardrail": (
            "Post-settlement gate-power diagnostic only; simulated outcomes never alter "
            "historical eligibility, direction, probability, or stake."
        ),
    }
    if "profit" in positions:
        actual_profit = positions["profit"].to_numpy(dtype=float)
        actual_five_profit, actual_five_stake = _remove_largest_winners(
            actual_profit, stake, 5
        )
        actual_monthly_profit = actual_profit @ month_matrix
        actual_monthly_five_profit = actual_five_profit @ month_matrix
        actual_monthly_five_stake = actual_five_stake @ month_matrix
        actual_sampled_profit = actual_monthly_five_profit[block_indices].sum(axis=1)
        actual_sampled_stake = actual_monthly_five_stake[block_indices].sum(axis=1)
        actual_sampled_roi = np.divide(
            actual_sampled_profit, actual_sampled_stake,
            out=np.zeros_like(actual_sampled_profit), where=actual_sampled_stake > 0,
        ) * 100.0
        actual_lower = float(np.quantile(actual_sampled_roi, 0.025))
        actual_ten_profit, _actual_ten_stake = _remove_largest_winners(
            actual_profit, stake, 10
        )
        actual_positive_months = int(
            (actual_monthly_profit[active_month_mask] > 0).sum()
        )
        lower_percentile = float((lower <= actual_lower).mean())
        ten_profit_percentile = float(
            (profit_ten <= float(actual_ten_profit.sum())).mean()
        )
        positive_month_percentile = float(
            (simulated_positive_months <= actual_positive_months).mean()
        )
        report["observed_calibrated_diagnostics"] = {
            "remove_top_5_block_lower_95_pct": round(actual_lower, 4),
            "remove_top_5_block_lower_percentile": round(lower_percentile, 6),
            "remove_top_10_retained_profit": round(float(actual_ten_profit.sum()), 2),
            "remove_top_10_profit_percentile": round(ten_profit_percentile, 6),
            "positive_active_months": actual_positive_months,
            "active_months": int(active_month_mask.sum()),
            "positive_month_count_percentile": round(positive_month_percentile, 6),
            "minimum_acceptable_percentile": 0.05,
            "calibrated_concentration_gate_passed": (
                lower_percentile >= 0.05
                and ten_profit_percentile >= 0.05
                and positive_month_percentile >= 0.05
            ),
        }
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--simulations", type=int, default=2000)
    parser.add_argument("--bootstrap-iterations", type=int, default=1000)
    args = parser.parse_args()
    summary = json.loads(
        (args.report_dir / "summary.json").read_text(encoding="utf-8")
    )
    month_names = [str(row["month"]) for row in summary["monthly"]]
    positions = pd.read_csv(args.report_dir / "positions.csv")
    report = simulate_gate_power(
        positions, month_names, args.simulations, args.bootstrap_iterations
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
