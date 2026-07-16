from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    frac = pos - low
    return ordered[low] * (1 - frac) + ordered[high] * frac


def _max_drawdown(profits: list[float]) -> float:
    equity = peak = worst = 0.0
    for profit in profits:
        equity += profit
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return round(worst, 2)


def _max_negative_streak(monthly: pd.DataFrame) -> int:
    streak = worst = 0
    for profit in monthly["profit"].tolist():
        if float(profit) < 0:
            streak += 1
            worst = max(worst, streak)
        else:
            streak = 0
    return worst


def _bootstrap_months(months: list[dict[str, float]], iterations: int,
                      seed: int) -> dict[str, Any]:
    rng = random.Random(seed)
    if not months:
        return {
            "iterations": iterations,
            "roi_ci_pct": {"p05": 0.0, "p50": 0.0, "p95": 0.0},
            "profit_ci": {"p05": 0.0, "p50": 0.0, "p95": 0.0},
            "probability_roi_positive": 0.0,
            "probability_profit_positive": 0.0,
        }
    roi_values: list[float] = []
    profit_values: list[float] = []
    for _ in range(iterations):
        sample = [rng.choice(months) for _ in months]
        staked = sum(item["staked"] for item in sample)
        profit = sum(item["profit"] for item in sample)
        profit_values.append(profit)
        roi_values.append(profit / staked * 100 if staked else 0.0)
    return {
        "iterations": iterations,
        "roi_ci_pct": {
            "p05": round(_percentile(roi_values, 0.05), 2),
            "p50": round(_percentile(roi_values, 0.50), 2),
            "p95": round(_percentile(roi_values, 0.95), 2),
        },
        "profit_ci": {
            "p05": round(_percentile(profit_values, 0.05), 2),
            "p50": round(_percentile(profit_values, 0.50), 2),
            "p95": round(_percentile(profit_values, 0.95), 2),
        },
        "probability_roi_positive": round(sum(value > 0 for value in roi_values) / len(roi_values), 4),
        "probability_profit_positive": round(sum(value > 0 for value in profit_values) / len(profit_values), 4),
    }


def _sign_flip_test(month_profits: list[float], observed_profit: float,
                    iterations: int, seed: int) -> dict[str, Any]:
    rng = random.Random(seed + 17)
    if not month_profits:
        return {"iterations": iterations, "one_sided_p_value": 1.0}
    simulated: list[float] = []
    for _ in range(iterations):
        simulated.append(sum(profit if rng.random() < 0.5 else -profit for profit in month_profits))
    p_value = sum(value >= observed_profit for value in simulated) / len(simulated)
    return {
        "iterations": iterations,
        "one_sided_p_value": round(p_value, 4),
        "null_profit_ci": {
            "p05": round(_percentile(simulated, 0.05), 2),
            "p50": round(_percentile(simulated, 0.50), 2),
            "p95": round(_percentile(simulated, 0.95), 2),
        },
    }


def _decision(overall: dict[str, Any], bootstrap: dict[str, Any],
              sign_flip: dict[str, Any], min_bets: int, min_months: int) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if overall["bets"] < min_bets:
        reasons.append("bets<minimum")
    if overall["active_months"] < min_months:
        reasons.append("active_months<minimum")
    if overall["roi_pct"] <= 0:
        reasons.append("observed_roi<=0")
    if bootstrap["roi_ci_pct"]["p05"] <= 0:
        reasons.append("bootstrap_roi_p05<=0")
    if bootstrap["probability_roi_positive"] < 0.95:
        reasons.append("bootstrap_positive_probability<0.95")
    if sign_flip["one_sided_p_value"] > 0.05:
        reasons.append("sign_flip_p_value>0.05")
    drawdown_to_profit = overall.get("drawdown_to_profit")
    if drawdown_to_profit is None:
        reasons.append("drawdown_to_profit_unavailable")
    elif drawdown_to_profit > 0.5:
        reasons.append("drawdown_to_profit>0.5")
    if overall["positive_months"] <= overall["negative_months"]:
        reasons.append("positive_months<=negative_months")
    if not reasons:
        return "STATISTICALLY_SUPPORTED_RESEARCH_CANDIDATE", []
    if overall["roi_pct"] > 0 and bootstrap["probability_roi_positive"] >= 0.8:
        return "POSITIVE_BUT_NOT_STATISTICALLY_CONFIRMED", reasons
    return "REJECT_STATISTICALLY_WEAK", reasons


def audit_bets_csv(path: Path | str, iterations: int = 5000, seed: int = 42,
                   min_bets: int = 200, min_months: int = 12) -> dict[str, Any]:
    bets_path = Path(path)
    bets = pd.read_csv(bets_path)
    if bets.empty:
        monthly = pd.DataFrame(columns=["month", "bets", "staked", "profit", "roi_pct"])
    else:
        if "month" not in bets.columns:
            bets["month"] = pd.to_datetime(bets["bet_date"]).dt.to_period("M").astype(str)
        monthly = bets.groupby("month", as_index=False).agg(
            bets=("profit", "size"),
            staked=("stake", "sum"),
            profit=("profit", "sum"),
        )
        monthly["roi_pct"] = monthly.apply(
            lambda row: row["profit"] / row["staked"] * 100 if row["staked"] else 0.0,
            axis=1,
        )
        monthly = monthly.sort_values("month").reset_index(drop=True)

    total_staked = float(monthly["staked"].sum()) if not monthly.empty else 0.0
    total_profit = float(monthly["profit"].sum()) if not monthly.empty else 0.0
    month_profits = [float(value) for value in monthly["profit"].tolist()]
    overall = {
        "bets": int(monthly["bets"].sum()) if not monthly.empty else 0,
        "active_months": int(len(monthly)),
        "total_staked": round(total_staked, 2),
        "profit": round(total_profit, 2),
        "roi_pct": round(total_profit / total_staked * 100, 2) if total_staked else 0.0,
        "positive_months": int((monthly["profit"] > 0).sum()) if not monthly.empty else 0,
        "negative_months": int((monthly["profit"] < 0).sum()) if not monthly.empty else 0,
        "max_negative_month_streak": _max_negative_streak(monthly),
        "max_month_drawdown": _max_drawdown(month_profits),
    }
    overall["drawdown_to_profit"] = round(overall["max_month_drawdown"] / total_profit, 4) if total_profit > 0 else None

    month_records = [
        {"month": str(row["month"]), "staked": float(row["staked"]), "profit": float(row["profit"])}
        for _, row in monthly.iterrows()
    ]
    bootstrap = _bootstrap_months(month_records, iterations, seed)
    sign_flip = _sign_flip_test(month_profits, total_profit, iterations, seed)
    decision, reasons = _decision(overall, bootstrap, sign_flip, min_bets, min_months)

    rules = []
    if not bets.empty and "rule_label" in bets.columns:
        for label, group in bets.groupby("rule_label"):
            staked = float(group["stake"].sum())
            profit = float(group["profit"].sum())
            rules.append({
                "rule_label": str(label),
                "bets": int(len(group)),
                "staked": round(staked, 2),
                "profit": round(profit, 2),
                "roi_pct": round(profit / staked * 100, 2) if staked else 0.0,
                "positive_months": int((group.groupby("month")["profit"].sum() > 0).sum()) if "month" in group else 0,
                "negative_months": int((group.groupby("month")["profit"].sum() < 0).sum()) if "month" in group else 0,
            })
        rules.sort(key=lambda item: (item["profit"], item["bets"]), reverse=True)

    return {
        "method": "monthly block bootstrap and sign-flip strategy audit",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "bets_path": str(bets_path),
        "config": {
            "iterations": iterations,
            "seed": seed,
            "min_bets": min_bets,
            "min_months": min_months,
            "resampling_unit": "active betting month",
        },
        "overall": overall,
        "bootstrap": bootstrap,
        "sign_flip_test": sign_flip,
        "rule_contributions": rules,
        "monthly": [
            {
                "month": str(row["month"]),
                "bets": int(row["bets"]),
                "staked": round(float(row["staked"]), 2),
                "profit": round(float(row["profit"]), 2),
                "roi_pct": round(float(row["roi_pct"]), 2),
            }
            for _, row in monthly.iterrows()
        ],
        "decision": decision,
        "decision_reasons": reasons,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Statistically audit a strategy bets.csv by active month.")
    parser.add_argument("--bets", required=True, type=Path)
    parser.add_argument("--iterations", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--min-bets", type=int, default=200)
    parser.add_argument("--min-months", type=int, default=12)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    report = audit_bets_csv(args.bets, args.iterations, args.seed, args.min_bets, args.min_months)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(report["monthly"]).to_csv(args.output_dir / "monthly.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(report["rule_contributions"]).to_csv(args.output_dir / "rule_contributions.csv", index=False, encoding="utf-8-sig")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
