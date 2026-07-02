from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


MARKET_ANCHORED_I2_DRAWS_STRATEGY_ID = "profit-i2-draw-market-anchored-stop3-cool3-v1"
MARKET_ANCHORED_I2_AVG_CLOSE_RESEARCH_ID = "profit-i2-draw-market-anchored-avg-close-stop3-cool14-v1"


@dataclass(frozen=True)
class ProfitStrategyPackage:
    strategy_id: str
    name: str
    status: str
    historical_report: str
    statistical_audit_report: str
    edge_calibration_report: str
    scorer_artifact_report: str | None
    selection: dict[str, Any]
    risk_control: dict[str, Any]
    historical_metrics: dict[str, Any]
    audit: dict[str, Any]
    calibration: dict[str, Any]
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


def build_market_anchored_i2_strategy_package(
    historical_report: Path | str = Path("reports/feature_enriched_market_anchored_i2_stop3_cool3_v1/summary.json"),
    statistical_audit_report: Path | str = Path("reports/strategy_statistical_audit_market_anchored_i2_stop3_cool3_v1/summary.json"),
    edge_calibration_report: Path | str = Path("reports/strategy_edge_calibration_market_anchored_i2_stop3_cool3_v1/summary.json"),
    scorer_artifact_report: Path | str = Path("reports/feature_enriched_market_anchored_i2_scorer_v1/scorer.json"),
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
    historical_overall = historical.get("overall", {})
    window_summary = historical.get("window_summary", {})
    audit_overall = statistical.get("overall", {})
    calibration_overall = calibration.get("overall", {})
    status = "PROMOTE_TO_OFFICIAL_SP_SHADOW_VALIDATION"
    blockers = [
        "historical validation uses football-data AVG_OPEN, not collected China Sporttery official SP snapshots",
        "first rolling annual window remains weak, so production allocation is blocked until prospective official-SP evidence accumulates",
    ]
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
        "decision": (official_sp or {}).get("decision", "PENDING_OFFICIAL_SP_VALIDATION"),
        "decision_reasons": (official_sp or {}).get("decision_reasons", []),
        "top_pool_blockers": (official_pool or {}).get("blocker_counts", [])[:5],
        "top_snapshot_blockers": (official_sp or {}).get("blocker_counts", [])[:5],
    }
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
    return packages
