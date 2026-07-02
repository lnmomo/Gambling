from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


def _max_drawdown(profits: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for profit in profits:
        equity += profit
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return round(worst, 2)


def _empty_summary(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "method": "rule-level dynamic exposure control",
        "config": config,
        "overall": {
            "bets": 0,
            "total_staked": 0.0,
            "profit": 0.0,
            "roi_pct": 0.0,
            "max_drawdown": 0.0,
        },
        "active_months": 0,
        "positive_months": 0,
        "negative_months": 0,
        "rule_summary": [],
    }


def simulate_rule_exposure_control(
    unit_bets: pd.DataFrame,
    *,
    candidate_id: str,
    odds_source: str | None = None,
    daily_limit: float = 100.0,
    max_single_stake: float = 10.0,
    settlement_delay_days: int = 1,
    rule_lookback_settlements: int = 20,
    min_rule_settlements: int = 8,
    min_rule_profit: float = 0.0,
    cooldown_days: int = 30,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    config = {
        "candidate_id": candidate_id,
        "odds_source": odds_source,
        "daily_limit": daily_limit,
        "max_single_stake": max_single_stake,
        "settlement_delay_days": settlement_delay_days,
        "rule_lookback_settlements": rule_lookback_settlements,
        "min_rule_settlements": min_rule_settlements,
        "min_rule_profit": min_rule_profit,
        "cooldown_days": cooldown_days,
        "same_day_results_hidden_until_settlement": True,
    }
    frame = unit_bets[unit_bets["candidate_id"] == candidate_id].copy()
    if odds_source is not None:
        frame = frame[frame["odds_source"] == odds_source].copy()
    if frame.empty:
        return _empty_summary(config), pd.DataFrame(), pd.DataFrame()

    frame["bet_date"] = pd.to_datetime(frame["date"])
    frame["odds"] = frame["odds"].astype(float)
    frame["won"] = frame["won"].astype(str).str.lower().isin({"true", "1", "yes"})
    frame = frame.sort_values(["bet_date", "odds"], ascending=[True, True]).reset_index(drop=True)

    pending: list[dict[str, Any]] = []
    rule_history: dict[str, list[float]] = {}
    cooldown_until: dict[str, pd.Timestamp] = {}
    bet_rows: list[dict[str, Any]] = []
    daily_rows: list[dict[str, Any]] = []
    settled_profit_series: list[float] = []

    start = frame["bet_date"].min()
    end = frame["bet_date"].max() + pd.Timedelta(days=settlement_delay_days)
    for current_date in pd.date_range(start, end, freq="D"):
        date_text = current_date.strftime("%Y-%m-%d")
        settled_today = [item for item in pending if item["settlement_date"] <= current_date]
        pending = [item for item in pending if item["settlement_date"] > current_date]
        settled_profit = round(sum(float(item["profit"]) for item in settled_today), 2)
        if settled_today:
            settled_profit_series.append(settled_profit)
        for item in settled_today:
            label = str(item["rule_label"])
            history = rule_history.setdefault(label, [])
            history.append(float(item["profit"]))
            recent = history[-rule_lookback_settlements:]
            if len(recent) >= min_rule_settlements and sum(recent) < min_rule_profit:
                cooldown_until[label] = current_date + pd.Timedelta(days=cooldown_days)

        day = frame[frame["bet_date"] == current_date].copy()
        placed_today = []
        skipped = 0
        if not day.empty:
            allowed_rows = []
            for _, row in day.iterrows():
                label = str(row["rule_label"])
                if cooldown_until.get(label, pd.Timestamp.min) > current_date:
                    skipped += 1
                    continue
                allowed_rows.append(row)
            if allowed_rows:
                stake = min(max_single_stake, daily_limit / len(allowed_rows))
                used = 0.0
                for row in allowed_rows:
                    if used + stake > daily_limit + 1e-9:
                        break
                    profit = round(stake * (float(row["odds"]) - 1.0) if bool(row["won"]) else -stake, 2)
                    settlement_date = current_date + pd.Timedelta(days=settlement_delay_days)
                    record = {
                        "bet_date": date_text,
                        "settlement_date": settlement_date.strftime("%Y-%m-%d"),
                        "candidate_id": candidate_id,
                        "odds_source": row.get("odds_source"),
                        "league": row["league"],
                        "home_team": row["home_team"],
                        "away_team": row["away_team"],
                        "outcome": row["outcome"],
                        "actual_result": row["actual_result"],
                        "odds": float(row["odds"]),
                        "stake": round(stake, 2),
                        "won": bool(row["won"]),
                        "profit": profit,
                        "rule_label": row["rule_label"],
                    }
                    pending.append({**record, "settlement_date": settlement_date})
                    bet_rows.append(record)
                    placed_today.append(record)
                    used += stake
        daily_rows.append({
            "date": date_text,
            "bets": len(placed_today),
            "staked": round(sum(item["stake"] for item in placed_today), 2),
            "settled_profit": settled_profit,
            "skipped_by_rule_cooldown": skipped,
        })

    bets = pd.DataFrame(bet_rows)
    daily = pd.DataFrame(daily_rows)
    if bets.empty:
        return _empty_summary(config), daily, bets

    total_staked = float(bets["stake"].sum())
    profit = float(bets["profit"].sum())
    bets["month"] = bets["bet_date"].str.slice(0, 7)
    monthly = []
    for month, group in bets.groupby("month"):
        month_profit = float(group["profit"].sum())
        monthly.append({
            "month": month,
            "bets": int(len(group)),
            "profit": round(month_profit, 2),
            "staked": round(float(group["stake"].sum()), 2),
        })
    rule_summary = []
    for label, group in bets.groupby("rule_label"):
        staked = float(group["stake"].sum())
        rule_profit = float(group["profit"].sum())
        rule_summary.append({
            "rule_label": str(label),
            "bets": int(len(group)),
            "profit": round(rule_profit, 2),
            "roi_pct": round(rule_profit / staked * 100, 2) if staked else 0.0,
        })
    rule_summary.sort(key=lambda row: (row["profit"], row["bets"]), reverse=True)
    summary = {
        "method": "rule-level dynamic exposure control",
        "config": config,
        "overall": {
            "bets": int(len(bets)),
            "total_staked": round(total_staked, 2),
            "profit": round(profit, 2),
            "roi_pct": round(profit / total_staked * 100, 2) if total_staked else 0.0,
            "max_drawdown": _max_drawdown(settled_profit_series),
            "skipped_by_rule_cooldown": int(daily["skipped_by_rule_cooldown"].sum()) if not daily.empty else 0,
        },
        "active_months": len(monthly),
        "positive_months": sum(row["profit"] > 0 for row in monthly),
        "negative_months": sum(row["profit"] < 0 for row in monthly),
        "monthly": monthly,
        "rule_summary": rule_summary,
    }
    return summary, daily, bets


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--unit-bets", type=Path, required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--odds-source")
    parser.add_argument("--daily-limit", type=float, default=100.0)
    parser.add_argument("--max-single-stake", type=float, default=10.0)
    parser.add_argument("--settlement-delay-days", type=int, default=1)
    parser.add_argument("--rule-lookback-settlements", type=int, default=20)
    parser.add_argument("--min-rule-settlements", type=int, default=8)
    parser.add_argument("--min-rule-profit", type=float, default=0.0)
    parser.add_argument("--cooldown-days", type=int, default=30)
    parser.add_argument("--output-dir", type=Path, default=Path("reports/rule_exposure_control"))
    args = parser.parse_args()
    unit_bets = pd.read_csv(args.unit_bets)
    summary, daily, bets = simulate_rule_exposure_control(
        unit_bets,
        candidate_id=args.candidate_id,
        odds_source=args.odds_source,
        daily_limit=args.daily_limit,
        max_single_stake=args.max_single_stake,
        settlement_delay_days=args.settlement_delay_days,
        rule_lookback_settlements=args.rule_lookback_settlements,
        min_rule_settlements=args.min_rule_settlements,
        min_rule_profit=args.min_rule_profit,
        cooldown_days=args.cooldown_days,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    daily.to_csv(args.output_dir / "daily.csv", index=False, encoding="utf-8-sig")
    bets.to_csv(args.output_dir / "bets.csv", index=False, encoding="utf-8-sig")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
