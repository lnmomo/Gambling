"""Aggregate independently-run dynamic league-selector folds."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.portfolio_algorithm_rolling_validation import _aggregate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--baseline", type=Path,
        help="Fixed-candidate rolling report required to claim an algorithm improvement.",
    )
    args = parser.parse_args()
    reports = [json.loads(path.read_text(encoding="utf-8")) for path in args.inputs]
    methods = [report.get("method") or {} for report in reports]
    candidate_names = {method.get("candidate") for method in methods}
    if len(candidate_names) != 1:
        raise SystemExit("All reports must use the same fixed candidate")
    names = set().union(*(set((report.get("variants") or {}).keys()) for report in reports))
    if len(names) != 1:
        raise SystemExit("All reports must use the same training threshold")
    name = names.pop()
    rows = [
        row
        for report in reports
        for row in report["variants"][name].get("folds", [])
    ]
    rows.sort(key=lambda row: row["train_window"])
    summary = _aggregate(rows)
    requirements = {
        "positive_aggregate_profit": float(summary["profit"]) > 0,
        "positive_folds_at_least_5": int(summary["positive_folds"]) >= 5,
        "holdout_bets_at_least_200": int(summary["bets"]) >= 200,
    }
    baseline_summary = None
    if args.baseline:
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        baseline_summary = (baseline.get("fixed_candidate_holdout_aggregate") or {}).get(
            methods[0].get("candidate")
        )
        if not baseline_summary:
            raise SystemExit("Baseline report does not contain the selected fixed candidate")
        requirements["roi_at_least_fixed_candidate"] = float(summary["roi_pct"] or 0) >= float(
            baseline_summary["roi_pct"]
        )
    payload = {
        "method": {
            **methods[0],
            "fold_starts": sorted({
                value for method in methods for value in method.get("fold_starts", [])
            }),
        },
        "threshold": reports[0]["variants"][name]["minimum_train_bets"],
        "folds": rows,
        "aggregate": summary,
        "fixed_candidate_baseline": baseline_summary,
        "decision": {
            "status": "RESEARCH_SURVIVOR" if all(requirements.values()) else "REJECTED",
            "requirements": requirements,
        },
        "guardrail": "Cross-book opening-price research only; no China Sporttery SP deployment.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
