import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from market_bias_profit_algorithm_scorecard import evaluate_profit_algorithm_scorecard  # noqa: E402


def _promotion(decision="SHADOW_READY_PRODUCTION_BLOCKED"):
    return {
        "decision": decision,
        "recommended_for_shadow": decision in {
            "SHADOW_READY_PRODUCTION_BLOCKED",
            "PRODUCTION_CANDIDATE_REQUIRES_HUMAN_CONFIRMATION",
        },
        "recommended_for_production": decision == "PRODUCTION_CANDIDATE_REQUIRES_HUMAN_CONFIRMATION",
        "failed_blocking_checks": [],
        "failed_production_checks": ["official_sample"],
    }


def test_scorecard_keeps_strong_historical_strategy_in_shadow_until_official_sp_passes():
    result = evaluate_profit_algorithm_scorecard(
        strategy_id="market-bias-i2-draw-plus-sp1-home-v1",
        rule=None,
        robustness={
            "decision": "RESEARCH_CANDIDATE_SHADOW_VALIDATION",
            "total_runs": 24,
            "passed_runs": 22,
            "source_passes": 8,
            "profile_passes": 3,
        },
        portfolio={
            "method": "settlement-aware market-bias portfolio simulation",
            "overall": {"profit": 1040.1, "roi_pct": 10.03, "max_drawdown": 143.1},
            "positive_months": 19,
            "negative_months": 12,
            "positive_seasons": 4,
            "negative_seasons": 0,
        },
        official_sp={"settled_candidate_count": 0, "roi_pct": 0.0, "monthly": []},
        promotion=_promotion(),
    )

    assert result["deployment_tier"] == "SHADOW_READY_PRODUCTION_BLOCKED"
    assert result["recommended_for_shadow"] is True
    assert result["recommended_for_production"] is False
    assert result["components"]["official_sp_prospective"]["score"] == 0.0


def test_scorecard_keeps_shadow_when_multi_window_gate_passes():
    result = evaluate_profit_algorithm_scorecard(
        strategy_id="market-bias-i2-draw-2.8-3.5-v1",
        rule=None,
        robustness={
            "decision": "RESEARCH_CANDIDATE_SHADOW_VALIDATION",
            "total_runs": 24,
            "passed_runs": 22,
            "source_passes": 8,
            "profile_passes": 3,
        },
        portfolio={
            "method": "settlement-aware market-bias portfolio simulation",
            "overall": {"profit": 827.6, "roi_pct": 9.5, "max_drawdown": 225.0},
            "positive_months": 17,
            "negative_months": 11,
            "positive_seasons": 3,
            "negative_seasons": 1,
        },
        official_sp={"settled_candidate_count": 0, "roi_pct": 0.0, "monthly": []},
        promotion=_promotion(),
        multi_window={
            "candidate_summaries": [{
                "candidate_id": "market-bias-i2-draw-2.8-3.5-v1",
                "decision": "MULTI_WINDOW_SHADOW_CANDIDATE",
                "passed_windows": 8,
                "window_count": 12,
                "pass_rate": 0.6667,
                "source_passes": 2,
                "source_count": 2,
                "combined_roi_pct": 8.85,
                "worst_window_roi_pct": -5.48,
            }],
        },
        statistical_audit={
            "decision": "STATISTICALLY_SUPPORTED_RESEARCH_CANDIDATE",
            "overall": {"bets": 871, "active_months": 28, "roi_pct": 9.5},
            "bootstrap": {"roi_ci_pct": {"p05": 1.85}, "probability_roi_positive": 0.9802},
            "sign_flip_test": {"one_sided_p_value": 0.0314},
        },
        edge_calibration={
            "decision": "CALIBRATED_EDGE_CONFIRMED",
            "overall": {
                "bets": 871,
                "hit_rate": 0.35,
                "wilson_hit_rate_lower_95": 0.33,
                "avg_implied_probability": 0.31,
                "edge_vs_implied_probability": 0.04,
                "conservative_edge_vs_implied": 0.02,
                "roi_pct": 9.5,
            },
        },
    )

    assert result["deployment_tier"] == "SHADOW_READY_PRODUCTION_BLOCKED"
    assert result["components"]["multi_window_validation"]["decision"] == "MULTI_WINDOW_SHADOW_CANDIDATE"
    assert result["components"]["statistical_audit"]["decision"] == "STATISTICALLY_SUPPORTED_RESEARCH_CANDIDATE"
    assert result["components"]["edge_calibration"]["decision"] == "CALIBRATED_EDGE_CONFIRMED"


def test_scorecard_downgrades_shadow_when_statistical_audit_fails():
    result = evaluate_profit_algorithm_scorecard(
        strategy_id="market-bias-i2-draw-2.8-3.5-v1",
        rule=None,
        robustness={
            "decision": "RESEARCH_CANDIDATE_SHADOW_VALIDATION",
            "total_runs": 24,
            "passed_runs": 22,
            "source_passes": 8,
            "profile_passes": 3,
        },
        portfolio={
            "method": "settlement-aware market-bias portfolio simulation",
            "overall": {"profit": 827.6, "roi_pct": 9.5, "max_drawdown": 225.0},
            "positive_months": 17,
            "negative_months": 11,
            "positive_seasons": 3,
            "negative_seasons": 1,
        },
        official_sp={"settled_candidate_count": 0, "roi_pct": 0.0, "monthly": []},
        promotion=_promotion(),
        multi_window={
            "candidate_summaries": [{
                "candidate_id": "market-bias-i2-draw-2.8-3.5-v1",
                "decision": "MULTI_WINDOW_SHADOW_CANDIDATE",
                "passed_windows": 8,
                "window_count": 12,
                "pass_rate": 0.6667,
                "source_passes": 2,
                "source_count": 2,
                "combined_roi_pct": 8.85,
                "worst_window_roi_pct": -5.48,
            }],
        },
        statistical_audit={
            "decision": "POSITIVE_BUT_NOT_STATISTICALLY_CONFIRMED",
            "overall": {"bets": 871, "active_months": 28, "roi_pct": 9.5},
            "bootstrap": {"roi_ci_pct": {"p05": -1.0}, "probability_roi_positive": 0.81},
            "sign_flip_test": {"one_sided_p_value": 0.20},
            "decision_reasons": ["bootstrap_roi_p05<=0"],
        },
    )

    assert result["deployment_tier"] == "RESEARCH_ONLY_STATISTICALLY_WEAK"
    assert result["recommended_for_shadow"] is False


def test_scorecard_downgrades_shadow_when_edge_calibration_is_not_conservative():
    result = evaluate_profit_algorithm_scorecard(
        strategy_id="market-bias-i2-draw-2.8-3.5-v1",
        rule=None,
        robustness={
            "decision": "RESEARCH_CANDIDATE_SHADOW_VALIDATION",
            "total_runs": 24,
            "passed_runs": 22,
            "source_passes": 8,
            "profile_passes": 3,
        },
        portfolio={
            "method": "settlement-aware market-bias portfolio simulation",
            "overall": {"profit": 827.6, "roi_pct": 9.5, "max_drawdown": 225.0},
            "positive_months": 17,
            "negative_months": 11,
            "positive_seasons": 3,
            "negative_seasons": 1,
        },
        official_sp={"settled_candidate_count": 0, "roi_pct": 0.0, "monthly": []},
        promotion=_promotion(),
        multi_window={
            "candidate_summaries": [{
                "candidate_id": "market-bias-i2-draw-2.8-3.5-v1",
                "decision": "MULTI_WINDOW_SHADOW_CANDIDATE",
                "passed_windows": 8,
                "window_count": 12,
                "pass_rate": 0.6667,
                "source_passes": 2,
                "source_count": 2,
                "combined_roi_pct": 8.85,
                "worst_window_roi_pct": -5.48,
            }],
        },
        statistical_audit={
            "decision": "STATISTICALLY_SUPPORTED_RESEARCH_CANDIDATE",
            "overall": {"bets": 871, "active_months": 28, "roi_pct": 9.5},
            "bootstrap": {"roi_ci_pct": {"p05": 1.85}, "probability_roi_positive": 0.9802},
            "sign_flip_test": {"one_sided_p_value": 0.0314},
        },
        edge_calibration={
            "decision": "POSITIVE_EDGE_BUT_NOT_CONSERVATIVE",
            "overall": {
                "bets": 871,
                "hit_rate": 0.3479,
                "wilson_hit_rate_lower_95": 0.317,
                "avg_implied_probability": 0.3174,
                "edge_vs_implied_probability": 0.0305,
                "conservative_edge_vs_implied": -0.0004,
                "roi_pct": 9.5,
            },
            "decision_reasons": ["wilson_lower<=average_implied_probability"],
        },
    )

    assert result["deployment_tier"] == "RESEARCH_ONLY_CALIBRATION_WEAK"
    assert result["recommended_for_shadow"] is False


def test_scorecard_matches_multi_window_candidate_without_version_suffix():
    result = evaluate_profit_algorithm_scorecard(
        strategy_id="market-bias-i2-draw-2.80-3.30-v1",
        rule=None,
        robustness={
            "decision": "RESEARCH_CANDIDATE_SHADOW_VALIDATION",
            "total_runs": 24,
            "passed_runs": 21,
            "source_passes": 8,
            "profile_passes": 3,
        },
        portfolio={
            "method": "settlement-aware market-bias portfolio simulation",
            "overall": {"profit": 410.6, "roi_pct": 5.47, "max_drawdown": 223.1},
            "positive_months": 16,
            "negative_months": 13,
            "positive_seasons": 4,
            "negative_seasons": 0,
        },
        official_sp={"settled_candidate_count": 0, "roi_pct": 0.0, "monthly": []},
        promotion=_promotion(),
        multi_window={
            "summaries": [{
                "candidate_id": "market-bias-i2-draw-2.80-3.30",
                "decision": "MULTI_WINDOW_SHADOW_CANDIDATE",
                "passed_windows": 15,
                "window_count": 24,
                "pass_rate": 0.625,
                "source_passes": 4,
                "source_count": 4,
                "combined_roi_pct": 10.64,
                "worst_window_roi_pct": -12.23,
            }],
        },
    )

    assert result["components"]["multi_window_validation"]["available"] is True
    assert result["components"]["multi_window_validation"]["passed_windows"] == 15


def test_scorecard_downgrades_shadow_when_multi_window_gate_fails():
    result = evaluate_profit_algorithm_scorecard(
        strategy_id="market-bias-i2-draw-plus-sp1-home-v1",
        rule=None,
        robustness={
            "decision": "RESEARCH_CANDIDATE_SHADOW_VALIDATION",
            "total_runs": 24,
            "passed_runs": 22,
            "source_passes": 8,
            "profile_passes": 3,
        },
        portfolio={
            "method": "settlement-aware market-bias portfolio simulation",
            "overall": {"profit": 1040.1, "roi_pct": 10.03, "max_drawdown": 143.1},
            "positive_months": 19,
            "negative_months": 12,
            "positive_seasons": 4,
            "negative_seasons": 0,
        },
        official_sp={"settled_candidate_count": 0, "roi_pct": 0.0, "monthly": []},
        promotion=_promotion(),
        multi_window={
            "candidate_summaries": [{
                "candidate_id": "market-bias-i2-draw-plus-sp1-home-v1",
                "decision": "RESEARCH_ONLY_UNSTABLE_WINDOWS",
                "passed_windows": 7,
                "window_count": 12,
                "pass_rate": 0.5833,
                "source_passes": 2,
                "source_count": 2,
                "combined_roi_pct": 8.81,
                "worst_window_roi_pct": -5.61,
            }],
        },
    )

    assert result["pre_multi_window_tier"] == "SHADOW_READY_PRODUCTION_BLOCKED"
    assert result["deployment_tier"] == "RESEARCH_ONLY_UNSTABLE_WINDOWS"
    assert result["recommended_for_shadow"] is False


def test_scorecard_keeps_cross_source_candidate_as_research_when_promotion_blocks_it():
    rule = "league|outcome|market_prob_bucket=JPN|away|[0.28,0.34)"
    result = evaluate_profit_algorithm_scorecard(
        strategy_id="research-market-bias-jpn-away-market-prob-0.28-0.34-v1",
        rule=rule,
        robustness={
            "decision": "KEEP_SHADOW_ONLY",
            "total_runs": 12,
            "passed_runs": 4,
            "source_passes": 2,
            "profile_passes": 3,
        },
        portfolio={
            "method": "settlement-aware market-bias portfolio simulation",
            "overall": {"profit": 211.4, "roi_pct": 6.24, "max_drawdown": 165.8},
            "positive_months": 7,
            "negative_months": 4,
            "positive_seasons": 2,
            "negative_seasons": 0,
        },
        official_sp={"settled_candidate_count": 0, "roi_pct": 0.0, "monthly": []},
        promotion={
            "decision": "REJECT_RESEARCH_CANDIDATE",
            "recommended_for_shadow": False,
            "recommended_for_production": False,
            "failed_blocking_checks": ["robust_decision", "source_passes"],
            "failed_production_checks": ["official_sample"],
        },
        candidate_screen={
            "rule_summary": [{
                "rule": rule,
                "validation_source_count": 2,
                "passed_validation_sources": 2,
                "combined_roi_pct": 5.45,
                "worst_source_roi_pct": 4.79,
                "total_portfolio_bets": 741,
                "passes_all_validation_sources": True,
            }],
        },
    )

    assert result["deployment_tier"] == "RESEARCH_WATCH_ONLY"
    assert result["recommended_for_shadow"] is False
    assert result["blocking_checks_failed"] == ["robust_decision", "source_passes"]
