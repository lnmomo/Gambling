from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from football_agents.db import Database
from football_agents.repository import Repository


def _match(repository: Repository, kickoff: datetime) -> tuple[int, dict]:
    match_id = repository.create_match({
        "official_match_id": "sporttery-free-prospective-1",
        "league": "Test League", "home_team": "Home", "away_team": "Away",
        "kickoff_time": kickoff.isoformat(), "status": "scheduled",
    })
    return match_id, repository.get_match(match_id)


def test_prospective_snapshot_is_pre_match_immutable_and_unique_per_window(tmp_path: Path) -> None:
    database = Database(tmp_path / "prospective.db")
    database.initialize()
    repository = Repository(database)
    captured = datetime.now(timezone.utc)
    match_id, match = _match(repository, captured + timedelta(hours=6))
    event = {"id": "event-1", "sport_key": "soccer_test", "home_team": "Home", "away_team": "Away"}
    books = [{"bookmaker": "Bet365", "bookmaker_key": "bet365", "market": "H2H",
              "odds": {"home": 2.1, "draw": 3.3, "away": 3.6}, "last_update": captured.isoformat()}]

    assert repository.archive_prospective_external_odds(
        match, event, books, captured.isoformat(), "T_MINUS_6H"
    ) == 1
    assert repository.archive_prospective_external_odds(
        match, event, books, (captured + timedelta(minutes=1)).isoformat(), "T_MINUS_6H"
    ) == 0
    with database.connect() as connection:
        row = connection.execute("SELECT * FROM prospective_external_odds_snapshots").fetchone()
        assert row["match_id"] == match_id
        assert row["payload_hash"]
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE prospective_external_odds_snapshots SET home_odds=9 WHERE snapshot_id=?", (
                row["snapshot_id"],
            ))


def test_prospective_snapshot_rejects_post_kickoff_capture(tmp_path: Path) -> None:
    database = Database(tmp_path / "post-kickoff.db")
    database.initialize()
    repository = Repository(database)
    kickoff = datetime.now(timezone.utc)
    _match_id, match = _match(repository, kickoff)

    with pytest.raises(ValueError, match="before kickoff"):
        repository.archive_prospective_external_odds(
            match, {"id": "event-2", "sport_key": "soccer_test"}, [],
            (kickoff + timedelta(seconds=1)).isoformat(), "OTHER_PRE_MATCH",
        )


def test_quota_ledger_tracks_monthly_cost_and_is_immutable(tmp_path: Path) -> None:
    database = Database(tmp_path / "quota.db")
    database.initialize()
    repository = Repository(database)
    repository.record_odds_api_request({
        "sport_key": "soccer_test", "endpoint": "/sports/soccer_test/odds",
        "regions": "eu", "markets": "h2h", "estimated_cost": 1,
        "credits_last": "1", "credits_remaining": "499", "credits_used": "1",
        "events_returned": 3, "response_hash": "hash-1",
    })

    status = repository.free_prospective_odds_status()

    assert status["monthly_quota"]["requests"] == 1
    assert status["monthly_quota"]["spent"] == 1
    with database.connect() as connection:
        request_id = connection.execute("SELECT request_id FROM odds_api_quota_ledger").fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM odds_api_quota_ledger WHERE request_id=?", (request_id,))
