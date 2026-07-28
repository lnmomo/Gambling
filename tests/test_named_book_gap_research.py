from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from football_agents.db import Database
from football_agents.named_book_gap_research import NamedBookGapResearchService
from football_agents.repository import Repository


def _seed(tmp_path: Path):
    database = Database(tmp_path / "named-gap.db")
    database.initialize()
    repository = Repository(database)
    now = datetime.now(timezone.utc)
    match_id = repository.create_match({
        "official_match_id": "sporttery-named-gap-1", "league": "Test",
        "home_team": "Home", "away_team": "Away",
        "kickoff_time": (now + timedelta(minutes=90)).isoformat(), "status": "scheduled",
    })
    with database.connect() as connection:
        connection.execute("UPDATE matches SET source_url=? WHERE id=?", ("https://example.test/official", match_id))
    repository.add_external_bookmaker_odds(match_id, [
        {"bookmaker": "Bet365", "bookmaker_key": "bet365", "market": "H2H",
         "odds": {"home": 2.20, "draw": 3.10, "away": 3.90}, "last_update": now.isoformat()},
        {"bookmaker": "Pinnacle", "bookmaker_key": "pinnacle", "market": "H2H",
         "odds": {"home": 2.00, "draw": 3.00, "away": 4.00}, "last_update": now.isoformat()},
    ], now.isoformat())
    return database, repository, match_id, now


def test_named_book_gap_freezes_timestamp_aligned_candidate_and_reports_settlement(tmp_path: Path) -> None:
    database, repository, match_id, now = _seed(tmp_path)
    service = NamedBookGapResearchService(database, repository)

    capture = service.capture(10, as_of=now + timedelta(seconds=2))
    repeat = service.capture(10, as_of=now + timedelta(seconds=3))

    assert capture["decisions"] == 1
    assert capture["predictions"] == 1
    assert repeat["decisions"] == 0
    assert capture["report"]["candidate_decisions"] == 1
    with database.connect() as connection:
        row = connection.execute("SELECT * FROM named_book_gap_decisions").fetchone()
        assert row["action"] == "CANDIDATE"
        assert row["selected_outcome"] == "home"
        assert row["expected_ev"] > 0
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE named_book_gap_decisions SET action='NO_BET'")
    repository.upsert_result(match_id, 2, 0, (now + timedelta(hours=3)).isoformat())
    report = service.report(capture["report"]["policy"]["policy_id"])
    assert report["settled_selections"] == 1
    assert report["profit"] == pytest.approx(1.2)
    assert "paper-portfolio positions" in report["guardrail"]


def test_named_book_gap_rejects_misaligned_bookmaker_updates(tmp_path: Path) -> None:
    database, repository, _match_id, now = _seed(tmp_path)
    with database.connect() as connection:
        connection.execute("UPDATE external_bookmaker_odds SET last_update=? WHERE bookmaker_key='pinnacle'", (
            (now - timedelta(minutes=11)).isoformat(),
        ))
    service = NamedBookGapResearchService(database, repository)

    capture = service.capture(10, as_of=now + timedelta(seconds=2))

    assert capture["decisions"] == 0
    assert capture["blocker_counts"][0]["reason"] == "named_bookmaker_update_skew>10m"
