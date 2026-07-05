import json
from pathlib import Path

from football_agents.db import Database
from football_agents.market_bias_monitor import MarketBiasMonitorService
from football_agents.repository import Repository


def write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _report_paths(tmp_path):
    return {
        "robustness": tmp_path / "reports" / "robustness.json",
        "portfolio": tmp_path / "reports" / "portfolio.json",
        "official_sp": tmp_path / "reports" / "official.json",
        "official_sp_funnel": tmp_path / "reports" / "official_funnel.json",
        "official_pool_relevance": tmp_path / "reports" / "official_pool_relevance.json",
        "promotion": tmp_path / "reports" / "promotion.json",
        "scorecard": tmp_path / "reports" / "scorecard.json",
        "multi_window": tmp_path / "reports" / "multi_window.json",
        "shadow_metrics": tmp_path / "reports" / "shadow_metrics.json",
    }


def _write_required_reports(paths):
    write_json(paths["robustness"], {
        "decision": "RESEARCH_CANDIDATE_SHADOW_VALIDATION",
        "total_runs": 24,
        "passed_runs": 22,
        "source_passes": 8,
        "profile_passes": 3,
        "rules": [
            "league|outcome|odds_bucket=I2|draw|[2.8,3.5)",
        ],
    })
    write_json(paths["portfolio"], {
        "overall": {"profit": 827.6, "roi_pct": 9.5, "max_drawdown": 225.0},
        "positive_months": 17,
        "negative_months": 11,
        "positive_seasons": 3,
        "negative_seasons": 1,
    })


def test_market_bias_monitor_can_skip_shadow_creation_when_requested(tmp_path):
    database = Database(tmp_path / "monitor.db")
    database.initialize()
    paths = _report_paths(tmp_path)
    _write_required_reports(paths)

    service = MarketBiasMonitorService(database, paths)
    result = service.refresh(run_shadow=True, ensure_shadow_config=False)

    assert result["promotion_decision"] == "SHADOW_READY_PRODUCTION_BLOCKED"
    assert result["active_shadow_configs"] == 0
    assert result["shadow_evaluations"] == []
    assert "no active shadow config version" in result["warnings"][0]
    assert paths["official_sp"].exists()
    assert paths["official_sp_funnel"].exists()
    assert paths["official_pool_relevance"].exists()
    assert paths["promotion"].exists()
    assert paths["scorecard"].exists()
    assert paths["shadow_metrics"].exists()
    assert json.loads(paths["promotion"].read_text(encoding="utf-8"))["strategy_id"] == "market-bias-i2-draw-2.8-3.5-v1"
    assert result["profit_algorithm_tier"] == "SHADOW_READY_PRODUCTION_BLOCKED"
    assert result["profit_algorithm_score"] >= 55
    assert result["official_sp_funnel_report"] == str(paths["official_sp_funnel"])
    assert result["official_pool_relevance_report"] == str(paths["official_pool_relevance"])


def test_market_bias_monitor_shadow_recommendation_uses_final_scorecard(tmp_path):
    database = Database(tmp_path / "monitor-scorecard.db")
    database.initialize()
    paths = _report_paths(tmp_path)
    _write_required_reports(paths)
    write_json(paths["multi_window"], {
        "candidate_summaries": [{
            "candidate_id": "market-bias-i2-draw-2.8-3.5-v1",
            "decision": "RESEARCH_ONLY_UNSTABLE_WINDOWS",
            "passed_windows": 3,
            "window_count": 12,
            "pass_rate": 0.25,
            "source_passes": 2,
            "source_count": 2,
            "combined_roi_pct": 2.57,
            "worst_window_roi_pct": -16.03,
        }],
    })

    result = MarketBiasMonitorService(database, paths).refresh(run_shadow=False, ensure_shadow_config=False)

    assert result["promotion_decision"] == "SHADOW_READY_PRODUCTION_BLOCKED"
    assert result["profit_algorithm_tier"] == "RESEARCH_ONLY_UNSTABLE_WINDOWS"
    assert result["recommended_for_shadow"] is False
    assert json.loads(paths["scorecard"].read_text(encoding="utf-8"))["recommended_for_shadow"] is False


def test_market_bias_monitor_creates_shadow_config_by_default(tmp_path):
    database = Database(tmp_path / "monitor-create.db")
    database.initialize()
    paths = _report_paths(tmp_path)
    _write_required_reports(paths)
    service = MarketBiasMonitorService(database, paths)

    result = service.refresh(run_shadow=True)

    assert result["active_shadow_configs"] == 1
    assert result["shadow_evaluations"][0]["pending"] == 0
    assert "created and started shadow config version" in result["warnings"][0]
    payload = json.loads(paths["shadow_metrics"].read_text(encoding="utf-8"))
    assert len(payload["active_config_versions"]) == 1


def test_market_bias_monitor_scans_live_i2_candidates(tmp_path):
    database = Database(tmp_path / "monitor-scan.db")
    database.initialize()
    repo = Repository(database)
    match_id = repo.create_match({
        "official_match_id": "sporttery-i2-live",
        "league": "Italian Serie B",
        "home_team": "A",
        "away_team": "B",
        "kickoff_time": "2027-01-01T12:00:00+00:00",
        "status": "scheduled",
    })
    with database.connect() as c:
        c.execute("UPDATE matches SET source_url=? WHERE id=?", ("test", match_id))
    repo.add_odds(match_id, {"home": 2.4, "draw": 3.1, "away": 3.0}, "official", "2027-01-01T10:00:00+00:00")
    paths = _report_paths(tmp_path)
    _write_required_reports(paths)

    result = MarketBiasMonitorService(database, paths).refresh(run_shadow=False)

    scan = result["live_candidate_scan"]
    assert scan["scanned_matches"] == 1
    assert scan["candidate_count"] == 1
    assert scan["candidate_counts_by_strategy"]["market-bias-i2-draw-2.8-3.5-v1"] == 1
    relevance = json.loads(paths["official_pool_relevance"].read_text(encoding="utf-8"))
    assert relevance["validated_shadow_candidates"] == 1
    assert relevance["leagues"][0]["strategy_coverage"] == "VALIDATED_SHADOW_RULE"


def test_market_bias_monitor_reports_sp1_as_research_watchlist(tmp_path):
    database = Database(tmp_path / "monitor-sp1-research.db")
    database.initialize()
    repo = Repository(database)
    match_id = repo.create_match({
        "official_match_id": "sporttery-sp1-research",
        "league": "Spanish La Liga",
        "home_team": "A",
        "away_team": "B",
        "kickoff_time": "2027-01-01T12:00:00+00:00",
        "status": "scheduled",
    })
    with database.connect() as c:
        c.execute("UPDATE matches SET source_url=? WHERE id=?", ("test", match_id))
    repo.add_odds(match_id, {"home": 1.6, "draw": 4.0, "away": 5.0}, "official", "2027-01-01T10:00:00+00:00")
    paths = _report_paths(tmp_path)
    _write_required_reports(paths)

    result = MarketBiasMonitorService(database, paths).refresh(run_shadow=False)

    scan = result["live_candidate_scan"]
    watchlist = scan["research_watchlist"]
    assert scan["candidate_count"] == 0
    assert watchlist["candidate_count"] == 1
    assert watchlist["candidate_counts_by_strategy"]["market-bias-sp1-home-market-prob-0.55-1.00-v1"] == 1
    assert watchlist["candidates"][0]["validation_stage"] == "RESEARCH_ONLY_UNSTABLE_WINDOWS"


def test_market_bias_monitor_reports_jpn_research_watchlist_separately(tmp_path):
    database = Database(tmp_path / "monitor-jpn-research.db")
    database.initialize()
    repo = Repository(database)
    match_id = repo.create_match({
        "official_match_id": "sporttery-jpn-research",
        "league": "Japanese J1 League",
        "home_team": "A",
        "away_team": "B",
        "kickoff_time": "2027-01-01T12:00:00+00:00",
        "status": "scheduled",
    })
    with database.connect() as c:
        c.execute("UPDATE matches SET source_url=? WHERE id=?", ("test", match_id))
    repo.add_odds(match_id, {"home": 2.1, "draw": 3.2, "away": 3.2}, "official", "2027-01-01T10:00:00+00:00")
    paths = _report_paths(tmp_path)
    _write_required_reports(paths)

    result = MarketBiasMonitorService(database, paths).refresh(run_shadow=False)

    scan = result["live_candidate_scan"]
    watchlist = scan["research_watchlist"]
    assert scan["candidate_count"] == 0
    assert watchlist["candidate_count"] == 1
    assert watchlist["candidate_counts_by_strategy"]["research-market-bias-jpn-away-market-prob-0.28-0.34-v1"] == 1
    assert watchlist["candidates"][0]["validation_stage"] == "RESEARCH_WATCH_ONLY"
