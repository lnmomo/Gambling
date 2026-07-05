from __future__ import annotations

from football_agents.db import Database
from football_agents.profit_data_domain_readiness import build_profit_data_domain_readiness
from football_agents.repository import Repository


def _write_csv(path, rows: int, with_odds: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = "Date,Home,Away,HG,AG,AvgCH,AvgCD,AvgCA\n"
    lines = [header]
    for index in range(rows):
        month = index % 36 + 1
        year = 2021 + (month - 1) // 12
        month_number = (month - 1) % 12 + 1
        date_text = f"01/{month_number:02d}/{year}"
        if with_odds:
            lines.append(f"{date_text},A{index},B{index},1,0,2.10,3.20,3.60\n")
        else:
            lines.append(f"{date_text},A{index},B{index},1,0,,,\n")
    path.write_text("".join(lines), encoding="utf-8")


def test_domain_readiness_prioritizes_search_ready_current_pool(tmp_path):
    root = tmp_path / "football-data"
    _write_csv(root / "new" / "I2.csv", 1200, with_odds=True)
    _write_csv(root / "new" / "INTERNATIONAL.csv", 1200, with_odds=False)
    database = Database(tmp_path / "domain.db")
    database.initialize()
    repo = Repository(database)
    match_id = repo.create_match({
        "official_match_id": "sporttery-domain-i2-1",
        "league": "Italian Serie B",
        "home_team": "A",
        "away_team": "B",
        "kickoff_time": "2027-01-01T12:00:00+00:00",
        "status": "scheduled",
    })
    with repo.db.connect() as c:
        c.execute("UPDATE matches SET source_url=? WHERE id=?", ("test", match_id))
    repo.add_odds(match_id, {"home": 2.2, "draw": 3.1, "away": 3.3}, "official")

    report = build_profit_data_domain_readiness(root, database)

    assert report["top_domains"][0]["code"] == "I2"
    assert report["top_domains"][0]["readiness"] == "SEARCH_READY_CURRENT_OFFICIAL_POOL"
    assert report["top_domains"][0]["official_pool_matches"] == 1
    assert report["top_domains"][0]["best_odds_source"] == "AVG_CLOSE"
    international = next(row for row in report["domains"] if row["code"] == "INTERNATIONAL")
    assert international["readiness"] == "FEATURES_ONLY_NO_1X2_ODDS"


def test_domain_readiness_marks_small_odds_domain_as_research_only(tmp_path):
    root = tmp_path / "football-data"
    _write_csv(root / "new" / "WORLD_CUP.csv", 128, with_odds=True)

    database = Database(tmp_path / "small.db")
    database.initialize()
    report = build_profit_data_domain_readiness(root, database)

    domain = report["domains"][0]
    assert domain["code"] == "WORLD_CUP"
    assert domain["readiness"] == "RESEARCH_ONLY_SMALL_SAMPLE"
    assert domain["research_priority"] == "LOW_RESEARCH"
    assert "sample size" in domain["blocker"]
