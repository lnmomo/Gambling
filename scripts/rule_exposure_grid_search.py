from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path
from typing import Any

import pandas as pd

from rule_exposure_control import _max_drawdown, simulate_rule_exposure_control


def _parse_ints(raw: str) -> tuple[int, ...]:
    return tuple(int(item.strip()) for item in raw.split(",") if item.strip())


def _window_rows(bets: pd.DataFrame, first_month: str, last_month: str) -> list[dict[str, Any]]:
    if bets.empty:
        return []
    frame = bets.copy()
    frame["month"] = pd.to_datetime(frame["bet_date"]).dt.to_period("M").astype(str)
    periods = list(pd.period_range(first_month, last_month, freq="M"))
    rows: list[dict[str, Any]] = []
    for start_idx in range(0, len(periods), 6):
        end_idx = start_idx + 11
        if end_idx >= len(periods):
            break
        start = str(periods[start_idx])
        end = str(periods[end_idx])
        window = frame[(frame["month"] >= start) & (frame["month"] <= end)].copy()
        if window.empty:
            rows.append({
                "window_start": start, "window_end": end, "bets": 0, "staked": 0.0,
                "profit": 0.0, "roi_pct": 0.0, "max_drawdown": 0.0,
                "positive_months": 0, "negative_months": 0, "passes_window": False,
            })
            continue
        month_profit = window.groupby("month")["profit"].sum()
        profit = float(window["profit"].sum())
        staked = float(window["stake"].sum())
        drawdown = _max_drawdown(window.sort_values("bet_date")["profit"].astype(float).tolist())
        positive = int((month_profit > 0).sum())
        negative = int((month_profit < 0).sum())
        drawdown_to_profit = drawdown / profit if profit > 0 else None
        passes = (
            len(window) >= 20
            and profit > 0
            and staked > 0
            and profit / staked * 100 >= 3.0
            and positive - negative >= 1
            and drawdown_to_profit is not None
            and drawdown_to_profit <= 1.5
        )
        rows.append({
            "window_start": start,
            "window_end": end,
            "bets": int(len(window)),
            "staked": round(staked, 2),
            "profit": round(profit, 2),
            "roi_pct": round(profit / staked * 100, 2) if staked else 0.0,
            "max_drawdown": drawdown,
            "positive_months": positive,
            "negative_months": negative,
            "passes_window": passes,
        })
    return rows


def _summarize_windows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    active = [row for row in rows if row["bets"] > 0]
    return {
        "window_count": len(rows),
        "passed_windows": sum(row["passes_window"] for row in rows),
        "active_window_count": len(active),
        "active_passed_windows": sum(row["passes_window"] for row in active),
        "active_pass_rate": round(sum(row["passes_window"] for row in active) / len(active), 4) if active else 0.0,
    }


def run_grid(
    unit_bets: pd.DataFrame,
    *,
    candidate_id: str,
    first_month: str,
    last_month: str,
    lookbacks: tuple[int, ...],
    min_settlements: tuple[int, ...],
    cooldowns: tuple[int, ...],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for lookback, minimum, cooldown in itertools.product(lookbacks, min_settlements, cooldowns):
        if minimum > lookback:
            continue
        summary, _, bets = simulate_rule_exposure_control(
            unit_bets,
            candidate_id=candidate_id,
            rule_lookback_settlements=lookback,
            min_rule_settlements=minimum,
            cooldown_days=cooldown,
        )
        windows = _window_rows(bets, first_month, last_month)
        window_summary = _summarize_windows(windows)
        overall = summary["overall"]
        profit = float(overall["profit"])
        drawdown = float(overall["max_drawdown"])
        rows.append({
            "rule_lookback_settlements": lookback,
            "min_rule_settlements": minimum,
            "cooldown_days": cooldown,
            "bets": int(overall["bets"]),
            "profit": profit,
            "roi_pct": float(overall["roi_pct"]),
            "max_drawdown": drawdown,
            "drawdown_to_profit": round(drawdown / profit, 4) if profit > 0 else None,
            "positive_months": int(summary["positive_months"]),
            "negative_months": int(summary["negative_months"]),
            "skipped_by_rule_cooldown": int(overall.get("skipped_by_rule_cooldown") or 0),
            **window_summary,
        })
    rows.sort(key=lambda row: (
        row["active_pass_rate"],
        row["profit"] > 0,
        row["roi_pct"],
        -row["max_drawdown"],
        row["profit"],
    ), reverse=True)
    return {
        "method": "rule exposure control parameter grid",
        "candidate_id": candidate_id,
        "first_month": first_month,
        "last_month": last_month,
        "grid_size": len(rows),
        "rows": rows,
        "best": rows[0] if rows else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--unit-bets", type=Path, required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--first-month", default="2013-04")
    parser.add_argument("--last-month", default="2026-05")
    parser.add_argument("--lookbacks", default="10,20,30")
    parser.add_argument("--min-settlements", default="4,8,12")
    parser.add_argument("--cooldowns", default="14,30,60")
    parser.add_argument("--output-dir", type=Path, default=Path("reports/rule_exposure_grid_search"))
    args = parser.parse_args()
    result = run_grid(
        pd.read_csv(args.unit_bets),
        candidate_id=args.candidate_id,
        first_month=args.first_month,
        last_month=args.last_month,
        lookbacks=_parse_ints(args.lookbacks),
        min_settlements=_parse_ints(args.min_settlements),
        cooldowns=_parse_ints(args.cooldowns),
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(result["rows"]).to_csv(args.output_dir / "grid.csv", index=False, encoding="utf-8-sig")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
