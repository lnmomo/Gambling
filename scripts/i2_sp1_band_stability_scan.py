from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from market_bias_custom_bands import add_i2_draw_band, i2_draw_band_rule  # noqa: E402
from market_bias_diagnostics import build_market_frame  # noqa: E402
from market_bias_multi_window_optimizer import (  # noqa: E402
    CandidateSpec,
    _evaluate_window,
    _month_windows,
    summarize_candidate_windows,
)
from market_bias_portfolio_simulation import simulate_settlement_portfolio  # noqa: E402
from market_bias_walk_forward import _parse_rule, run_walk_forward_frame  # noqa: E402


SP1_HOME_RULE = "league|outcome|market_prob_bucket=SP1|home|[0.55,1.00]"


@dataclass(frozen=True)
class BandCandidate:
    low: float
    high: float

    @property
    def candidate_id(self) -> str:
        return f"market-bias-i2-draw-{self.low:.2f}-{self.high:.2f}-plus-sp1-home-v1"

    @property
    def rules(self) -> tuple[str, str]:
        return (i2_draw_band_rule(self.low, self.high), SP1_HOME_RULE)


def _parse_raw_rules(raw_rules: tuple[str, ...]) -> list[tuple[tuple[str, ...], tuple[str, ...]]]:
    parsed = []
    for raw in raw_rules:
        columns_raw, key_raw = raw.split("=", 1)
        parsed.append((_parse_rule(columns_raw), _parse_rule(key_raw)))
    return parsed


def _float_grid(raw: str) -> list[float]:
    return [round(float(item.strip()), 4) for item in raw.split(",") if item.strip()]


def make_band_candidates(lows: list[float], highs: list[float], min_width: float = 0.1) -> list[BandCandidate]:
    candidates = []
    for low in lows:
        for high in highs:
            if high - low >= min_width - 1e-9:
                candidates.append(BandCandidate(low, high))
    return candidates


def _portfolio_for_source(frame: pd.DataFrame, band: BandCandidate, source: str,
                          args: argparse.Namespace) -> tuple[dict[str, Any], pd.DataFrame]:
    labeled = add_i2_draw_band(frame, band.low, band.high)
    _, _, unit_bets = run_walk_forward_frame(
        labeled,
        tuple(args.seasons),
        args.first_month,
        args.last_month,
        _parse_raw_rules(band.rules),
        args.lookback_months,
        args.min_active_months,
        args.selection_min_bets,
        args.selection_min_roi,
        args.max_rules,
        args.daily_limit,
        source,
    )
    portfolio, _, placed = simulate_settlement_portfolio(
        unit_bets,
        daily_limit=args.daily_limit,
        max_single_stake=args.max_single_stake,
        settlement_delay_days=args.settlement_delay_days,
        stop_after_losing_settlement_days=args.stop_after_losing_settlement_days,
        cooldown_days=args.cooldown_days,
    )
    return portfolio, placed


def scan_bands(args: argparse.Namespace) -> dict[str, Any]:
    odds_sources = tuple(args.odds_sources)
    bands = make_band_candidates(args.band_lows, args.band_highs, args.min_band_width)
    frames = {source: build_market_frame(tuple(args.seasons), source) for source in odds_sources}
    all_rows: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    portfolio_rows: list[dict[str, Any]] = []
    portfolio_bets: list[pd.DataFrame] = []

    for band in bands:
        candidate = CandidateSpec(
            band.candidate_id,
            band.rules,
            tuple(args.seasons),
            args.first_month,
            args.last_month,
        )
        candidate_rows = []
        combined_portfolio_profit = 0.0
        combined_portfolio_staked = 0.0
        for source, frame in frames.items():
            labeled = add_i2_draw_band(frame, band.low, band.high)
            _, _, unit_bets = run_walk_forward_frame(
                labeled,
                tuple(args.seasons),
                args.first_month,
                args.last_month,
                _parse_raw_rules(band.rules),
                args.lookback_months,
                args.min_active_months,
                args.selection_min_bets,
                args.selection_min_roi,
                args.max_rules,
                args.daily_limit,
                source,
            )
            for start_month, end_month in _month_windows(args.first_month, args.last_month, args.window_months, args.step_months):
                row = _evaluate_window(unit_bets, candidate, source, start_month, end_month, args)
                row["band_low"] = band.low
                row["band_high"] = band.high
                candidate_rows.append(row)
                all_rows.append(row)
            portfolio, _, placed = simulate_settlement_portfolio(
                unit_bets,
                daily_limit=args.daily_limit,
                max_single_stake=args.max_single_stake,
                settlement_delay_days=args.settlement_delay_days,
                stop_after_losing_settlement_days=args.stop_after_losing_settlement_days,
                cooldown_days=args.cooldown_days,
            )
            overall = portfolio["overall"]
            combined_portfolio_profit += float(overall["profit"])
            combined_portfolio_staked += float(overall["total_staked"])
            portfolio_rows.append({
                "candidate_id": band.candidate_id,
                "band_low": band.low,
                "band_high": band.high,
                "odds_source": source,
                "bets": int(overall["bets"]),
                "profit": float(overall["profit"]),
                "roi_pct": float(overall["roi_pct"]),
                "positive_months": int(portfolio.get("positive_months") or 0),
                "negative_months": int(portfolio.get("negative_months") or 0),
            })
            if not placed.empty:
                portfolio_bets.append(placed.assign(candidate_id=band.candidate_id, odds_source=source))
        summary = {
            "candidate_id": band.candidate_id,
            "band_low": band.low,
            "band_high": band.high,
            "rules": list(band.rules),
            **summarize_candidate_windows(
                candidate_rows,
                min_pass_rate=args.min_pass_rate,
                min_source_pass_rate=args.min_source_pass_rate,
                min_active_windows=args.min_active_windows,
            ),
            "combined_portfolio_profit": round(combined_portfolio_profit, 2),
            "combined_portfolio_roi_pct": round(combined_portfolio_profit / combined_portfolio_staked * 100, 2)
            if combined_portfolio_staked else 0.0,
        }
        summaries.append(summary)

    summaries.sort(key=lambda row: (
        row["decision"] == "MULTI_WINDOW_SHADOW_CANDIDATE",
        row["pass_rate"],
        row["active_pass_rate"],
        row["combined_roi_pct"],
        row["combined_portfolio_roi_pct"],
    ), reverse=True)
    return {
        "method": "I2 draw band + SP1 home stability scan",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "config": {
            "seasons": list(args.seasons),
            "first_month": args.first_month,
            "last_month": args.last_month,
            "odds_sources": list(odds_sources),
            "band_lows": args.band_lows,
            "band_highs": args.band_highs,
            "min_band_width": args.min_band_width,
            "sp1_home_rule": SP1_HOME_RULE,
            "validation_min_bets": args.validation_min_bets,
            "validation_min_roi_pct": args.validation_min_roi_pct,
            "min_positive_month_edge": args.min_positive_month_edge,
            "max_drawdown_to_profit": args.max_drawdown_to_profit,
        },
        "candidate_summaries": summaries,
        "rows": all_rows,
        "portfolio_rows": portfolio_rows,
        "portfolio_bets": pd.concat(portfolio_bets, ignore_index=True) if portfolio_bets else pd.DataFrame(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan custom I2 draw odds bands combined with SP1 home.")
    parser.add_argument("--seasons", default="2122,2223,2324,2425,2526")
    parser.add_argument("--first-month", default="2022-08")
    parser.add_argument("--last-month", default="2026-05")
    parser.add_argument("--odds-sources", default="AVG_OPEN,AVG_CLOSE")
    parser.add_argument("--band-lows", default="2.80,2.90,3.00,3.10,3.20")
    parser.add_argument("--band-highs", default="3.20,3.30,3.40,3.50,3.60")
    parser.add_argument("--min-band-width", type=float, default=0.15)
    parser.add_argument("--window-months", type=int, default=12)
    parser.add_argument("--step-months", type=int, default=6)
    parser.add_argument("--lookback-months", type=int, default=12)
    parser.add_argument("--min-active-months", type=int, default=6)
    parser.add_argument("--selection-min-bets", type=int, default=50)
    parser.add_argument("--selection-min-roi", type=float, default=0.02)
    parser.add_argument("--max-rules", type=int, default=3)
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
    parser.add_argument("--min-active-windows", type=int, default=12)
    parser.add_argument("--output-dir", type=Path, default=Path("reports/i2_sp1_band_stability_scan"))
    parsed = parser.parse_args()
    parsed.seasons = tuple(item.strip() for item in parsed.seasons.split(",") if item.strip())
    parsed.odds_sources = tuple(item.strip() for item in parsed.odds_sources.split(",") if item.strip())
    parsed.band_lows = _float_grid(parsed.band_lows)
    parsed.band_highs = _float_grid(parsed.band_highs)

    result = scan_bands(parsed)
    parsed.output_dir.mkdir(parents=True, exist_ok=True)
    portfolio_bets = result.pop("portfolio_bets")
    (parsed.output_dir / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(result["candidate_summaries"]).to_csv(parsed.output_dir / "candidate_summaries.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(result["rows"]).to_csv(parsed.output_dir / "windows.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(result["portfolio_rows"]).to_csv(parsed.output_dir / "portfolio_rows.csv", index=False, encoding="utf-8-sig")
    portfolio_bets.to_csv(parsed.output_dir / "portfolio_bets.csv", index=False, encoding="utf-8-sig")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
