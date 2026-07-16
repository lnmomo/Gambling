from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from football_agents.db import Database
from football_agents.paper_portfolio import PaperPortfolioService
from football_agents.external_consensus_challenger import ExternalConsensusChallengerService
from football_agents.repository import Repository

from tests.test_external_consensus_challenger import _seed_challenger


AS_OF = datetime(2026, 8, 1, 10, tzinfo=timezone.utc)


def _database(tmp_path: Path) -> tuple[Database, Repository]:
    database = Database(tmp_path / "paper.db")
    database.initialize()
    return database, Repository(database)


def _readiness(decision="PAPER_ALLOCATION_READY"):
    return {
        "generated_at": AS_OF.isoformat(),
        "daily_budget": 100.0,
        "decision": decision,
        "reason": "test",
        "allocated_budget": 100.0 if decision == "PAPER_ALLOCATION_READY" else 0.0,
        "cash_reserved": 0.0 if decision == "PAPER_ALLOCATION_READY" else 100.0,
        "allocations": ([{"strategy_id": "strategy-a", "paper_budget": 100.0}]
                        if decision == "PAPER_ALLOCATION_READY" else []),
    }


def _seed_candidate(tmp_path: Path, database: Database, repo: Repository):
    artifact = tmp_path / "scorer.json"
    artifact.write_text('{"frozen":true}', encoding="utf-8")
    artifact_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()
    match_id = repo.create_match({
        "official_match_id": "sporttery-paper-1",
        "league": "Spanish La Liga",
        "home_team": "Home",
        "away_team": "Away",
        "kickoff_time": "2026-08-01T12:00:00+00:00",
        "status": "scheduled",
    })
    opening_id = repo.archive_official_odds_observation(
        match_id, "sporttery-paper-1", {"home": 1.5, "draw": 4.0, "away": 7.0},
        "2026-08-01T08:00:00+00:00", "2026-08-01T12:00:00+00:00",
        "ON_SALE", "official", "test", "opening",
    )
    repo.add_profit_scorer_evidence({
        "match_id": match_id,
        "official_odds_observation_id": opening_id,
        "scorer_artifact_sha256": artifact_hash,
        "strategy_label": "SP1_home",
        "selected_outcome": "HOME",
        "feature_engine": "test",
        "features": {"odds": 1.5},
        "market_probability": 0.65,
        "predicted_probability": 0.70,
        "predicted_ev": 0.05,
        "passes_scorer": True,
        "scored_at": "2026-08-01T08:01:00+00:00",
    })
    current_id = repo.archive_official_odds_observation(
        match_id, "sporttery-paper-1", {"home": 1.6, "draw": 3.9, "away": 6.8},
        "2026-08-01T09:55:00+00:00", "2026-08-01T12:00:00+00:00",
        "ON_SALE", "official", "test", "current",
    )
    package = {
        "strategy_id": "strategy-a",
        "scorer_artifact_report": str(artifact),
        "selection": {"min_predicted_ev": 0.0, "max_bets_per_day": 1},
        "risk_control": {"max_single_stake": 10.0},
    }
    return match_id, current_id, package


def test_blocked_readiness_creates_immutable_cash_hold(tmp_path: Path, monkeypatch) -> None:
    database, _ = _database(tmp_path)
    monkeypatch.setattr(
        "football_agents.paper_portfolio.build_profit_allocation_readiness",
        lambda _budget: _readiness("WAIT_FOR_OFFICIAL_SP_EVIDENCE_QUALITY"),
    )
    monkeypatch.setattr("football_agents.paper_portfolio.list_profit_strategy_packages", lambda: [])
    service = PaperPortfolioService(database)

    report = service.allocate(AS_OF, 100)
    repeated = service.allocate(AS_OF, 100)

    assert report["status"] == "hold"
    assert report["positions_created"] == 0
    assert report["cash_reserved"] == 100.0
    assert repeated["status"] == "duplicate"
    with database.connect() as connection:
        run = connection.execute("SELECT * FROM paper_portfolio_runs").fetchone()
        assert run["status"] == "HOLD"
        with __import__("pytest").raises(sqlite3.IntegrityError):
            connection.execute("UPDATE paper_portfolio_runs SET status='ALLOCATED' WHERE run_id=?", (run["run_id"],))


def test_allocation_uses_latest_executable_sp_and_settles_once(tmp_path: Path, monkeypatch) -> None:
    database, repo = _database(tmp_path)
    match_id, current_id, package = _seed_candidate(tmp_path, database, repo)
    monkeypatch.setattr(
        "football_agents.paper_portfolio.build_profit_allocation_readiness", lambda _budget: _readiness()
    )
    monkeypatch.setattr(
        "football_agents.paper_portfolio.list_profit_strategy_packages", lambda: [package]
    )
    service = PaperPortfolioService(database)

    allocation = service.allocate(AS_OF, 100)

    assert allocation["status"] == "allocated"
    assert allocation["positions_created"] == 1
    assert allocation["new_stake"] == 5.0
    with database.connect() as connection:
        position = connection.execute("SELECT * FROM paper_portfolio_positions").fetchone()
    assert position["official_odds_observation_id"] == current_id
    assert position["selected_sp"] == 1.6
    assert round(position["predicted_ev"], 6) == 0.12

    closing_id = repo.archive_official_odds_observation(
        match_id, "sporttery-paper-1", {"home": 1.5, "draw": 4.0, "away": 7.0},
        "2026-08-01T11:55:00+00:00", "2026-08-01T12:00:00+00:00",
        "ON_SALE", "official", "test", "closing",
    )
    repo.upsert_result(match_id, 2, 0, "2026-08-01T14:00:00+00:00")
    settled = service.settle("2026-08-01T14:05:00+00:00")
    repeated = service.settle("2026-08-01T14:10:00+00:00")
    summary = service.summary()

    assert settled == {"status": "success", "matches": 1, "settled": 1, "profit": 3.0, "missing_closing_sp": 0}
    assert repeated["settled"] == 0
    assert summary["positions"] == 1
    assert summary["settled_positions"] == 1
    assert summary["profit"] == 3.0
    assert summary["roi_pct"] == 60.0
    assert summary["average_clv"] == round(1.6 / 1.5 - 1, 6)
    with database.connect() as connection:
        settlement = connection.execute("SELECT * FROM paper_portfolio_settlements").fetchone()
    assert settlement["closing_odds_observation_id"] == closing_id


def test_stale_sp_cannot_be_retroactively_allocated(tmp_path: Path, monkeypatch) -> None:
    database, repo = _database(tmp_path)
    _, _, package = _seed_candidate(tmp_path, database, repo)
    monkeypatch.setattr(
        "football_agents.paper_portfolio.build_profit_allocation_readiness", lambda _budget: _readiness()
    )
    monkeypatch.setattr(
        "football_agents.paper_portfolio.list_profit_strategy_packages", lambda: [package]
    )

    report = PaperPortfolioService(database).allocate("2026-08-01T11:00:00+00:00", 100)

    assert report["status"] == "no_eligible_positions"
    assert report["positions_created"] == 0
    assert report["skipped"] == {"stale_current_official_sp": 1}
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM paper_portfolio_positions").fetchone()[0] == 0


def test_daily_strategy_count_applies_across_multiple_runs(tmp_path: Path, monkeypatch) -> None:
    database, repo = _database(tmp_path)
    _, _, package = _seed_candidate(tmp_path, database, repo)
    artifact_hash = hashlib.sha256(Path(package["scorer_artifact_report"]).read_bytes()).hexdigest()
    match_id = repo.create_match({
        "official_match_id": "sporttery-paper-2", "league": "Spanish La Liga",
        "home_team": "Home 2", "away_team": "Away 2",
        "kickoff_time": "2026-08-01T13:00:00+00:00", "status": "scheduled",
    })
    observation_id = repo.archive_official_odds_observation(
        match_id, "sporttery-paper-2", {"home": 1.7, "draw": 3.8, "away": 6.0},
        "2026-08-01T09:56:00+00:00", "2026-08-01T13:00:00+00:00",
        "ON_SALE", "official", "test", "paper-2",
    )
    repo.add_profit_scorer_evidence({
        "match_id": match_id, "official_odds_observation_id": observation_id,
        "scorer_artifact_sha256": artifact_hash, "strategy_label": "SP1_home",
        "selected_outcome": "HOME", "feature_engine": "test", "features": {},
        "market_probability": 0.65, "predicted_probability": 0.71,
        "predicted_ev": 0.20, "passes_scorer": True,
        "scored_at": "2026-08-01T09:57:00+00:00",
    })
    monkeypatch.setattr(
        "football_agents.paper_portfolio.build_profit_allocation_readiness", lambda _budget: _readiness()
    )
    monkeypatch.setattr(
        "football_agents.paper_portfolio.list_profit_strategy_packages", lambda: [package]
    )
    service = PaperPortfolioService(database)

    first = service.allocate(AS_OF, 100)
    second = service.allocate("2026-08-01T10:05:00+00:00", 100)

    assert first["positions_created"] == 1
    assert second["positions_created"] == 0
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM paper_portfolio_positions").fetchone()[0] == 1


def test_same_match_cannot_be_allocated_by_two_strategies(tmp_path: Path, monkeypatch) -> None:
    database, repo = _database(tmp_path)
    match_id, current_id, package_a = _seed_candidate(tmp_path, database, repo)
    artifact_b = tmp_path / "scorer-b.json"
    artifact_b.write_text('{"frozen":"b"}', encoding="utf-8")
    hash_b = hashlib.sha256(artifact_b.read_bytes()).hexdigest()
    repo.add_profit_scorer_evidence({
        "match_id": match_id, "official_odds_observation_id": current_id,
        "scorer_artifact_sha256": hash_b, "strategy_label": "SP1_home_b",
        "selected_outcome": "HOME", "feature_engine": "test", "features": {},
        "market_probability": 0.65, "predicted_probability": 0.72,
        "predicted_ev": 0.15, "passes_scorer": True,
        "scored_at": "2026-08-01T09:56:00+00:00",
    })
    package_b = {
        **package_a, "strategy_id": "strategy-b", "scorer_artifact_report": str(artifact_b),
    }
    readiness = _readiness()
    readiness["allocations"] = [
        {"strategy_id": "strategy-a", "paper_budget": 50.0},
        {"strategy_id": "strategy-b", "paper_budget": 50.0},
    ]
    monkeypatch.setattr(
        "football_agents.paper_portfolio.build_profit_allocation_readiness", lambda _budget: readiness
    )
    monkeypatch.setattr(
        "football_agents.paper_portfolio.list_profit_strategy_packages", lambda: [package_a, package_b]
    )

    report = PaperPortfolioService(database).allocate(AS_OF, 100)

    assert report["positions_created"] == 1
    assert report["skipped"]["match_already_in_portfolio"] == 1
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM paper_portfolio_positions").fetchone()[0] == 1


def test_promoted_external_consensus_candidate_can_enter_multi_source_ledger(
    tmp_path: Path, monkeypatch,
) -> None:
    database, repository, match, now = _seed_challenger(tmp_path)
    challenger = ExternalConsensusChallengerService(database, repository)
    capture = challenger.capture(10, as_of=now + timedelta(seconds=5))
    policy = capture["report"]["policy"]
    strategy_id = "external-consensus-test"
    package = {
        "strategy_id": strategy_id,
        "source_type": "EXTERNAL_CONSENSUS",
        "policy_id": policy["policy_id"],
        "policy_hash": policy["policy_hash"],
        "selection": {
            "min_predicted_ev": 0.0, "max_bets_per_day": 1,
            "primary_horizon_minutes": 60, "horizon_tolerance_minutes": 60,
        },
        "risk_control": {"max_single_stake": 10.0},
    }
    readiness = _readiness()
    readiness["allocations"] = [{"strategy_id": strategy_id, "paper_budget": 100.0}]
    monkeypatch.setattr(
        "football_agents.paper_portfolio.build_profit_allocation_readiness", lambda _budget: readiness
    )
    monkeypatch.setattr(
        "football_agents.paper_portfolio.list_profit_strategy_packages", lambda: [package]
    )

    allocation = PaperPortfolioService(database).allocate(
        now + timedelta(seconds=10), 100
    )

    assert allocation["status"] == "allocated"
    assert allocation["positions_created"] == 1
    with database.connect() as connection:
        position = connection.execute("SELECT * FROM paper_portfolio_positions").fetchone()
    assert position["source_type"] == "EXTERNAL_CONSENSUS"
    assert position["scorer_evidence_id"] is None
    assert position["external_consensus_decision_id"] is not None
    assert position["match_id"] == match["id"]
    assert position["predicted_probability"] < 0.60
