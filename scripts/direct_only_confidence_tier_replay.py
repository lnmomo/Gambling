"""Add a cross-cost high-confidence direct-only tier to a frozen portfolio."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from scripts.clv_model_agreement_replay import cap_daily_group_exposure
from scripts.frozen_portfolio_report import write_frozen_portfolio_report
from scripts.multi_horizon_clv_replay import SETTLEMENT_COLUMNS, cap_daily_exposure
from scripts.v6_staking_policy_replay import StakePolicy, freeze_stakes


def add_direct_only_confidence_tier(
    base: pd.DataFrame,
    direct: pd.DataFrame,
    peer: pd.DataFrame,
    minimum_consensus_probability: float = 0.65,
    kelly_fraction: float = 0.50,
) -> pd.DataFrame:
    if not 0.5 <= minimum_consensus_probability <= 1.0:
        raise ValueError("minimum consensus probability must be between 0.5 and 1")
    common_required = {
        "candidate_id", "outcome", "date", "league", "odds", "stake",
        "decision_frozen_before_closing_and_result",
    }
    direct_required = common_required | {
        "lower_closing_edge_pct", "estimated_probability_from_training_market",
        "predicted_positive_clv_probability",
    }
    requirements = (
        ("base", base, common_required),
        ("direct", direct, direct_required),
        ("peer", peer, {
            "candidate_id", "outcome", "predicted_positive_clv_probability",
        }),
    )
    for label, frame, required in requirements:
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(f"{label} portfolio is missing columns: {sorted(missing)}")
    key_columns = ["candidate_id", "outcome"]
    peer_probability = peer[
        [*key_columns, "predicted_positive_clv_probability"]
    ].rename(columns={"predicted_positive_clv_probability": "peer_probability"})
    candidates = direct.merge(
        peer_probability, on=key_columns, how="inner", validate="one_to_one"
    )
    candidates["cross_cost_positive_clv_probability"] = candidates[[
        "predicted_positive_clv_probability", "peer_probability",
    ]].min(axis=1)

    base_match_ids = set(base["candidate_id"].astype(str))
    decision_only = candidates.drop(
        columns=[column for column in SETTLEMENT_COLUMNS if column in candidates],
        errors="ignore",
    ).copy()
    decision_only = decision_only.loc[
        decision_only["cross_cost_positive_clv_probability"].ge(
            minimum_consensus_probability
        )
        & ~decision_only["candidate_id"].astype(str).isin(base_match_ids)
    ].copy()
    decision_only["staking_probability"] = decision_only[
        "estimated_probability_from_training_market"
    ].astype(float)
    tier_opening = freeze_stakes(
        decision_only,
        StakePolicy(
            "cross_cost_direct_only_half_kelly", "kelly", kelly_fraction, 15.0
        ),
    )
    settlement_columns = [
        column for column in SETTLEMENT_COLUMNS if column in candidates.columns
    ]
    tier = tier_opening.merge(
        candidates[[*key_columns, *settlement_columns]],
        on=key_columns, how="left", validate="one_to_one",
    )
    tier["horizon_role"] = "9m3m_direct_only"
    combined = pd.concat([base, tier], ignore_index=True, sort=False)
    combined = cap_daily_group_exposure(combined, "league", 15.0)
    combined = cap_daily_exposure(combined, 100.0)
    combined["profit"] = combined.apply(
        lambda row: (
            float(row["stake"]) * (float(row["odds"]) - 1.0)
            if bool(row["won"]) else -float(row["stake"])
        ), axis=1,
    ).round(2)
    return combined


def replay_direct_only_tier(
    base_dir: Path,
    direct_dir: Path,
    peer_file: Path,
    output_dir: Path,
    minimum_consensus_probability: float = 0.65,
    kelly_fraction: float = 0.50,
) -> dict[str, Any]:
    base = pd.read_csv(base_dir / "positions.csv")
    direct = pd.read_csv(direct_dir / "positions.csv")
    peer = pd.read_csv(peer_file)
    source_summary = json.loads(
        (base_dir / "summary.json").read_text(encoding="utf-8-sig")
    )
    selected = add_direct_only_confidence_tier(
        base, direct, peer, minimum_consensus_probability, kelly_fraction
    )
    return write_frozen_portfolio_report(
        selected, source_summary, output_dir,
        "cross-cost positive-CLV direct-only core tier",
        "Tier membership and stakes use only frozen candidate identity, direction, "
        "opening odds, training-market probability and two decision-time classifier "
        "probabilities. Closing prices and results are attached only after freezing.",
        {
            "base_positions": int(len(base)),
            "incremental_positions": int(len(selected) - len(base)),
            "minimum_consensus_probability": minimum_consensus_probability,
            "incremental_kelly_fraction": kelly_fraction,
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-dir", type=Path, required=True)
    parser.add_argument("--direct-dir", type=Path, required=True)
    parser.add_argument("--peer-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--minimum-consensus-probability", type=float, default=0.65)
    parser.add_argument("--kelly-fraction", type=float, default=0.50)
    args = parser.parse_args()
    report = replay_direct_only_tier(
        args.base_dir, args.direct_dir, args.peer_file, args.output_dir,
        args.minimum_consensus_probability, args.kelly_fraction,
    )
    print(json.dumps(
        {key: value for key, value in report.items() if key != "monthly"},
        ensure_ascii=False, indent=2,
    ))


if __name__ == "__main__":
    main()
