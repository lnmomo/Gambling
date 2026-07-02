from __future__ import annotations

import sqlite3

from scripts.official_market_data_sufficiency import diagnose_official_market_data


def test_diagnosis_blocks_when_required_objects_are_missing(tmp_path):
    database = tmp_path / "missing.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE matches(id INTEGER PRIMARY KEY,kickoff_time TEXT)")

    report = diagnose_official_market_data(database, min_settled=1, min_months=1)

    assert report["decision"] == "BLOCKED_SCHEMA_MISSING"
    assert report["algorithm_blocked"] is True
    missing = {item["name"] for item in report["required_objects"] if item["status"] == "missing"}
    assert "official_odds_observations" in missing
    assert "results" in missing


def test_diagnosis_requires_settled_official_sp_sample(tmp_path):
    database = tmp_path / "ready.db"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE matches(id INTEGER PRIMARY KEY,kickoff_time TEXT);
            CREATE TABLE results(match_id INTEGER PRIMARY KEY,outcome TEXT);
            CREATE TABLE official_odds_observations(
                id INTEGER PRIMARY KEY,
                match_id INTEGER,
                is_pre_match INTEGER,
                observed_at TEXT
            );
            CREATE VIEW official_odds_closing_observations AS
                SELECT * FROM official_odds_observations WHERE is_pre_match=1;
            CREATE TABLE external_bookmaker_odds(match_id INTEGER, fetched_at TEXT);
            INSERT INTO matches VALUES(1,'2026-01-05T10:00:00+00:00');
            INSERT INTO matches VALUES(2,'2026-02-05T10:00:00+00:00');
            INSERT INTO results VALUES(1,'home');
            INSERT INTO results VALUES(2,'away');
            INSERT INTO official_odds_observations VALUES(1,1,1,'2026-01-04T10:00:00+00:00');
            INSERT INTO official_odds_observations VALUES(2,2,1,'2026-02-04T10:00:00+00:00');
            INSERT INTO external_bookmaker_odds VALUES(1,'2026-01-04T10:00:00+00:00');
            INSERT INTO external_bookmaker_odds VALUES(2,'2026-02-04T10:00:00+00:00');
            """
        )

    report = diagnose_official_market_data(database, min_settled=2, min_months=2)

    assert report["decision"] == "READY_FOR_OFFICIAL_MARKET_EDGE_RESEARCH"
    assert report["algorithm_blocked"] is False
    assert report["counts"]["official_opening_settled_matches"] == 2
    assert report["counts"]["official_settled_months"] == 2
