"""Cross-fold test of executable single-book opening-price candidates.

This deliberately excludes the football-data ``Max*`` columns: they are an
unattributed cross-book maximum and cannot establish that a quoted price was
simultaneously executable. Every candidate below uses a complete Pinnacle
opening 1X2 triplet for both its market prior and its settlement price.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from football_agents.portfolio_backtest import BacktestConfig, load_football_data_rows, run_daily_portfolio
from scripts.portfolio_algorithm_optimization import ALL_SEASONS, DATA_BASE, PROJECT_ROOT, window_bounds
from scripts.portfolio_algorithm_rolling_validation import _aggregate, _fold


FOLDS = (
    (2022, 3), (2022, 9), (2023, 3), (2023, 9),
    (2024, 3), (2024, 9), (2025, 3), (2025, 9),
)

# Fixed before running. These are model-residual hypotheses, not line-shopping
# rules: no candidate reads or bets an aggregated Max* price.
CANDIDATES = (
    BacktestConfig(
        name="P1-pinnacle-anchor10",
        execution_price_source="pinnacle_opening",
        residual_retention=0.10,
        min_ev=0.01,
        minimum_odds=1.5,
        maximum_odds=6.0,
        drawdown_control=True,
    ),
    BacktestConfig(
        name="P2-pinnacle-anchor20",
        execution_price_source="pinnacle_opening",
        residual_retention=0.20,
        min_ev=0.02,
        minimum_odds=1.5,
        maximum_odds=6.0,
        drawdown_control=True,
    ),
    BacktestConfig(
        name="P3-pinnacle-favorite-anchor15",
        execution_price_source="pinnacle_opening",
        residual_retention=0.15,
        min_ev=0.01,
        minimum_odds=1.5,
        maximum_odds=6.0,
        bet_region="strong_favorite",
        favorite_min=0.50,
        drawdown_control=True,
    ),
    BacktestConfig(
        name="P4-pinnacle-midhome-anchor15",
        execution_price_source="pinnacle_opening",
        residual_retention=0.15,
        min_ev=0.01,
        minimum_odds=1.5,
        maximum_odds=6.0,
        bet_region="mid_home",
        mid_home_min=0.45,
        mid_home_max=0.55,
        drawdown_control=True,
    ),
)


def _parse_fold(value: str) -> tuple[int, int]:
    try:
        year, month = (int(part) for part in value.split("-", maxsplit=1))
        datetime(year, month, 1)
        return year, month
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected YYYY-MM") from exc


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fold-start", action="append", type=_parse_fold)
    parser.add_argument(
        "--price-source",
        choices=("pinnacle_opening", "bet365_opening"),
        default="pinnacle_opening",
        help="Named complete opening 1X2 source used for every decision and price.",
    )
    parser.add_argument(
        "--output-dir", type=Path,
        default=PROJECT_ROOT / "reports" / "executable_pinnacle_rolling_validation",
    )
    args = parser.parse_args()
    folds = tuple(args.fold_start) if args.fold_start else FOLDS
    source_prefix = "pinnacle" if args.price_source == "pinnacle_opening" else "bet365"
    candidates = tuple(
        replace(
            candidate,
            name=candidate.name.replace("pinnacle", source_prefix),
            execution_price_source=args.price_source,
        )
        for candidate in CANDIDATES
    )
    loader_source = "pinnacle" if args.price_source == "pinnacle_opening" else "bet365"
    records = load_football_data_rows(
        [str(DATA_BASE / season) for season in ALL_SEASONS],
        primary_price_source=loader_source,
    )
    rows_by_candidate: dict[str, list[dict]] = {candidate.name: [] for candidate in candidates}
    report_folds: list[dict] = []

    for year, month in folds:
        fold = _fold(year, month)
        per_candidate: dict[str, dict] = {}
        for candidate in candidates:
            report = run_daily_portfolio(
                records, candidate, fold["holdout_start"], fold["holdout_end"]
            )
            row = {
                key: report[key] for key in (
                    "config_name", "matches_in_window", "bets", "staked", "profit",
                    "roi_pct", "win_rate", "max_drawdown", "execution_price_source",
                )
            }
            rows_by_candidate[candidate.name].append(row)
            per_candidate[candidate.name] = row
        report_folds.append({
            "holdout_window": f"{fold['holdout_start'].date()}..{fold['holdout_end'].date()}",
            "candidates": per_candidate,
        })

    observed_rows = {
        name: [row for row in candidate_rows if row["matches_in_window"] > 0]
        for name, candidate_rows in rows_by_candidate.items()
    }
    aggregates = {name: _aggregate(rows) for name, rows in observed_rows.items()}
    payload = {
        "method": {
            "price_source": args.price_source,
            "timing": "opening",
            "folds": len(folds),
            "holdout_months": 3,
            "rule": "all same-date decisions freeze before any same-date result is revealed",
            "excluded": "MaxH/MaxD/MaxA aggregated cross-book prices",
        },
        "folds": report_folds,
        "aggregate": aggregates,
        "unavailable_holdout_folds": {
            name: len(rows_by_candidate[name]) - len(observed_rows[name])
            for name in rows_by_candidate
        },
        "promotion_rule": (
            "Research-only unless a fixed candidate has positive aggregate profit, broad positive-fold "
            "coverage, and later prospective evidence using the same executable price source."
        ),
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    destination = args.output_dir / "rolling_validation_summary.json"
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"Wrote {destination}")


if __name__ == "__main__":
    main()
