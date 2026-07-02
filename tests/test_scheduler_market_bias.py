from pathlib import Path

from football_agents.db import Database
from football_agents.health import build_health_report
from football_agents.repository import Repository
from football_agents.config import settings
from football_agents.scheduler import BackgroundAgentScheduler
from football_agents.services.task_runner_service import TaskRunnerService


def test_background_scheduler_includes_market_bias_shadow_monitor(tmp_path):
    database = Database(Path(tmp_path) / "scheduler.db")
    database.initialize()
    scheduler = BackgroundAgentScheduler(
        Repository(database),
        TaskRunnerService(database),
        interval_seconds=60,
    )
    task_names = [name for name, _ in scheduler._tasks()]
    assert "market_bias_shadow_monitor" in task_names


def test_background_scheduler_includes_profit_scorer_official_sp_validation(tmp_path):
    database = Database(Path(tmp_path) / "scheduler-profit.db")
    database.initialize()
    scheduler = BackgroundAgentScheduler(
        Repository(database),
        TaskRunnerService(database),
        interval_seconds=60,
    )
    task_names = [name for name, _ in scheduler._tasks()]
    assert "profit_scorer_official_sp_validation" in task_names


def test_background_profit_scorer_validation_uses_configured_artifact(tmp_path, monkeypatch):
    database = Database(Path(tmp_path) / "scheduler-profit-artifact.db")
    database.initialize()
    seen = {}

    def fake_validate(database_arg, scorer_artifact, *_args):
        seen["database"] = database_arg
        seen["scorer_artifact"] = str(scorer_artifact)
        return {
            "opening_pre_match_snapshots": 0,
            "scored_snapshots": 0,
            "selected_snapshots": 0,
            "settled_selected_snapshots": 0,
            "decision": "OFFICIAL_SP_PROSPECTIVE_BLOCKED",
            "decision_reasons": ["no_samples"],
        }

    monkeypatch.setattr("football_agents.scheduler.validate_profit_scorer_on_official_sp", fake_validate)
    scheduler = BackgroundAgentScheduler(
        Repository(database),
        TaskRunnerService(database),
        interval_seconds=60,
    )

    report = scheduler._validate_profit_scorer_official_sp()

    assert seen["database"] is database
    assert seen["scorer_artifact"] == settings.profit_scorer_artifact_path
    assert report["decision"] == "OFFICIAL_SP_PROSPECTIVE_BLOCKED"


def test_health_exposes_profit_scorer_official_sp_validation_progress(tmp_path):
    database = Database(Path(tmp_path) / "health-profit.db")
    database.initialize()
    tasks = TaskRunnerService(database)
    run = tasks.start_task_run("profit_scorer_official_sp_validation")
    tasks.finish_task_run_success(
        run["id"],
        affected_matches=28,
        created_predictions=3,
        created_snapshots=1,
        warnings=["settled_selected<200"],
    )

    health = build_health_report(database)

    progress = health["profitScorerOfficialSp"]
    assert progress["status"] == "SUCCESS"
    assert progress["openingPreMatchSnapshots"] == 28
    assert progress["selectedSnapshots"] == 3
    assert progress["settledSelectedSnapshots"] == 1
    assert progress["remainingSettledSelected"] == 199
    assert progress["decision"] == "OFFICIAL_SP_PROSPECTIVE_BLOCKED"
