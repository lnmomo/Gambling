"""Cross-league robustness check for fixed opening-price research candidates.

This is deliberately not an optimizer: candidate parameters and holdout folds
are fixed before this script runs. It asks whether a candidate's return is
distributed across leagues or dominated by one source of historical profit.
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
DEFAULT_VARIANTS = (
    "Q-max-edge-fav040-edge105",
    "V-max-edge-fav040-edge105-no-drawdown-control",
    "X-max-edge-fav040-edge105-hardkill30",
)


def _survivor(summary: dict) -> dict:
    requirements = {
        "positive_aggregate_profit": float(summary["profit"]) > 0,
        "positive_folds_at_least_5": int(summary["positive_folds"]) >= 5,
        "holdout_bets_at_least_100": int(summary["bets"]) >= 100,
    }
    return {
        "status": "ROBUST_WITHIN_LEAGUE" if all(requirements.values()) else "NOT_ROBUST_WITHIN_LEAGUE",
        "requirements": requirements,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variants", nargs="+", default=list(DEFAULT_VARIANTS))
    parser.add_argument("--leagues", nargs="+", help="optional football-data league codes")
    parser.add_argument(
        "--output", type=Path,
        default=Path("reports/opening_price_league_robustness_v1/summary.json"),
    )
    args = parser.parse_args()
    by_name = {candidate.name: candidate for candidate in VARIANTS}
    missing = set(args.variants) - set(by_name)
    if missing:
        raise SystemExit(f"Unknown registered variants: {', '.join(sorted(missing))}")
    candidates = [by_name[name] for name in args.variants]
    records = load_football_data_rows([str(DATA_BASE / season) for season in ALL_SEASONS])
    leagues = sorted(set(args.leagues or [record.league for record in records]))
    output: dict[str, dict] = {}
    for league in leagues:
        league_records = [record for record in records if record.league == league]
        if not league_records:
            continue
        candidate_results: dict[str, dict] = {}
        for candidate in candidates:
            folds = []
            for train_year, train_month in FOLD_STARTS:
                fold = _fold(train_year, train_month)
                report = run_daily_portfolio(
                    league_records, candidate, fold["holdout_start"], fold["holdout_end"],
                )
                folds.append({
                    "holdout_window": f"{fold['holdout_start'].date()}..{fold['holdout_end'].date()}",
                    "bets": report["bets"], "staked": report["staked"],
                    "profit": report["profit"], "roi_pct": report["roi_pct"],
                    "max_drawdown": report["max_drawdown"],
                })
            summary = _aggregate(folds)
            candidate_results[candidate.name] = {
                "aggregate": summary,
                "decision": _survivor(summary),
                "folds": folds,
            }
        output[league] = candidate_results
    payload = {
        "method": {
            "price_timing": "pre-match opening only; closing fields are rejected by the backtest",
            "folds": [f"{year:04d}-{month:02d}" for year, month in FOLD_STARTS],
            "selection": "none; candidates were fixed before the league breakdown",
            "purpose": "concentration-risk diagnosis, not automatic strategy selection",
        },
        "variants": [candidate.name for candidate in candidates],
        "leagues": output,
        "guardrail": (
            "These are cross-book opening-price research results and are not executable China Sporttery SP evidence."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        league: {
            name: result["aggregate"]
            for name, result in candidates.items()
        }
        for league, candidates in output.items()
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
