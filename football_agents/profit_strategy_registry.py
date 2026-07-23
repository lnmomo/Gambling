from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


MARKET_ANCHORED_I2_DRAWS_STRATEGY_ID = "profit-i2-draw-market-anchored-stop3-cool3-v1"
MARKET_ANCHORED_I2_AVG_CLOSE_RESEARCH_ID = "profit-i2-draw-market-anchored-avg-close-stop3-cool14-v1"
MARKET_ANCHORED_SP1_HOME_RESEARCH_ID = "profit-sp1-home-market-prob-55-market-anchored-v1"
EXTERNAL_CONSENSUS_CHALLENGER_STRATEGY_ID = "profit-external-consensus-official-sp-quarter-residual-v1"
MARKET_BIAS_I2_SCORECARD_REPORT = Path("reports/market_bias_profit_algorithm_scorecard_i2_draw/summary.json")


@dataclass(frozen=True)
class ProfitStrategyPackage:
    strategy_id: str
    name: str
    status: str
    historical_report: str
    statistical_audit_report: str
    edge_calibration_report: str
    scorer_artifact_report: str | None
    profit_scorecard_report: str | None
    selection: dict[str, Any]
    risk_control: dict[str, Any]
    historical_metrics: dict[str, Any]
    audit: dict[str, Any]
    calibration: dict[str, Any]
    profit_scorecard: dict[str, Any] | None
    recommended_for_shadow: bool | None
    deployment_blockers: tuple[str, ...]
    next_validation: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _optional_json(path_text: str | None) -> dict[str, Any] | None:
    if not path_text:
        return None
    path = Path(path_text)
    if not path.exists():
        return None
    return _read_json(path)


def _report_uses_artifact(report: dict[str, Any] | None, artifact_path: Path) -> bool:
    if not report or not report.get("scorer_artifact"):
        return False
    try:
        return Path(str(report["scorer_artifact"])).resolve() == artifact_path.resolve()
    except (OSError, RuntimeError):
        return False


def _apply_fixed_daily_budget_metrics(
    validation: dict[str, Any], report: dict[str, Any] | None,
) -> dict[str, Any]:
    """Prefer the frozen 100-yuan daily replay for allocation-facing metrics."""
    portfolio = (report or {}).get("daily_portfolio")
    if not isinstance(portfolio, dict):
        return validation
    summary = portfolio.get("summary")
    if not isinstance(summary, dict):
        return validation
    validation.update({
        "portfolio_method": portfolio.get("method"),
        "portfolio_daily_budget": portfolio.get("daily_budget"),
        "portfolio_max_single_stake": portfolio.get("max_single_stake"),
        "portfolio_same_day_results_hidden_until_allocation": portfolio.get(
            "same_day_results_hidden_until_allocation"
        ),
        "profit": summary.get("profit"),
        "roi_pct": summary.get("roi_pct"),
        "max_drawdown": summary.get("max_drawdown"),
        "active_months": summary.get("active_months", len(portfolio.get("monthly") or [])),
        "positive_months": summary.get("positive_months"),
        "negative_months": summary.get("negative_months"),
        "monthly": portfolio.get("monthly") or [],
        "daily": portfolio.get("daily") or [],
        "portfolio_summary": summary,
    })
    return validation


def build_market_anchored_i2_strategy_package(
    historical_report: Path | str = Path("reports/feature_enriched_market_anchored_i2_stop3_cool3_v1/summary.json"),
    statistical_audit_report: Path | str = Path("reports/strategy_statistical_audit_market_anchored_i2_stop3_cool3_v1/summary.json"),
    edge_calibration_report: Path | str = Path("reports/strategy_edge_calibration_market_anchored_i2_stop3_cool3_v1/summary.json"),
    scorer_artifact_report: Path | str = Path("reports/feature_enriched_market_anchored_i2_scorer_v1/scorer.json"),
    scorecard_report: Path | str | None = MARKET_BIAS_I2_SCORECARD_REPORT,
) -> ProfitStrategyPackage:
    historical_path = Path(historical_report)
    statistical_path = Path(statistical_audit_report)
    calibration_path = Path(edge_calibration_report)
    scorer_path = Path(scorer_artifact_report)
    missing = [str(path) for path in (historical_path, statistical_path, calibration_path) if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing strategy evidence report(s): " + ", ".join(missing))

    historical = _read_json(historical_path)
    statistical = _read_json(statistical_path)
    calibration = _read_json(calibration_path)
    scorecard_path = Path(scorecard_report) if scorecard_report else None
    scorecard = _read_json(scorecard_path) if scorecard_path and scorecard_path.exists() else None
    historical_overall = historical.get("overall", {})
    window_summary = historical.get("window_summary", {})
    audit_overall = statistical.get("overall", {})
    calibration_overall = calibration.get("overall", {})
    status = "PROMOTE_TO_OFFICIAL_SP_SHADOW_VALIDATION"
    recommended_for_shadow: bool | None = True
    blockers = [
        "historical validation uses football-data AVG_OPEN, not collected China Sporttery official SP snapshots",
        "first rolling annual window remains weak, so production allocation is blocked until prospective official-SP evidence accumulates",
    ]
    if scorecard:
        status = str(scorecard.get("deployment_tier") or status)
        recommended_for_shadow = bool(scorecard.get("recommended_for_shadow"))
        if not recommended_for_shadow:
            blockers.insert(
                0,
                (
                    "latest profit scorecard does not recommend shadow promotion "
                    f"({status}); treat this package as research-only until multi-window evidence improves"
                ),
            )
    if not scorer_path.exists():
        blockers.append("live deployment still needs an exported residual model or equivalent no-leak feature scorer")
    else:
        scorer = _read_json(scorer_path)
        if scorer.get("artifact_type") != "market_anchored_feature_residual_scorer":
            blockers.append("exported scorer artifact type is not recognized")
        if scorer.get("selection", {}).get("selected_rules") != ["I2_draw_2p8_3p5"]:
            blockers.append("exported scorer does not match the formal I2 draw rule")
    return ProfitStrategyPackage(
        strategy_id=MARKET_ANCHORED_I2_DRAWS_STRATEGY_ID,
        name="Market-anchored Italy Serie B draw residual strategy with settled-loss cooldown",
        status=status,
        historical_report=str(historical_path),
        statistical_audit_report=str(statistical_path),
        edge_calibration_report=str(calibration_path),
        scorer_artifact_report=str(scorer_path) if scorer_path.exists() else None,
        profit_scorecard_report=str(scorecard_path) if scorecard_path and scorecard_path.exists() else None,
        selection={
            "league_family": "I2",
            "outcome": "DRAW",
            "odds_source": "AVG_OPEN",
            "odds_band": "[2.8,3.5)",
            "train_months": 30,
            "min_prior_candidates": 120,
            "min_predicted_ev": 0.02,
            "ridge": 10.0,
            "market_residual_cap": 0.08,
            "max_bets_per_day": 1,
        },
        risk_control=historical.get("risk_control", {
            "stop_after_losing_settlement_days": 3,
            "cooldown_days": 3,
            "uses_only_settled_results": True,
        }),
        historical_metrics={
            "bets": historical_overall.get("bets"),
            "profit": historical_overall.get("profit"),
            "roi_pct": historical_overall.get("roi_pct"),
            "max_drawdown": historical_overall.get("max_drawdown"),
            "positive_months": historical.get("positive_months"),
            "negative_months": historical.get("negative_months"),
            "passed_windows": window_summary.get("passed_windows"),
            "window_count": window_summary.get("window_count"),
            "active_pass_rate": window_summary.get("active_pass_rate"),
        },
        audit={
            "decision": statistical.get("decision"),
            "bootstrap_roi_p05": statistical.get("bootstrap", {}).get("roi_ci_pct", {}).get("p05"),
            "probability_roi_positive": statistical.get("bootstrap", {}).get("probability_roi_positive"),
            "sign_flip_p_value": statistical.get("sign_flip_test", {}).get("one_sided_p_value"),
            "drawdown_to_profit": audit_overall.get("drawdown_to_profit"),
        },
        calibration={
            "decision": calibration.get("decision"),
            "hit_rate": calibration_overall.get("hit_rate"),
            "wilson_hit_rate_lower_95": calibration_overall.get("wilson_hit_rate_lower_95"),
            "avg_implied_probability": calibration_overall.get("avg_implied_probability"),
            "conservative_edge_vs_implied": calibration_overall.get("conservative_edge_vs_implied"),
        },
        profit_scorecard={
            "deployment_tier": scorecard.get("deployment_tier"),
            "score": scorecard.get("score"),
            "recommended_for_shadow": scorecard.get("recommended_for_shadow"),
            "recommended_for_production": scorecard.get("recommended_for_production"),
            "multi_window_validation": scorecard.get("components", {}).get("multi_window_validation"),
            "interpretation": scorecard.get("interpretation"),
        } if scorecard else None,
        recommended_for_shadow=recommended_for_shadow,
        deployment_blockers=tuple(blockers),
        next_validation=(
            "Replay the same candidate rule on official_odds_observations using only pre-match snapshots.",
            "Map official live features into the scorer feature schema before generating residual-scored shadow picks.",
            "Re-train or refresh the scorer artifact on a scheduled cadence as new settled history arrives.",
            "Keep the strategy in shadow/research mode until official-SP sample size and rolling-window gates pass.",
        ),
    )


def build_market_anchored_i2_avg_close_research_package(
    manifest_report: Path | str = Path("reports/profit_strategy_research_candidates/i2_avg_close_stop3_cool14_v1/manifest.json"),
) -> dict[str, Any]:
    manifest_path = Path(manifest_report)
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing strategy research manifest: {manifest_path}")

    manifest = _read_json(manifest_path)
    evidence_reports = manifest.get("evidence_reports", {})
    statistical = _optional_json(evidence_reports.get("statistical_audit"))
    calibration = _optional_json(evidence_reports.get("edge_calibration"))
    official_pool = _optional_json(evidence_reports.get("official_pool_diagnosis"))
    official_sp = _optional_json(evidence_reports.get("official_sp_validation"))
    audit_overall = (statistical or {}).get("overall", {})
    calibration_overall = (calibration or {}).get("overall", {})
    audit_payload = {
        "decision": "PENDING_STATISTICAL_AUDIT",
        "reason": "This candidate is frozen from a close-price stress test and cooldown grid; it needs a fresh audit before promotion.",
    }
    if statistical:
        audit_payload = {
            "decision": statistical.get("decision"),
            "bootstrap_roi_p05": statistical.get("bootstrap", {}).get("roi_ci_pct", {}).get("p05"),
            "probability_roi_positive": statistical.get("bootstrap", {}).get("probability_roi_positive"),
            "sign_flip_p_value": statistical.get("sign_flip_test", {}).get("one_sided_p_value"),
            "drawdown_to_profit": audit_overall.get("drawdown_to_profit"),
            "decision_reasons": statistical.get("decision_reasons", []),
        }
    calibration_payload = {
        "decision": "PENDING_EDGE_CALIBRATION",
        "reason": "Official-SP prospective calibration is required before any production allocation.",
    }
    if calibration:
        calibration_payload = {
            "decision": calibration.get("decision"),
            "hit_rate": calibration_overall.get("hit_rate"),
            "wilson_hit_rate_lower_95": calibration_overall.get("wilson_hit_rate_lower_95"),
            "avg_implied_probability": calibration_overall.get("avg_implied_probability"),
            "conservative_edge_vs_implied": calibration_overall.get("conservative_edge_vs_implied"),
            "decision_reasons": calibration.get("decision_reasons", []),
        }
    official_validation_payload = {
        "pool_diagnosis_report": evidence_reports.get("official_pool_diagnosis"),
        "official_sp_validation_report": evidence_reports.get("official_sp_validation"),
        "pool_scanned_matches": (official_pool or {}).get("scanned_matches"),
        "pool_scored_matches": (official_pool or {}).get("scored_matches"),
        "pool_passed_scorer": (official_pool or {}).get("passed_scorer"),
        "opening_pre_match_snapshots": (official_sp or {}).get("opening_pre_match_snapshots"),
        "scored_snapshots": (official_sp or {}).get("scored_snapshots"),
        "selected_snapshots": (official_sp or {}).get("selected_snapshots"),
        "settled_selected_snapshots": (official_sp or {}).get("settled_selected_snapshots"),
        "active_months": (official_sp or {}).get("active_months", len((official_sp or {}).get("monthly", []))),
        "profit": (official_sp or {}).get("profit"),
        "roi_pct": (official_sp or {}).get("roi_pct"),
        "max_drawdown": (official_sp or {}).get("max_drawdown"),
        "average_clv": (official_sp or {}).get("average_clv"),
        "positive_clv_rate": (official_sp or {}).get("positive_clv_rate"),
        "closing_sp_coverage": (official_sp or {}).get("closing_sp_coverage"),
        "positive_months": (official_sp or {}).get("positive_months"),
        "negative_months": (official_sp or {}).get("negative_months"),
        "monthly": (official_sp or {}).get("monthly", []),
        "daily": (official_sp or {}).get("daily", []),
        "statistical_evidence": (official_sp or {}).get("statistical_evidence", {}),
        "decision": (official_sp or {}).get("decision", "PENDING_OFFICIAL_SP_VALIDATION"),
        "decision_reasons": (official_sp or {}).get("decision_reasons", []),
        "top_pool_blockers": (official_pool or {}).get("blocker_counts", [])[:5],
        "top_snapshot_blockers": (official_sp or {}).get("blocker_counts", [])[:5],
    }
    _apply_fixed_daily_budget_metrics(official_validation_payload, official_sp)
    return {
        "strategy_id": manifest.get("strategy_id", MARKET_ANCHORED_I2_AVG_CLOSE_RESEARCH_ID),
        "name": "Frozen AVG_CLOSE Italy Serie B draw residual strategy with settled-loss cooldown",
        "status": manifest.get("status", "RESEARCH_LEAD_FREEZE_FOR_PROSPECTIVE_SHADOW"),
        "research_manifest_report": str(manifest_path),
        "historical_report": evidence_reports.get("cooldown_grid"),
        "statistical_audit_report": evidence_reports.get("statistical_audit"),
        "edge_calibration_report": evidence_reports.get("edge_calibration"),
        "scorer_artifact_report": evidence_reports.get("scorer_artifact"),
        "selection": manifest.get("selection", {}),
        "risk_control": manifest.get("risk_control", {}),
        "historical_metrics": manifest.get("historical_metrics", {}).get("cooldown_best", {}),
        "audit": audit_payload,
        "calibration": calibration_payload,
        "official_validation": official_validation_payload,
        "deployment_blockers": tuple(manifest.get("blockers", ())),
        "next_validation": tuple(manifest.get("promotion_requirements", ())),
        "freeze_notes": tuple(manifest.get("freeze_notes", ())),
    }


def build_market_anchored_sp1_home_research_package(
    cross_source_report: Path | str = Path("reports/market_anchored_feature_scorer_cross_source_current/summary.json"),
    statistical_audit_report: Path | str = Path(
        "reports/strategy_statistical_audit_sp1_home_prob_feature_avg_close_current/summary.json"
    ),
    edge_calibration_report: Path | str = Path(
        "reports/strategy_edge_calibration_sp1_home_prob_feature_avg_close_current/summary.json"
    ),
    scorer_artifact_report: Path | str = Path(
        "reports/market_anchored_sp1_home_avg_close_shadow_scorer_v1/scorer.json"
    ),
    official_pool_report: Path | str = Path("reports/profit_scorer_official_pool/summary.json"),
    official_sp_report: Path | str = Path("reports/profit_scorer_official_sp_validation/summary.json"),
) -> dict[str, Any]:
    paths = {
        "cross_source": Path(cross_source_report),
        "statistical_audit": Path(statistical_audit_report),
        "edge_calibration": Path(edge_calibration_report),
        "scorer_artifact": Path(scorer_artifact_report),
        "official_pool_diagnosis": Path(official_pool_report),
        "official_sp_validation": Path(official_sp_report),
    }
    required = ("cross_source", "statistical_audit", "edge_calibration", "scorer_artifact")
    missing = [str(paths[key]) for key in required if not paths[key].exists()]
    if missing:
        raise FileNotFoundError("Missing SP1 strategy evidence report(s): " + ", ".join(missing))

    cross_source = _read_json(paths["cross_source"])
    statistical = _read_json(paths["statistical_audit"])
    calibration = _read_json(paths["edge_calibration"])
    official_pool = _optional_json(str(paths["official_pool_diagnosis"]))
    official_sp = _optional_json(str(paths["official_sp_validation"]))
    scorer = _read_json(paths["scorer_artifact"])
    pool_artifact_matches = _report_uses_artifact(official_pool, paths["scorer_artifact"])
    official_artifact_matches = _report_uses_artifact(official_sp, paths["scorer_artifact"])
    if not pool_artifact_matches:
        official_pool = None
    if not official_artifact_matches:
        official_sp = None
    target_rule = next((
        row for row in cross_source.get("rules", [])
        if row.get("rule") == "rule_league_SP1_market_prob_bucket_0p55_1p00_outcome_home"
    ), {})
    cross_source_pass = bool(
        cross_source.get("decision") == "FEATURE_SCORER_CROSS_SOURCE_CANDIDATE"
        and target_rule.get("passes_all_sources")
    )
    audit_pass = statistical.get("decision") == "STATISTICALLY_SUPPORTED_RESEARCH_CANDIDATE"
    calibration_decision = str(calibration.get("decision") or "PENDING_EDGE_CALIBRATION")
    calibration_usable_for_shadow = calibration_decision in {
        "CALIBRATED_EDGE_CONFIRMED",
        "POSITIVE_EDGE_BUT_NOT_CONSERVATIVE",
    }
    scorer_matches = scorer.get("selection", {}).get("selected_rules") == ["SP1_home_market_ge_55"]
    recommended_for_shadow = cross_source_pass and audit_pass and calibration_usable_for_shadow and scorer_matches
    status = (
        "OFFICIAL_SP_SHADOW_VALIDATION"
        if recommended_for_shadow
        else "RESEARCH_ONLY_EVIDENCE_INCOMPLETE"
    )
    audit_overall = statistical.get("overall", {})
    calibration_overall = calibration.get("overall", {})
    official_validation = {
        "pool_diagnosis_report": str(paths["official_pool_diagnosis"]),
        "official_sp_validation_report": str(paths["official_sp_validation"]),
        "pool_scanned_matches": (official_pool or {}).get("scanned_matches"),
        "pool_scored_matches": (official_pool or {}).get("scored_matches"),
        "pool_passed_scorer": (official_pool or {}).get("passed_scorer"),
        "opening_pre_match_snapshots": (official_sp or {}).get("opening_pre_match_snapshots"),
        "selected_snapshots": (official_sp or {}).get("selected_snapshots"),
        "settled_selected_snapshots": (official_sp or {}).get("settled_selected_snapshots"),
        "active_months": (official_sp or {}).get("active_months", len((official_sp or {}).get("monthly", []))),
        "profit": (official_sp or {}).get("profit"),
        "roi_pct": (official_sp or {}).get("roi_pct"),
        "max_drawdown": (official_sp or {}).get("max_drawdown"),
        "average_clv": (official_sp or {}).get("average_clv"),
        "positive_clv_rate": (official_sp or {}).get("positive_clv_rate"),
        "closing_sp_coverage": (official_sp or {}).get("closing_sp_coverage"),
        "positive_months": (official_sp or {}).get("positive_months"),
        "negative_months": (official_sp or {}).get("negative_months"),
        "monthly": (official_sp or {}).get("monthly", []),
        "daily": (official_sp or {}).get("daily", []),
        "statistical_evidence": (official_sp or {}).get("statistical_evidence", {}),
        "decision": (official_sp or {}).get("decision", "PENDING_OFFICIAL_SP_VALIDATION"),
        "decision_reasons": (official_sp or {}).get("decision_reasons", []),
        "top_pool_blockers": (official_pool or {}).get("blocker_counts", [])[:5],
        "top_snapshot_blockers": (official_sp or {}).get("blocker_counts", [])[:5],
    }
    _apply_fixed_daily_budget_metrics(official_validation, official_sp)
    blockers = [
        "Official-SP prospective validation has not passed on at least 200 settled selections across 6 active months.",
        "AVG_CLOSE historical calibration is positive but its Wilson 95% lower edge is not above zero.",
        "The four historical odds sources overlap on matches and are robustness checks, not independent samples.",
    ]
    if not pool_artifact_matches or not official_artifact_matches:
        blockers.insert(0, "Official evidence report is missing or belongs to a different frozen scorer artifact.")
    return {
        "strategy_id": MARKET_ANCHORED_SP1_HOME_RESEARCH_ID,
        "name": "Market-anchored Spanish La Liga high-probability home residual strategy",
        "status": status,
        "recommended_for_shadow": recommended_for_shadow,
        "historical_report": str(paths["cross_source"]),
        "statistical_audit_report": str(paths["statistical_audit"]),
        "edge_calibration_report": str(paths["edge_calibration"]),
        "scorer_artifact_report": str(paths["scorer_artifact"]),
        "selection": {
            "league_family": "SP1",
            "outcome": "HOME",
            "odds_source": "AVG_CLOSE",
            "min_market_probability": 0.55,
            "train_months": 18,
            "min_prior_candidates": 80,
            "min_predicted_ev": 0.0,
            "ridge": 35.0,
            "market_residual_cap": 0.08,
            "max_bets_per_day": 1,
        },
        "risk_control": {
            "daily_budget_cap": 100.0,
            "max_single_stake": 10.0,
            "max_bets_per_day": 1,
            "uses_only_settled_results": True,
            "two_negative_months_trigger_cooldown": True,
        },
        "historical_metrics": {
            "bets": audit_overall.get("bets"),
            "profit": audit_overall.get("profit"),
            "roi_pct": audit_overall.get("roi_pct"),
            "max_drawdown": audit_overall.get("max_month_drawdown"),
            "positive_months": audit_overall.get("positive_months"),
            "negative_months": audit_overall.get("negative_months"),
        },
        "audit": {
            "decision": statistical.get("decision"),
            "bootstrap_roi_p05": statistical.get("bootstrap", {}).get("roi_ci_pct", {}).get("p05"),
            "probability_roi_positive": statistical.get("bootstrap", {}).get("probability_roi_positive"),
            "sign_flip_p_value": statistical.get("sign_flip_test", {}).get("one_sided_p_value"),
            "drawdown_to_profit": audit_overall.get("drawdown_to_profit"),
        },
        "calibration": {
            "decision": calibration_decision,
            "hit_rate": calibration_overall.get("hit_rate"),
            "wilson_hit_rate_lower_95": calibration_overall.get("wilson_hit_rate_lower_95"),
            "avg_implied_probability": calibration_overall.get("avg_implied_probability"),
            "conservative_edge_vs_implied": calibration_overall.get("conservative_edge_vs_implied"),
        },
        "cross_source_validation": {
            "decision": cross_source.get("decision"),
            "passes_all_sources": cross_source_pass,
            "source_count": target_rule.get("source_count"),
            "worst_source_roi_pct": target_rule.get("worst_source_roi_pct"),
            "worst_active_pass_rate": target_rule.get("worst_active_pass_rate"),
        },
        "official_validation": official_validation,
        "deployment_blockers": tuple(blockers),
        "next_validation": (
            "Collect official opening and closing SP for eligible SP1 matches without changing the frozen scorer.",
            "Require positive official-SP CLV, positive profit, and controlled drawdown across at least 6 active months.",
            "Keep allocation in shadow/paper mode until the prospective gate passes.",
        ),
    }


def build_external_consensus_challenger_package(
    report_path: Path | str = Path("reports/external_consensus_challenger/summary.json"),
) -> dict[str, Any]:
    path = Path(report_path)
    if not path.exists():
        raise FileNotFoundError(f"Missing external consensus challenger report: {path}")
    report = _read_json(path)
    policy = report.get("policy") or {}
    config = policy.get("config") or {}
    source_decision = str(report.get("decision") or "EXTERNAL_CONSENSUS_PROSPECTIVE_COLLECTING")
    canonical_decision = (
        "OFFICIAL_SP_PROSPECTIVE_PASS"
        if source_decision == "EXTERNAL_CONSENSUS_PROSPECTIVE_PASS"
        else "OFFICIAL_SP_PROSPECTIVE_BLOCKED"
    )
    monthly = report.get("monthly") or []
    official_validation = {
        "source_decision": source_decision,
        "policy_id": policy.get("policy_id"),
        "policy_hash": policy.get("policy_hash"),
        "pool_passed_scorer": report.get("candidate_decisions", 0),
        "selected_snapshots": report.get("primary_horizon_candidates", 0),
        "settled_selected_snapshots": report.get("settled_selections", 0),
        "active_months": report.get("active_months", len(monthly)),
        "profit": report.get("profit", 0),
        "roi_pct": report.get("roi_pct", 0),
        "max_drawdown": report.get("max_drawdown", 0),
        "average_clv": report.get("average_clv"),
        "positive_clv_rate": report.get("positive_clv_rate"),
        "closing_sp_coverage": report.get("closing_sp_coverage", 0),
        "positive_months": report.get("positive_months", 0),
        "negative_months": report.get("negative_months", 0),
        "monthly": monthly,
        "daily": report.get("daily") or [],
        "statistical_evidence": report.get("statistical_evidence") or {},
        "decision": canonical_decision,
        "decision_reasons": report.get("decision_reasons") or [],
        "top_snapshot_blockers": (report.get("blocker_counts") or [])[:5],
    }
    return {
        "strategy_id": EXTERNAL_CONSENSUS_CHALLENGER_STRATEGY_ID,
        "name": "Pre-registered external consensus versus executable official-SP challenger",
        "status": source_decision,
        "evidence_basis": "PRE_REGISTERED_PROSPECTIVE",
        "recommended_for_shadow": True,
        "source_type": "EXTERNAL_CONSENSUS",
        "policy_id": policy.get("policy_id"),
        "policy_hash": policy.get("policy_hash"),
        "research_manifest_report": str(path),
        "selection": {
            "outcome": "DYNAMIC",
            "odds_source": "OFFICIAL_SP_EXECUTABLE",
            "min_predicted_ev": config.get("minimum_conservative_ev", 0.0),
            "max_bets_per_day": config.get("maximum_bets_per_day", 1),
            "primary_horizon_minutes": config.get("primary_horizon_minutes", 60),
            "horizon_tolerance_minutes": config.get("horizon_tolerance_minutes", 60),
        },
        "risk_control": {
            "daily_budget_cap": 100.0,
            "max_single_stake": 10.0,
            "max_bets_per_day": config.get("maximum_bets_per_day", 1),
            "uses_only_settled_results": True,
            "two_negative_months_trigger_cooldown": True,
        },
        "audit": {"decision": "PRE_REGISTERED_PROSPECTIVE_ONLY"},
        "calibration": {"decision": "PENDING_PROSPECTIVE_EXTERNAL_MARKET_CALIBRATION"},
        "official_validation": official_validation,
        "deployment_blockers": tuple(report.get("decision_reasons") or ()),
        "next_validation": (
            "Do not alter the registered policy while its 180-day prospective cohort is collecting.",
            "Require positive ROI/CLV lower bounds and paired calibration superiority to external consensus.",
            "Permit paper allocation only after the immutable prospective report passes.",
        ),
    }


def list_profit_strategy_packages() -> list[dict[str, Any]]:
    packages: list[dict[str, Any]] = []
    try:
        packages.append(build_market_anchored_i2_strategy_package().to_dict())
    except FileNotFoundError as exc:
        packages.append({
            "strategy_id": MARKET_ANCHORED_I2_DRAWS_STRATEGY_ID,
            "status": "MISSING_EVIDENCE_REPORTS",
            "error": str(exc),
        })
    try:
        packages.append(build_market_anchored_i2_avg_close_research_package())
    except FileNotFoundError as exc:
        packages.append({
            "strategy_id": MARKET_ANCHORED_I2_AVG_CLOSE_RESEARCH_ID,
            "status": "MISSING_RESEARCH_MANIFEST",
            "error": str(exc),
        })
    try:
        packages.append(build_market_anchored_sp1_home_research_package())
    except FileNotFoundError as exc:
        packages.append({
            "strategy_id": MARKET_ANCHORED_SP1_HOME_RESEARCH_ID,
            "status": "MISSING_EVIDENCE_REPORTS",
            "error": str(exc),
        })
    try:
        packages.append(build_external_consensus_challenger_package())
    except FileNotFoundError as exc:
        packages.append({
            "strategy_id": EXTERNAL_CONSENSUS_CHALLENGER_STRATEGY_ID,
            "status": "MISSING_PROSPECTIVE_REPORT",
            "error": str(exc),
        })
    return packages
