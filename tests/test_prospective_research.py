from __future__ import annotations

import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from football_agents.agents.workflow import DecisionWorkflow
from football_agents.db import Database
from football_agents.repository import Repository
from football_agents.research.prospective import ProspectiveResearchService


def _seed_match(repository: Repository, status: str = "scheduled",
                official_match_id: str = "sporttery-prospective-1") -> dict:
    now = datetime.now(timezone.utc)
    kickoff = now + timedelta(minutes=90)
    observed = now - timedelta(minutes=1)
    kickoff_text = kickoff.isoformat()
    observed_text = observed.isoformat()
    match_id, _, _ = repository.upsert_official_match({
        "official_match_id": official_match_id, "match_no": "001", "league": "Test League",
        "home_team": "Home", "away_team": "Away", "kickoff_time": kickoff_text,
        "status": status, "source_url": "https://example.test", "data_quality_score": 1.0,
        "raw_hash": "match-hash",
    })
    repository.add_odds(match_id, {"home": 2.1, "draw": 3.2, "away": 3.6}, "official",
                        observed_text)
    repository.add_odds(match_id, {"home": 2.0, "draw": 3.3, "away": 3.8}, "market",
                        observed_text, external=True)
    repository.archive_official_odds_observation(
        match_id, official_match_id, {"home": 2.1, "draw": 3.2, "away": 3.6},
        observed_text, kickoff_text, status,
        "official", "https://example.test", "odds-hash",
    )
    repository.add_features(match_id, {
        "home_rating": 1530, "away_rating": 1490, "lambda_home": 1.45, "lambda_away": 1.05,
        "source_confidence": 0.9, "home_recent_matches": 20, "away_recent_matches": 20,
    })
    return repository.get_match(match_id) or {}


def test_prospective_predictions_are_immutable_and_confirmation_runs_once(tmp_path: Path) -> None:
    database = Database(tmp_path / "prospective.db")
    database.initialize()
    repository = Repository(database)
    match = _seed_match(repository)
    workflow = DecisionWorkflow(repository)
    service = ProspectiveResearchService(database, repository, workflow)
    freeze = service.freeze_current_model()
    study = service.register_study("unit-confirmation", "proposed log loss is lower", freeze["freeze_id"], 1, 0)

    report = service.capture(10, study["study_id"])
    assert report["predictions"] == 1
    duplicate = service.capture(10, study["study_id"])
    assert duplicate["predictions"] == 0
    assert duplicate["duplicates"] == 1

    with database.connect() as connection:
        prediction = connection.execute("SELECT * FROM prospective_predictions").fetchone()
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE prospective_predictions SET p_home=0.5 WHERE prediction_id=?",
                               (prediction["prediction_id"],))

    repository.upsert_result(match["id"], 2, 1, "2030-01-02T15:00:00+00:00")
    first = service.run_confirmation_once(study["study_id"])
    second = service.run_confirmation_once(study["study_id"])
    assert first["run_id"] == second["run_id"]
    assert first["settled_matches"] == 1
    assert first["decision"] in {"SUPERIOR", "INFERIOR", "INCONCLUSIVE"}


def test_confirmation_refuses_to_run_before_registered_threshold(tmp_path: Path) -> None:
    database = Database(tmp_path / "threshold.db")
    database.initialize()
    service = ProspectiveResearchService(database, Repository(database))
    freeze = service.freeze_current_model()
    study = service.register_study("threshold", "registered hypothesis", freeze["freeze_id"], 5000, 365)
    with pytest.raises(RuntimeError, match="not ready"):
        service.run_confirmation_once(study["study_id"])


def test_capture_accepts_normalized_not_started_status(tmp_path: Path) -> None:
    database = Database(tmp_path / "not-started.db")
    database.initialize()
    repository = Repository(database)
    _seed_match(repository, status="NOT_STARTED")
    service = ProspectiveResearchService(database, repository, DecisionWorkflow(repository))
    freeze = service.freeze_current_model()
    study = service.register_study("not-started", "status normalization", freeze["freeze_id"], 1, 0)

    report = service.capture(10, study["study_id"])

    assert report["eligible_pre_match"] == 1
    assert report["predictions"] == 1
    assert report["skip_reasons"] == {}


def test_capture_reports_ineligible_status_without_green_zero_output(tmp_path: Path) -> None:
    database = Database(tmp_path / "closed.db")
    database.initialize()
    repository = Repository(database)
    _seed_match(repository, status="CANCELLED")
    service = ProspectiveResearchService(database, repository, DecisionWorkflow(repository))
    freeze = service.freeze_current_model()
    study = service.register_study("cancelled", "status exclusion", freeze["freeze_id"], 1, 0)

    report = service.capture(10, study["study_id"])

    assert report["eligible_pre_match"] == 0
    assert report["predictions"] == 0
    assert report["skip_reasons"] == {"ineligible_status": 1}


def test_capture_limit_prioritizes_active_matches_over_closed_rows(tmp_path: Path) -> None:
    database = Database(tmp_path / "active-priority.db")
    database.initialize()
    repository = Repository(database)
    _seed_match(repository, status="CANCELLED", official_match_id="sporttery-closed-first")
    active = _seed_match(repository, status="scheduled", official_match_id="sporttery-active-second")
    service = ProspectiveResearchService(database, repository, DecisionWorkflow(repository))
    freeze = service.freeze_current_model()
    study = service.register_study("active-priority", "active rows must not be displaced", freeze["freeze_id"], 1, 0)

    report = service.capture(1, study["study_id"])

    assert report["eligible_pre_match"] == 1
    assert report["predictions"] == 1
    with database.connect() as connection:
        captured = connection.execute("SELECT match_id FROM prospective_predictions").fetchone()
    assert captured["match_id"] == active["id"]
