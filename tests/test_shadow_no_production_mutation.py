from football_agents.db import Database
from football_agents.live_shadow_validation import run_live_shadow_prediction
from football_agents.promotion_gate import evaluate_promotion_gate, save_promotion_gate_result
from football_agents.shadow_evaluator import ShadowValidationMetrics
from football_agents.shadow_prediction_store import ShadowPredictionStore
from football_agents.true_odds_config import get_default_true_odds_filter_config


def _metrics(config_version_id):
    return ShadowValidationMetrics(
        config_version_id=config_version_id, created_at="now", sample_count=250, evaluated_count=250,
        pending_count=0, void_count=0, baseline_recommendation_count=100, shadow_recommendation_count=70,
        shadow_blocked_count=30, shadow_added_count=0, baseline_roi=.02, shadow_roi=.04,
        baseline_average_clv=.00, shadow_average_clv=.02, baseline_positive_clv_rate=.50,
        shadow_positive_clv_rate=.58, baseline_hit_rate=.5, shadow_hit_rate=.55,
        baseline_max_drawdown=10, shadow_max_drawdown=9, blocked_recommendation_count=25,
        blocked_roi=-.1, blocked_average_clv=-.01, blocked_positive_clv_rate=.4,
        passed_recommendation_count=70, passed_roi=.04, passed_average_clv=.02,
        passed_positive_clv_rate=.58, high_edge_count=20, medium_edge_count=40,
        low_edge_count=10, no_edge_count=0, high_edge_roi=.05, medium_edge_roi=.03,
        recommendation_retention_rate=.7, no_bet_increase_rate=.3, warnings=[],
    )


def test_shadow_prediction_and_promotion_gate_do_not_mutate_production_state(tmp_path):
    database = Database(tmp_path / "shadow_no_mutation.db")
    database.initialize()
    store = ShadowPredictionStore(database)
    version = store.create_config_version(get_default_true_odds_filter_config(), name="no-mutation")
    baseline = {
        "officialSp": {"home": 2.1, "draw": 3.2, "away": 3.4},
        "finalProbability": {"home": .52, "draw": .27, "away": .21},
        "recommendation": "HOME",
        "recommendedEv": .092,
        "recommendedProbability": .52,
        "recommendedSp": 2.1,
        "stakeFraction": .01,
        "lifecycleStatus": "RECOMMENDED",
        "features": {"lambda_home": 1.4, "lambda_away": 1.1, "source_confidence": .8},
    }
    before = dict(baseline)

    run_live_shadow_prediction(
        {"id": "1", "official_match_id": "P1", "kickoff_time": "2027-01-01T12:00:00Z", "league": "L"},
        baseline,
        version,
        {"official_sp_snapshot_id": "sp1"},
    )
    assert baseline == before

    result = evaluate_promotion_gate(_metrics(version.config_version_id), version)
    assert result.decision == "ENABLE_FILTER_ONLY_RECOMMENDED"
    save_promotion_gate_result(result, _metrics(version.config_version_id))
    reloaded = store.get_config_version(version.config_version_id)
    assert reloaded is not None
    assert reloaded.status == "RECOMMENDED_FOR_FILTER_ONLY"
    assert reloaded.activated_at is None
    assert reloaded.promotion_status == "ENABLE_FILTER_ONLY_RECOMMENDED"
