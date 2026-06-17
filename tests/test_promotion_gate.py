from football_agents.promotion_gate import evaluate_promotion_gate
from football_agents.shadow_evaluator import ShadowValidationMetrics
from football_agents.shadow_prediction_store import TrueOddsConfigVersion
from football_agents.true_odds_config import get_default_true_odds_filter_config


def metrics(**overrides):
    base = dict(config_version_id="v", created_at="now", sample_count=250, evaluated_count=250, pending_count=0, void_count=0,
                baseline_recommendation_count=100, shadow_recommendation_count=70, shadow_blocked_count=30, shadow_added_count=0,
                baseline_roi=.02, shadow_roi=.04, baseline_average_clv=.00, shadow_average_clv=.02,
                baseline_positive_clv_rate=.50, shadow_positive_clv_rate=.58, baseline_hit_rate=.5, shadow_hit_rate=.55,
                baseline_max_drawdown=10, shadow_max_drawdown=9, blocked_recommendation_count=25,
                blocked_roi=-.1, blocked_average_clv=-.01, blocked_positive_clv_rate=.4,
                passed_recommendation_count=70, passed_roi=.04, passed_average_clv=.02, passed_positive_clv_rate=.58,
                high_edge_count=20, medium_edge_count=40, low_edge_count=10, no_edge_count=0,
                high_edge_roi=.05, medium_edge_roi=.03, recommendation_retention_rate=.7, no_bet_increase_rate=.3, warnings=[])
    return ShadowValidationMetrics(**{**base, **overrides})


def version(mode="FILTER_ONLY"):
    config = get_default_true_odds_filter_config()
    config.mode = mode
    return TrueOddsConfigVersion("v", "v", config)


def test_promotion_gate_recommends_when_shadow_metrics_pass():
    result = evaluate_promotion_gate(metrics(), version())
    assert result.decision == "ENABLE_FILTER_ONLY_RECOMMENDED"
    assert result.recommended_for_production
    assert result.requires_human_confirmation


def test_promotion_gate_needs_more_data_and_blocks_adjust_probability():
    assert evaluate_promotion_gate(metrics(evaluated_count=20), version()).decision == "NEED_MORE_DATA"
    result = evaluate_promotion_gate(metrics(), version("ADJUST_PROBABILITY"))
    assert not result.recommended_for_production
    assert any(rule.rule_id == "mode" and not rule.passed for rule in result.rules)
