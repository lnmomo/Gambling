from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def run_window(window: int, args: argparse.Namespace) -> dict:
    output_dir = args.output_dir / f"train{window}"
    command = [
        sys.executable,
        "scripts/cross_league_rule_search.py",
        "--first-month", args.first_month,
        "--last-month", args.last_month,
        "--portfolio-gate", args.portfolio_gate,
        "--cooldown-months", str(args.cooldown_months),
        "--lcb-z", str(args.lcb_z),
        "--training-months", str(window),
        "--structure-modes", args.structure_modes,
        "--outcome-scope", args.outcome_scope,
        "--odds-bucket-scope", args.odds_bucket_scope,
        "--output-dir", str(output_dir),
    ]
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    stability = summary.get("stability_assessment", {})
    latest = stability.get("latest_season") or {}
    return {
        "training_months": window,
        "output_dir": str(output_dir),
        "bets": summary["overall"]["bets"],
        "profit": summary["overall"]["profit"],
        "roi_pct": summary["overall"]["roi_pct"],
        "max_drawdown": summary["overall"]["max_drawdown"],
        "active_months": summary["active_months"],
        "positive_months": summary["positive_months"],
        "negative_months": summary["negative_months"],
        "latest_season": latest.get("season"),
        "latest_profit": latest.get("profit"),
        "verdict": stability.get("verdict"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--first-month", default="2022-08")
    parser.add_argument("--last-month", default="2026-05")
    parser.add_argument("--windows", default="12,18,24,30")
    parser.add_argument("--portfolio-gate", choices=("off", "balanced", "conservative"), default="balanced")
    parser.add_argument("--cooldown-months", type=int, default=3)
    parser.add_argument("--lcb-z", type=float, default=0.0)
    parser.add_argument("--structure-modes", default="any,fav_relation,goal_env")
    parser.add_argument("--outcome-scope", default="draw")
    parser.add_argument("--odds-bucket-scope", default="2.8-3.5")
    parser.add_argument("--output-dir", type=Path, default=Path("reports/training_window_sensitivity"))
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    windows = [int(item.strip()) for item in args.windows.split(",") if item.strip()]
    rows = [run_window(window, args) for window in windows]
    profitable_windows = sum(row["profit"] > 0 for row in rows)
    robust = (
        len(rows) >= 3
        and profitable_windows == len(rows)
        and all(row["bets"] >= 50 for row in rows)
        and all((row["latest_profit"] or 0) >= 0 for row in rows)
    )
    report = {
        "method": "training-window sensitivity for cross-league rule search",
        "robust_across_windows": robust,
        "profitable_windows": profitable_windows,
        "windows_tested": windows,
        "rows": rows,
    }
    (args.output_dir / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
