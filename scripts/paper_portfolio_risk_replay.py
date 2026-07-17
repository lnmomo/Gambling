from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, time, timezone
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from football_agents.paper_portfolio import RISK_POLICY, settled_risk_state


def _max_drawdown(profits: list[float]) -> float:
    equity = peak = worst = 0.0
    for profit in profits:
        equity += profit
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return round(worst, 2)


def _simulate(frame: pd.DataFrame, unit_stake: float, daily_budget: float) -> tuple[dict, list[dict]]:
    settled_days: list[dict[str, object]] = []
    last_settled_at: datetime | None = None
    fixed_profits: list[float] = []
    controlled_profits: list[float] = []
    rows: list[dict[str, object]] = []
    for item in frame.itertuples():
        decision_at = datetime.combine(item.date.date(), time.min, tzinfo=timezone.utc)
        state = settled_risk_state(settled_days, decision_at, daily_budget, last_settled_at)
        fixed_profit = round(unit_stake * float(item.unit_profit), 2)
        stake = round(unit_stake * float(state["stake_multiplier"]), 2)
        controlled_profit = round(stake * float(item.unit_profit), 2)
        fixed_profits.append(fixed_profit)
        if stake > 0:
            controlled_profits.append(controlled_profit)
            settled_days.append({
                "date": item.date.date().isoformat(),
                "profit": controlled_profit,
            })
            last_settled_at = datetime.combine(
                item.date.date(), time.max, tzinfo=timezone.utc
            )
        rows.append({
            "date": item.date.date().isoformat(),
            "risk_status": state["status"],
            "stake_multiplier": state["stake_multiplier"],
            "fixed_stake": unit_stake,
            "controlled_stake": stake,
            "unit_profit": float(item.unit_profit),
            "fixed_profit": fixed_profit,
            "controlled_profit": controlled_profit,
            "prior_consecutive_losing_days": state["consecutive_losing_settlement_days"],
            "prior_drawdown": state["current_drawdown"],
        })
    fixed_staked = round(unit_stake * len(fixed_profits), 2)
    controlled_staked = round(sum(float(row["controlled_stake"]) for row in rows), 2)
    fixed_profit = round(sum(fixed_profits), 2)
    controlled_profit = round(sum(controlled_profits), 2)
    return {
        "fixed_stake": {
            "bets": len(fixed_profits),
            "staked": fixed_staked,
            "profit": fixed_profit,
            "roi_pct": round(fixed_profit / fixed_staked * 100, 2) if fixed_staked else 0.0,
            "max_drawdown": _max_drawdown(fixed_profits),
        },
        "dynamic_risk": {
            "bets": sum(float(row["controlled_stake"]) > 0 for row in rows),
            "skipped": sum(float(row["controlled_stake"]) <= 0 for row in rows),
            "staked": controlled_staked,
            "profit": controlled_profit,
            "roi_pct": round(controlled_profit / controlled_staked * 100, 2)
            if controlled_staked else 0.0,
            "max_drawdown": _max_drawdown(controlled_profits),
            "paused_decisions": sum(row["risk_status"] == "PAUSED" for row in rows),
            "reduced_decisions": sum(row["risk_status"] == "REDUCED" for row in rows),
            "recovery_decisions": sum(row["risk_status"] == "RECOVERY" for row in rows),
        },
    }, rows


def run(source: Path, output: Path, unit_stake: float = 10.0, daily_budget: float = 100.0) -> dict:
    frame = pd.read_csv(source)
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["unit_profit"] = pd.to_numeric(frame["unit_profit"], errors="coerce")
    frame = frame.dropna(subset=["date", "unit_profit"]).sort_values("date")
    frame = frame.drop_duplicates(["date"], keep="first").reset_index(drop=True)
    overall, rows = _simulate(frame, unit_stake, daily_budget)
    windows: list[dict[str, object]] = []
    for start in ("2022-08-01", "2023-07-01", "2024-07-01", "2025-07-01"):
        metrics, _ = _simulate(frame[frame["date"] >= start], unit_stake, daily_budget)
        fixed = metrics["fixed_stake"]
        dynamic = metrics["dynamic_risk"]
        windows.append({
            "start": start,
            "fixed_stake": fixed,
            "dynamic_risk": dynamic,
            "profit_retention": round(
                float(dynamic["profit"]) / float(fixed["profit"]), 4
            ) if float(fixed["profit"]) > 0 else None,
            "drawdown_ratio": round(
                float(dynamic["max_drawdown"]) / float(fixed["max_drawdown"]), 4
            ) if float(fixed["max_drawdown"]) > 0 else None,
        })
    promotion_passes = all(
        window["profit_retention"] is not None
        and float(window["profit_retention"]) >= 0.65
        and window["drawdown_ratio"] is not None
        and float(window["drawdown_ratio"]) <= 1.0
        for window in windows
    )
    report = {
        "method": "settlement-aware replay of immutable paper portfolio risk policy",
        "source": str(source),
        "source_rows": len(frame),
        "unit_stake": unit_stake,
        "daily_budget": daily_budget,
        "risk_policy": RISK_POLICY,
        **overall,
        "multi_window": windows,
        "promotion_decision": (
            "PROMOTE_DYNAMIC_RISK_CANDIDATE" if promotion_passes
            else "REJECT_DYNAMIC_RISK_PROMOTION"
        ),
        "guardrails": [
            "Risk state for each date uses only earlier settled days.",
            "The current date result is applied only after its stake is frozen.",
            "This replay evaluates drawdown control, not strategy promotion or official-SP profitability.",
        ],
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    pd.DataFrame(rows).to_csv(output / "daily_replay.csv", index=False, encoding="utf-8-sig")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("reports/feature_enriched_market_anchored_i2_formal_avg_close_v1/selected.csv"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("reports/paper_portfolio_dynamic_risk_replay"),
    )
    parser.add_argument("--unit-stake", type=float, default=10.0)
    parser.add_argument("--daily-budget", type=float, default=100.0)
    args = parser.parse_args()
    print(json.dumps(
        run(args.source, args.output_dir, args.unit_stake, args.daily_budget),
        ensure_ascii=False,
        indent=2,
    ))


if __name__ == "__main__":
    main()
