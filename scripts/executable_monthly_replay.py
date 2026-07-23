"""Replay a pre-declared calendar month under the executable-price rules."""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path

from football_agents.portfolio_backtest import load_football_data_rows, run_daily_portfolio
from scripts.executable_pinnacle_rolling_validation import CANDIDATES
from scripts.portfolio_algorithm_optimization import ALL_SEASONS, DATA_BASE, PROJECT_ROOT, month_bounds


def _month(value: str) -> tuple[int, int]:
    try:
        year, month = (int(part) for part in value.split("-", maxsplit=1))
        datetime(year, month, 1)
        return year, month
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected YYYY-MM") from exc


def main() -> None:
    parser = argparse.ArgumentParser()
    # First fixed holdout month: it was selected before its result is read,
    # rather than after searching for a profitable month.
    parser.add_argument("--month", type=_month, default=(2022, 9))
    parser.add_argument(
        "--price-source", choices=("pinnacle_opening", "bet365_opening"),
        default="pinnacle_opening",
    )
    parser.add_argument("--candidate-index", type=int, default=1)
    parser.add_argument("--daily-budget", type=float, default=100.0)
    parser.add_argument(
        "--starting-bankroll", type=float, default=1_000_000.0,
        help="Notional unconstrained capital; daily-budget remains the hard exposure cap.",
    )
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if not 0 <= args.candidate_index < len(CANDIDATES):
        raise SystemExit(f"candidate index must be 0..{len(CANDIDATES) - 1}")

    source_label = "pinnacle" if args.price_source == "pinnacle_opening" else "bet365"
    loader_source = source_label
    base = CANDIDATES[args.candidate_index]
    from dataclasses import replace
    candidate = replace(
        base,
        name=base.name.replace("pinnacle", source_label),
        execution_price_source=args.price_source,
        daily_budget=args.daily_budget,
        starting_bankroll=args.starting_bankroll,
    )
    start, end = month_bounds(*args.month)
    records = load_football_data_rows(
        [str(DATA_BASE / season) for season in ALL_SEASONS],
        primary_price_source=loader_source,
    )
    report = run_daily_portfolio(records, candidate, start, end)
    output_dir = args.output_dir or (
        PROJECT_ROOT / "reports" / f"executable_monthly_replay_{args.month[0]}_{args.month[1]:02d}_{source_label}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = {key: value for key, value in report.items() if key not in {"daily_rows", "bets_sample"}}
    summary["method"] = {
        "predeclared_month": f"{args.month[0]}-{args.month[1]:02d}",
        "price_source": args.price_source,
        "decision_timing": "opening",
        "same_day_result_rule": "all decisions freeze before any result on that date is applied",
        "daily_budget_limit": args.daily_budget,
        "notional_starting_bankroll": args.starting_bankroll,
        "purpose": "research replay only; not a promotion result",
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if report["daily_rows"]:
        with (output_dir / "daily_equity.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=report["daily_rows"][0].keys())
            writer.writeheader()
            writer.writerows(report["daily_rows"])
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Wrote {output_dir}")


if __name__ == "__main__":
    main()
