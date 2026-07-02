from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GateCheck:
    check_id: str
    description: str
    passed: bool
    value: float | int | str | None
    threshold: float | int | str | None
    severity: str
    message: str


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _check(check_id: str, description: str, passed: bool, value: Any, threshold: Any,
           severity: str, message: str) -> GateCheck:
    return GateCheck(check_id, description, bool(passed), value, threshold, severity, message)


def _strategy_id(robustness: dict[str, Any], official_sp: dict[str, Any], options: dict[str, Any]) -> str:
    explicit = str(options.get("strategy_id") or "").strip()
    if explicit:
        return explicit
    official = str(official_sp.get("strategy_id") or "").strip()
    if official and official != "ALL_MARKET_BIAS_SHADOW_CANDIDATES":
        return official
    rules = robustness.get("rules") or []
    if rules:
        return str(rules[0])
    return "UNKNOWN_MARKET_BIAS_STRATEGY"


def evaluate_market_bias_promotion(
    robustness: dict[str, Any],
    portfolio: dict[str, Any],
    official_sp: dict[str, Any],
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    options = options or {}
    min_robust_pass_rate = float(options.get("min_robust_pass_rate", 0.75))
    min_source_passes = int(options.get("min_source_passes", 4))
    min_profile_passes = int(options.get("min_profile_passes", 2))
    min_portfolio_roi = float(options.get("min_portfolio_roi", 3.0))
    min_positive_month_edge = int(options.get("min_positive_month_edge", 2))
    max_drawdown_to_profit = float(options.get("max_drawdown_to_profit", 1.0))
    min_official_candidates = int(options.get("min_official_candidates", 100))
    min_official_active_months = int(options.get("min_official_active_months", 12))
    min_official_roi = float(options.get("min_official_roi", 3.0))
    strategy_id = _strategy_id(robustness, official_sp, options)

    robust_rate = (float(robustness.get("passed_runs") or 0) / float(robustness.get("total_runs") or 1))
    portfolio_overall = portfolio.get("overall") or {}
    portfolio_profit = float(portfolio_overall.get("profit") or 0)
    portfolio_drawdown = float(portfolio_overall.get("max_drawdown") or 0)
    drawdown_to_profit = round(portfolio_drawdown / portfolio_profit, 4) if portfolio_profit > 0 else None
    official_months = official_sp.get("monthly") or []
    checks = [
        _check("robust_decision", "Robustness gate remains research/shadow eligible",
               robustness.get("decision") == "RESEARCH_CANDIDATE_SHADOW_VALIDATION",
               robustness.get("decision"), "RESEARCH_CANDIDATE_SHADOW_VALIDATION", "BLOCKING",
               "historical multi-source gate"),
        _check("robust_pass_rate", "Robust pass rate >= minimum", robust_rate >= min_robust_pass_rate,
               round(robust_rate, 4), min_robust_pass_rate, "BLOCKING", "historical robustness pass rate"),
        _check("source_passes", "Enough odds sources pass", int(robustness.get("source_passes") or 0) >= min_source_passes,
               int(robustness.get("source_passes") or 0), min_source_passes, "BLOCKING", "odds-source diversity"),
        _check("profile_passes", "Enough rolling profiles pass", int(robustness.get("profile_passes") or 0) >= min_profile_passes,
               int(robustness.get("profile_passes") or 0), min_profile_passes, "BLOCKING", "rolling-profile diversity"),
        _check("portfolio_profit", "Portfolio profit is positive", portfolio_profit > 0,
               round(portfolio_profit, 2), ">0", "BLOCKING", "settlement-aware portfolio profit"),
        _check("portfolio_roi", "Portfolio ROI >= minimum", float(portfolio_overall.get("roi_pct") or 0) >= min_portfolio_roi,
               float(portfolio_overall.get("roi_pct") or 0), min_portfolio_roi, "BLOCKING", "settlement-aware portfolio ROI"),
        _check("portfolio_month_balance", "Positive months exceed negative months by margin",
               int(portfolio.get("positive_months") or 0) - int(portfolio.get("negative_months") or 0) >= min_positive_month_edge,
               f"{portfolio.get('positive_months')}/{portfolio.get('negative_months')}",
               f"+{min_positive_month_edge}", "BLOCKING", "monthly stability"),
        _check("portfolio_season_balance", "More positive than negative seasons",
               int(portfolio.get("positive_seasons") or 0) > int(portfolio.get("negative_seasons") or 0),
               f"{portfolio.get('positive_seasons')}/{portfolio.get('negative_seasons')}",
               "positive>negative", "BLOCKING", "season stability"),
        _check("drawdown_to_profit", "Portfolio drawdown <= profit",
               drawdown_to_profit is not None and drawdown_to_profit <= max_drawdown_to_profit,
               drawdown_to_profit, max_drawdown_to_profit, "WARNING", "drawdown guard"),
        _check("official_sample", "Official-SP settled candidate sample >= minimum",
               int(official_sp.get("settled_candidate_count") or 0) >= min_official_candidates,
               int(official_sp.get("settled_candidate_count") or 0), min_official_candidates, "PRODUCTION_BLOCKING",
               "official SP prospective sample"),
        _check("official_months", "Official-SP active months >= minimum",
               len(official_months) >= min_official_active_months,
               len(official_months), min_official_active_months, "PRODUCTION_BLOCKING",
               "official SP month coverage"),
        _check("official_roi", "Official-SP ROI >= minimum",
               float(official_sp.get("roi_pct") or 0) >= min_official_roi,
               float(official_sp.get("roi_pct") or 0), min_official_roi, "PRODUCTION_BLOCKING",
               "official SP ROI"),
        _check("official_month_balance", "Official-SP positive months exceed negative months",
               int(official_sp.get("positive_months") or 0) > int(official_sp.get("negative_months") or 0),
               f"{official_sp.get('positive_months')}/{official_sp.get('negative_months')}",
               "positive>negative", "PRODUCTION_BLOCKING", "official SP monthly stability"),
    ]
    blocking_failed = [item for item in checks if item.severity == "BLOCKING" and not item.passed]
    production_failed = [item for item in checks if item.severity == "PRODUCTION_BLOCKING" and not item.passed]
    warning_failed = [item for item in checks if item.severity == "WARNING" and not item.passed]
    if blocking_failed:
        decision = "REJECT_RESEARCH_CANDIDATE"
    elif production_failed:
        decision = "SHADOW_READY_PRODUCTION_BLOCKED"
    elif warning_failed:
        decision = "KEEP_SHADOW_RISK_REVIEW"
    else:
        decision = "PRODUCTION_CANDIDATE_REQUIRES_HUMAN_CONFIRMATION"
    return {
        "method": "market-bias promotion gate",
        "strategy_id": strategy_id,
        "rules": robustness.get("rules") or [],
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "decision": decision,
        "recommended_for_shadow": decision in {
            "SHADOW_READY_PRODUCTION_BLOCKED",
            "KEEP_SHADOW_RISK_REVIEW",
            "PRODUCTION_CANDIDATE_REQUIRES_HUMAN_CONFIRMATION",
        },
        "recommended_for_production": decision == "PRODUCTION_CANDIDATE_REQUIRES_HUMAN_CONFIRMATION",
        "requires_human_confirmation": True,
        "checks": [asdict(item) for item in checks],
        "failed_blocking_checks": [item.check_id for item in blocking_failed],
        "failed_production_checks": [item.check_id for item in production_failed],
        "failed_warning_checks": [item.check_id for item in warning_failed],
        "summary": [
            f"Decision: {decision}",
            "Historical robustness and settlement-aware portfolio evidence are necessary but not sufficient.",
            "Production remains blocked until official-SP prospective settlement satisfies sample, ROI, and month-balance gates.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--robustness", type=Path, default=Path("reports/market_bias_robustness_gate_i2_draw/summary.json"))
    parser.add_argument("--portfolio", type=Path, default=Path("reports/market_bias_portfolio_simulation_i2_draw_avg_open_default/summary.json"))
    parser.add_argument("--official-sp", type=Path, default=Path("reports/official_sp_market_bias_validation/summary.json"))
    parser.add_argument("--output", type=Path, default=Path("reports/market_bias_promotion_gate_i2_draw/summary.json"))
    parser.add_argument("--strategy-id", default="")
    args = parser.parse_args()
    result = evaluate_market_bias_promotion(
        _load(args.robustness),
        _load(args.portfolio),
        _load(args.official_sp),
        {"strategy_id": args.strategy_id} if args.strategy_id else None,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
