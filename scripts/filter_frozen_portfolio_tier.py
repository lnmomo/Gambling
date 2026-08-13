"""Filter an already frozen portfolio by a decision-time confidence tier."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


FUTURE_COLUMNS = {
    "actual_outcome", "closing_edge_pct", "closing_probability",
    "closing_fair_odds", "positive_clv", "profit", "won",
}


def filter_frozen_confidence_tier(
    positions: pd.DataFrame, lower_pct: float, upper_pct: float,
    column: str = "lower_closing_edge_pct",
) -> pd.DataFrame:
    if lower_pct >= upper_pct:
        raise ValueError("lower_pct must be below upper_pct")
    required = {
        "candidate_id", "outcome", column, "stake",
        "decision_frozen_before_closing_and_result",
    }
    missing = required - set(positions.columns)
    if missing:
        raise ValueError(f"frozen portfolio is missing columns: {sorted(missing)}")
    frozen = positions["decision_frozen_before_closing_and_result"].astype(str).str.lower()
    if not frozen.isin({"true", "1"}).all():
        raise ValueError("portfolio contains a decision that was not frozen")
    opening = positions.drop(
        columns=[column for column in FUTURE_COLUMNS if column in positions],
        errors="ignore",
    )
    edge = pd.to_numeric(opening[column], errors="coerce")
    selected_keys = set(map(tuple, opening.loc[
        edge.ge(lower_pct) & edge.lt(upper_pct), ["candidate_id", "outcome"]
    ].astype(str).to_numpy()))
    keys = pd.Series(
        map(tuple, positions[["candidate_id", "outcome"]].astype(str).to_numpy()),
        index=positions.index,
    )
    return positions.loc[keys.isin(selected_keys)].copy()


def replay_tier(
    source_dir: Path, output_dir: Path, lower_pct: float, upper_pct: float,
    column: str = "lower_closing_edge_pct",
) -> dict[str, Any]:
    positions = pd.read_csv(source_dir / "positions.csv")
    source_summary = json.loads(
        (source_dir / "summary.json").read_text(encoding="utf-8-sig")
    )
    selected = filter_frozen_confidence_tier(
        positions, lower_pct, upper_pct, column
    )
    payload = {
        "method": "decision-time lower closing-edge confidence tier",
        "source_dir": str(source_dir),
        "decision_time_column": column,
        "lower_pct_inclusive": lower_pct,
        "upper_pct_exclusive": upper_pct,
        "source_positions": len(positions),
        "positions": len(selected),
        "staked": round(float(selected["stake"].sum()), 2),
        "monthly": source_summary.get("monthly", []),
        "anti_leakage": (
            "Candidate keys are selected after settlement columns are removed; closing "
            "prices and match outcomes cannot alter membership."
        ),
        "live_promotion_allowed": False,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    selected.to_csv(output_dir / "positions.csv", index=False, encoding="utf-8-sig")
    (output_dir / "summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--lower-pct", type=float, default=1.0)
    parser.add_argument("--upper-pct", type=float, default=2.0)
    parser.add_argument("--column", default="lower_closing_edge_pct")
    args = parser.parse_args()
    print(json.dumps(replay_tier(
        args.source_dir, args.output_dir, args.lower_pct, args.upper_pct,
        args.column,
    ), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
