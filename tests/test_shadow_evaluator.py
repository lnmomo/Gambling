from football_agents.db import Database
from football_agents.live_shadow_validation import run_live_shadow_prediction
from football_agents.shadow_evaluator import build_shadow_validation_metrics, evaluate_shadow_prediction
from football_agents.shadow_prediction_store import ShadowPredictionStore
from football_agents.true_odds_config import get_default_true_odds_filter_config


def make_prediction(tmp_path):
    database = Database(tmp_path / "eval.db")
    database.initialize()
    store = ShadowPredictionStore(database)
    version = store.create_config_version(get_default_true_odds_filter_config(), name="eval")
    record = run_live_shadow_prediction(
        {"id": "1", "official_match_id": "M1", "kickoff_time": "2027-01-01T12:00:00Z", "league": "L"},
        {"officialSp": {"home": 2.1, "draw": 3.2, "away": 3.4}, "finalProbability": {"home": .6, "draw": .22, "away": .18},
         "recommendation": "HOME", "recommendedEv": .26, "recommendedProbability": .6, "recommendedSp": 2.1},
        version,
        {"official_sp_snapshot_id": "s"},
    )
    return version, record


def test_evaluate_shadow_prediction_profit_and_clv(tmp_path):
    version, record = make_prediction(tmp_path)
    result = evaluate_shadow_prediction(record, "HOME", {"home": 2.0, "draw": 3.3, "away": 3.6})
    assert result["baseline_profit"] == 1.1
    assert result["baseline_clv"] == 2.1 / 2.0 - 1
    metrics = build_shadow_validation_metrics(version.config_version_id)
    assert metrics.evaluated_count == 1


def test_missing_result_and_closing_are_safe(tmp_path):
    _, record = make_prediction(tmp_path)
    result = evaluate_shadow_prediction(record, None, None)
    assert result["evaluation_status"] == "MISSING_RESULT"
