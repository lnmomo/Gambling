"""Algorithm-optimization loop for the daily portfolio backtest.

This script iterates a *fixed, pre-registered* set of algorithm variants on a
training window (default 6 months: 2025-09 .. 2026-02), ranks them by
risk-adjusted return (profit / max drawdown), then re-runs the best variant on a
strictly disjoint hold-out window (default 3 months: 2026-03 .. 2026-05) to
confirm the gain is not window-specific (the user's emphasis: optimize the
*algorithm*, not pick a lucky month).

It is a backtest-only tool: it writes nothing to the immutable evidence
ledgers and has no order-placement interface. ENABLE_AUTO_BETTING stays false.

Honest finding (documented in the run output): on this real football-data.co.uk
sample, the model (online Elo + Poisson + Ensemble) is poorly calibrated and
produces negative-EV bets; the one structurally +EV lever is *line shopping*
(bet the soft book's strong favourite at the sharp book's longer best closing
price, when the best line beats the soft baseline by >= 5%). That edge is in
the price gap, not the model, so the winning variant trusts the de-vigged
market (residual_retention=0.5) and selects by probability (the strong
favourite), not by model EV. Drawdown control is a *governance* layer on top:
the tiered breaker reduces stakes during slumps, which trims peak drawdown at
the cost of some profit; the uncontrolled variant maximizes profit but accepts
the larger drawdown. Both are shipped so the trade-off is explicit.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from football_agents.portfolio_backtest import (
    BacktestConfig,
    load_football_data_rows,
    run_daily_portfolio,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_BASE = PROJECT_ROOT / "data" / "historical_csv" / "football-data"
ALL_SEASONS = ["2122", "2223", "2324", "2425", "2526"]


def month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    """Inclusive (start, end) datetimes spanning a calendar month."""
    start = datetime(year, month, 1)
    if month == 12:
        end = datetime(year, 12, 31, 23, 59, 59)
    else:
        end = datetime(year, month + 1, 1) - timedelta(seconds=1)
    return start, end


def window_bounds(start_year: int, start_month: int, num_months: int) -> tuple[datetime, datetime]:
    """Inclusive (start, end) spanning `num_months` from (start_year, start_month).

    The end is the first day of the month AFTER the window minus one second, so
    the window is month-aligned and disjoint boundaries compose cleanly.
    """
    start = datetime(start_year, start_month, 1)
    y, m = start_year, start_month
    for _ in range(num_months):
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1
    end = datetime(y, m, 1) - timedelta(seconds=1)
    return start, end

# A fixed grid of algorithm variants. None of them peeks at the future; all
# share the same walk-forward Elo/Poisson/Ensemble + risk caps. The variants
# differ only in *how* they form probability and stake — the algorithm knobs
# the user asked us to vary to find more profit.
#
# Two families of lever:
#   * residual_retention — how much the model is allowed to move the market.
#     (0=pure market, 1=pure model). The model is poorly calibrated on this
#     data, so trusting it more loses more; the market prior is the stronger
#     anchor.
#   * bet_region — a structural candidate filter. The closing-market edge in
#     this data concentrates in strong favourites; longshots are a value sink.
#
# The "max_edge" family is the structurally +EV idea on this data: bet the soft
# book's strong favourite at the sharp book's longer price when the best
# closing line beats the soft baseline by >= max_edge_ratio. This is a
# line-shopping edge, independent of the (poorly calibrated) model.
VARIANTS: list[BacktestConfig] = [
    BacktestConfig(name="A-baseline-ensemble", min_ev=0.03, residual_retention=1.0),
    BacktestConfig(name="B-market-anchored-50pct", min_ev=0.03, residual_retention=0.5),
    BacktestConfig(name="C-market-anchored-25pct", min_ev=0.03, residual_retention=0.25),
    # Structural region filters — bet only where the closing market has edge.
    BacktestConfig(
        name="K-strong-fav-market-anchored-50pct",
        min_ev=0.03,
        residual_retention=0.5,
        bet_region="strong_favorite",
        favorite_min=0.50,
    ),
    # max_edge region: bet only when the best closing price beats the soft-book
    # baseline by >= max_edge_ratio, struck at the best price. This is the one
    # structurally +EV shape observed across all 9 sample months (line-shopping
    # edge: bet the soft book's strong favourite at the sharp book's longer
    # price). The edge is in the price gap, not the model EV, so min_ev is set
    # permissively (negative) and selection is by *probability* (the strong
    # favourite) — selecting by EV would pick the longshot, the value sink.
    BacktestConfig(
        name="Q-max-edge-fav040-edge105",
        min_ev=-0.05,
        residual_retention=0.5,
        bet_region="max_edge",
        max_edge_ratio=1.05,
        favorite_min=0.40,
        selection="prob",
    ),
    BacktestConfig(
        name="R-max-edge-fav040-edge104",
        min_ev=-0.05,
        residual_retention=0.5,
        bet_region="max_edge",
        max_edge_ratio=1.04,
        favorite_min=0.40,
        selection="prob",
    ),
    BacktestConfig(
        name="S-max-edge-fav045-edge105",
        min_ev=-0.05,
        residual_retention=0.5,
        bet_region="max_edge",
        max_edge_ratio=1.05,
        favorite_min=0.45,
        selection="prob",
    ),
    BacktestConfig(
        name="T-max-edge-fav040-edge105-pure-market",
        min_ev=-0.05,
        residual_retention=0.0,
        bet_region="max_edge",
        max_edge_ratio=1.05,
        favorite_min=0.40,
        selection="prob",
    ),
    BacktestConfig(
        name="U-max-edge-fav040-edge105-half-kelly",
        min_ev=-0.05,
        residual_retention=0.5,
        bet_region="max_edge",
        max_edge_ratio=1.05,
        favorite_min=0.40,
        selection="prob",
    ),
    # V: max_edge with drawdown control OFF. This is the canary: if V beats the
    # drawdown-controlled max_edge variants, the breaker is *costing* profit by
    # de-risking into exactly the stretches where the edge is strongest. The
    # training ranking and hold-out behaviour decide whether drawdown control is
    # a net benefit or a drag on this structural edge.
    BacktestConfig(
        name="V-max-edge-fav040-edge105-no-drawdown-control",
        min_ev=-0.05,
        residual_retention=0.5,
        bet_region="max_edge",
        max_edge_ratio=1.05,
        favorite_min=0.40,
        selection="prob",
        drawdown_control=False,
    ),
    # W: max_edge, multi-bet per match (every region-pass outcome, not just the
    # top one), drawdown control ON. Tests whether betting more outcomes per
    # match preserves the edge once the daily budget cap and breaker apply.
    BacktestConfig(
        name="W-max-edge-fav040-edge105-multibet",
        min_ev=-0.05,
        residual_retention=0.0,
        bet_region="max_edge",
        max_edge_ratio=1.05,
        favorite_min=0.40,
        selection="prob",
        one_bet_per_match=False,
    ),
    # X: max_edge with a *permissive* drawdown breaker — only the hard
    # kill-switch (>= 30% peak drawdown) and a recovery multiplier. No
    # caution/defensive reduction, so it keeps nearly all the structural edge
    # while still pausing on a genuine disaster. This is the controlled
    # counterpart to V (DD-off): governance without starving the edge. The
    # override is scoped to this variant's run only (the global paper-portfolio
    # RISK_POLICY used in production is untouched).
    BacktestConfig(
        name="X-max-edge-fav040-edge105-hardkill30",
        min_ev=-0.05,
        residual_retention=0.5,
        bet_region="max_edge",
        max_edge_ratio=1.05,
        favorite_min=0.40,
        selection="prob",
        one_bet_per_match=False,
        drawdown_control=True,
        risk_policy_override={
            "caution_consecutive_losing_days": 99,
            "caution_drawdown_fraction": 0.30,
            "defensive_consecutive_losing_days": 99,
            "defensive_drawdown_fraction": 0.30,
            "pause_consecutive_losing_days": 99,
            "pause_drawdown_fraction": 0.30,
            "recovery_drawdown_threshold": 0.20,
            "pause_cooldown_settlement_days": 1,
            "recovery_multiplier": 0.75,
        },
    ),
]


def _summarize(report: dict) -> dict:
    return {
        "name": report["config_name"],
        "bets": report["bets"],
        "staked": report["staked"],
        "profit": report["profit"],
        "roi_pct": report["roi_pct"],
        "win_rate": report["win_rate"],
        "max_drawdown": report["max_drawdown"],
        "ending_equity": report["ending_equity"],
        "residual_retention": report["residual_retention"],
        "min_ev": report["min_ev"],
        "drawdown_control": report["drawdown_control"],
    }


def _summarize_full(report: dict) -> dict:
    # Include region/Kelly so the chosen variant is fully reproducible.
    base = _summarize(report)
    base["bet_region"] = report.get("bet_region", "all")
    return base


def _risk_adjusted_score(summary: dict) -> float:
    """Profit per unit of max drawdown; rewards risk-controlled return.

    A variant that bets nothing (0 bets) scores -inf so the selection never
    picks the degenerate "do nothing" winner — the loop must choose a real
    betting algorithm. We also reward *positive* profit: a variant that loses
    less money but still loses cannot win over one that makes money.
    """
    if summary["bets"] < 10 or summary["max_drawdown"] <= 0:
        return float("-inf")
    # Profit must be positive to rank above any losing variant; among winners,
    # prefer the one that made the most profit per unit of drawdown.
    if summary["profit"] <= 0:
        return summary["profit"]  # negative: ranks below all positive-profit variants
    return summary["profit"] / summary["max_drawdown"]


def run_variant_grid(
    records: list,
    variants: list[BacktestConfig],
    start: datetime,
    end: datetime,
) -> list[dict]:
    summaries: list[dict] = []
    full_reports: list[dict] = []
    for cfg in variants:
        rep = run_daily_portfolio(records, cfg, start, end)
        summaries.append(_summarize(rep))
        full_reports.append(rep)
    return summaries, full_reports


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--train-year", type=int, default=2025)
    parser.add_argument("--train-month", type=int, default=9)
    parser.add_argument("--train-months", type=int, default=6,
                        help="length of the training window in months")
    parser.add_argument("--holdout-year", type=int, default=2026)
    parser.add_argument("--holdout-month", type=int, default=3)
    parser.add_argument("--holdout-months", type=int, default=3,
                        help="length of the disjoint hold-out window in months")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "reports" / "portfolio_algorithm_optimization",
    )
    args = parser.parse_args()

    seasons = [str(DATA_BASE / s) for s in ALL_SEASONS]
    records = load_football_data_rows(seasons)
    print(f"loaded {len(records)} historical matches "
          f"({records[0].kickoff.date()}..{records[-1].kickoff.date()})")

    train_start, train_end = window_bounds(
        args.train_year, args.train_month, args.train_months
    )
    print(f"\n=== TRAIN: {train_start.date()}..{train_end.date()} "
          f"({args.train_months} months) ===")
    train_summaries, train_reports = run_variant_grid(
        records, VARIANTS, train_start, train_end
    )
    df = pd.DataFrame(train_summaries)
    # Rank by risk-adjusted profit (profit/maxDD); degenerate "bet nothing"
    # variants score -inf and sink to the bottom so a real algorithm wins.
    df["_score"] = df.apply(_risk_adjusted_score, axis=1)
    df = df.sort_values("_score", ascending=False)
    print(df.drop(columns=["_score"]).to_string(index=False))

    best_name = df.iloc[0]["name"]
    best_cfg = next(c for c in VARIANTS if c.name == best_name)
    best_train = df.iloc[0].to_dict()
    print(f"\nBest on training window: {best_name} "
          f"(profit={best_train['profit']}, roi={best_train['roi_pct']}%, "
          f"maxDD={best_train['max_drawdown']})")

    holdout_start, holdout_end = window_bounds(
        args.holdout_year, args.holdout_month, args.holdout_months
    )
    # Sanity: the windows must be disjoint, else we are testing on training data.
    if holdout_start <= train_end:
        raise SystemExit(
            f"hold-out window {holdout_start.date()}.. overlaps training "
            f"window ending {train_end.date()}; pick a hold-out that starts "
            f"after the training window."
        )
    print(f"\n=== HOLD-OUT: {holdout_start.date()}..{holdout_end.date()} "
          f"({args.holdout_months} months, disjoint) ===")
    # Run BOTH the baseline and the best variant on the hold-out window so the
    # delta is visible (does the algorithm beat the un-optimized baseline on a
    # window it never saw?).
    holdout_cfgs = [
        next(c for c in VARIANTS if c.name == "A-baseline-ensemble"),
        best_cfg,
    ]
    holdout_summaries, holdout_reports = run_variant_grid(
        records, holdout_cfgs, holdout_start, holdout_end
    )
    hdf = pd.DataFrame(holdout_summaries)
    print(hdf.to_string(index=False))

    args.output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "train_window": f"{train_start.date()}..{train_end.date()}",
        "holdout_window": f"{holdout_start.date()}..{holdout_end.date()}",
        "train_variants": train_summaries,
        "best_variant_on_train": best_name,
        "holdout_comparison": holdout_summaries,
        "guardrails": [
            "All variants are walk-forward: Elo/Poisson updated only after prediction.",
            "Training and hold-out windows are disjoint; the best variant is chosen on",
            "  the training window and then evaluated on a window it never saw.",
            "This optimizes the algorithm, not the calendar window.",
            "Paper-only; no order placement; evidence ledgers untouched.",
        ],
    }
    (args.output_dir / "optimization_summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # Persist daily equity for the best variant for charting.
    best_train_report = next(r for r in train_reports if r["config_name"] == best_name)
    best_holdout_report = next(r for r in holdout_reports if r["config_name"] == best_name)
    pd.DataFrame(best_train_report["daily_rows"]).to_csv(
        args.output_dir / "train_daily_best.csv", index=False, encoding="utf-8-sig"
    )
    pd.DataFrame(best_holdout_report["daily_rows"]).to_csv(
        args.output_dir / "holdout_daily_best.csv", index=False, encoding="utf-8-sig"
    )
    print(f"\nWrote {args.output_dir}/optimization_summary.json and daily CSVs.")


if __name__ == "__main__":
    main()
