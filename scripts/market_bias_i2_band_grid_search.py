from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from market_bias_diagnostics import build_market_frame  # noqa: E402
from market_bias_custom_bands import add_i2_draw_band, band_label, i2_draw_band_rule  # noqa: E402
from market_bias_multi_window_optimizer import (  # noqa: E402
    CandidateSpec,
    _evaluate_window,
    _month_windows,
    summarize_candidate_windows,
)
from market_bias_walk_forward import run_walk_forward_frame  # noqa: E402


def generate_bands(min_low: float, max_low: float, min_width: float, max_width: float,
                   step: float) -> list[tuple[float, float]]:
    bands: list[tuple[float, float]] = []
    low = min_low
    while low <= max_low + 1e-9:
        width = min_width
        while width <= max_width + 1e-9:
            high = round(low + width, 2)
            if high > low:
                bands.append((round(low, 2), high))
            width = round(width + step, 10)
        low = round(low + step, 10)
    return bands


def frame_for_band(frame: pd.DataFrame, low: float, high: float) -> pd.DataFrame:
    return add_i2_draw_band(frame, low, high)


def _rule_for_band(low: float, high: float) -> str:
    return i2_draw_band_rule(low, high)


def _parse_rule(raw: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    columns_raw, key_raw = raw.split("=", 1)
    return _parse_rule_tuple(columns_raw), _parse_rule_tuple(key_raw)


def _parse_rule_tuple(raw: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in raw.split("|"))


def evaluate_band(low: float, high: float, source_frames: dict[str, pd.DataFrame], args: argparse.Namespace) -> dict[str, Any]:
    label = band_label(low, high)
    candidate_id = f"market-bias-i2-draw-{low:.2f}-{high:.2f}"
    rule = _rule_for_band(low, high)
    candidate = CandidateSpec(
        candidate_id,
        (rule,),
        args.seasons,
        args.first_month,
        args.last_month,
    )
    rows: list[dict[str, Any]] = []
    for odds_source, source_frame in source_frames.items():
        frame = frame_for_band(source_frame, low, high)
        _, _, unit_bets = run_walk_forward_frame(
            frame,
            args.seasons,
            args.first_month,
            args.last_month,
            [_parse_rule(rule)],
            args.lookback_months,
            args.min_active_months,
            args.selection_min_bets,
            args.selection_min_roi,
            args.max_rules,
            args.daily_limit,
            odds_source,
        )
        for start_month, end_month in _month_windows(args.first_month, args.last_month, args.window_months, args.step_months):
            rows.append(_evaluate_window(unit_bets, candidate, odds_source, start_month, end_month, args))
    summary = summarize_candidate_windows(
        rows,
        min_pass_rate=args.min_pass_rate,
        min_source_pass_rate=args.min_source_pass_rate,
    )
    return {
        "candidate_id": candidate_id,
        "rule": rule,
        "band": label,
        "low": low,
        "high": high,
        **summary,
    }


def run_grid_search(args: argparse.Namespace) -> dict[str, Any]:
    bands = generate_bands(args.min_low, args.max_low, args.min_width, args.max_width, args.step)
    odds_sources = tuple(item.strip() for item in args.odds_sources.split(",") if item.strip())
    source_frames = {odds_source: build_market_frame(args.seasons, odds_source) for odds_source in odds_sources}
    summaries = [evaluate_band(low, high, source_frames, args) for low, high in bands]
    summaries.sort(key=lambda row: (
        row["decision"] == "MULTI_WINDOW_SHADOW_CANDIDATE",
        row["pass_rate"],
        row["source_pass_rate"],
        row["combined_roi_pct"],
        row["total_bets"],
        -abs(float(row["low"]) - 2.8),
    ), reverse=True)
    current = next((row for row in summaries if row["band"] == "[2.80,3.50)"), None)
    return {
        "method": "I2 draw odds-band grid search with multi-window validation",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "config": {
            "seasons": list(args.seasons),
            "first_month": args.first_month,
            "last_month": args.last_month,
            "odds_sources": list(odds_sources),
            "min_low": args.min_low,
            "max_low": args.max_low,
            "min_width": args.min_width,
            "max_width": args.max_width,
            "step": args.step,
            "window_months": args.window_months,
            "step_months": args.step_months,
            "daily_limit": args.daily_limit,
            "max_single_stake": args.max_single_stake,
            "min_pass_rate": args.min_pass_rate,
            "min_source_pass_rate": args.min_source_pass_rate,
        },
        "band_count": len(summaries),
        "current_band": current,
        "top": summaries[: args.top_n],
        "summaries": summaries,
        "next_step": "Prefer bands that beat the current [2.80,3.50) rule on pass rate without sacrificing source diversity.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seasons", default="2122,2223,2324,2425,2526")
    parser.add_argument("--first-month", default="2022-08")
    parser.add_argument("--last-month", default="2026-05")
    parser.add_argument("--odds-sources", default="AVG_OPEN,AVG_CLOSE")
    parser.add_argument("--min-low", type=float, default=2.5)
    parser.add_argument("--max-low", type=float, default=3.0)
    parser.add_argument("--min-width", type=float, default=0.4)
    parser.add_argument("--max-width", type=float, default=0.8)
    parser.add_argument("--step", type=float, default=0.1)
    parser.add_argument("--window-months", type=int, default=12)
    parser.add_argument("--step-months", type=int, default=6)
    parser.add_argument("--lookback-months", type=int, default=12)
    parser.add_argument("--min-active-months", type=int, default=6)
    parser.add_argument("--selection-min-bets", type=int, default=50)
    parser.add_argument("--selection-min-roi", type=float, default=0.02)
    parser.add_argument("--max-rules", type=int, default=1)
    parser.add_argument("--daily-limit", type=float, default=100.0)
    parser.add_argument("--max-single-stake", type=float, default=10.0)
    parser.add_argument("--settlement-delay-days", type=int, default=1)
    parser.add_argument("--stop-after-losing-settlement-days", type=int, default=999)
    parser.add_argument("--cooldown-days", type=int, default=0)
    parser.add_argument("--validation-min-bets", type=int, default=20)
    parser.add_argument("--validation-min-roi-pct", type=float, default=3.0)
    parser.add_argument("--min-positive-month-edge", type=int, default=1)
    parser.add_argument("--max-drawdown-to-profit", type=float, default=1.5)
    parser.add_argument("--min-pass-rate", type=float, default=0.6)
    parser.add_argument("--min-source-pass-rate", type=float, default=0.5)
    parser.add_argument("--top-n", type=int, default=20)
    parser.add_argument("--output-dir", type=Path, default=Path("reports/market_bias_i2_band_grid_search"))
    args = parser.parse_args()
    args.seasons = tuple(item.strip() for item in args.seasons.split(",") if item.strip())
    result = run_grid_search(args)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(result["summaries"]).to_csv(args.output_dir / "bands.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(result["top"]).to_csv(args.output_dir / "top_bands.csv", index=False, encoding="utf-8-sig")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
