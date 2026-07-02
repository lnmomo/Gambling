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

from market_bias_diagnostics import build_market_frame, run_diagnostics  # noqa: E402


def _parse_rule(rule: str) -> tuple[list[str], list[str]]:
    columns, key = rule.split("=", 1)
    return columns.split("|"), key.split("|")


def _filter_rule(frame: pd.DataFrame, rule: str) -> pd.DataFrame:
    columns, values = _parse_rule(rule)
    if len(columns) != len(values):
        return frame.iloc[0:0].copy()
    mask = pd.Series(True, index=frame.index)
    for column, value in zip(columns, values):
        if column not in frame.columns:
            return frame.iloc[0:0].copy()
        mask &= frame[column].astype(str) == value
    return frame[mask].copy()


def _metrics(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {
            "bets": 0,
            "profit": 0.0,
            "roi_pct": 0.0,
            "positive_months": 0,
            "negative_months": 0,
            "max_drawdown": 0.0,
        }
    monthly = frame.groupby("month")["unit_profit"].sum().sort_index()
    settlement_days = int(frame["date"].nunique())
    equity = peak = max_drawdown = 0.0
    for profit in frame.sort_values("date")["unit_profit"].astype(float):
        equity += profit
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    profit = float(frame["unit_profit"].sum())
    return {
        "bets": int(len(frame)),
        "profit": round(profit, 2),
        "roi_pct": round(profit / len(frame) * 100, 2),
        "positive_months": int((monthly > 0).sum()),
        "negative_months": int((monthly < 0).sum()),
        "max_drawdown": round(float(max_drawdown), 2),
        "settlement_days": settlement_days,
    }


def _decision(test: dict[str, Any], min_test_bets: int, min_roi_pct: float) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if test["bets"] < min_test_bets:
        reasons.append("test_bets<minimum")
    if test["profit"] <= 0:
        reasons.append("test_profit<=0")
    if test["roi_pct"] < min_roi_pct:
        reasons.append("test_roi<threshold")
    if test["positive_months"] <= test["negative_months"]:
        reasons.append("positive_months<=negative_months")
    if test["max_drawdown"] > max(test["profit"], 1.0):
        reasons.append("drawdown>profit")
    if reasons:
        return "REJECT_TOURNAMENT_HOLDOUT_WEAK", reasons
    return "TOURNAMENT_HOLDOUT_POSITIVE_RESEARCH_ONLY", []


def _match_count(frame: pd.DataFrame) -> int:
    if frame.empty:
        return 0
    return int(frame[["date", "home_team", "away_team"]].drop_duplicates().shape[0])


def _flatten_rule_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for row in rows:
        flattened = {
            "rule": row["rule"],
            "decision": row["decision"],
            "decision_reasons": ";".join(row["decision_reasons"]),
        }
        for side in ("train", "test"):
            for key, value in row[side].items():
                flattened[f"{side}_{key}"] = value
        output.append(flattened)
    return output


def validate_world_cup_tournament_holdout(
    seasons: tuple[str, ...] = ("WORLD_CUP",),
    odds_source: str = "AVG_CLOSE",
    train_year: int = 2018,
    test_year: int = 2022,
    top_n: int = 12,
    min_train_samples: int = 8,
    min_train_active_months: int = 1,
    min_test_bets: int = 20,
    min_roi_pct: float = 3.0,
) -> dict[str, Any]:
    frame = build_market_frame(seasons, odds_source)
    frame["year"] = pd.to_datetime(frame["date"]).dt.year
    available_years = sorted(int(year) for year in frame["year"].dropna().unique())
    train = frame[frame["year"] == train_year].copy()
    test = frame[frame["year"] == test_year].copy()
    diagnostics = run_diagnostics(train, min_train_samples, min_train_active_months, 3)
    rules: list[str] = []
    for _, row in diagnostics.head(top_n).iterrows():
        rule = f"{row['columns']}={row['key']}"
        if rule not in rules:
            rules.append(rule)

    rows: list[dict[str, Any]] = []
    for rule in rules:
        train_selected = _filter_rule(train, rule)
        test_selected = _filter_rule(test, rule)
        train_metrics = _metrics(train_selected)
        test_metrics = _metrics(test_selected)
        decision, reasons = _decision(test_metrics, min_test_bets, min_roi_pct)
        rows.append({
            "rule": rule,
            "train": train_metrics,
            "test": test_metrics,
            "decision": decision,
            "decision_reasons": reasons,
        })
    passed = [row for row in rows if row["decision"] == "TOURNAMENT_HOLDOUT_POSITIVE_RESEARCH_ONLY"]
    overall_decision = "REJECT_NO_REUSABLE_WORLD_CUP_RULE"
    if passed:
        overall_decision = "RESEARCH_ONLY_TOURNAMENT_HOLDOUT_POSITIVE"
    stability_gate = {
        "status": "BLOCKED",
        "reason": "only_two_world_cup_tournaments_with_archived_odds",
        "minimum_tournament_years": 3,
        "available_tournament_years": available_years,
        "note": "Tournament holdout can reject bad rules, but cannot prove a stable live allocation algorithm with only two World Cups.",
    }
    if len(available_years) >= stability_gate["minimum_tournament_years"]:
        stability_gate = {
            **stability_gate,
            "status": "ELIGIBLE_FOR_MULTI_TOURNAMENT_WALK_FORWARD",
            "reason": "minimum_tournament_years_available",
        }
    promotion_decision = (
        "BLOCK_PRODUCTION_WORLD_CUP_SAMPLE_TOO_SMALL"
        if stability_gate["status"] == "BLOCKED"
        else "RESEARCH_ONLY_PENDING_BROADER_GATES"
    )
    return {
        "method": "World Cup tournament holdout validation",
        "seasons": seasons,
        "odds_source": odds_source,
        "train_year": train_year,
        "test_year": test_year,
        "train_market_rows": int(len(train)),
        "test_market_rows": int(len(test)),
        "train_matches": _match_count(train),
        "test_matches": _match_count(test),
        "available_tournament_years": available_years,
        "top_n": top_n,
        "min_train_samples": min_train_samples,
        "min_test_bets": min_test_bets,
        "min_roi_pct": min_roi_pct,
        "candidate_rules": len(rows),
        "passed_rules": len(passed),
        "decision": overall_decision,
        "promotion_decision": promotion_decision,
        "stability_gate": stability_gate,
        "rows": rows,
        "notes": [
            "Rules are discovered only on the training tournament and tested on a later tournament.",
            "A positive tournament holdout is research-only; it is not enough for live allocation without broader multi-period evidence.",
            "World Cup data is sparse; use it to reject fragile ideas, not to promote a standalone money-allocation strategy.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate World Cup rules by tournament holdout.")
    parser.add_argument("--seasons", default="WORLD_CUP")
    parser.add_argument("--odds-source", default="AVG_CLOSE")
    parser.add_argument("--train-year", type=int, default=2018)
    parser.add_argument("--test-year", type=int, default=2022)
    parser.add_argument("--top-n", type=int, default=12)
    parser.add_argument("--min-train-samples", type=int, default=8)
    parser.add_argument("--min-test-bets", type=int, default=20)
    parser.add_argument("--min-roi-pct", type=float, default=3.0)
    parser.add_argument("--output-dir", type=Path, default=Path("reports/world_cup_tournament_validation"))
    args = parser.parse_args()
    summary = validate_world_cup_tournament_holdout(
        tuple(item.strip() for item in args.seasons.split(",") if item.strip()),
        args.odds_source,
        args.train_year,
        args.test_year,
        args.top_n,
        args.min_train_samples,
        1,
        args.min_test_bets,
        args.min_roi_pct,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(_flatten_rule_rows(summary["rows"])).to_csv(args.output_dir / "rules.csv", index=False, encoding="utf-8-sig")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
