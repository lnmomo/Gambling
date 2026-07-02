from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


RESIDUAL_PREFIXES = (
    "cross_league_rule_search",
    "fixed_sp2",
    "residual_walk_forward",
)


def _number(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _tier(row: dict[str, Any]) -> str:
    if row["profit"] <= 0 or row["roi_pct"] <= 0:
        return "REJECT_NEGATIVE_EDGE"
    if row["bets"] < 100:
        return "REJECT_SMALL_SAMPLE"
    if row["active_months"] < 24:
        return "REJECT_TOO_FEW_ACTIVE_MONTHS"
    if row["positive_months"] <= row["negative_months"]:
        return "REJECT_MONTH_BALANCE"
    if row["drawdown_to_profit"] is None or row["drawdown_to_profit"] > 1.0:
        return "RESEARCH_POSITIVE_UNSTABLE_DRAWDOWN"
    if row["latest_season_profit"] is not None and row["latest_season_profit"] < 0:
        return "RESEARCH_RECENT_SEASON_WEAK"
    return "SHADOW_RESEARCH_CANDIDATE"


def _score(row: dict[str, Any]) -> float:
    if row["profit"] <= 0 or row["roi_pct"] <= 0:
        return 0.0
    sample_score = min(25.0, row["bets"] / 8.0)
    month_score = min(20.0, row["active_months"])
    balance_score = max(0.0, min(20.0, (row["positive_months"] - row["negative_months"]) * 4.0 + 10.0))
    roi_score = max(0.0, min(20.0, row["roi_pct"]))
    if row["drawdown_to_profit"] is None:
        drawdown_score = 0.0
    else:
        drawdown_score = max(0.0, min(15.0, (1.5 - row["drawdown_to_profit"]) * 10.0))
    return round(sample_score + month_score + balance_score + roi_score + drawdown_score, 2)


def summarize_report(path: Path) -> dict[str, Any] | None:
    name = path.parent.name
    if not name.startswith(RESIDUAL_PREFIXES):
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    overall = payload.get("overall") or {}
    stability = payload.get("stability_assessment") or {}
    latest_season = stability.get("latest_season") or {}
    profit = _number(overall.get("profit"))
    max_drawdown = _number(overall.get("max_drawdown"))
    row = {
        "name": name,
        "method": payload.get("method"),
        "first_month": payload.get("first_month"),
        "last_month": payload.get("last_month"),
        "bets": _int(overall.get("bets")),
        "profit": round(profit, 2),
        "roi_pct": round(_number(overall.get("roi_pct")), 2),
        "max_drawdown": round(max_drawdown, 2),
        "drawdown_to_profit": round(max_drawdown / profit, 3) if profit > 0 else None,
        "active_months": _int(payload.get("active_months") or stability.get("active_months")),
        "positive_months": _int(payload.get("positive_months") or stability.get("positive_months")),
        "negative_months": _int(payload.get("negative_months") or stability.get("negative_months")),
        "latest_season_profit": latest_season.get("profit"),
        "source_verdict": stability.get("verdict") or payload.get("promotion_decision"),
        "report": str(path),
    }
    row["tier"] = _tier(row)
    row["score"] = _score(row)
    return row


def build_scorecard(reports_dir: Path = Path("reports")) -> dict[str, Any]:
    rows = [
        row for row in (
            summarize_report(path)
            for path in reports_dir.glob("*/summary.json")
        )
        if row is not None
    ]
    rows.sort(key=lambda row: (
        row["tier"] == "SHADOW_RESEARCH_CANDIDATE",
        row["score"],
        row["profit"],
        row["bets"],
    ), reverse=True)
    tier_counts: dict[str, int] = {}
    for row in rows:
        tier_counts[row["tier"]] = tier_counts.get(row["tier"], 0) + 1
    return {
        "method": "residual strategy stability scorecard",
        "reports_scanned": len(rows),
        "tier_counts": tier_counts,
        "top": rows[:25],
        "rows": rows,
        "promotion_rule": {
            "min_bets": 100,
            "min_active_months": 24,
            "positive_months_must_exceed_negative": True,
            "max_drawdown_to_profit": 1.0,
            "latest_season_profit_must_not_be_negative": True,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reports-dir", type=Path, default=Path("reports"))
    parser.add_argument("--output", type=Path, default=Path("reports/residual_strategy_scorecard/summary.json"))
    args = parser.parse_args()
    scorecard = build_scorecard(args.reports_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(scorecard, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(scorecard, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
