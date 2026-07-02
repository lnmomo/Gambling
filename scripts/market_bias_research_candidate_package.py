from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from market_bias_promotion_gate import evaluate_market_bias_promotion


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _empty_official_report(strategy_id: str) -> dict[str, Any]:
    return {
        "strategy_id": strategy_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "sample_count": 0,
        "candidate_count": 0,
        "settled_candidate_count": 0,
        "winning_count": 0,
        "total_staked": 0.0,
        "profit": 0.0,
        "roi_pct": 0.0,
        "hit_rate": None,
        "max_drawdown": 0.0,
        "positive_months": 0,
        "negative_months": 0,
        "monthly": [],
        "selections": [],
        "warnings": ["no official-SP prospective samples for this research candidate"],
    }


def _candidate_screen_row(candidate_screen: dict[str, Any], rule: str) -> dict[str, Any] | None:
    for row in candidate_screen.get("rule_summary") or []:
        if row.get("rule") == rule:
            return row
    for row in candidate_screen.get("rows") or []:
        if row.get("rule") == rule:
            return row
    return None


def _classification(promotion: dict[str, Any], candidate_screen_row: dict[str, Any] | None) -> str:
    if promotion.get("recommended_for_production"):
        return "PRODUCTION_CANDIDATE_REQUIRES_HUMAN_CONFIRMATION"
    if promotion.get("recommended_for_shadow"):
        return "SHADOW_READY_PRODUCTION_BLOCKED"
    if candidate_screen_row and candidate_screen_row.get("passes_all_validation_sources"):
        return "RESEARCH_WATCH_ONLY"
    if candidate_screen_row and candidate_screen_row.get("passes_screen"):
        return "RESEARCH_SCREEN_ONLY"
    return "REJECTED"


def build_research_candidate_package(
    *,
    strategy_id: str,
    rule: str,
    robustness: dict[str, Any],
    portfolio: dict[str, Any],
    candidate_screen: dict[str, Any] | None = None,
    official_sp: dict[str, Any] | None = None,
) -> dict[str, Any]:
    official = official_sp or _empty_official_report(strategy_id)
    promotion = evaluate_market_bias_promotion(
        robustness,
        portfolio,
        official,
        {"strategy_id": strategy_id},
    )
    screen_row = _candidate_screen_row(candidate_screen or {}, rule)
    classification = _classification(promotion, screen_row)
    return {
        "method": "market-bias research candidate package",
        "strategy_id": strategy_id,
        "rule": rule,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "classification": classification,
        "promotion_decision": promotion["decision"],
        "recommended_for_shadow": promotion["recommended_for_shadow"],
        "recommended_for_production": promotion["recommended_for_production"],
        "candidate_screen": screen_row,
        "robustness": {
            "decision": robustness.get("decision"),
            "passed_runs": robustness.get("passed_runs"),
            "total_runs": robustness.get("total_runs"),
            "source_passes": robustness.get("source_passes"),
            "profile_passes": robustness.get("profile_passes"),
            "decision_reasons": robustness.get("decision_reasons") or [],
        },
        "portfolio": {
            "overall": portfolio.get("overall") or {},
            "positive_months": portfolio.get("positive_months"),
            "negative_months": portfolio.get("negative_months"),
            "positive_seasons": portfolio.get("positive_seasons"),
            "negative_seasons": portfolio.get("negative_seasons"),
        },
        "official_sp": {
            "settled_candidate_count": official.get("settled_candidate_count", 0),
            "roi_pct": official.get("roi_pct", 0.0),
            "positive_months": official.get("positive_months", 0),
            "negative_months": official.get("negative_months", 0),
            "warnings": official.get("warnings") or [],
        },
        "failed_blocking_checks": promotion.get("failed_blocking_checks") or [],
        "failed_production_checks": promotion.get("failed_production_checks") or [],
        "failed_warning_checks": promotion.get("failed_warning_checks") or [],
        "promotion": promotion,
        "next_step": (
            "Keep as research watch only until robustness and official-SP prospective gates pass."
            if classification == "RESEARCH_WATCH_ONLY"
            else "Follow promotion gate decision."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy-id", required=True)
    parser.add_argument("--rule", required=True)
    parser.add_argument("--robustness", type=Path, required=True)
    parser.add_argument("--portfolio", type=Path, required=True)
    parser.add_argument("--candidate-screen", type=Path)
    parser.add_argument("--official-sp", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build_research_candidate_package(
        strategy_id=args.strategy_id,
        rule=args.rule,
        robustness=_load(args.robustness),
        portfolio=_load(args.portfolio),
        candidate_screen=_load(args.candidate_screen) if args.candidate_screen else None,
        official_sp=_load(args.official_sp) if args.official_sp else None,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
