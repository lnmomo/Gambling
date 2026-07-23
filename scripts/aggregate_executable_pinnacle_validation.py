"""Merge partitioned executable-Pinnacle rolling-validation reports."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.portfolio_algorithm_rolling_validation import _aggregate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    folds: list[dict] = []
    rows: dict[str, list[dict]] = {}
    method: dict | None = None
    for directory in args.inputs:
        source = directory / "rolling_validation_summary.json"
        payload = json.loads(source.read_text(encoding="utf-8"))
        if method is None:
            method = dict(payload["method"])
        folds.extend(payload["folds"])
        for name, aggregate in payload["aggregate"].items():
            rows.setdefault(name, [])
        for fold in payload["folds"]:
            for name, row in fold["candidates"].items():
                rows[name].append(row)

    assert method is not None
    method["folds"] = len(folds)
    folds.sort(key=lambda row: row["holdout_window"])
    observed_rows = {
        name: [row for row in candidate_rows if row["matches_in_window"] > 0]
        for name, candidate_rows in rows.items()
    }
    merged = {
        "method": method,
        "folds": folds,
        "aggregate": {name: _aggregate(candidate_rows) for name, candidate_rows in observed_rows.items()},
        "unavailable_holdout_folds": {
            name: len(rows[name]) - len(observed_rows[name]) for name in rows
        },
        "decision": "REJECTED_ALL_CANDIDATES",
        "reason": (
            "No fixed executable single-book candidate may be promoted unless it clears "
            "the aggregate profitability and positive-fold coverage gates."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(merged["aggregate"], ensure_ascii=False, indent=2))
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
