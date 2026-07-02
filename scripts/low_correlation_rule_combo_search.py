from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path
from typing import Any

import pandas as pd

from rule_exposure_control import _max_drawdown


EVENT_COLUMNS = (
    "date",
    "league",
    "home_team",
    "away_team",
    "outcome",
    "odds_source",
    "rule_label",
)


def _month_windows(first_month: str, last_month: str, window_months: int, step_months: int) -> list[tuple[str, str]]:
    periods = list(pd.period_range(first_month, last_month, freq="M"))
    windows: list[tuple[str, str]] = []
    for start_idx in range(0, len(periods), step_months):
        end_idx = start_idx + window_months - 1
        if end_idx >= len(periods):
            break
        windows.append((str(periods[start_idx]), str(periods[end_idx])))
    return windows


def load_unit_bets(paths: list[Path]) -> pd.DataFrame:
    frames = [pd.read_csv(path) for path in paths]
    if not frames:
        return pd.DataFrame()
    frame = pd.concat(frames, ignore_index=True)
    missing = [column for column in EVENT_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"unit bets missing required columns: {missing}")
    if "stake" not in frame.columns:
        frame["stake"] = 1.0
    if "profit" not in frame.columns:
        raise ValueError("unit bets missing required column: profit")
    frame["date"] = pd.to_datetime(frame["date"]).dt.date.astype(str)
    frame["month"] = pd.to_datetime(frame["date"]).dt.to_period("M").astype(str)
    frame["rule_key"] = frame["odds_source"].astype(str) + "::" + frame["rule_label"].astype(str)
    return frame.drop_duplicates(list(EVENT_COLUMNS)).reset_index(drop=True)


def _candidate_rules(frame: pd.DataFrame, min_bets: int, min_roi_pct: float) -> list[str]:
    rows: list[dict[str, Any]] = []
    for rule_key, group in frame.groupby("rule_key"):
        staked = float(group["stake"].sum())
        profit = float(group["profit"].sum())
        roi = profit / staked * 100 if staked else 0.0
        if len(group) >= min_bets and roi >= min_roi_pct and profit > 0:
            rows.append({"rule_key": str(rule_key), "profit": profit, "roi": roi, "bets": len(group)})
    rows.sort(key=lambda row: (row["roi"], row["profit"], row["bets"]), reverse=True)
    return [row["rule_key"] for row in rows]


def _profit_matrix(frame: pd.DataFrame, rules: list[str]) -> pd.DataFrame:
    selected = frame[frame["rule_key"].isin(rules)]
    matrix = selected.pivot_table(index="month", columns="rule_key", values="profit", aggfunc="sum", fill_value=0.0)
    return matrix.reindex(columns=rules, fill_value=0.0)


def _max_pairwise_correlation(matrix: pd.DataFrame, rules: tuple[str, ...]) -> float:
    if len(rules) < 2:
        return 0.0
    subset = matrix.loc[:, list(rules)]
    corr = subset.corr().fillna(0.0).abs()
    values = []
    for left, right in itertools.combinations(rules, 2):
        values.append(float(corr.loc[left, right]))
    return max(values) if values else 0.0


def _combo_bets(frame: pd.DataFrame, rules: tuple[str, ...]) -> pd.DataFrame:
    selected = frame[frame["rule_key"].isin(rules)].copy()
    if selected.empty:
        return selected
    event_key = ["date", "league", "home_team", "away_team", "outcome", "odds_source"]
    selected = selected.sort_values(["date", "rule_key"]).drop_duplicates(event_key)
    selected["combo_rules"] = " + ".join(rules)
    return selected.sort_values("date").reset_index(drop=True)


def _evaluate_windows(
    bets: pd.DataFrame,
    *,
    first_month: str,
    last_month: str,
    window_months: int,
    step_months: int,
    min_window_bets: int,
    min_window_roi_pct: float,
    min_positive_month_edge: int,
    max_drawdown_to_profit: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for start, end in _month_windows(first_month, last_month, window_months, step_months):
        window = bets[(bets["month"] >= start) & (bets["month"] <= end)].copy()
        if window.empty:
            rows.append({
                "window_start": start,
                "window_end": end,
                "bets": 0,
                "staked": 0.0,
                "profit": 0.0,
                "roi_pct": 0.0,
                "max_drawdown": 0.0,
                "positive_months": 0,
                "negative_months": 0,
                "passes_window": False,
            })
            continue
        staked = float(window["stake"].sum())
        profit = float(window["profit"].sum())
        month_profit = window.groupby("month")["profit"].sum()
        positive = int((month_profit > 0).sum())
        negative = int((month_profit < 0).sum())
        drawdown = _max_drawdown(window.sort_values("date")["profit"].astype(float).tolist())
        drawdown_to_profit = drawdown / profit if profit > 0 else None
        passes = (
            len(window) >= min_window_bets
            and profit > 0
            and staked > 0
            and profit / staked * 100 >= min_window_roi_pct
            and positive - negative >= min_positive_month_edge
            and drawdown_to_profit is not None
            and drawdown_to_profit <= max_drawdown_to_profit
        )
        rows.append({
            "window_start": start,
            "window_end": end,
            "bets": int(len(window)),
            "staked": round(staked, 2),
            "profit": round(profit, 2),
            "roi_pct": round(profit / staked * 100, 2) if staked else 0.0,
            "max_drawdown": round(drawdown, 2),
            "positive_months": positive,
            "negative_months": negative,
            "passes_window": passes,
        })
    return rows


def _summarize_combo(
    bets: pd.DataFrame,
    windows: list[dict[str, Any]],
    rules: tuple[str, ...],
    max_correlation: float,
) -> dict[str, Any]:
    active = [row for row in windows if row["bets"] > 0]
    staked = float(bets["stake"].sum()) if not bets.empty else 0.0
    profit = float(bets["profit"].sum()) if not bets.empty else 0.0
    month_profit = bets.groupby("month")["profit"].sum() if not bets.empty else pd.Series(dtype=float)
    return {
        "rules": list(rules),
        "rule_count": len(rules),
        "max_pairwise_monthly_profit_corr": round(max_correlation, 4),
        "bets": int(len(bets)),
        "staked": round(staked, 2),
        "profit": round(profit, 2),
        "roi_pct": round(profit / staked * 100, 2) if staked else 0.0,
        "positive_months": int((month_profit > 0).sum()),
        "negative_months": int((month_profit < 0).sum()),
        "window_count": len(windows),
        "passed_windows": int(sum(row["passes_window"] for row in windows)),
        "active_window_count": len(active),
        "active_passed_windows": int(sum(row["passes_window"] for row in active)),
        "active_pass_rate": round(sum(row["passes_window"] for row in active) / len(active), 4) if active else 0.0,
    }


def run_low_correlation_search(
    unit_bets: pd.DataFrame,
    *,
    first_month: str,
    last_month: str,
    combo_size: int,
    max_rules: int,
    min_rule_bets: int,
    min_rule_roi_pct: float,
    max_pairwise_corr: float,
    window_months: int,
    step_months: int,
    min_window_bets: int,
    min_window_roi_pct: float,
    min_positive_month_edge: int,
    max_drawdown_to_profit: float,
) -> dict[str, Any]:
    rules = _candidate_rules(unit_bets, min_rule_bets, min_rule_roi_pct)[:max_rules]
    matrix = _profit_matrix(unit_bets, rules)
    rows: list[dict[str, Any]] = []
    windows_by_combo: dict[str, list[dict[str, Any]]] = {}
    for combo in itertools.combinations(rules, combo_size):
        corr = _max_pairwise_correlation(matrix, combo)
        if corr > max_pairwise_corr:
            continue
        bets = _combo_bets(unit_bets, combo)
        windows = _evaluate_windows(
            bets,
            first_month=first_month,
            last_month=last_month,
            window_months=window_months,
            step_months=step_months,
            min_window_bets=min_window_bets,
            min_window_roi_pct=min_window_roi_pct,
            min_positive_month_edge=min_positive_month_edge,
            max_drawdown_to_profit=max_drawdown_to_profit,
        )
        row = _summarize_combo(bets, windows, combo, corr)
        rows.append(row)
        windows_by_combo[" || ".join(combo)] = windows
    rows.sort(key=lambda row: (
        row["active_pass_rate"],
        row["active_passed_windows"],
        row["profit"] > 0,
        row["roi_pct"],
        row["profit"],
        -row["max_pairwise_monthly_profit_corr"],
    ), reverse=True)
    return {
        "method": "low-correlation rule combination search",
        "first_month": first_month,
        "last_month": last_month,
        "candidate_rule_count": len(rules),
        "combo_size": combo_size,
        "max_pairwise_corr": max_pairwise_corr,
        "rows": rows,
        "best": rows[0] if rows else None,
        "windows_by_combo": windows_by_combo,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--unit-bets", type=Path, action="append", required=True)
    parser.add_argument("--first-month", default="2013-04")
    parser.add_argument("--last-month", default="2026-05")
    parser.add_argument("--combo-size", type=int, default=3)
    parser.add_argument("--max-rules", type=int, default=20)
    parser.add_argument("--min-rule-bets", type=int, default=20)
    parser.add_argument("--min-rule-roi-pct", type=float, default=1.0)
    parser.add_argument("--max-pairwise-corr", type=float, default=0.35)
    parser.add_argument("--window-months", type=int, default=12)
    parser.add_argument("--step-months", type=int, default=6)
    parser.add_argument("--min-window-bets", type=int, default=20)
    parser.add_argument("--min-window-roi-pct", type=float, default=3.0)
    parser.add_argument("--min-positive-month-edge", type=int, default=1)
    parser.add_argument("--max-drawdown-to-profit", type=float, default=1.5)
    parser.add_argument("--output-dir", type=Path, default=Path("reports/low_correlation_rule_combo_search"))
    args = parser.parse_args()

    result = run_low_correlation_search(
        load_unit_bets(args.unit_bets),
        first_month=args.first_month,
        last_month=args.last_month,
        combo_size=args.combo_size,
        max_rules=args.max_rules,
        min_rule_bets=args.min_rule_bets,
        min_rule_roi_pct=args.min_rule_roi_pct,
        max_pairwise_corr=args.max_pairwise_corr,
        window_months=args.window_months,
        step_months=args.step_months,
        min_window_bets=args.min_window_bets,
        min_window_roi_pct=args.min_window_roi_pct,
        min_positive_month_edge=args.min_positive_month_edge,
        max_drawdown_to_profit=args.max_drawdown_to_profit,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    windows_by_combo = result.pop("windows_by_combo")
    (args.output_dir / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(result["rows"]).to_csv(args.output_dir / "combos.csv", index=False, encoding="utf-8-sig")
    window_rows = []
    for combo_id, rows in windows_by_combo.items():
        for row in rows:
            window_rows.append({"combo_id": combo_id, **row})
    pd.DataFrame(window_rows).to_csv(args.output_dir / "windows.csv", index=False, encoding="utf-8-sig")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
