from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from football_agents.db import Database
from football_agents.integrations.external_universe import ExternalMarketUniverseService
from football_agents.repository import Repository


def _event(now: datetime, *, completed: bool = False, away_score: int = 1) -> dict:
    value = {
        "id": "external-event-1",
        "sport_key": "soccer_epl",
        "sport_title": "EPL",
        "commence_time": (now - timedelta(hours=3)).isoformat(),
        "home_team": "Arsenal",
        "away_team": "Coventry City",
        "completed": completed,
        "last_update": (now + timedelta(days=2, hours=2)).isoformat(),
    }
    if completed:
        value["scores"] = [
            {"name": "Arsenal", "score": "2"},
            {"name": "Coventry City", "score": str(away_score)},
        ]
    return value


def _audit(endpoint: str, events: int, cost: int = 0) -> dict:
    return {
        "sport_key": "soccer_epl", "endpoint": endpoint,
        "regions": "none", "markets": "none", "estimated_cost": cost,
        "credits_last": cost, "credits_remaining": 490,
        "credits_used": 10, "events_returned": events,
        "response_hash": f"hash-{endpoint}",
    }


class FakeOddsClient:
    def __init__(self, now: datetime) -> None:
        self.now = now
        self.request_audits = []
        self.score_calls = 0

    def configured(self) -> bool:
        return True

    def fixture_events(self, _sport_keys):
        self.request_audits = [_audit("/events", 1)]
        return [_event(self.now)], {"x-requests-remaining": "490"}

    def scores(self, _sport_key, days_from=3):
        self.score_calls += 1
        return [_event(self.now, completed=True)], {}, _audit("/scores", 1, 2)


def test_external_fixture_and_result_evidence_are_labelled_and_settled(
    tmp_path: Path, monkeypatch,
) -> None:
    database = Database(tmp_path / "external-universe.db")
    database.initialize()
    repository = Repository(database)
    now = datetime(2026, 8, 7, 9, tzinfo=timezone.utc)
    client = FakeOddsClient(now)
    monkeypatch.setattr(
        "football_agents.integrations.external_universe.settings",
        SimpleNamespace(
            external_fixture_sport_keys=("soccer_epl",),
            prospective_max_active_sports=1,
            external_results_sync_interval_hours=24,
            prospective_monthly_credit_budget=450,
            prospective_credit_reserve=50,
        ),
    )
    service = ExternalMarketUniverseService(repository, client)

    report = service.sync(now)

    assert report["created"] == 1
    assert report["settled"] == 1
    assert client.score_calls == 1
    assert repository.list_active_official_matches(as_of=now) == []
    with database.connect() as connection:
        match = connection.execute("SELECT * FROM matches").fetchone()
        result = connection.execute("SELECT * FROM results").fetchone()
        evidence = connection.execute(
            "SELECT * FROM external_market_result_observations"
        ).fetchone()
    assert match["official_match_id"] == "oddsapi-external-event-1"
    assert match["source_kind"] == "external_market"
    assert (result["home_score"], result["away_score"], result["outcome"]) == (2, 1, "home")
    assert evidence["resolution_status"] == "SETTLED"

    second = service.sync(now + timedelta(hours=1))
    assert second["scores_status"] == "minimum_interval"
    assert client.score_calls == 1


def test_external_result_conflict_is_quarantined_without_overwrite(tmp_path: Path) -> None:
    database = Database(tmp_path / "external-conflict.db")
    database.initialize()
    repository = Repository(database)
    now = datetime(2026, 8, 7, 9, tzinfo=timezone.utc)
    repository.upsert_external_market_match(_event(now), "E0")
    first = repository.archive_external_market_result(
        _event(now, completed=True, away_score=1), now.isoformat()
    )
    conflict = repository.archive_external_market_result(
        _event(now, completed=True, away_score=3),
        (now + timedelta(hours=1)).isoformat(),
    )

    assert first["status"] == "SETTLED"
    assert conflict["status"] == "CONFLICT"
    with database.connect() as connection:
        result = connection.execute("SELECT home_score,away_score FROM results").fetchone()
        statuses = [row[0] for row in connection.execute(
            "SELECT resolution_status FROM external_market_result_observations ORDER BY observed_at"
        )]
    assert (result["home_score"], result["away_score"]) == (2, 1)
    assert statuses == ["SETTLED", "CONFLICT"]


def test_external_result_observed_before_kickoff_cannot_settle(tmp_path: Path) -> None:
    database = Database(tmp_path / "external-future-result.db")
    database.initialize()
    repository = Repository(database)
    now = datetime(2026, 8, 7, 9, tzinfo=timezone.utc)
    event = _event(now, completed=True)
    event["commence_time"] = (now + timedelta(hours=2)).isoformat()
    repository.upsert_external_market_match(event, "E0")

    result = repository.archive_external_market_result(event, now.isoformat())

    assert result["status"] == "INVALID"
    assert result["reason"] == "completed_result_observed_before_kickoff"
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM results").fetchone()[0] == 0
