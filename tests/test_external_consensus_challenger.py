from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from football_agents.agents.workflow import DecisionWorkflow
from football_agents.db import Database
from football_agents.external_consensus_challenger import ExternalConsensusChallengerService
from football_agents.repository import Repository
from football_agents.research.prospective import ProspectiveResearchService

from tests.test_prospective_research import _seed_match


def _seed_challenger(tmp_path: Path, *, external_age_minutes: int = 0):
    database = Database(tmp_path / "challenger.db")
    database.initialize()
    repository = Repository(database)
    match = _seed_match(repository)
    now = datetime.now(timezone.utc)
    kickoff = datetime.fromisoformat(match["kickoff_time"])
    repository.archive_official_odds_observation(
        match["id"], match["official_match_id"],
        {"home": 2.40, "draw": 3.30, "away": 4.20},
        (now - timedelta(minutes=1)).isoformat(), kickoff.isoformat(),
        "ON_SALE", "official", "https://example.test", "favorable-official-sp",
    )
    prospective = ProspectiveResearchService(database, repository, DecisionWorkflow(repository))
    study = prospective.ensure_default_study()
    assert prospective.capture(10, study["study_id"])["predictions"] == 1
    fetched_at = now - timedelta(minutes=external_age_minutes)
    repository.add_external_bookmaker_odds(
        match["id"],
        [
            {
                "bookmaker": f"Book {index}", "bookmaker_key": f"book-{index}", "market": "H2H",
                "odds": {"home": 1.90 + index * 0.002, "draw": 3.60, "away": 4.50},
                "last_update": fetched_at.isoformat(),
            }
            for index in range(12)
        ],
        fetched_at.isoformat(),
    )
    decision_time = datetime.now(timezone.utc)
    return database, repository, match, decision_time


def test_challenger_freezes_candidate_and_is_immutable(tmp_path: Path) -> None:
    database, repository, match, now = _seed_challenger(tmp_path)
    service = ExternalConsensusChallengerService(database, repository)

    first = service.capture(10, as_of=now + timedelta(seconds=5))
    repeated = service.capture(10, as_of=now + timedelta(seconds=10))

    assert first["decisions"] == 1
    assert first["predictions"] == 1
    assert repeated["decisions"] == 0
    assert repeated["duplicates"] == 1
    decision = first["report"]["recent_decisions"][0]
    assert decision["action"] == "CANDIDATE"
    assert decision["selected_outcome"] == "home"
    assert decision["bookmaker_count"] == 12
    assert decision["conservative_ev"] > 0

    with database.connect() as connection:
        row = connection.execute("SELECT * FROM external_consensus_decisions").fetchone()
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE external_consensus_decisions SET action='NO_BET' WHERE decision_id=?",
                (row["decision_id"],),
            )
        policy = connection.execute("SELECT * FROM external_consensus_policy_registrations").fetchone()
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE external_consensus_policy_registrations SET hypothesis='changed' WHERE policy_id=?",
                (policy["policy_id"],),
            )

    close_at = datetime.fromisoformat(match["kickoff_time"]) - timedelta(minutes=5)
    repository.archive_official_odds_observation(
        match["id"], match["official_match_id"],
        {"home": 2.30, "draw": 3.40, "away": 4.30},
        close_at.isoformat(), match["kickoff_time"], "ON_SALE", "official",
        "https://example.test", "closing-official-sp",
    )
    repository.upsert_result(match["id"], 2, 0, (close_at + timedelta(hours=2)).isoformat())
    report = service.report(first["policy_id"], as_of=now + timedelta(days=1))

    assert report["settled_selections"] == 1
    assert report["profit"] == 1.4
    assert report["closing_sp_coverage"] == 1.0
    assert report["average_clv"] > 0
    assert report["statistical_evidence"]["point_estimates"]["bets"] == 1
    assert report["decision"] == "EXTERNAL_CONSENSUS_PROSPECTIVE_COLLECTING"


def test_challenger_refuses_stale_external_consensus(tmp_path: Path) -> None:
    database, repository, _match, now = _seed_challenger(tmp_path, external_age_minutes=181)
    service = ExternalConsensusChallengerService(database, repository)

    result = service.capture(10, as_of=now)

    assert result["decisions"] == 0
    assert result["predictions"] == 0
    assert result["blocker_counts"][0]["reason"] == "stale_external_consensus"
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) n FROM external_consensus_decisions").fetchone()["n"] == 0


def test_current_official_margin_can_freeze_honest_no_bet(tmp_path: Path) -> None:
    database, repository, match, now = _seed_challenger(tmp_path)
    repository.archive_official_odds_observation(
        match["id"], match["official_match_id"],
        {"home": 1.70, "draw": 2.80, "away": 3.50},
        now.isoformat(), match["kickoff_time"], "ON_SALE", "official",
        "https://example.test", "low-official-sp",
    )
    service = ExternalConsensusChallengerService(database, repository)

    result = service.capture(10, as_of=now + timedelta(seconds=5))

    assert result["decisions"] == 1
    assert result["predictions"] == 0
    decision = result["report"]["recent_decisions"][0]
    assert decision["action"] == "NO_BET"
    assert "conservative_ev<0" in decision["blockers"]
