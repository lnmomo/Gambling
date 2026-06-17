from football_agents.edge_quality_optimizer import analyze_blocked_recommendations
from football_agents.edge_quality_optimizer import EdgeQualityBacktestRecord


def record(blocked: bool, profit: float, clv: float) -> EdgeQualityBacktestRecord:
    return EdgeQualityBacktestRecord(
        match_id="m", official_match_id="M", kickoff_time="2025-01-01", league="L", actual_result="HOME",
        baseline_recommendation="HOME", baseline_ev=.08, baseline_profit=profit, baseline_clv=clv,
        true_odds_recommendation="NO_BET" if blocked else "HOME", true_odds_ev=0 if blocked else .08,
        true_odds_profit=None if blocked else profit, true_odds_clv=None if blocked else clv,
        was_blocked_by_true_odds=blocked, block_reason="x" if blocked else None,
        edge_quality_score=50, edge_quality_level="LOW", lower_bound_ev=-.01, adaptive_ev_threshold=.04,
        method_agreement_score=.6, recommended_devig_method="POWER", outcome="HOME", odds_bucket="2.00-3.00",
        lower_bound_ev_bucket="<=0", edge_quality_bucket="35-55", market_quality="MEDIUM",
        model_disagreement_bucket="LOW", passed_true_odds_filter=not blocked,
    )


def test_blocked_analysis_counts_and_metrics_are_finite():
    records = [record(True, -1, -.02), record(True, 1, .01), record(False, 1, .02)]
    result = analyze_blocked_recommendations(records)
    assert result.blocked_count == 2
    assert result.blocked_ratio == 2 / 3
    assert result.would_have_lost_count == 1
    assert result.would_have_won_count == 1
    assert result.blocked_average_clv == (-.02 + .01) / 2
    assert result.warnings
