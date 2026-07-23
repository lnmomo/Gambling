"""Validate timestamp-unverified, named B365-versus-Pinnacle opening gaps.

The CSV provides named opening columns but not an intra-day quote timestamp.
This is therefore a research-only bridge hypothesis, never a promotion input.
All decisions use B365 as the executable price and a complete Pinnacle triplet
only for de-vigging; the model probability is not used for EV.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from football_agents.portfolio_backtest import BacktestConfig, load_football_data_rows, run_daily_portfolio
from scripts.portfolio_algorithm_optimization import ALL_SEASONS, DATA_BASE, PROJECT_ROOT
from scripts.portfolio_algorithm_rolling_validation import _aggregate, _fold


FOLDS = (
    (2022, 3), (2022, 9), (2023, 3), (2023, 9),
    (2024, 3), (2024, 9), (2025, 3), (2025, 9),
)
CANDIDATES = tuple(
    BacktestConfig(
        name=f"B365-vs-Pinnacle-edge{ratio:.2f}",
        execution_price_source="bet365_opening",
        bet_region="named_book_edge",
        named_book_edge_ratio=ratio,
        min_ev=0.0,
        minimum_odds=1.5,
        maximum_odds=6.0,
        drawdown_control=True,
        residual_retention=0.0,
    )
    for ratio in (1.02, 1.04, 1.06)
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
        "--output-dir", type=Path,
        default=PROJECT_ROOT / "reports" / "named_book_edge_rolling_validation",
    )
    args = parser.parse_args()
    folds = tuple(args.fold_start) if args.fold_start else FOLDS
    records = load_football_data_rows(
        [str(DATA_BASE / season) for season in ALL_SEASONS], primary_price_source="bet365"
    )
    rows = {candidate.name: [] for candidate in CANDIDATES}
    fold_rows: list[dict] = []
    for year, month in folds:
        fold = _fold(year, month)
        candidates = {}
        for candidate in CANDIDATES:
            report = run_daily_portfolio(records, candidate, fold["holdout_start"], fold["holdout_end"])
            row = {key: report[key] for key in (
                "config_name", "matches_in_window", "bets", "staked", "profit", "roi_pct",
                "win_rate", "max_drawdown", "execution_price_source", "named_book_edge_ratio",
            )}
            rows[candidate.name].append(row)
            candidates[candidate.name] = row
        fold_rows.append({
            "holdout_window": f"{fold['holdout_start'].date()}..{fold['holdout_end'].date()}",
            "candidates": candidates,
        })
    observed = {name: [row for row in values if row["matches_in_window"] > 0] for name, values in rows.items()}
    payload = {
        "method": {
            "execution_price": "bet365_opening",
            "reference_probability": "pinnacle_opening multiplicative de-vig",
            "timing": "opening fields only; source alignment timestamp unavailable",
            "same_day_rule": "all decisions freeze before any result on that date is revealed",
            "research_only": True,
        },
        "folds": fold_rows,
        "aggregate": {name: _aggregate(values) for name, values in observed.items()},
        "promotion_rule": "RESEARCH_ONLY: a timestamp-aligned prospective study is required even if the historical aggregate is positive.",
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    destination = args.output_dir / "rolling_validation_summary.json"
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"Wrote {destination}")


if __name__ == "__main__":
    main()
