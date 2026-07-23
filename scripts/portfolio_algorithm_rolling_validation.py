"""Rolling, no-lookahead validation for the daily portfolio candidates.

The optimizer chooses a candidate only from each fold's six-month training
period, then evaluates every fixed candidate on the following three months.
The aggregate is intentionally cross-period: it is evidence about a rule, not
evidence that one convenient calendar slice happened to be profitable.
"""
from __future__ import annotations

import argparse
import json
from statistics import median
from datetime import datetime
from pathlib import Path

from scripts.portfolio_algorithm_optimization import (
    ALL_SEASONS,
    DATA_BASE,
    PROJECT_ROOT,
    VARIANTS,
    _risk_adjusted_score,
    run_variant_grid,
    window_bounds,
)
from football_agents.portfolio_backtest import load_football_data_rows


FOLDS = (
    (2024, 3),
    (2024, 9),
    (2025, 3),
    (2025, 9),
)


def _fold(train_year: int, train_month: int) -> dict[str, str | datetime]:
    train_start, train_end = window_bounds(train_year, train_month, 6)
    holdout_start, holdout_end = window_bounds(
        train_end.year, train_end.month + 1 if train_end.month < 12 else 1, 3
    )
    if train_end.month == 12:
        holdout_start, holdout_end = window_bounds(train_end.year + 1, 1, 3)
    return {
        "train_start": train_start,
        "train_end": train_end,
        "holdout_start": holdout_start,
        "holdout_end": holdout_end,
    }


def _aggregate(rows: list[dict]) -> dict:
    staked = round(sum(float(row["staked"]) for row in rows), 2)
    profit = round(sum(float(row["profit"]) for row in rows), 2)
    rois = [float(row["roi_pct"]) for row in rows]
    return {
        "folds": len(rows),
        "positive_folds": sum(float(row["profit"]) > 0 for row in rows),
        "bets": int(sum(int(row["bets"]) for row in rows)),
        "staked": staked,
        "profit": profit,
        "roi_pct": round(profit / staked * 100, 2) if staked else None,
        "median_fold_roi_pct": round(median(rois), 2) if rois else None,
        "worst_fold_roi_pct": round(min(rois), 2) if rois else None,
        "max_fold_drawdown": round(max(float(row["max_drawdown"]) for row in rows), 2) if rows else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "reports" / "portfolio_algorithm_rolling_validation",
    )
    parser.add_argument(
        "--variant-names",
        nargs="+",
        help="Optional fixed candidate names. Useful for a focused challenger run.",
    )
    parser.add_argument(
        "--fold-start",
        action="append",
        metavar="YYYY-MM",
        help="Optional training-window start; repeat to run selected rolling folds.",
    )
    args = parser.parse_args()
    records = load_football_data_rows([str(DATA_BASE / season) for season in ALL_SEASONS])
    variants = VARIANTS
    if args.variant_names:
        requested = set(args.variant_names)
        variants = [variant for variant in VARIANTS if variant.name in requested]
        missing = requested - {variant.name for variant in variants}
        if missing:
            raise SystemExit(f"Unknown variant names: {', '.join(sorted(missing))}")
        if not variants:
            raise SystemExit("At least one variant is required")
    folds = FOLDS
    if args.fold_start:
        parsed_folds: list[tuple[int, int]] = []
        for value in args.fold_start:
            try:
                year, month = (int(part) for part in value.split("-", maxsplit=1))
                datetime(year, month, 1)
            except ValueError as exc:
                raise SystemExit(f"Invalid --fold-start {value!r}; expected YYYY-MM") from exc
            parsed_folds.append((year, month))
        folds = tuple(parsed_folds)

    fixed_holdouts: dict[str, list[dict]] = {variant.name: [] for variant in variants}
    selected_holdouts: list[dict] = []
    fold_reports: list[dict] = []
    for train_year, train_month in folds:
        fold = _fold(train_year, train_month)
        train_summaries, _ = run_variant_grid(
            records, variants, fold["train_start"], fold["train_end"]
        )
        ranked = sorted(train_summaries, key=_risk_adjusted_score, reverse=True)
        selected_name = ranked[0]["name"]
        holdout_summaries, _ = run_variant_grid(
            records, variants, fold["holdout_start"], fold["holdout_end"]
        )
        by_name = {row["name"]: row for row in holdout_summaries}
        for name, row in by_name.items():
            fixed_holdouts[name].append(row)
        selected_holdouts.append(by_name[selected_name])
        fold_reports.append({
            "train_window": f"{fold['train_start'].date()}..{fold['train_end'].date()}",
            "holdout_window": f"{fold['holdout_start'].date()}..{fold['holdout_end'].date()}",
            "selected_on_train": selected_name,
            "selected_holdout": by_name[selected_name],
            "baseline_holdout": by_name.get("A-baseline-ensemble"),
        })

    fixed_summary = {
        name: _aggregate(rows) for name, rows in fixed_holdouts.items()
    }
    payload = {
        "method": {
            "training_months": 6,
            "holdout_months": 3,
            "folds": len(folds),
            "variants": [variant.name for variant in variants],
            "selection": "training profit divided by maximum drawdown",
            "rule": "all results are updated only after every decision for that match date is frozen",
        },
        "folds": fold_reports,
        "train_selected_aggregate": _aggregate(selected_holdouts),
        "fixed_candidate_holdout_aggregate": fixed_summary,
        "interpretation": (
            "A candidate requires positive cross-fold aggregate profit and broad positive fold "
            "coverage before it can be treated as a research survivor. This uses only opening-price "
            "CSV fields, but is not proof of executable China Sporttery SP profitability."
        ),
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / "rolling_validation_summary.json"
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
