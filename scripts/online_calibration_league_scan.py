from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from online_calibrated_edge_strategy import load_seasons, run_online_calibrated_strategy  # noqa: E402
from walk_forward_residual_strategy import build_feature_history  # noqa: E402


def _parse_columns(raw: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def run_league_scan(
    features: pd.DataFrame,
    *,
    first_month: str,
    last_month: str,
    train_months: int,
    min_lower_ev: float,
    min_odds: float,
    max_odds: float,
    min_bucket_samples: int,
    min_bucket_roi: float,
    min_positive_month_edge: int,
    stake: float,
    bucket_columns: tuple[str, ...],
    min_bets: int,
) -> tuple[dict[str, Any], dict[str, tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]]]:
    rows: list[dict[str, Any]] = []
    artifacts: dict[str, tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]] = {}
    for league in sorted(features["league"].astype(str).unique()):
        summary, days, bets, candidates = run_online_calibrated_strategy(
            features,
            first_month=first_month,
            last_month=last_month,
            train_months=train_months,
            min_lower_ev=min_lower_ev,
            min_odds=min_odds,
            max_odds=max_odds,
            min_bucket_samples=min_bucket_samples,
            min_bucket_roi=min_bucket_roi,
            min_positive_month_edge=min_positive_month_edge,
            stake=stake,
            bucket_columns=bucket_columns,
            league_filter=league,
        )
        overall = summary["overall"]
        rows.append({
            "league": league,
            "bets": int(overall["bets"]),
            "winning_bets": int(overall["winning_bets"]),
            "profit": float(overall["profit"]),
            "roi_pct": float(overall["roi_pct"]),
            "max_drawdown": float(overall["max_drawdown"]),
            "active_months": int(summary["active_months"]),
            "positive_months": int(summary["positive_months"]),
            "negative_months": int(summary["negative_months"]),
            "candidate_count": int(len(candidates)),
            "decision": _decision(summary, min_bets),
        })
        artifacts[league] = (days, bets, candidates)
    rows.sort(key=lambda row: (
        row["decision"] == "RESEARCH_WATCH",
        row["roi_pct"],
        row["profit"],
        row["bets"],
    ), reverse=True)
    report = {
        "method": "online calibration league scan",
        "first_month": first_month,
        "last_month": last_month,
        "config": {
            "train_months": train_months,
            "min_lower_ev": min_lower_ev,
            "min_odds": min_odds,
            "max_odds": max_odds,
            "min_bucket_samples": min_bucket_samples,
            "min_bucket_roi": min_bucket_roi,
            "min_positive_month_edge": min_positive_month_edge,
            "stake": stake,
            "bucket_columns": bucket_columns,
            "min_bets": min_bets,
        },
        "leagues": rows,
        "watchlist": [row for row in rows if row["decision"] == "RESEARCH_WATCH"],
    }
    return report, artifacts


def _decision(summary: dict[str, Any], min_bets: int) -> str:
    overall = summary["overall"]
    if int(overall["bets"]) < min_bets:
        return "TOO_FEW_BETS"
    if float(overall["profit"]) <= 0 or float(overall["roi_pct"]) <= 0:
        return "REJECT_NEGATIVE"
    if int(summary["positive_months"]) <= int(summary["negative_months"]):
        return "REJECT_MONTH_BALANCE"
    drawdown = float(overall["max_drawdown"])
    profit = float(overall["profit"])
    if profit > 0 and drawdown / profit > 2.0:
        return "REJECT_DRAWDOWN"
    return "RESEARCH_WATCH"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--first-month", default="2022-08")
    parser.add_argument("--last-month", default="2026-05")
    parser.add_argument("--seasons", default="2122,2223,2324,2425,2526")
    parser.add_argument("--train-months", type=int, default=18)
    parser.add_argument("--min-lower-ev", type=float, default=-0.02)
    parser.add_argument("--min-odds", type=float, default=1.0)
    parser.add_argument("--max-odds", type=float, default=6.0)
    parser.add_argument("--min-bucket-samples", type=int, default=6)
    parser.add_argument("--min-bucket-roi", type=float, default=0.0)
    parser.add_argument("--min-positive-month-edge", type=int, default=0)
    parser.add_argument("--stake", type=float, default=1.0)
    parser.add_argument("--bucket-columns", default="league,outcome,odds_bucket")
    parser.add_argument("--min-bets", type=int, default=20)
    parser.add_argument("--output-dir", type=Path, default=Path("reports/online_calibration_league_scan"))
    args = parser.parse_args()
    seasons = tuple(item.strip() for item in args.seasons.split(",") if item.strip())
    features = build_feature_history(load_seasons(seasons))
    report, artifacts = run_league_scan(
        features,
        first_month=args.first_month,
        last_month=args.last_month,
        train_months=args.train_months,
        min_lower_ev=args.min_lower_ev,
        min_odds=args.min_odds,
        max_odds=args.max_odds,
        min_bucket_samples=args.min_bucket_samples,
        min_bucket_roi=args.min_bucket_roi,
        min_positive_month_edge=args.min_positive_month_edge,
        stake=args.stake,
        bucket_columns=_parse_columns(args.bucket_columns),
        min_bets=args.min_bets,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(report["leagues"]).to_csv(args.output_dir / "leagues.csv", index=False, encoding="utf-8-sig")
    for league, (days, bets, candidates) in artifacts.items():
        safe = "".join(char if char.isalnum() else "_" for char in league)
        days.to_csv(args.output_dir / f"{safe}_daily.csv", index=False, encoding="utf-8-sig")
        bets.to_csv(args.output_dir / f"{safe}_bets.csv", index=False, encoding="utf-8-sig")
        candidates.to_csv(args.output_dir / f"{safe}_candidates.csv", index=False, encoding="utf-8-sig")
    print(json.dumps({
        "method": report["method"],
        "watchlist": report["watchlist"],
        "league_count": len(report["leagues"]),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
