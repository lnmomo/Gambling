"""Leak-free dynamic league selection for a fixed opening-price candidate.

For every rolling fold, league eligibility is calculated from the preceding
six months only. The selected league set is then frozen and evaluated on the
following three months, so holdout outcomes cannot choose their own universe.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from football_agents.portfolio_backtest import load_football_data_rows, run_daily_portfolio
from scripts.portfolio_algorithm_optimization import ALL_SEASONS, DATA_BASE, VARIANTS
from scripts.portfolio_algorithm_rolling_validation import _aggregate, _fold


FOLD_STARTS = (
    (2022, 3), (2022, 9), (2023, 3), (2023, 9),
    (2024, 3), (2024, 9), (2025, 3), (2025, 9),
)
DEFAULT_MIN_TRAIN_BETS = (10, 20, 40)


def _candidate(name: str):
    candidate = next((item for item in VARIANTS if item.name == name), None)
    if candidate is None:
        raise ValueError(f"Unknown registered variant: {name}")
    return candidate


def _eligible_leagues(records, candidate, fold: dict, minimum_bets: int) -> list[str]:
    eligible = []
    for league in sorted({record.league for record in records}):
        train_records = [record for record in records if record.league == league]
        train = run_daily_portfolio(train_records, candidate, fold["train_start"], fold["train_end"])
        if int(train["bets"]) >= minimum_bets and float(train["profit"]) > 0:
            eligible.append(league)
    return eligible


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", default="X-max-edge-fav040-edge105-hardkill30")
    parser.add_argument("--min-train-bets", nargs="+", type=int, default=list(DEFAULT_MIN_TRAIN_BETS))
    parser.add_argument(
        "--fold-start", action="append", metavar="YYYY-MM",
        help="Optional training-fold start, repeatable for independently runnable batches.",
    )
    parser.add_argument(
        "--output", type=Path,
        default=Path("reports/opening_price_dynamic_league_selector_v1/summary.json"),
    )
    args = parser.parse_args()
    if any(value <= 0 for value in args.min_train_bets):
        raise SystemExit("--min-train-bets values must be positive")
    candidate = _candidate(args.variant)
    records = load_football_data_rows([str(DATA_BASE / season) for season in ALL_SEASONS])
    folds = FOLD_STARTS
    if args.fold_start:
        parsed = []
        for value in args.fold_start:
            try:
                year, month = (int(part) for part in value.split("-", maxsplit=1))
                datetime(year, month, 1)
            except ValueError as exc:
                raise SystemExit(f"Invalid --fold-start {value!r}; expected YYYY-MM") from exc
            parsed.append((year, month))
        folds = tuple(parsed)
    variants: dict[str, dict] = {}
    for minimum_bets in sorted(set(args.min_train_bets)):
        rows = []
        for train_year, train_month in folds:
            fold = _fold(train_year, train_month)
            selected = _eligible_leagues(records, candidate, fold, minimum_bets)
            holdout_records = [record for record in records if record.league in selected]
            holdout = run_daily_portfolio(
                holdout_records, candidate, fold["holdout_start"], fold["holdout_end"],
            )
            rows.append({
                "train_window": f"{fold['train_start'].date()}..{fold['train_end'].date()}",
                "holdout_window": f"{fold['holdout_start'].date()}..{fold['holdout_end'].date()}",
                "eligible_leagues": selected,
                "eligible_league_count": len(selected),
                "bets": holdout["bets"], "staked": holdout["staked"],
                "profit": holdout["profit"], "roi_pct": holdout["roi_pct"],
                "max_drawdown": holdout["max_drawdown"],
            })
        aggregate = _aggregate(rows)
        variants[f"min_train_bets_{minimum_bets}"] = {
            "minimum_train_bets": minimum_bets,
            "holdout_aggregate": aggregate,
            "positive_holdout_folds": aggregate["positive_folds"],
            "folds": rows,
        }
    payload = {
        "method": {
            "candidate": candidate.name,
            "price_timing": "pre-match opening only",
            "selection": "per-league preceding six-month profit > 0 and minimum training bets",
            "holdout": "following three months",
            "fold_starts": [f"{year:04d}-{month:02d}" for year, month in folds],
            "future_results_used_for_selection": False,
            "purpose": "research comparison; no automatic promotion or deployment",
        },
        "variants": variants,
        "guardrail": "Cross-book opening-price research only, not executable China Sporttery SP evidence.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({name: value["holdout_aggregate"] for name, value in variants.items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
