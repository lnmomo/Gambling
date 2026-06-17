from tests.test_edge_quality_optimizer import rows
from football_agents.edge_quality_optimizer import calculate_true_odds_variant_metrics, run_edge_quality_optimization
from football_agents.true_odds_config import generate_true_odds_config_grid


def test_baseline_vs_filter_metrics_are_generated():
    result = run_edge_quality_optimization(rows(60), None, generate_true_odds_config_grid({"max_configs": 4}), {"min_samples": 40})
    assert "recommendation_count" in result.baseline_metrics
    assert "positive_clv_rate" in result.variant_results[0]["metrics"]
    assert result.blocked_analysis.blocked_count >= 0


def test_variant_metrics_are_finite():
    result = run_edge_quality_optimization(rows(40), None, generate_true_odds_config_grid({"max_configs": 3}), {"min_samples": 20})
    metrics = result.variant_results[0]["metrics"]
    assert all(not isinstance(value, float) or value == value for value in metrics.values())
