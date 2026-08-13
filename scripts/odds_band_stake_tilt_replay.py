"""Apply a decision-time odds-band stake tilt to a frozen portfolio."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from scripts.clv_model_agreement_replay import cap_daily_group_exposure
from scripts.frozen_portfolio_report import write_frozen_portfolio_report
from scripts.multi_horizon_clv_replay import SETTLEMENT_COLUMNS, cap_daily_exposure


def apply_odds_band_tilt(
    positions: pd.DataFrame,
    preferred_multiplier: float = 1.05,
    reduced_multiplier: float = 0.95,
) -> pd.DataFrame:
    if preferred_multiplier < 1.0 or not 0.0 < reduced_multiplier <= 1.0:
        raise ValueError("invalid odds-band stake multipliers")
    required = {
        "candidate_id", "outcome", "odds", "stake", "date", "league",
        "decision_frozen_before_closing_and_result",
    }
    missing = required - set(positions.columns)
    if missing:
        raise ValueError(f"frozen portfolio is missing columns: {sorted(missing)}")
    frozen = positions["decision_frozen_before_closing_and_result"].astype(str).str.lower()
    if not frozen.isin({"true", "1"}).all():
        raise ValueError("portfolio contains a decision that was not frozen")

    settlement_columns = [
        column for column in SETTLEMENT_COLUMNS if column in positions.columns
    ]
    opening = positions.drop(columns=settlement_columns, errors="ignore").copy()
    odds = opening["odds"].astype(float)
    opening["odds_band_stake_multiplier"] = 1.0
    opening.loc[odds.ge(2.0) & odds.lt(3.0), "odds_band_stake_multiplier"] = (
        preferred_multiplier
    )
    opening.loc[odds.ge(3.0) & odds.lt(4.0), "odds_band_stake_multiplier"] = (
        reduced_multiplier
    )
    opening["stake"] = (
        opening["stake"].astype(float) * opening["odds_band_stake_multiplier"]
    ).round(2)
    opening = cap_daily_group_exposure(opening, "league", 15.0)
    opening = cap_daily_exposure(opening, 100.0)

    settlement = positions[["candidate_id", "outcome", *settlement_columns]]
    selected = opening.merge(
        settlement, on=["candidate_id", "outcome"], how="left",
        validate="one_to_one",
    )
    selected["profit"] = selected.apply(
        lambda row: (
            float(row["stake"]) * (float(row["odds"]) - 1.0)
            if bool(row["won"]) else -float(row["stake"])
        ), axis=1,
    ).round(2)
    return selected


def replay_odds_band_tilt(
    source_dir: Path,
    output_dir: Path,
    preferred_multiplier: float = 1.05,
    reduced_multiplier: float = 0.95,
) -> dict[str, Any]:
    positions = pd.read_csv(source_dir / "positions.csv")
    source_summary = json.loads(
        (source_dir / "summary.json").read_text(encoding="utf-8-sig")
    )
    selected = apply_odds_band_tilt(
        positions, preferred_multiplier, reduced_multiplier
    )
    return write_frozen_portfolio_report(
        selected, source_summary, output_dir,
        "fixed decision-time odds-band stake tilt",
        "Stake multipliers are chosen from frozen execution odds after all settlement "
        "columns are removed; closing prices and match outcomes cannot alter them.",
        {
            "preferred_odds_band": "2.0-3.0",
            "preferred_multiplier": preferred_multiplier,
            "reduced_odds_band": "3.0-4.0",
            "reduced_multiplier": reduced_multiplier,
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--preferred-multiplier", type=float, default=1.05)
    parser.add_argument("--reduced-multiplier", type=float, default=0.95)
    args = parser.parse_args()
    report = replay_odds_band_tilt(
        args.source_dir, args.output_dir,
        args.preferred_multiplier, args.reduced_multiplier,
    )
    print(json.dumps(
        {key: value for key, value in report.items() if key != "monthly"},
        ensure_ascii=False, indent=2,
    ))


if __name__ == "__main__":
    main()
