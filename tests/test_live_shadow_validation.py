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


def test_i2_market_bias_shadow_candidate_can_add_draw_without_mutating_baseline(tmp_path):
    _, version = setup_store(tmp_path)
    match = {"id": "1", "official_match_id": "M3", "kickoff_time": "2027-01-01T12:00:00Z", "league": "Italian Serie B"}
    original = baseline("NO_BET")
    original["officialSp"] = {"home": 2.4, "draw": 3.1, "away": 3.0}
    record = run_live_shadow_prediction(match, original, version, {"official_sp_snapshot_id": "s3"})
    assert original["recommendation"] == "NO_BET"
    assert record["baseline_recommendation"] == "NO_BET"
    assert record["shadow_recommendation"] == "DRAW"
    assert record["shadow_selected_outcome"] == "DRAW"
    assert record["shadow_would_recommend_new"] == 1
    assert record["shadow_edge_quality_level"] == "MARKET_BIAS"
    assert record["shadow_ev"] == 0.0774


def test_i2_market_bias_shadow_candidate_requires_valid_draw_band(tmp_path):
    _, version = setup_store(tmp_path)
    match = {"id": "1", "official_match_id": "M4", "kickoff_time": "2027-01-01T12:00:00Z", "league": "Italian Serie B"}
    original = baseline("NO_BET")
    original["officialSp"] = {"home": 1.8, "draw": 3.7, "away": 4.2}
    record = run_live_shadow_prediction(match, original, version, {"official_sp_snapshot_id": "s4"})
    assert record["baseline_recommendation"] == "NO_BET"
    assert record["shadow_recommendation"] == "NO_BET"
    assert record["shadow_would_recommend_new"] == 0


def test_sp1_research_candidate_does_not_create_shadow_recommendation(tmp_path):
    _, version = setup_store(tmp_path)
    match = {"id": "1", "official_match_id": "M5", "kickoff_time": "2027-01-01T12:00:00Z", "league": "Spanish La Liga"}
    original = baseline("NO_BET")
    original["officialSp"] = {"home": 1.6, "draw": 4.0, "away": 5.0}
    record = run_live_shadow_prediction(match, original, version, {"official_sp_snapshot_id": "s5"})
    assert record["baseline_recommendation"] == "NO_BET"
    assert record["shadow_recommendation"] == "NO_BET"
    assert record["shadow_would_recommend_new"] == 0


def test_sp1_research_candidate_still_does_not_create_shadow_when_probability_is_low(tmp_path):
    _, version = setup_store(tmp_path)
    match = {"id": "1", "official_match_id": "M6", "kickoff_time": "2027-01-01T12:00:00Z", "league": "Spanish La Liga"}
    original = baseline("NO_BET")
    original["officialSp"] = {"home": 1.9, "draw": 3.5, "away": 4.0}
    record = run_live_shadow_prediction(match, original, version, {"official_sp_snapshot_id": "s6"})
    assert record["baseline_recommendation"] == "NO_BET"
    assert record["shadow_recommendation"] == "NO_BET"
    assert record["shadow_would_recommend_new"] == 0


def test_jpn_research_candidate_does_not_create_shadow_recommendation(tmp_path):
    _, version = setup_store(tmp_path)
    match = {"id": "1", "official_match_id": "M7", "kickoff_time": "2027-01-01T12:00:00Z", "league": "Japanese J1 League"}
    original = baseline("NO_BET")
    original["officialSp"] = {"home": 2.1, "draw": 3.2, "away": 3.2}
    record = run_live_shadow_prediction(match, original, version, {"official_sp_snapshot_id": "s7"})
    assert record["baseline_recommendation"] == "NO_BET"
    assert record["shadow_recommendation"] == "NO_BET"
    assert record["shadow_would_recommend_new"] == 0
