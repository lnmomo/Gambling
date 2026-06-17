from football_agents.db import Database
from football_agents.live_shadow_validation import run_live_shadow_prediction
from football_agents.shadow_evaluator import evaluate_shadow_prediction
from football_agents.shadow_prediction_store import ShadowPredictionStore
from football_agents.true_odds_config import get_default_true_odds_filter_config


def test_shadow_prediction_does_not_read_result_or_closing(tmp_path):
    database = Database(tmp_path / "leak.db")
    database.initialize()
    version = ShadowPredictionStore(database).create_config_version(get_default_true_odds_filter_config(), name="leak")
    record = run_live_shadow_prediction(
        {"id": "1", "official_match_id": "M1", "kickoff_time": "2027-01-01T12:00:00Z", "league": "L", "actual_result": "AWAY"},
        {"officialSp": {"home": 2.1, "draw": 3.2, "away": 3.4}, "finalProbability": {"home": .6, "draw": .22, "away": .18}, "recommendation": "HOME"},
        version,
        {"official_sp_snapshot_id": "s", "closing_sp": {"home": 1.8, "draw": 3.5, "away": 4}},
    )
    assert record["lifecycle_status"] == "PENDING_RESULT"
    assert "actual_result" not in (record["true_odds_estimate"] or {})
    result = evaluate_shadow_prediction(record, "AWAY", {"home": 1.8, "draw": 3.5, "away": 4})
    assert result["evaluation_status"] == "EVALUATED"
