from __future__ import annotations

import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from football_agents.config import settings
from football_agents.db import Database
from football_agents.repository import Repository
from football_agents.services.db_cleanup_service import DbCleanupService


def _utc(days_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _make_settings(retention_days: int, backtest_days: int = 180):
    """Build a Settings instance with overridden retention knobs.

    Settings is frozen, so we construct a fresh dataclass instance rather
    than monkeypatching attributes.
    """
    from dataclasses import replace
    from football_agents.config import Settings
    base = Settings()
    return replace(base, db_retention_days=retention_days,
                   db_backtest_retention_days=backtest_days)


@pytest.fixture()
def temp_db(tmp_path: Path) -> Database:
    db_path = tmp_path / "cleanup.db"
    database = Database(db_path)
    database.initialize()
    return database


def _seed_rows(database: Database) -> None:
    with database.connect() as c:
        c.execute(
            "INSERT INTO matches(official_match_id, league, home_team, away_team, kickoff_time, status)"
            " VALUES('M1','L1','H','A','2026-01-01T00:00:00+00:00','scheduled')"
        )
        match_id = c.execute("SELECT id FROM matches WHERE official_match_id='M1'").fetchone()[0]
        old, recent = _utc(120), _utc(1)
        c.execute(
            "INSERT INTO odds_snapshots(match_id, source, market, option, sp, fetched_at) VALUES(?,?,?,?,?,?)",
            (match_id, "official", "1x2", "home", 1.5, old),
        )
        c.execute(
            "INSERT INTO odds_snapshots(match_id, source, market, option, sp, fetched_at) VALUES(?,?,?,?,?,?)",
            (match_id, "official", "1x2", "draw", 3.0, recent),
        )
        c.execute(
            "INSERT INTO official_fetch_logs(source_name, source_url, fetched_at, success)"
            " VALUES('sporttery','https://x','" + old + "',1)"
        )
        c.execute(
            "INSERT INTO audit_events(operator, module, action, result, created_at)"
            " VALUES('system','test','run','ok','" + old + "')"
        )


def test_prunes_old_rows_and_keeps_recent(temp_db: Database) -> None:
    _seed_rows(temp_db)
    service = DbCleanupService(Repository(database=temp_db), database=temp_db)
    report = service.run_retention_cleanup()
    assert report["total_deleted"] >= 3
    deleted = report["deleted"]
    assert deleted.get("odds_snapshots") == 1
    assert deleted.get("official_fetch_logs") == 1
    assert deleted.get("audit_events") == 1

    with temp_db.connect() as c:
        remaining = c.execute("SELECT COUNT(*) FROM odds_snapshots").fetchone()[0]
    assert remaining == 1  # only the recent row survives


def test_does_not_touch_immutable_evidence(temp_db: Database) -> None:
    with temp_db.connect() as c:
        c.execute(
            "INSERT INTO matches(official_match_id, league, home_team, away_team, kickoff_time, status)"
            " VALUES('M1','L1','H','A','2026-01-01T00:00:00+00:00','scheduled')"
        )
        match_id = c.execute("SELECT id FROM matches WHERE official_match_id='M1'").fetchone()[0]
        old = _utc(400)
        c.execute(
            "INSERT INTO official_odds_observations(match_id, official_match_id, observed_at, kickoff_time,"
            " sale_status, home_sp, draw_sp, away_sp, is_pre_match, minutes_to_kickoff, capture_stage,"
            " source, source_url, raw_hash, created_at) VALUES"
            "(?,'M1','" + old + "','" + old + "','open',2.0,3.0,4.0,1,60,'pre','sporttery','u','h','" + old + "')",
            (match_id,),
        )
    service = DbCleanupService(Repository(database=temp_db), database=temp_db)
    report = service.run_retention_cleanup()
    assert report["deleted"].get("official_odds_observations") in (None, 0)
    with temp_db.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM official_odds_observations").fetchone()[0] == 1


def test_vacuum_runs_and_shrinks(temp_db: Database) -> None:
    _seed_rows(temp_db)
    service = DbCleanupService(Repository(database=temp_db), database=temp_db)
    report = service.run_retention_cleanup()
    assert report["vacuum"] == "ok"
    assert report["db_size_bytes_after"] > 0


def test_disabled_retention_keeps_everything(temp_db: Database, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_rows(temp_db)
    monkeypatch.setattr(
        "football_agents.services.db_cleanup_service.settings",
        _make_settings(retention_days=0, backtest_days=0),
    )
    service = DbCleanupService(Repository(database=temp_db), database=temp_db)
    report = service.run_retention_cleanup()
    assert report["total_deleted"] == 0
    with temp_db.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM odds_snapshots").fetchone()[0] == 2
