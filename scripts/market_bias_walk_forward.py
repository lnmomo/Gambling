from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from fixed_sp2_edge_strategy import _stability_assessment  # noqa: E402
from market_bias_diagnostics import ODDS_SOURCE_COLUMNS, build_market_frame  # noqa: E402
from walk_forward_residual_strategy import metrics  # noqa: E402


def _parse_rule(raw: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in raw.split("|"))


def apply_rule(frame: pd.DataFrame, columns: tuple[str, ...], key: tuple[str, ...]) -> pd.DataFrame:
    selected = frame
    for column, value in zip(columns, key):
        selected = selected[selected[column].astype(str) == value]
    return selected


def monthly_rule_results(history_frame: pd.DataFrame, rules: list[tuple[tuple[str, ...], tuple[str, ...]]]) -> dict[str, dict]:
    results = {}
    for columns, key in rules:
        selected = apply_rule(history_frame, columns, key)
        label = "|".join(columns) + "=" + "|".join(key)
        if selected.empty:
            results[label] = {"bets": 0, "profit": 0.0, "total_staked": 0.0}
            continue
        results[label] = {
            "bets": int(len(selected)),
            "profit": round(float(selected["unit_profit"].sum()), 2),
            "total_staked": float(len(selected)),
        }
    return results


def select_market_rules(history: list[dict], min_active_months: int, min_bets: int,
                        min_roi: float, max_rules: int) -> tuple[list[str], dict]:
    recent_active_months = min(3, max(1, min_active_months))
    min_recent_roi = 0.0
    lcb_z = 0.50
    labels = sorted({label for row in history for label in row["rule_results"]})
    rows = []
    for label in labels:
        sample = [row["rule_results"][label] for row in history if row["rule_results"].get(label, {}).get("bets", 0) > 0]
        if len(sample) < min_active_months:
            continue
        bets = sum(item["bets"] for item in sample)
        staked = sum(item["total_staked"] for item in sample)
        profit = sum(item["profit"] for item in sample)
        positive = sum(item["profit"] > 0 for item in sample)
        negative = sum(item["profit"] < 0 for item in sample)
        monthly_rois = [
            item["profit"] / item["total_staked"]
            for item in sample
            if item["total_staked"] > 0
        ]
        if bets < min_bets or staked <= 0:
            continue
        roi = profit / staked
        if profit <= 0 or roi < min_roi or positive <= negative:
            continue
        recent_sample = sample[-recent_active_months:]
        recent_bets = sum(item["bets"] for item in recent_sample)
        recent_staked = sum(item["total_staked"] for item in recent_sample)
        recent_profit = sum(item["profit"] for item in recent_sample)
        recent_positive = sum(item["profit"] > 0 for item in recent_sample)
        recent_negative = sum(item["profit"] < 0 for item in recent_sample)
        recent_roi = recent_profit / recent_staked if recent_staked else -1.0
        roi_std = float(pd.Series(monthly_rois).std(ddof=0)) if monthly_rois else 999.0
        edge_lcb = roi - lcb_z * roi_std
        if recent_bets < max(5, min_bets // 4) or recent_roi < min_recent_roi or recent_positive < recent_negative:
            continue
        if edge_lcb <= 0:
            continue
        rows.append({
            "label": label,
            "bets": bets,
            "profit": round(profit, 2),
            "roi": round(roi, 4),
            "edge_lcb": round(edge_lcb, 4),
            "monthly_roi_std": round(roi_std, 4),
            "recent_bets": recent_bets,
            "recent_profit": round(recent_profit, 2),
            "recent_roi": round(recent_roi, 4),
            "positive_months": positive,
            "negative_months": negative,
            "recent_positive_months": recent_positive,
            "recent_negative_months": recent_negative,
            "active_months": len(sample),
            "score": (positive - negative) * 2 + edge_lcb * 20 + recent_roi * 8 + profit / max(bets, 1),
        })
    rows.sort(key=lambda row: (row["score"], row["positive_months"] - row["negative_months"], row["profit"]), reverse=True)
    selected = rows[:max_rules]
    return [row["label"] for row in selected], {
        "eligible_rules": len(rows),
        "selected": selected,
        "stability_filters": {
            "recent_active_months": recent_active_months,
            "min_recent_roi": min_recent_roi,
            "lcb_z": lcb_z,
            "edge_lcb_must_be_positive": True,
        },
    }


def simulate_month(frame: pd.DataFrame, selected_labels: list[str], rule_lookup: dict[str, tuple[tuple[str, ...], tuple[str, ...]]],
                   daily_limit: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    if frame.empty or not selected_labels:
        days = pd.DataFrame([
            {"date": date.strftime("%Y-%m-%d"), "bets": 0, "staked": 0.0, "profit": 0.0}
            for date in pd.date_range(pd.to_datetime(frame["date"]).min(), pd.to_datetime(frame["date"]).max(), freq="D")
        ]) if not frame.empty else pd.DataFrame(columns=["date", "bets", "staked", "profit"])
        return days, pd.DataFrame()
    selections = []
    for label in selected_labels:
        columns, key = rule_lookup[label]
        selected = apply_rule(frame, columns, key).copy()
        if not selected.empty:
            selected["rule_label"] = label
            selections.append(selected)
    if not selections:
        return simulate_month(frame, [], rule_lookup, daily_limit)
    selected = pd.concat(selections, ignore_index=True)
    selected["bet_key"] = selected["date"] + "|" + selected["home_team"] + "|" + selected["away_team"] + "|" + selected["outcome"]
    selected = selected.sort_values(["market_probability", "unit_profit"], ascending=[False, False]).drop_duplicates("bet_key")
    bets = []
    days = []
    for date, day in selected.groupby("date"):
        used = 0.0
        profit = 0.0
        count = 0
        for _, row in day.sort_values("market_probability", ascending=False).iterrows():
            if used >= daily_limit - 0.01:
                break
            stake = min(1.0, daily_limit - used)
            bet_profit = float(row["unit_profit"]) * stake
            used += stake
            profit += bet_profit
            count += 1
            bets.append({
                "date": date,
                "league": row["league"],
                "home_team": row["home_team"],
                "away_team": row["away_team"],
                "outcome": row["outcome"],
                "actual_result": row["actual_result"],
                "odds": row["odds"],
                "odds_bucket": row["odds_bucket"],
                "market_prob_bucket": row["market_prob_bucket"],
                "favorite_relation": row["favorite_relation"],
                "stake": stake,
                "won": bool(row["won"]),
                "profit": round(bet_profit, 2),
                "rule_label": row["rule_label"],
            })
        days.append({"date": date, "bets": count, "staked": round(used, 2), "profit": round(profit, 2)})
    return pd.DataFrame(days), pd.DataFrame(bets)


def run_walk_forward(seasons: tuple[str, ...], first_month: str, last_month: str,
                     rules: list[tuple[tuple[str, ...], tuple[str, ...]]],
                     lookback_months: int, min_active_months: int, min_bets: int,
                     min_roi: float, max_rules: int, daily_limit: float,
                     odds_source: str = "B365_OPEN") -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    frame = build_market_frame(seasons, odds_source)
    return run_walk_forward_frame(
        frame,
        seasons,
        first_month,
        last_month,
        rules,
        lookback_months,
        min_active_months,
        min_bets,
        min_roi,
        max_rules,
        daily_limit,
        odds_source,
    )


def run_walk_forward_frame(frame: pd.DataFrame, seasons: tuple[str, ...], first_month: str, last_month: str,
                           rules: list[tuple[tuple[str, ...], tuple[str, ...]]],
                           lookback_months: int, min_active_months: int, min_bets: int,
                           min_roi: float, max_rules: int, daily_limit: float,
                           odds_source: str = "B365_OPEN") -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    rule_lookup = {"|".join(columns) + "=" + "|".join(key): (columns, key) for columns, key in rules}
    history: list[dict] = []
    monthly = []
    all_days = []
    all_bets = []
    for period in pd.period_range(first_month, last_month, freq="M"):
        month = str(period)
        current = frame[frame["month"] == month]
        recent_history = history[-lookback_months:]
        selected_labels, selection = select_market_rules(recent_history, min_active_months, min_bets, min_roi, max_rules)
        days, bets = simulate_month(current, selected_labels, rule_lookup, daily_limit)
        result = metrics(days, bets)
        monthly.append({"month": month, "selection": selection, "decision": "INVEST" if selected_labels else "ABSTAIN", **result})
        history_frame = current
        history.append({"month": month, "rule_results": monthly_rule_results(history_frame, rules)})
        if not days.empty:
            all_days.append(days.assign(month=month))
        if not bets.empty:
            all_bets.append(bets.assign(month=month))
    days = pd.concat(all_days, ignore_index=True) if all_days else pd.DataFrame(columns=["date", "bets", "staked", "profit", "month"])
    bets = pd.concat(all_bets, ignore_index=True) if all_bets else pd.DataFrame()
    overall = metrics(days, bets)
    active = [row for row in monthly if row["bets"] > 0]
    assessment_rows = [{"month": row["month"], "bets": row["bets"], "profit": row["profit"], "roi_pct": row["roi_pct"], "staked": row["total_staked"]} for row in active]
    summary = {
        "method": "market-bias no-lookahead walk-forward",
        "seasons": seasons,
        "first_month": first_month,
        "last_month": last_month,
        "same_day_results_hidden_until_settlement": True,
        "config": {
            "odds_source": odds_source,
            "lookback_months": lookback_months,
            "min_active_months": min_active_months,
            "min_bets": min_bets,
            "min_roi": min_roi,
            "max_rules": max_rules,
            "daily_limit": daily_limit,
            "rules": list(rule_lookup),
        },
        "overall": overall,
        "active_months": len(active),
        "positive_months": sum(row["profit"] > 0 for row in active),
        "negative_months": sum(row["profit"] < 0 for row in active),
        "stability_assessment": _stability_assessment(overall, assessment_rows),
        "monthly": monthly,
    }
    return summary, days, bets


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seasons", default="2122,2223,2324,2425,2526")
    parser.add_argument("--odds-source", choices=tuple(ODDS_SOURCE_COLUMNS), default="B365_OPEN")
    parser.add_argument("--first-month", default="2022-08")
    parser.add_argument("--last-month", default="2026-05")
    parser.add_argument("--rule", action="append", required=True, help="Format: col1|col2=value1|value2")
    parser.add_argument("--lookback-months", type=int, default=12)
    parser.add_argument("--min-active-months", type=int, default=6)
    parser.add_argument("--min-bets", type=int, default=50)
    parser.add_argument("--min-roi", type=float, default=0.02)
    parser.add_argument("--max-rules", type=int, default=3)
    parser.add_argument("--daily-limit", type=float, default=100.0)
    parser.add_argument("--output-dir", type=Path, default=Path("reports/market_bias_walk_forward"))
    args = parser.parse_args()
    seasons = tuple(item.strip() for item in args.seasons.split(",") if item.strip())
    rules = []
    for raw in args.rule:
        columns_raw, key_raw = raw.split("=", 1)
        rules.append((_parse_rule(columns_raw), _parse_rule(key_raw)))
    summary, days, bets = run_walk_forward(
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
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    days.to_csv(args.output_dir / "daily.csv", index=False, encoding="utf-8-sig")
    bets.to_csv(args.output_dir / "bets.csv", index=False, encoding="utf-8-sig")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
