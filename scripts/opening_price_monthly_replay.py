"""Write a fixed, opening-price monthly replay for one registered candidate.

The month is a reporting slice, not a parameter-selection tool. Candidate
definitions remain fixed in portfolio_algorithm_optimization.VARIANTS.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

import pandas as pd

from football_agents.portfolio_backtest import load_football_data_rows, run_daily_portfolio
from scripts.portfolio_algorithm_optimization import ALL_SEASONS, DATA_BASE, VARIANTS, window_bounds


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", default="2022-09", help="calendar month in YYYY-MM format")
    parser.add_argument("--variant", default="X-max-edge-fav040-edge105-hardkill30")
    parser.add_argument("--output-dir", type=Path, default=Path("reports/opening_price_monthly_replay"))
    args = parser.parse_args()
    try:
        year, month = (int(part) for part in args.month.split("-", maxsplit=1))
        start, end = window_bounds(year, month, 1)
    except ValueError as exc:
        raise SystemExit("--month must be YYYY-MM") from exc

    source = next((candidate for candidate in VARIANTS if candidate.name == args.variant), None)
    if source is None:
        raise SystemExit(f"Unknown registered variant: {args.variant}")
    # Unlimited capital does not relax the 100-yuan daily or per-bet caps.
    config = replace(source, starting_bankroll=1_000_000.0, daily_budget=100.0)
    records = load_football_data_rows([str(DATA_BASE / season) for season in ALL_SEASONS])
    report = run_daily_portfolio(records, config, start, end)
    summary = {key: report[key] for key in (
        "config_name", "market_price_timing", "period_start", "period_end", "daily_budget",
        "starting_bankroll", "bets", "staked", "profit", "roi_pct", "win_rate",
        "max_drawdown", "ending_equity", "drawdown_control", "bet_region",
    )}
    payload = {
        "method": {
            "decision_inputs": "walk-forward team history plus opening odds only",
            "same_day_results_hidden_until_allocation": True,
            "capital_model": "unlimited bankroll with a 100-yuan maximum daily exposure",
            "not_executable_china_sporttery_evidence": True,
        },
        "summary": summary,
        "daily": report["daily_rows"],
        "bets_sample": report["bets_sample"],
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    pd.DataFrame(report["daily_rows"]).to_csv(args.output_dir / "daily_equity.csv", index=False, encoding="utf-8-sig")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
