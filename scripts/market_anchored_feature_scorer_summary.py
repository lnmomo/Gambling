from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _best_rows_by_rule(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    best: dict[str, dict[str, Any]] = {}
    for row in report.get("results") or []:
        rule = str(row.get("rule_description") or row.get("rule_id") or row.get("label"))
        current = best.get(rule)
        key = (
            row.get("decision") == "RESEARCH_CANDIDATE_NEEDS_AUDIT",
            float(row.get("active_pass_rate") or 0.0),
            float(row.get("roi_pct") or 0.0),
            float(row.get("profit") or 0.0),
            int(row.get("bets") or 0),
        )
        current_key = (
            current.get("decision") == "RESEARCH_CANDIDATE_NEEDS_AUDIT",
            float(current.get("active_pass_rate") or 0.0),
            float(current.get("roi_pct") or 0.0),
            float(current.get("profit") or 0.0),
            int(current.get("bets") or 0),
        ) if current else None
        if current is None or key > current_key:
            best[rule] = row
    return best


def summarize_feature_scorer_reports(paths: list[Path]) -> dict[str, Any]:
    reports = []
    for path in paths:
        report = _load(path)
        reports.append((path, report))
    sources = [str(report.get("odds_source") or path.parent.name) for path, report in reports]
    all_rules = sorted({
        rule
        for _, report in reports
        for rule in _best_rows_by_rule(report)
    })
    rule_summaries = []
    for rule in all_rules:
        source_results = []
        for path, report in reports:
            odds_source = str(report.get("odds_source") or path.parent.name)
            row = _best_rows_by_rule(report).get(rule)
            if row is None:
                source_results.append({
                    "odds_source": odds_source,
                    "available": False,
                    "passed": False,
                    "reason": "rule_not_tested_or_no_candidates",
                })
                continue
            source_results.append({
                "odds_source": odds_source,
                "available": True,
                "passed": row.get("decision") == "RESEARCH_CANDIDATE_NEEDS_AUDIT",
                "label": row.get("label"),
                "bets": int(row.get("bets") or 0),
                "profit": float(row.get("profit") or 0.0),
                "roi_pct": float(row.get("roi_pct") or 0.0),
                "max_drawdown": float(row.get("max_drawdown") or 0.0),
                "active_pass_rate": float(row.get("active_pass_rate") or 0.0),
                "latest_season_profit": float(row.get("latest_season_profit") or 0.0),
                "decision_reasons": row.get("decision_reasons") or [],
            })
        available = [row for row in source_results if row["available"]]
        passed = [row for row in source_results if row["passed"]]
        total_profit = sum(float(row.get("profit") or 0.0) for row in available)
        total_bets = sum(int(row.get("bets") or 0) for row in available)
        worst_roi = min((float(row.get("roi_pct") or 0.0) for row in available), default=0.0)
        worst_active_pass_rate = min((float(row.get("active_pass_rate") or 0.0) for row in available), default=0.0)
        rule_summaries.append({
            "rule": rule,
            "available_sources": len(available),
            "passed_sources": len(passed),
            "source_count": len(sources),
            "passes_all_sources": len(passed) == len(sources) and len(sources) > 0,
            "total_bets": total_bets,
            "total_profit": round(total_profit, 2),
            "combined_profit_per_bet": round(total_profit / total_bets, 4) if total_bets else 0.0,
            "worst_source_roi_pct": round(worst_roi, 2),
            "worst_active_pass_rate": round(worst_active_pass_rate, 4),
            "source_results": source_results,
        })
    rule_summaries.sort(
        key=lambda row: (
            row["passes_all_sources"],
            row["passed_sources"],
            row["available_sources"],
            row["worst_source_roi_pct"],
            row["total_profit"],
            row["total_bets"],
        ),
        reverse=True,
    )
    passed_all = [row for row in rule_summaries if row["passes_all_sources"]]
    return {
        "method": "market-anchored feature scorer cross-source summary",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "report_paths": [str(path) for path in paths],
        "odds_sources": sources,
        "rule_count": len(rule_summaries),
        "rules_passing_all_sources": len(passed_all),
        "decision": (
            "FEATURE_SCORER_CROSS_SOURCE_CANDIDATE"
            if passed_all
            else "NO_CROSS_SOURCE_FEATURE_SCORER_CANDIDATE"
        ),
        "rules": rule_summaries,
        "top": rule_summaries[:20],
        "interpretation": (
            "A feature scorer candidate must pass each tested odds source before it can move to "
            "statistical audit and official-SP prospective validation."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate market-anchored feature scorer reports across odds sources.")
    parser.add_argument("--report", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, default=Path("reports/market_anchored_feature_scorer_cross_source/summary.json"))
    args = parser.parse_args()
    summary = summarize_feature_scorer_reports(args.report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
