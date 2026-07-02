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

from market_bias_robustness_gate import DEFAULT_RULE  # noqa: E402
from market_bias_custom_bands import add_i2_draw_band, i2_draw_band_rule  # noqa: E402
from market_bias_diagnostics import build_market_frame  # noqa: E402
from market_bias_walk_forward import _parse_rule, run_walk_forward, run_walk_forward_frame  # noqa: E402


def _parse_rules(raw_rules: list[str]) -> list[tuple[tuple[str, ...], tuple[str, ...]]]:
    rules = []
    for raw in raw_rules:
        columns_raw, key_raw = raw.split("=", 1)
        rules.append((_parse_rule(columns_raw), _parse_rule(key_raw)))
    return rules


def _max_drawdown(equity: list[float]) -> float:
    peak = 0.0
    worst = 0.0
    for value in equity:
        peak = max(peak, value)
        worst = max(worst, peak - value)
    return round(worst, 2)


def _season(date: str) -> str:
    year = int(date[:4])
    month = int(date[5:7])
    start = year if month >= 7 else year - 1
    return f"{start}-{str(start + 1)[-2:]}"


def _empty_result(config: dict[str, Any]) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    summary = {
        "method": "settlement-aware market-bias portfolio simulation",
        "config": config,
        "overall": {
            "bets": 0,
            "winning_bets": 0,
            "active_bet_days": 0,
            "skipped_cooldown_days": 0,
            "total_staked": 0.0,
            "profit": 0.0,
            "roi_pct": 0.0,
            "ending_equity": 0.0,
            "max_drawdown": 0.0,
        },
        "monthly": [],
        "season_summary": [],
        "warnings": ["no bets selected by upstream walk-forward rule"],
    }
    return summary, pd.DataFrame(), pd.DataFrame()


def simulate_settlement_portfolio(
    bets: pd.DataFrame,
    daily_limit: float = 100.0,
    max_single_stake: float = 10.0,
    settlement_delay_days: int = 1,
    stop_after_losing_settlement_days: int = 999,
    cooldown_days: int = 0,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    config = {
        "daily_limit": daily_limit,
        "max_single_stake": max_single_stake,
        "settlement_delay_days": settlement_delay_days,
        "stop_after_losing_settlement_days": stop_after_losing_settlement_days,
        "cooldown_days": cooldown_days,
        "stake_mode": "split_daily_limit_evenly_across_selected_bets",
        "same_day_results_hidden_until_settlement": True,
    }
    if bets.empty:
        return _empty_result(config)
    frame = bets.copy()
    frame["bet_date"] = pd.to_datetime(frame["date"])
    frame["odds"] = frame["odds"].astype(float)
    frame["won"] = frame["won"].astype(str).str.lower().isin({"true", "1", "yes"})
    frame = frame.sort_values(["bet_date", "odds"], ascending=[True, True]).reset_index(drop=True)
    start = frame["bet_date"].min()
    end = frame["bet_date"].max() + pd.Timedelta(days=settlement_delay_days)
    pending: list[dict[str, Any]] = []
    bet_rows: list[dict[str, Any]] = []
    daily_rows: list[dict[str, Any]] = []
    equity_values: list[float] = []
    equity = 0.0
    consecutive_losing_settlement_days = 0
    cooldown_until: pd.Timestamp | None = None

    for current_date in pd.date_range(start, end, freq="D"):
        date_text = current_date.strftime("%Y-%m-%d")
        settled_today = [item for item in pending if item["settlement_date"] <= current_date]
        pending = [item for item in pending if item["settlement_date"] > current_date]
        settled_profit = round(sum(float(item["profit"]) for item in settled_today), 2)
        if settled_today:
            equity = round(equity + settled_profit, 2)
            if settled_profit < 0:
                consecutive_losing_settlement_days += 1
            elif settled_profit > 0:
                consecutive_losing_settlement_days = 0
            if consecutive_losing_settlement_days >= stop_after_losing_settlement_days:
                cooldown_until = current_date + pd.Timedelta(days=cooldown_days)
                consecutive_losing_settlement_days = 0
        day_candidates = frame[frame["bet_date"] == current_date]
        cooldown_active = bool(cooldown_until is not None and current_date < cooldown_until)
        placed_today = []
        skipped_reason = None
        if cooldown_active and not day_candidates.empty:
            skipped_reason = "cooldown_after_losing_settlement_days"
        elif not day_candidates.empty:
            stake = min(max_single_stake, daily_limit / len(day_candidates))
            used = 0.0
            for _, row in day_candidates.iterrows():
                if used + stake > daily_limit + 1e-9:
                    break
                profit = round(stake * (float(row["odds"]) - 1.0) if bool(row["won"]) else -stake, 2)
                settlement_date = current_date + pd.Timedelta(days=settlement_delay_days)
                record = {
                    "bet_date": date_text,
                    "settlement_date": settlement_date.strftime("%Y-%m-%d"),
                    "league": row["league"],
                    "home_team": row["home_team"],
                    "away_team": row["away_team"],
                    "outcome": row["outcome"],
                    "actual_result": row["actual_result"],
                    "odds": float(row["odds"]),
                    "stake": round(stake, 2),
                    "won": bool(row["won"]),
                    "profit": profit,
                    "rule_label": row.get("rule_label"),
                }
                pending.append({**record, "settlement_date": settlement_date})
                bet_rows.append(record)
                placed_today.append(record)
                used += stake
        equity_values.append(equity)
        daily_rows.append({
            "date": date_text,
            "bets": len(placed_today),
            "staked": round(sum(item["stake"] for item in placed_today), 2),
            "settled_bets": len(settled_today),
            "settled_profit": settled_profit,
            "equity": equity,
            "cooldown_active": cooldown_active,
            "skipped_reason": skipped_reason,
        })

    bet_frame = pd.DataFrame(bet_rows)
    daily_frame = pd.DataFrame(daily_rows)
    total_staked = float(bet_frame["stake"].sum()) if not bet_frame.empty else 0.0
    profit = float(bet_frame["profit"].sum()) if not bet_frame.empty else 0.0
    monthly = []
    if not bet_frame.empty:
        bet_frame["month"] = bet_frame["bet_date"].str.slice(0, 7)
        for month, group in bet_frame.groupby("month"):
            staked = float(group["stake"].sum())
            month_profit = float(group["profit"].sum())
            monthly.append({
                "month": month,
                "bets": int(len(group)),
                "staked": round(staked, 2),
                "profit": round(month_profit, 2),
                "roi_pct": round(month_profit / staked * 100, 2) if staked else 0.0,
            })
        bet_frame["season"] = bet_frame["bet_date"].map(_season)
    season_summary = []
    if not bet_frame.empty:
        for season, group in bet_frame.groupby("season"):
            staked = float(group["stake"].sum())
            season_profit = float(group["profit"].sum())
            season_summary.append({
                "season": season,
                "bets": int(len(group)),
                "staked": round(staked, 2),
                "profit": round(season_profit, 2),
                "roi_pct": round(season_profit / staked * 100, 2) if staked else 0.0,
            })
    summary = {
        "method": "settlement-aware market-bias portfolio simulation",
        "config": config,
        "overall": {
            "bets": int(len(bet_frame)),
            "winning_bets": int(bet_frame["won"].sum()) if not bet_frame.empty else 0,
            "active_bet_days": int((daily_frame["staked"] > 0).sum()) if not daily_frame.empty else 0,
            "skipped_cooldown_days": int((daily_frame["skipped_reason"].notna()).sum()) if not daily_frame.empty else 0,
            "total_staked": round(total_staked, 2),
            "profit": round(profit, 2),
            "roi_pct": round(profit / total_staked * 100, 2) if total_staked else 0.0,
            "ending_equity": round(float(daily_frame["equity"].iloc[-1]), 2) if not daily_frame.empty else 0.0,
            "max_drawdown": _max_drawdown(equity_values),
        },
        "monthly": monthly,
        "positive_months": sum(row["profit"] > 0 for row in monthly),
        "negative_months": sum(row["profit"] < 0 for row in monthly),
        "season_summary": season_summary,
        "positive_seasons": sum(row["profit"] > 0 for row in season_summary),
        "negative_seasons": sum(row["profit"] < 0 for row in season_summary),
        "warnings": [
            "Historical football-data odds are not Chinese official SP; keep official-SP shadow validation separate.",
            "Cooling decisions use only already-settled results, not same-day final scores.",
        ],
    }
    return summary, daily_frame, bet_frame


def run_from_walk_forward(args: argparse.Namespace) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    seasons = tuple(item.strip() for item in args.seasons.split(",") if item.strip())
    i2_draw_band = None
    if getattr(args, "i2_draw_band_low", None) is not None or getattr(args, "i2_draw_band_high", None) is not None:
        if args.i2_draw_band_low is None or args.i2_draw_band_high is None:
            raise SystemExit("--i2-draw-band-low and --i2-draw-band-high must be provided together")
        i2_draw_band = (args.i2_draw_band_low, args.i2_draw_band_high)
    raw_rules = args.rule or ([i2_draw_band_rule(*i2_draw_band)] if i2_draw_band else [DEFAULT_RULE])
    rules = _parse_rules(raw_rules)
    if i2_draw_band:
        frame = add_i2_draw_band(build_market_frame(seasons, args.odds_source), *i2_draw_band)
        wf_summary, _, unit_bets = run_walk_forward_frame(
            frame,
            seasons,
            args.first_month,
            args.last_month,
            rules,
            args.lookback_months,
            args.min_active_months,
            args.min_bets,
            args.min_roi,
            args.max_rules,
            args.daily_limit,
            args.odds_source,
        )
    else:
        wf_summary, _, unit_bets = run_walk_forward(
            seasons,
            args.first_month,
            args.last_month,
            rules,
            args.lookback_months,
            args.min_active_months,
            args.min_bets,
            args.min_roi,
            args.max_rules,
            args.daily_limit,
            args.odds_source,
        )
    summary, daily, bets = simulate_settlement_portfolio(
        unit_bets,
        args.daily_limit,
        args.max_single_stake,
        args.settlement_delay_days,
        args.stop_after_losing_settlement_days,
        args.cooldown_days,
    )
    summary["walk_forward_config"] = wf_summary["config"]
    summary["walk_forward_overall_unit_stake"] = wf_summary["overall"]
    summary["custom_i2_draw_band"] = i2_draw_band
    return summary, daily, bets


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seasons", default="2122,2223,2324,2425,2526")
    parser.add_argument("--first-month", default="2022-08")
    parser.add_argument("--last-month", default="2026-05")
    parser.add_argument("--rule", action="append", default=None)
    parser.add_argument("--odds-source", default="AVG_OPEN")
    parser.add_argument("--lookback-months", type=int, default=12)
    parser.add_argument("--min-active-months", type=int, default=6)
    parser.add_argument("--min-bets", type=int, default=50)
    parser.add_argument("--min-roi", type=float, default=0.02)
    parser.add_argument("--max-rules", type=int, default=3)
    parser.add_argument("--daily-limit", type=float, default=100.0)
    parser.add_argument("--max-single-stake", type=float, default=10.0)
    parser.add_argument("--settlement-delay-days", type=int, default=1)
    parser.add_argument("--stop-after-losing-settlement-days", type=int, default=999)
    parser.add_argument("--cooldown-days", type=int, default=0)
    parser.add_argument("--i2-draw-band-low", type=float)
    parser.add_argument("--i2-draw-band-high", type=float)
    parser.add_argument("--output-dir", type=Path, default=Path("reports/market_bias_portfolio_simulation_i2_draw"))
    args = parser.parse_args()
    summary, daily, bets = run_from_walk_forward(args)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    daily.to_csv(args.output_dir / "daily.csv", index=False, encoding="utf-8-sig")
    bets.to_csv(args.output_dir / "bets.csv", index=False, encoding="utf-8-sig")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
