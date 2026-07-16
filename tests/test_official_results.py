from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from football_agents.db import Database
from football_agents.official_data.results import OfficialResultService
from football_agents.repository import Repository


class FakeResultClient:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def fetch_results(self, url, windows):
        self.calls.append((url, windows))
        return {"results": self.rows, "windows": [{"rows": len(self.rows)}]}


def _repo(tmp_path: Path) -> Repository:
    database = Database(tmp_path / "results.db")
    database.initialize()
    return Repository(database)


def _match(repo: Repository, source_id: str = "2040514", date: str = "2026-07-16") -> int:
    match_id, _, _ = repo.upsert_official_match({
        "official_match_id": f"sporttery-{source_id}",
        "match_no": "周三202",
        "league": "欧洲冠军联赛",
        "home_team": "苏捷斯卡",
        "away_team": "阿拉木图",
        "kickoff_time": f"{date}T03:00:00+08:00",
        "status": "scheduled",
        "source_url": "https://m.sporttery.cn/mjc/zqsj/?tab=schedule",
        "data_quality_score": 1.0,
        "raw_hash": source_id,
    })
    return match_id


def _row(match_id=2040514, date="2026-07-16", score="0:2", status="2"):
    return {
        "matchId": match_id,
        "matchDate": date,
        "matchNumStr": "周三202",
        "leagueName": "欧洲冠军联赛",
        "allHomeTeam": "苏捷斯卡",
        "allAwayTeam": "阿拉木图凯拉特",
        "matchResultStatus": status,
        "poolStatus": "Payout",
        "sectionsNo999": score,
    }


def test_result_sync_settles_exact_id_and_archives_non_final_rows(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    match_id = _match(repo)
    _match(repo, source_id="2040515")
    client = FakeResultClient([
        _row(),
        _row(match_id=9999999),
        _row(match_id=2040515, status="1", score=""),
    ])

    report = OfficialResultService(repo, client).sync(
        datetime(2026, 7, 16, 8, tzinfo=timezone.utc)
    )

    assert report["settled"] == 1
    assert report["out_of_scope"] == 1
    assert report["skipped"] == 1
    with repo.db.connect() as connection:
        result = connection.execute("SELECT * FROM results WHERE match_id=?", (match_id,)).fetchone()
        match = connection.execute("SELECT status FROM matches WHERE id=?", (match_id,)).fetchone()
    assert (result["home_score"], result["away_score"], result["outcome"]) == (0, 2, "away")
    assert match["status"] == "finished"
    assert repo.official_result_evidence_status()["observations"] == 2


def test_result_sync_quarantines_conflict_without_overwrite(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    match_id = _match(repo)
    repo.upsert_result(match_id, 1, 0, "2026-07-16T06:00:00+00:00")

    report = OfficialResultService(repo, FakeResultClient([_row(score="0:2")])).sync(
        datetime(2026, 7, 16, 8, tzinfo=timezone.utc)
    )

    assert report["conflicts"] == 1
    with repo.db.connect() as connection:
        result = connection.execute("SELECT home_score,away_score FROM results WHERE match_id=?", (match_id,)).fetchone()
        evidence = connection.execute(
            "SELECT resolution_status FROM official_result_observations"
        ).fetchone()
    assert tuple(result) == (1, 0)
    assert evidence["resolution_status"] == "CONFLICT"


def test_result_sync_rejects_date_mismatch_and_is_idempotent(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    match_id = _match(repo)
    service = OfficialResultService(repo, FakeResultClient([_row(date="2026-07-15")]))

    first = service.sync(datetime(2026, 7, 16, 8, tzinfo=timezone.utc))
    second = service.sync(datetime(2026, 7, 16, 8, tzinfo=timezone.utc))

    assert first["ambiguous"] == 1
    assert second["duplicates"] == 1
    with repo.db.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM results WHERE match_id=?", (match_id,)).fetchone()[0] == 0
        observation_id = connection.execute("SELECT id FROM official_result_observations").fetchone()[0]
        try:
            connection.execute(
                "UPDATE official_result_observations SET resolution_reason='changed' WHERE id=?",
                (observation_id,),
            )
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError("official result evidence must be immutable")
