from pathlib import Path
from unittest.mock import patch

from football_agents.db import Database
from football_agents.official_pool_research import plan_official_pool_profit_research
from football_agents.official_pool_research import _world_cup_validation_evidence
from football_agents.repository import Repository


def _official_match(repo: Repository, league: str, suffix: str = "1") -> int:
    match_id = repo.create_match({
        "official_match_id": f"sporttery-research-{league}-{suffix}",
        "league": league,
        "home_team": "A",
        "away_team": "B",
        "kickoff_time": "2027-01-01T12:00:00+00:00",
        "status": "scheduled",
    })
    with repo.db.connect() as c:
        c.execute("UPDATE matches SET source_url=? WHERE id=?", ("test", match_id))
    return match_id


def test_official_pool_profit_research_requires_world_cup_odds_history(tmp_path):
    database = Database(tmp_path / "pool-world-cup.db")
    database.initialize()
    repo = Repository(database)
    match_id = _official_match(repo, "\u4e16\u754c\u676f")
    repo.add_odds(match_id, {"home": 2.2, "draw": 3.1, "away": 3.3}, "official")

    with patch("football_agents.official_pool_research._history_paths", return_value=[]):
        report = plan_official_pool_profit_research(database)

    assert report["official_matches"] == 1
    league = report["leagues"][0]
    assert league["mapped_history_code"] == "WORLD_CUP"
    assert league["historical_odds_available"] is False
    assert league["evidence_status"] == "missing_historical_1x2_odds"
    assert "odds-edge validation requires historical 1X2 prices" in league["blocker"]


def test_official_pool_profit_research_detects_archived_world_cup_odds(tmp_path):
    database = Database(tmp_path / "pool-world-cup-odds.db")
    database.initialize()
    repo = Repository(database)
    match_id = _official_match(repo, "\u4e16\u754c\u676f")
    repo.add_odds(match_id, {"home": 2.2, "draw": 3.1, "away": 3.3}, "official")

    archived = tmp_path / "WORLD_CUP.csv"
    archived.write_text("Date,Home,Away,HG,AG,AvgCH,AvgCD,AvgCA\n", encoding="utf-8")
    with (
        patch("football_agents.official_pool_research._history_paths", return_value=[Path(archived)]),
        patch("football_agents.official_pool_research._world_cup_validation_evidence", return_value=None),
    ):
        report = plan_official_pool_profit_research(database)

    league = report["leagues"][0]
    assert league["mapped_history_code"] == "WORLD_CUP"
    assert league["historical_odds_available"] is True
    assert league["evidence_status"] == "historical_1x2_odds_collected_needs_walk_forward_validation"
    assert league["research_priority"] == "HIGH_RESEARCH"


def test_official_pool_profit_research_uses_world_cup_rejection_report(tmp_path):
    database = Database(tmp_path / "pool-world-cup-rejected.db")
    database.initialize()
    repo = Repository(database)
    match_id = _official_match(repo, "\u4e16\u754c\u676f")
    repo.add_odds(match_id, {"home": 2.2, "draw": 3.1, "away": 3.3}, "official")

    archived = tmp_path / "WORLD_CUP.csv"
    archived.write_text("Date,Home,Away,HG,AG,AvgCH,AvgCD,AvgCA\n01/01/2022,A,B,1,0,2.2,3.1,3.3\n", encoding="utf-8")
    validation = {
        "status": "rejected_by_world_cup_tournament_holdout",
        "blocker": "World Cup holdout rejected reusable rules",
        "priority": "LOW_DO_NOT_LOOSEN",
        "reports": ["reports/world_cup_tournament_validation_current/summary.json"],
        "commands": ["rerun"],
    }
    with (
        patch("football_agents.official_pool_research._history_paths", return_value=[Path(archived)]),
        patch("football_agents.official_pool_research._world_cup_validation_evidence", return_value=validation),
    ):
        report = plan_official_pool_profit_research(database)

    league = report["leagues"][0]
    assert league["evidence_status"] == "rejected_by_world_cup_tournament_holdout"
    assert league["research_priority"] == "LOW_DO_NOT_LOOSEN"
    assert league["evidence_reports"] == ["reports/world_cup_tournament_validation_current/summary.json"]
    assert "rejected" in league["blocker"]


def test_world_cup_evidence_treats_rolling_reject_promotion_as_blocker(tmp_path, monkeypatch):
    report_dir = tmp_path / "reports" / "world_cup_rolling_validation_avg_close_current_research"
    report_dir.mkdir(parents=True)
    (report_dir / "summary.json").write_text(
        '{"promotion_decision":"REJECT_NO_REUSABLE_WORLD_CUP_ROLLING_RULE"}',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    evidence = _world_cup_validation_evidence()

    assert evidence is not None
    assert evidence["status"] == "rejected_by_world_cup_tournament_holdout"
    assert evidence["priority"] == "LOW_DO_NOT_LOOSEN"
    assert "REJECT_NO_REUSABLE_WORLD_CUP_ROLLING_RULE" in evidence["blocker"]


def test_official_pool_profit_research_keeps_fin_rejected(tmp_path):
    database = Database(tmp_path / "pool-fin.db")
    database.initialize()
    repo = Repository(database)
    match_id = _official_match(repo, "\u82ac\u8d85")
    repo.add_odds(match_id, {"home": 2.6, "draw": 3.2, "away": 2.7}, "official")

    report = plan_official_pool_profit_research(database)

    league = report["leagues"][0]
    assert league["mapped_history_code"] == "FIN"
    assert league["historical_odds_available"] is True
    assert league["historical_rows"] > 0
    assert league["evidence_status"] == "rejected_by_existing_market_bias_and_residual_tests"
    assert league["research_priority"] == "LOW_DO_NOT_LOOSEN"


def test_official_pool_profit_research_maps_swedish_top_flight(tmp_path):
    database = Database(tmp_path / "pool-swe.db")
    database.initialize()
    repo = Repository(database)
    match_id = _official_match(repo, "\u745e\u8d85")
    repo.add_odds(match_id, {"home": 2.4, "draw": 3.2, "away": 3.1}, "official")

    report = plan_official_pool_profit_research(database)

    league = report["leagues"][0]
    assert league["mapped_history_code"] == "SWE"
    assert league["historical_odds_available"] is True
    assert league["historical_rows"] > 0
    assert league["evidence_status"] == "rejected_by_current_pool_feature_hard_gates"
    assert league["research_priority"] == "LOW_DO_NOT_LOOSEN"


def test_official_pool_profit_research_prioritizes_i2_when_present(tmp_path):
    database = Database(tmp_path / "pool-i2.db")
    database.initialize()
    repo = Repository(database)
    match_id = _official_match(repo, "Italian Serie B")
    repo.add_odds(match_id, {"home": 2.5, "draw": 3.1, "away": 2.9}, "official")

    report = plan_official_pool_profit_research(database)

    league = report["leagues"][0]
    assert league["mapped_history_code"] == "I2"
    assert league["research_priority"] == "HIGH_WHEN_PRESENT"
    assert "frozen I2 scorer" in report["next_algorithmic_action"]
