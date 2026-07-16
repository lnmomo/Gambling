from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from football_agents.db import Database
from football_agents.official_sp_evidence_quality import build_official_sp_evidence_quality
from football_agents.repository import Repository


def _seed_complete_evidence(database: Database, now: datetime, *, closing_minutes: int = 30) -> None:
    repository = Repository(database)
    for index in range(10):
        kickoff = now - timedelta(days=10 - index)
        match_id, _, _ = repository.upsert_official_match({
            "official_match_id": f"sporttery-quality-{index}",
            "match_no": f"Q{index}",
            "league": "西甲",
            "home_team": f"Home {index}",
            "away_team": f"Away {index}",
            "kickoff_time": kickoff.isoformat(),
            "status": "finished",
            "source_url": "https://example.test",
            "data_quality_score": 1.0,
            "raw_hash": f"match-{index}",
        })
        observed = kickoff - timedelta(minutes=closing_minutes)
        repository.archive_official_market_availability(
            match_id,
            f"sporttery-quality-{index}",
            observed.isoformat(),
            kickoff.isoformat(),
            "已开售",
            "scheduled",
            True,
            None,
            "中国竞彩网",
            "https://example.test",
            f"availability-{index}",
        )
        repository.archive_official_odds_observation(
            match_id,
            f"sporttery-quality-{index}",
            {"home": 1.8, "draw": 3.4, "away": 4.5},
            observed.isoformat(),
            kickoff.isoformat(),
            "scheduled",
            "中国竞彩网",
            "https://example.test",
            f"odds-{index}",
        )
        repository.upsert_result(match_id, 2, 1, (kickoff + timedelta(hours=2)).isoformat())
    with database.connect() as connection:
        connection.execute("""INSERT INTO official_fetch_logs
            (source_name,source_url,fetched_at,success,status_code,raw_hash,record_count,error_message)
            VALUES('中国竞彩网','https://example.test',?,1,200,'latest',10,NULL)""",
            ((now - timedelta(minutes=15)).isoformat(),))


def test_official_sp_evidence_quality_passes_complete_fresh_chain(tmp_path) -> None:
    database = Database(tmp_path / "quality-ready.db")
    database.initialize()
    now = datetime(2026, 2, 1, 12, tzinfo=timezone.utc)
    _seed_complete_evidence(database, now)
    repository = Repository(database)
    for index in range(20):
        repository.upsert_official_match({
            "official_match_id": f"sporttery-pre-monitoring-{index}",
            "match_no": f"OLD{index}", "league": "西甲",
            "home_team": f"Old Home {index}", "away_team": f"Old Away {index}",
            "kickoff_time": "2025-01-01T12:00:00+00:00", "status": "finished",
            "source_url": "https://example.test", "data_quality_score": 1.0,
            "raw_hash": f"old-{index}",
        })

    report = build_official_sp_evidence_quality(database, now)

    assert report["decision"] == "EVIDENCE_READY"
    assert report["research_usable"] is True
    assert report["failed_checks"] == 0
    assert report["summary"]["pre_match_matches"] == 10
    assert report["summary"]["offered_matches"] == 10
    assert report["summary"]["pre_match_sp_coverage"] == pytest.approx(1.0)
    assert report["summary"]["closing_1h_coverage"] == pytest.approx(1.0)
    assert report["summary"]["settlement_coverage"] == pytest.approx(1.0)


def test_official_sp_evidence_quality_fails_sold_cards_without_archived_sp(tmp_path) -> None:
    database = Database(tmp_path / "quality-parser-gap.db")
    database.initialize()
    now = datetime(2026, 2, 1, 12, tzinfo=timezone.utc)
    repository = Repository(database)
    for index in range(10):
        kickoff = now - timedelta(days=10 - index)
        match_id, _, _ = repository.upsert_official_match({
            "official_match_id": f"sporttery-parser-gap-{index}",
            "match_no": f"G{index}", "league": "西甲",
            "home_team": f"Gap Home {index}", "away_team": f"Gap Away {index}",
            "kickoff_time": kickoff.isoformat(), "status": "finished",
            "source_url": "https://example.test", "data_quality_score": 1.0,
            "raw_hash": f"gap-{index}",
        })
        repository.archive_official_market_availability(
            match_id, f"sporttery-parser-gap-{index}",
            (kickoff - timedelta(hours=2)).isoformat(), kickoff.isoformat(),
            "已开售", "scheduled", False, "invalid_or_incomplete_three_way_sp",
            "中国竞彩网", "https://example.test", f"gap-availability-{index}",
        )
        repository.upsert_result(match_id, 1, 0, (kickoff + timedelta(hours=2)).isoformat())
    with database.connect() as connection:
        connection.execute("""INSERT INTO official_fetch_logs
            (source_name,source_url,fetched_at,success,status_code,raw_hash,record_count,error_message)
            VALUES('中国竞彩网','https://example.test',?,1,200,'latest',10,NULL)""",
            ((now - timedelta(minutes=15)).isoformat(),))

    report = build_official_sp_evidence_quality(database, now)
    checks = {item["id"]: item for item in report["checks"]}

    assert report["decision"] == "EVIDENCE_DEGRADED"
    assert checks["pre_match_sp_coverage"]["status"] == "FAIL"
    assert checks["pre_match_sp_coverage"]["value"] == 0.0


def test_official_sp_evidence_quality_blocks_stale_and_non_closing_chain(tmp_path) -> None:
    database = Database(tmp_path / "quality-blocked.db")
    database.initialize()
    now = datetime(2026, 2, 1, 12, tzinfo=timezone.utc)
    _seed_complete_evidence(database, now, closing_minutes=180)
    with database.connect() as connection:
        connection.execute("DELETE FROM official_fetch_logs")
        connection.execute("""INSERT INTO official_fetch_logs
            (source_name,source_url,fetched_at,success,status_code,raw_hash,record_count,error_message)
            VALUES('中国竞彩网','https://example.test',?,1,200,'stale',10,NULL)""",
            ((now - timedelta(hours=12)).isoformat(),))

    report = build_official_sp_evidence_quality(database, now)
    checks = {item["id"]: item for item in report["checks"]}

    assert report["decision"] == "EVIDENCE_CRITICAL"
    assert report["research_usable"] is False
    assert checks["collector_freshness"]["status"] == "FAIL"
    assert checks["closing_sp_within_1h"]["status"] == "FAIL"
