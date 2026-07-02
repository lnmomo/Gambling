from __future__ import annotations

import json

from football_agents.profit_strategy_registry import (
    MARKET_ANCHORED_I2_DRAWS_STRATEGY_ID,
    build_market_anchored_i2_strategy_package,
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
