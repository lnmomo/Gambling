"""Combine independently-run rolling-validation folds without changing them."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.portfolio_algorithm_rolling_validation import _aggregate


def _promotion_decision(summary: dict) -> dict:
    requirements = {
        "positive_aggregate_profit": float(summary["profit"]) > 0,
        "positive_folds_at_least_3": int(summary["positive_folds"]) >= 3,
        "holdout_bets_at_least_200": int(summary["bets"]) >= 200,
        "holdout_staked_at_least_100": float(summary["staked"]) >= 100.0,
    }
    return {
        "status": "RESEARCH_SURVIVOR" if all(requirements.values()) else "REJECTED",
        "requirements": requirements,
        "failed_requirements": [name for name, passed in requirements.items() if not passed],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    reports = []
    for path in args.inputs:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if int(payload.get("method", {}).get("folds", 0)) != 1:
            raise SystemExit(f"Expected one fold per input: {path}")
        reports.append(payload)
    reports.sort(key=lambda report: report["folds"][0]["train_window"])

    variant_names = reports[0]["method"]["variants"]
    if any(report["method"]["variants"] != variant_names for report in reports[1:]):
        raise SystemExit("All inputs must evaluate the same fixed candidate set")
    fixed = {name: [] for name in variant_names}
    selected = []
    folds = []
    for report in reports:
        fold = report["folds"][0]
        folds.append(fold)
        selected.append(fold["selected_holdout"])
        for name in variant_names:
            fixed[name].append(report["fixed_candidate_holdout_aggregate"][name])

    fixed_summary = {
        name: _aggregate([
            {
                **row,
                "max_drawdown": row.get("max_drawdown", row.get("max_fold_drawdown", 0.0)),
            }
            for row in rows
        ])
        for name, rows in fixed.items()
    }
    output = {
        "method": {
            **reports[0]["method"],
            "folds": len(reports),
            "execution": "each fold was run independently; this file combines immutable fold outputs",
        },
        "folds": folds,
        "train_selected_aggregate": _aggregate(selected),
        "fixed_candidate_holdout_aggregate": fixed_summary,
        "candidate_decisions": {name: _promotion_decision(summary) for name, summary in fixed_summary.items()},
        "interpretation": (
            "Candidates require positive aggregate profit, at least three positive folds, and material stake "
            "volume before they can continue. A positive result on a few cents of staking is not evidence."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
