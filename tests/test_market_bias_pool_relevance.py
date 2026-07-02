from football_agents.db import Database
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


def test_official_pool_relevance_reports_validated_i2_candidate(tmp_path):
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
