from football_agents.db import Database
from football_agents.live_shadow_validation import run_live_shadow_prediction
from football_agents.shadow_prediction_store import ShadowPredictionStore
from football_agents.true_odds_config import get_default_true_odds_filter_config


def setup_store(tmp_path):
    database = Database(tmp_path / "shadow.db")
    database.initialize()
    store = ShadowPredictionStore(database)
    version = store.create_config_version(get_default_true_odds_filter_config(), name="test-shadow")
    return store, version


def baseline(recommendation="HOME"):
    return {
        "officialSp": {"home": 2.1, "draw": 3.2, "away": 3.4},
        "finalProbability": {"home": .52, "draw": .27, "away": .21},
        "recommendation": recommendation,
        "recommendedEv": .092,
        "recommendedProbability": .52,
        "recommendedSp": 2.1,
        "features": {"lambda_home": 1.4, "lambda_away": 1.1, "source_confidence": .8},
    }


def test_run_live_shadow_prediction_generates_record_and_does_not_change_baseline(tmp_path):
    store, version = setup_store(tmp_path)
    match = {"id": "1", "official_match_id": "M1", "kickoff_time": "2027-01-01T12:00:00Z", "league": "L"}
    original = baseline("HOME")
    record = run_live_shadow_prediction(match, original, version, {"official_sp_snapshot_id": "s1"})
    assert record["baseline_recommendation"] == "HOME"
    assert original["recommendation"] == "HOME"
    assert record["lifecycle_status"] == "PENDING_RESULT"
    duplicate = run_live_shadow_prediction(match, original, version, {"official_sp_snapshot_id": "s1"})
    assert duplicate["id"] == record["id"]
    assert len(store.list_shadow_predictions(version.config_version_id)) == 1


def test_shadow_new_recommendation_is_record_only(tmp_path):
    _, version = setup_store(tmp_path)
    match = {"id": "1", "official_match_id": "M2", "kickoff_time": "2027-01-01T12:00:00Z", "league": "L"}
    record = run_live_shadow_prediction(match, baseline("NO_BET"), version, {"official_sp_snapshot_id": "s2"})
    assert record["baseline_recommendation"] == "NO_BET"
    assert "shadow_would_recommend_new" in record
    assert record["lifecycle_status"] == "PENDING_RESULT"
