from football_agents.db import Database
from football_agents.live_shadow_validation import run_live_shadow_prediction
from football_agents.market_bias_official_validation import diagnose_market_bias_official_sp_funnel, validate_market_bias_on_official_sp
from football_agents.shadow_evaluator import build_shadow_validation_metrics, evaluate_pending_shadow_predictions, evaluate_shadow_prediction
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


def test_market_bias_shadow_added_draw_settles_with_draw_sp(tmp_path):
    database = Database(tmp_path / "market-bias-shadow.db")
    database.initialize()
    store = ShadowPredictionStore(database)
    version = store.create_config_version(get_default_true_odds_filter_config(), name="market-bias")
    record = run_live_shadow_prediction(
        {"id": "1", "official_match_id": "M2", "kickoff_time": "2027-01-01T12:00:00Z", "league": "Italian Serie B"},
        {"officialSp": {"home": 2.4, "draw": 3.1, "away": 3.0},
         "finalProbability": {"home": .42, "draw": .28, "away": .30}, "recommendation": "NO_BET"},
        version,
        {"official_sp_snapshot_id": "s2"},
    )
    result = evaluate_shadow_prediction(record, "DRAW", {"home": 2.3, "draw": 3.0, "away": 3.2})
    assert result["baseline_would_have_bet"] == 0
    assert result["shadow_would_have_bet"] == 1
    assert result["shadow_profit"] == 2.1
    assert result["shadow_clv"] == 3.1 / 3.0 - 1


def test_shadow_metrics_tracks_market_bias_i2_leaf_and_combo_strategy(tmp_path):
    database = Database(tmp_path / "market-bias-metrics.db")
    database.initialize()
    store = ShadowPredictionStore(database)
    version = store.create_config_version(get_default_true_odds_filter_config(), name="market-bias-metrics")
    i2_record = run_live_shadow_prediction(
        {"id": "1", "official_match_id": "M-I2", "kickoff_time": "2027-01-01T12:00:00Z", "league": "Italian Serie B"},
        {"officialSp": {"home": 2.4, "draw": 3.1, "away": 3.0},
         "finalProbability": {"home": .42, "draw": .28, "away": .30}, "recommendation": "NO_BET"},
        version,
        {"official_sp_snapshot_id": "s-i2"},
    )
    sp1_record = run_live_shadow_prediction(
        {"id": "2", "official_match_id": "M-SP1", "kickoff_time": "2027-01-02T12:00:00Z", "league": "Spanish La Liga"},
        {"officialSp": {"home": 1.6, "draw": 4.0, "away": 5.0},
         "finalProbability": {"home": .52, "draw": .24, "away": .24}, "recommendation": "NO_BET"},
        version,
        {"official_sp_snapshot_id": "s-sp1"},
    )
    evaluate_shadow_prediction(i2_record, "DRAW", {"home": 2.3, "draw": 3.0, "away": 3.2})
    evaluate_shadow_prediction(sp1_record, "HOME", {"home": 1.55, "draw": 4.2, "away": 5.4})

    metrics = build_shadow_validation_metrics(version.config_version_id)
    by_strategy = {row.strategy_id: row for row in metrics.market_bias_strategy_metrics}
    assert by_strategy["market-bias-i2-draw-2.8-3.5-v1"].profit == 2.1
    assert "market-bias-sp1-home-market-prob-0.55-1.00-v1" not in by_strategy
    combo = by_strategy["market-bias-i2-draw-plus-sp1-home-v1"]
    assert combo.sample_count == 1
    assert combo.evaluated_count == 1
    assert combo.profit == 2.1
    assert combo.roi == 2.1


def test_evaluate_pending_shadow_predictions_uses_stored_result_and_closing_sp(tmp_path):
    database = Database(tmp_path / "pending-shadow.db")
    database.initialize()
    from football_agents.repository import Repository

    repo = Repository(database)
    match_id = repo.create_match({
        "official_match_id": "sporttery-pending-i2",
        "league": "Italian Serie B",
        "home_team": "A",
        "away_team": "B",
        "kickoff_time": "2027-01-01T12:00:00+00:00",
        "status": "FINISHED",
    })
    repo.archive_official_odds_observation(
        match_id,
        "sporttery-pending-i2",
        {"home": 2.4, "draw": 3.1, "away": 3.0},
        "2027-01-01T10:00:00+00:00",
        "2027-01-01T12:00:00+00:00",
        "ON_SALE",
        "test",
        "local",
        "hash-pending-open",
    )
    repo.archive_official_odds_observation(
        match_id,
        "sporttery-pending-i2",
        {"home": 2.3, "draw": 3.0, "away": 3.2},
        "2027-01-01T11:50:00+00:00",
        "2027-01-01T12:00:00+00:00",
        "ON_SALE",
        "test",
        "local",
        "hash-pending-close",
    )
    store = ShadowPredictionStore(database)
    version = store.create_config_version(get_default_true_odds_filter_config(), name="pending")
    version = store.start_shadow_validation(version.config_version_id)
    run_live_shadow_prediction(
        {"id": str(match_id), "official_match_id": "sporttery-pending-i2", "kickoff_time": "2027-01-01T12:00:00+00:00", "league": "Italian Serie B"},
        {"officialSp": {"home": 2.4, "draw": 3.1, "away": 3.0},
         "finalProbability": {"home": .42, "draw": .28, "away": .30}, "recommendation": "NO_BET"},
        version,
        {"official_sp_snapshot_id": "s-pending"},
    )
    repo.upsert_result(match_id, 1, 1, "2027-01-01T14:00:00+00:00")

    report = evaluate_pending_shadow_predictions(version.config_version_id, database)
    metrics = build_shadow_validation_metrics(version.config_version_id)

    assert report["evaluated"] == 1
    assert report["pending"] == 0
    assert report["missing_closing"] == 0
    combo = {row.strategy_id: row for row in metrics.market_bias_strategy_metrics}["market-bias-i2-draw-plus-sp1-home-v1"]
    assert combo.evaluated_count == 1
    assert combo.profit == 2.1


def test_validate_market_bias_on_official_sp_uses_opening_snapshot_only(tmp_path):
    database = Database(tmp_path / "official-sp.db")
    database.initialize()
    from football_agents.repository import Repository

    repo = Repository(database)
    match_id = repo.create_match({
        "official_match_id": "sporttery-i2-1",
        "league": "Italian Serie B",
        "home_team": "A",
        "away_team": "B",
        "kickoff_time": "2027-01-15T12:00:00+00:00",
        "status": "FINISHED",
    })
    repo.archive_official_odds_observation(
        match_id,
        "sporttery-i2-1",
        {"home": 2.4, "draw": 3.1, "away": 3.0},
        "2027-01-14T12:00:00+00:00",
        "2027-01-15T12:00:00+00:00",
        "ON_SALE",
        "test",
        "local",
        "hash1",
    )
    repo.archive_official_odds_observation(
        match_id,
        "sporttery-i2-1",
        {"home": 2.1, "draw": 3.7, "away": 3.4},
        "2027-01-15T11:00:00+00:00",
        "2027-01-15T12:00:00+00:00",
        "ON_SALE",
        "test",
        "local",
        "hash2",
    )
    repo.upsert_result(match_id, 1, 1, "2027-01-15T14:00:00+00:00")

    report = validate_market_bias_on_official_sp(database)
    assert report.sample_count == 1
    assert report.candidate_count == 1
    assert report.profit == 2.1
    assert report.selections[0]["selected_sp"] == 3.1


def test_validate_market_bias_on_official_sp_sp1_research_strategy_no_longer_selects(tmp_path):
    database = Database(tmp_path / "official-sp-sp1.db")
    database.initialize()
    from football_agents.repository import Repository

    repo = Repository(database)
    match_id = repo.create_match({
        "official_match_id": "sporttery-sp1-1",
        "league": "Spanish La Liga",
        "home_team": "A",
        "away_team": "B",
        "kickoff_time": "2027-02-15T12:00:00+00:00",
        "status": "FINISHED",
    })
    repo.archive_official_odds_observation(
        match_id,
        "sporttery-sp1-1",
        {"home": 1.6, "draw": 4.0, "away": 5.0},
        "2027-02-14T12:00:00+00:00",
        "2027-02-15T12:00:00+00:00",
        "ON_SALE",
        "test",
        "local",
        "hash-sp1-open",
    )
    repo.archive_official_odds_observation(
        match_id,
        "sporttery-sp1-1",
        {"home": 1.9, "draw": 3.4, "away": 4.0},
        "2027-02-15T11:00:00+00:00",
        "2027-02-15T12:00:00+00:00",
        "ON_SALE",
        "test",
        "local",
        "hash-sp1-late",
    )
    repo.upsert_result(match_id, 2, 0, "2027-02-15T14:00:00+00:00")

    report = validate_market_bias_on_official_sp(
        database,
        strategy_id="market-bias-sp1-home-market-prob-0.55-1.00-v1",
    )
    assert report.strategy_id == "market-bias-sp1-home-market-prob-0.55-1.00-v1"
    assert report.sample_count == 1
    assert report.candidate_count == 0
    assert report.profit == 0
    assert report.selections == []


def test_validate_market_bias_on_official_sp_can_validate_i2_sp1_combo_strategy(tmp_path):
    database = Database(tmp_path / "official-sp-combo.db")
    database.initialize()
    from football_agents.repository import Repository

    repo = Repository(database)
    i2_match_id = repo.create_match({
        "official_match_id": "sporttery-i2-combo",
        "league": "Italian Serie B",
        "home_team": "I2A",
        "away_team": "I2B",
        "kickoff_time": "2027-03-01T12:00:00+00:00",
        "status": "FINISHED",
    })
    repo.archive_official_odds_observation(
        i2_match_id,
        "sporttery-i2-combo",
        {"home": 2.4, "draw": 3.1, "away": 3.0},
        "2027-02-28T12:00:00+00:00",
        "2027-03-01T12:00:00+00:00",
        "ON_SALE",
        "test",
        "local",
        "hash-i2-combo",
    )
    repo.upsert_result(i2_match_id, 1, 1, "2027-03-01T14:00:00+00:00")

    sp1_match_id = repo.create_match({
        "official_match_id": "sporttery-sp1-combo",
        "league": "Spanish La Liga",
        "home_team": "SP1A",
        "away_team": "SP1B",
        "kickoff_time": "2027-03-02T12:00:00+00:00",
        "status": "FINISHED",
    })
    repo.archive_official_odds_observation(
        sp1_match_id,
        "sporttery-sp1-combo",
        {"home": 1.6, "draw": 4.0, "away": 5.0},
        "2027-03-01T12:00:00+00:00",
        "2027-03-02T12:00:00+00:00",
        "ON_SALE",
        "test",
        "local",
        "hash-sp1-combo",
    )
    repo.upsert_result(sp1_match_id, 2, 0, "2027-03-02T14:00:00+00:00")

    report = validate_market_bias_on_official_sp(
        database,
        strategy_id="market-bias-i2-draw-plus-sp1-home-v1",
    )
    assert report.strategy_id == "market-bias-i2-draw-plus-sp1-home-v1"
    assert report.sample_count == 2
    assert report.candidate_count == 1
    assert report.profit == 2.1
    assert {row["strategy_id"] for row in report.selections} == {
        "market-bias-i2-draw-2.8-3.5-v1",
    }


def test_diagnose_market_bias_official_sp_funnel_explains_zero_or_small_samples(tmp_path):
    database = Database(tmp_path / "official-sp-funnel.db")
    database.initialize()
    from football_agents.repository import Repository

    repo = Repository(database)
    e0_id = repo.create_match({
        "official_match_id": "sporttery-e0-funnel",
        "league": "English Premier League",
        "home_team": "A",
        "away_team": "B",
        "kickoff_time": "2027-04-01T12:00:00+00:00",
        "status": "FINISHED",
    })
    i2_out_id = repo.create_match({
        "official_match_id": "sporttery-i2-out-band",
        "league": "Italian Serie B",
        "home_team": "C",
        "away_team": "D",
        "kickoff_time": "2027-04-02T12:00:00+00:00",
        "status": "FINISHED",
    })
    i2_unsettled_id = repo.create_match({
        "official_match_id": "sporttery-i2-unsettled",
        "league": "Italian Serie B",
        "home_team": "E",
        "away_team": "F",
        "kickoff_time": "2027-04-03T12:00:00+00:00",
        "status": "SCHEDULED",
    })
    i2_settled_id = repo.create_match({
        "official_match_id": "sporttery-i2-settled",
        "league": "Italian Serie B",
        "home_team": "G",
        "away_team": "H",
        "kickoff_time": "2027-04-04T12:00:00+00:00",
        "status": "FINISHED",
    })
    repo.archive_official_odds_observation(e0_id, "sporttery-e0-funnel", {"home": 2.0, "draw": 3.2, "away": 3.8},
                                           "2027-04-01T10:00:00+00:00", "2027-04-01T12:00:00+00:00", "ON_SALE", "test", "local", "h1")
    repo.archive_official_odds_observation(i2_out_id, "sporttery-i2-out-band", {"home": 1.8, "draw": 3.7, "away": 4.2},
                                           "2027-04-02T10:00:00+00:00", "2027-04-02T12:00:00+00:00", "ON_SALE", "test", "local", "h2")
    repo.archive_official_odds_observation(i2_unsettled_id, "sporttery-i2-unsettled", {"home": 2.4, "draw": 3.1, "away": 3.0},
                                           "2027-04-03T10:00:00+00:00", "2027-04-03T12:00:00+00:00", "ON_SALE", "test", "local", "h3")
    repo.archive_official_odds_observation(i2_settled_id, "sporttery-i2-settled", {"home": 2.4, "draw": 3.1, "away": 3.0},
                                           "2027-04-04T10:00:00+00:00", "2027-04-04T12:00:00+00:00", "ON_SALE", "test", "local", "h4")
    repo.upsert_result(e0_id, 1, 0, "2027-04-01T14:00:00+00:00")
    repo.upsert_result(i2_out_id, 1, 0, "2027-04-02T14:00:00+00:00")
    repo.upsert_result(i2_settled_id, 1, 1, "2027-04-04T14:00:00+00:00")

    report = diagnose_market_bias_official_sp_funnel(database)

    assert report["valid_three_way_samples"] == 4
    assert report["i2_opening_samples"] == 3
    assert report["i2_draw_band_samples"] == 2
    assert report["i2_draw_band_settled_samples"] == 1
    assert report["i2_draw_band_unsettled_samples"] == 1
    assert report["blocker"] == "settled target-band samples exist"
