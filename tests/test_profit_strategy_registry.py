from __future__ import annotations

import json

from football_agents.profit_strategy_registry import (
    MARKET_ANCHORED_I2_AVG_CLOSE_RESEARCH_ID,
    MARKET_ANCHORED_I2_DRAWS_STRATEGY_ID,
    build_market_anchored_i2_avg_close_research_package,
    build_market_anchored_i2_strategy_package,
    list_profit_strategy_packages,
)


def test_build_market_anchored_i2_package_from_reports(tmp_path):
    historical = tmp_path / "historical.json"
    statistical = tmp_path / "statistical.json"
    calibration = tmp_path / "calibration.json"
    scorer = tmp_path / "scorer.json"
    historical.write_text(json.dumps({
        "overall": {"bets": 303, "profit": 644.1, "roi_pct": 21.26, "max_drawdown": 90.0},
        "positive_months": 25,
        "negative_months": 15,
        "window_summary": {"passed_windows": 5, "window_count": 6, "active_pass_rate": 0.8333},
        "risk_control": {"stop_after_losing_settlement_days": 3, "cooldown_days": 3},
    }), encoding="utf-8")
    statistical.write_text(json.dumps({
        "decision": "STATISTICALLY_SUPPORTED_RESEARCH_CANDIDATE",
        "overall": {"drawdown_to_profit": 0.1143},
        "bootstrap": {"roi_ci_pct": {"p05": 8.91}, "probability_roi_positive": 0.9975},
        "sign_flip_test": {"one_sided_p_value": 0.0065},
    }), encoding="utf-8")
    calibration.write_text(json.dumps({
        "decision": "CALIBRATED_EDGE_CONFIRMED",
        "overall": {
            "hit_rate": 0.3795,
            "wilson_hit_rate_lower_95": 0.3267,
            "avg_implied_probability": 0.3119,
            "conservative_edge_vs_implied": 0.0148,
        },
    }), encoding="utf-8")
    scorer.write_text(json.dumps({
        "artifact_type": "market_anchored_feature_residual_scorer",
        "selection": {"selected_rules": ["I2_draw_2p8_3p5"]},
    }), encoding="utf-8")

    package = build_market_anchored_i2_strategy_package(historical, statistical, calibration, scorer)

    assert package.strategy_id == MARKET_ANCHORED_I2_DRAWS_STRATEGY_ID
    assert package.status == "PROMOTE_TO_OFFICIAL_SP_SHADOW_VALIDATION"
    assert package.selection["market_residual_cap"] == 0.08
    assert package.scorer_artifact_report == str(scorer)
    assert package.risk_control["cooldown_days"] == 3
    assert package.historical_metrics["passed_windows"] == 5
    assert package.audit["sign_flip_p_value"] == 0.0065
    assert package.calibration["decision"] == "CALIBRATED_EDGE_CONFIRMED"
    assert "official SP" in package.deployment_blockers[0]
    assert not any("needs an exported residual model" in blocker for blocker in package.deployment_blockers)


def test_build_market_anchored_i2_avg_close_research_package_from_manifest(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "strategy_id": MARKET_ANCHORED_I2_AVG_CLOSE_RESEARCH_ID,
        "status": "RESEARCH_LEAD_FREEZE_FOR_PROSPECTIVE_SHADOW",
        "selection": {"league_family": "I2", "outcome": "DRAW", "odds_source": "AVG_CLOSE"},
        "risk_control": {"stop_after_losing_settlement_days": 3, "cooldown_days": 14},
        "evidence_reports": {
            "cooldown_grid": "reports/cooldown/summary.json",
            "scorer_artifact": "reports/scorer/scorer.json",
        },
        "historical_metrics": {
            "cooldown_best": {"bets": 218, "profit": 549.1, "roi_pct": 25.19, "passed_windows": 5},
        },
        "freeze_notes": ["shadow validation only"],
        "promotion_requirements": ["At least 200 settled selected official-SP shadow samples."],
        "blockers": ["historical reports use football-data AVG_CLOSE, not China Sporttery official SP"],
    }), encoding="utf-8")

    package = build_market_anchored_i2_avg_close_research_package(manifest)

    assert package["strategy_id"] == MARKET_ANCHORED_I2_AVG_CLOSE_RESEARCH_ID
    assert package["status"] == "RESEARCH_LEAD_FREEZE_FOR_PROSPECTIVE_SHADOW"
    assert package["selection"]["odds_source"] == "AVG_CLOSE"
    assert package["risk_control"]["cooldown_days"] == 14
    assert package["historical_metrics"]["roi_pct"] == 25.19
    assert package["audit"]["decision"] == "PENDING_STATISTICAL_AUDIT"
    assert package["calibration"]["decision"] == "PENDING_EDGE_CALIBRATION"
    assert "official-SP" in package["next_validation"][0]
    assert package["deployment_blockers"][0].startswith("historical reports")


def test_avg_close_research_package_reads_optional_audit_and_calibration(tmp_path):
    statistical = tmp_path / "statistical.json"
    calibration = tmp_path / "calibration.json"
    pool = tmp_path / "pool.json"
    official_sp = tmp_path / "official_sp.json"
    manifest = tmp_path / "manifest.json"
    statistical.write_text(json.dumps({
        "decision": "STATISTICALLY_SUPPORTED_RESEARCH_CANDIDATE",
        "overall": {"drawdown_to_profit": 0.185},
        "bootstrap": {"roi_ci_pct": {"p05": 8.79}, "probability_roi_positive": 0.9934},
        "sign_flip_test": {"one_sided_p_value": 0.0128},
        "decision_reasons": [],
    }), encoding="utf-8")
    calibration.write_text(json.dumps({
        "decision": "CALIBRATED_EDGE_CONFIRMED",
        "overall": {
            "hit_rate": 0.3991,
            "wilson_hit_rate_lower_95": 0.3364,
            "avg_implied_probability": 0.3161,
            "conservative_edge_vs_implied": 0.0202,
        },
        "decision_reasons": [],
    }), encoding="utf-8")
    pool.write_text(json.dumps({
        "scanned_matches": 100,
        "scored_matches": 0,
        "passed_scorer": 0,
        "blocker_counts": [{"reason": "league_not_i2", "matches": 100}],
    }), encoding="utf-8")
    official_sp.write_text(json.dumps({
        "opening_pre_match_snapshots": 28,
        "scored_snapshots": 0,
        "selected_snapshots": 0,
        "settled_selected_snapshots": 0,
        "decision": "OFFICIAL_SP_PROSPECTIVE_BLOCKED",
        "decision_reasons": ["settled_selected<200"],
        "blocker_counts": [{"reason": "league_not_i2", "snapshots": 28}],
    }), encoding="utf-8")
    manifest.write_text(json.dumps({
        "strategy_id": MARKET_ANCHORED_I2_AVG_CLOSE_RESEARCH_ID,
        "status": "STATISTICALLY_CALIBRATED_RESEARCH_LEAD_WAITING_OFFICIAL_SP_SHADOW",
        "selection": {"league_family": "I2", "outcome": "DRAW", "odds_source": "AVG_CLOSE"},
        "risk_control": {"stop_after_losing_settlement_days": 3, "cooldown_days": 14},
        "evidence_reports": {
            "statistical_audit": str(statistical),
            "edge_calibration": str(calibration),
            "official_pool_diagnosis": str(pool),
            "official_sp_validation": str(official_sp),
            "cooldown_grid": "reports/cooldown/summary.json",
        },
        "historical_metrics": {"cooldown_best": {"bets": 218, "roi_pct": 25.19}},
        "promotion_requirements": ["At least 200 settled selected official-SP shadow samples."],
        "blockers": ["official pool currently has insufficient I2 eligible settled snapshots"],
    }), encoding="utf-8")

    package = build_market_anchored_i2_avg_close_research_package(manifest)

    assert package["status"] == "STATISTICALLY_CALIBRATED_RESEARCH_LEAD_WAITING_OFFICIAL_SP_SHADOW"
    assert package["statistical_audit_report"] == str(statistical)
    assert package["edge_calibration_report"] == str(calibration)
    assert package["audit"]["decision"] == "STATISTICALLY_SUPPORTED_RESEARCH_CANDIDATE"
    assert package["audit"]["bootstrap_roi_p05"] == 8.79
    assert package["audit"]["sign_flip_p_value"] == 0.0128
    assert package["calibration"]["decision"] == "CALIBRATED_EDGE_CONFIRMED"
    assert package["calibration"]["conservative_edge_vs_implied"] == 0.0202
    assert package["official_validation"]["pool_scanned_matches"] == 100
    assert package["official_validation"]["opening_pre_match_snapshots"] == 28
    assert package["official_validation"]["settled_selected_snapshots"] == 0
    assert package["official_validation"]["decision"] == "OFFICIAL_SP_PROSPECTIVE_BLOCKED"
    assert package["official_validation"]["top_pool_blockers"][0]["reason"] == "league_not_i2"


def test_list_profit_strategy_packages_includes_registered_candidates():
    packages = list_profit_strategy_packages()
    strategy_ids = {package["strategy_id"] for package in packages}

    assert MARKET_ANCHORED_I2_DRAWS_STRATEGY_ID in strategy_ids
    assert MARKET_ANCHORED_I2_AVG_CLOSE_RESEARCH_ID in strategy_ids
