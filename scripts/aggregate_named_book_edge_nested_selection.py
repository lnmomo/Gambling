"""Aggregate partitioned no-lookahead named-book threshold selections."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.portfolio_algorithm_rolling_validation import _aggregate


def build_report(inputs: list[Path]) -> dict:
    folds: list[dict] = []
    for directory in inputs:
        payload = json.loads((directory / "rolling_validation_summary.json").read_text(encoding="utf-8"))
        if not payload.get("nested_selection", {}).get("enabled"):
            raise ValueError(f"{directory} was not run with --nested-selection")
        folds.extend(payload["folds"])
    folds.sort(key=lambda row: row["holdout_window"])
    selected = [
        row["candidates"][row["selected_on_train"]]
        for row in folds
        if row.get("selected_on_train") not in {None, "ABSTAIN"}
    ]
    aggregate = _aggregate(selected)
    reasons: list[str] = []
    if aggregate["folds"] < 5:
        reasons.append("active_holdout_folds<5")
    if aggregate["positive_folds"] < 3:
        reasons.append("positive_holdout_folds<3")
    if float(aggregate["profit"]) <= 0:
        reasons.append("aggregate_profit<=0")
    if float(aggregate["staked"]) < 100.0:
        reasons.append("staked<100_units")
    return {
        "method": "six-month train, three-month holdout nested B365-vs-Pinnacle threshold selection",
        "daily_budget_limit": 100.0,
        "execution_price": "B365 opening",
        "reference_probability": "Pinnacle opening multiplicative de-vig",
        "same_day_results_hidden_until_settlement": True,
        "timing_limitation": "Opening columns lack intraday quote timestamps; research-only until prospective aligned snapshots mature.",
        "folds": folds,
        "selected_holdout_aggregate": aggregate,
        "abstained_folds": sum(row.get("selected_on_train") == "ABSTAIN" for row in folds),
        "decision": "REJECTED_NESTED_SELECTION" if reasons else "RESEARCH_SURVIVOR",
        "reasons": reasons,
        "promotion_guardrail": "A research survivor still requires timestamp-aligned prospective validation; it never creates live positions.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = build_report(args.inputs)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
