from football_agents.db import Database
import football_agents.market_bias_pool_relevance as relevance
from football_agents.market_bias_pool_relevance import diagnose_market_bias_official_pool_relevance
from football_agents.repository import Repository


def _official_match(repo: Repository, league: str) -> int:
    match_id = repo.create_match({
        "official_match_id": f"sporttery-{league}-1",
        "league": league,
        "home_team": "A",
        "away_team": "B",
        "kickoff_time": "2027-01-01T12:00:00+00:00",
        "status": "scheduled",
    })
    with repo.db.connect() as c:
        c.execute("UPDATE matches SET source_url=? WHERE id=?", ("test", match_id))
    return match_id


def test_official_pool_relevance_reports_validated_i2_candidate_when_scorecard_shadow_ready(tmp_path, monkeypatch):
    scorecard = tmp_path / "scorecard.json"
    scorecard.write_text('{"deployment_tier":"SHADOW_READY_PRODUCTION_BLOCKED"}', encoding="utf-8")
    monkeypatch.setattr(relevance, "I2_SCORECARD_PATH", scorecard)
    database = Database(tmp_path / "pool-i2.db")
    database.initialize()
    repo = Repository(database)
    match_id = _official_match(repo, "Italian Serie B")
    repo.add_odds(match_id, {"home": 2.4, "draw": 3.1, "away": 3.0}, "official", "2027-01-01T10:00:00+00:00")

    report = diagnose_market_bias_official_pool_relevance(database)

    assert report["official_matches"] == 1
    assert report["with_latest_odds"] == 1
    assert report["validated_shadow_candidates"] == 1
    assert report["leagues"][0]["mapped_history_code"] == "I2"
    assert report["leagues"][0]["blocker"] == "validated shadow candidates exist; await settlement and official-SP promotion checks"


def test_official_pool_relevance_blocks_i2_when_scorecard_unstable(tmp_path, monkeypatch):
    scorecard = tmp_path / "scorecard.json"
    scorecard.write_text('{"deployment_tier":"RESEARCH_ONLY_UNSTABLE_WINDOWS"}', encoding="utf-8")
    monkeypatch.setattr(relevance, "I2_SCORECARD_PATH", scorecard)
    database = Database(tmp_path / "pool-i2-unstable.db")
    database.initialize()
    repo = Repository(database)
    match_id = _official_match(repo, "Italian Serie B")
    repo.add_odds(match_id, {"home": 2.4, "draw": 3.1, "away": 3.0}, "official", "2027-01-01T10:00:00+00:00")

    report = diagnose_market_bias_official_pool_relevance(database)

    assert report["validated_shadow_candidates"] == 0
    assert report["research_watch_candidates"] == 1
    assert report["leagues"][0]["strategy_coverage"] == "RESEARCH_ONLY_UNSTABLE_WINDOWS"
    assert report["leagues"][0]["blocker"] == "historical I2 rule matches current odds, but scorecard blocks shadow allocation"


def test_official_pool_relevance_blocks_fin_even_with_current_odds(tmp_path):
    database = Database(tmp_path / "pool-fin.db")
    database.initialize()
    repo = Repository(database)
    match_id = _official_match(repo, "\u82ac\u8d85")
    repo.add_odds(match_id, {"home": 2.6, "draw": 3.2, "away": 2.7}, "official", "2027-01-01T10:00:00+00:00")

    report = diagnose_market_bias_official_pool_relevance(database)

    assert report["official_matches"] == 1
    assert report["with_latest_odds"] == 1
    assert report["validated_shadow_candidates"] == 0
    assert report["leagues"][0]["mapped_history_code"] == "FIN"
    assert report["leagues"][0]["strategy_coverage"] == "REJECTED_RESEARCH_RULE"
    assert report["leagues"][0]["blocker"] == "current league has historical data, but candidate rule failed robustness"


def test_official_pool_relevance_marks_world_cup_rejected_when_validation_exists(tmp_path, monkeypatch):
    database = Database(tmp_path / "pool-world-cup.db")
    database.initialize()
    repo = Repository(database)
    match_id = _official_match(repo, "\u4e16\u754c\u676f")
    repo.add_odds(match_id, {"home": 2.4, "draw": 3.2, "away": 3.1}, "official", "2027-01-01T10:00:00+00:00")
    monkeypatch.setattr(relevance, "_history_paths", lambda code: [tmp_path / "WORLD_CUP.csv"])
    monkeypatch.setattr(relevance, "_world_cup_validation_evidence", lambda: {
        "status": "rejected_by_world_cup_tournament_holdout",
        "reports": ["reports/world_cup_portfolio_grid_current_research/summary.json"],
    })

    report = diagnose_market_bias_official_pool_relevance(database)

    assert report["validated_shadow_candidates"] == 0
    league = report["leagues"][0]
    assert league["mapped_history_code"] == "WORLD_CUP"
    assert league["strategy_coverage"] == "REJECTED_WORLD_CUP_RULE"
    assert league["evidence_status"] == "rejected_by_world_cup_tournament_holdout"
    assert league["blocker"] == "World Cup odds history exists, but no-lookahead portfolio validation rejected allocation rules"
