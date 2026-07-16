import json
from pathlib import Path
from types import SimpleNamespace

from football_agents.db import Database
from football_agents.health import build_health_report
from football_agents.repository import Repository
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
    assert "profit_scorer_official_pool_diagnosis" in task_names
    assert "profit_scorer_official_sp_validation" in task_names


def test_official_sp_tasks_use_fast_refresh_without_accelerating_heavy_agents(tmp_path, monkeypatch):
    database = Database(Path(tmp_path) / "scheduler-cadence.db")
    configured = SimpleNamespace(
        background_agent_interval_seconds=3600,
        official_sp_refresh_minutes=15,
    )
    monkeypatch.setattr("football_agents.scheduler.settings", configured)
    scheduler = BackgroundAgentScheduler(Repository(database), TaskRunnerService(database))

    assert scheduler._interval_for("official_sp_sync") == 900
    assert scheduler._interval_for("official_sp_evidence_quality") == 900
    assert scheduler._interval_for("historical_data_sync") == 3600


def test_hourly_pipeline_runs_dependencies_before_prospective_capture(tmp_path, monkeypatch):
    database = Database(Path(tmp_path) / "scheduler-pipeline.db")
    database.initialize()
    scheduler = BackgroundAgentScheduler(
        Repository(database), TaskRunnerService(database), interval_seconds=60
    )
    seen: list[str] = []
    scheduler.stop_event.wait = lambda _seconds: True
    monkeypatch.setattr(
        scheduler,
        "_run_task",
        lambda task_name, _action: seen.append(task_name),
    )
    tasks = [item for item in scheduler._tasks() if item[0] != "official_sp_sync"]

    scheduler._pipeline_loop(tasks, 60)

    assert seen.index("external_odds_news_weather_sync") < seen.index("historical_data_sync")
    assert seen.index("historical_data_sync") < seen.index("feature_build")
    assert seen.index("feature_build") < seen.index("prospective_research_capture")
    assert seen.index("prospective_research_capture") < seen.index("external_consensus_challenger_capture")
    assert seen.index("external_consensus_challenger_capture") < seen.index("profit_scorer_official_sp_validation")
    assert seen.index("prospective_research_capture") < seen.index("profit_scorer_official_sp_validation")


def test_qwen_terminal_auth_and_quota_errors_trip_circuit_breaker(tmp_path):
    database = Database(Path(tmp_path) / "scheduler-qwen-breaker.db")
    database.initialize()
    scheduler = BackgroundAgentScheduler(
        Repository(database), TaskRunnerService(database), interval_seconds=60
    )

    assert scheduler._terminal_qwen_error(
        "Qwen API HTTP 403: AllocationQuota.FreeTierOnly"
    )
    assert scheduler._terminal_qwen_error("Qwen API HTTP 401: Unauthorized")
    assert not scheduler._terminal_qwen_error("temporary connection timeout")


def test_official_sp_quality_runs_after_each_official_sync(tmp_path, monkeypatch):
    database = Database(Path(tmp_path) / "scheduler-quality-order.db")
    database.initialize()
    scheduler = BackgroundAgentScheduler(
        Repository(database), TaskRunnerService(database), interval_seconds=60
    )
    child_tasks: list[str] = []
    monkeypatch.setattr(
        "football_agents.scheduler.OfficialDataService",
        lambda _repository: SimpleNamespace(sync=lambda: {"status": "success", "records": 3}),
    )
    monkeypatch.setattr(
        "football_agents.scheduler.OfficialResultService",
        lambda _repository: SimpleNamespace(sync=lambda: {"status": "success", "records": 2}),
    )
    monkeypatch.setattr(
        scheduler,
        "_run_task",
        lambda task_name, _action: child_tasks.append(task_name),
    )

    report = scheduler._sync_official()

    assert report["status"] == "success"
    assert child_tasks == [
        "official_results_sync",
        "paper_portfolio_settlement",
        "official_sp_evidence_quality",
        "prospective_research_critical_capture",
    ]


def test_background_profit_scorer_validation_uses_configured_artifact(tmp_path, monkeypatch):
    database = Database(Path(tmp_path) / "scheduler-profit-artifact.db")
    database.initialize()
    seen = {}
    configured = SimpleNamespace(
        profit_scorer_artifact_path="reports/custom-scorer.json",
        profit_scorer_official_sp_validation_report_path="reports/validation.json",
        project_dir=Path(tmp_path),
    )
    child_tasks: list[str] = []

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

    monkeypatch.setattr("football_agents.scheduler.settings", configured)
    monkeypatch.setattr("football_agents.scheduler.validate_profit_scorer_on_official_sp", fake_validate)
    scheduler = BackgroundAgentScheduler(
        Repository(database),
        TaskRunnerService(database),
        interval_seconds=60,
    )
    monkeypatch.setattr(
        scheduler,
        "_run_task",
        lambda task_name, _action: child_tasks.append(task_name),
    )

    report = scheduler._validate_profit_scorer_official_sp()

    assert seen["database"] is database
    assert seen["scorer_artifact"] == configured.profit_scorer_artifact_path
    assert report["decision"] == "OFFICIAL_SP_PROSPECTIVE_BLOCKED"
    assert child_tasks == ["profit_allocation_readiness"]
    output = Path(tmp_path) / "reports" / "validation.json"
    assert json.loads(output.read_text(encoding="utf-8"))["decision"] == "OFFICIAL_SP_PROSPECTIVE_BLOCKED"


def test_background_profit_scorer_pool_diagnosis_writes_report(tmp_path, monkeypatch):
    database = Database(Path(tmp_path) / "scheduler-profit-pool.db")
    database.initialize()
    seen = {}
    configured = SimpleNamespace(
        profit_scorer_artifact_path="reports/custom-scorer.json",
        profit_scorer_official_pool_report_path="reports/pool.json",
        agent_match_limit=17,
        project_dir=Path(tmp_path),
    )

    def fake_diagnose(database_arg, scorer_artifact, limit):
        seen["database"] = database_arg
        seen["scorer_artifact"] = str(scorer_artifact)
        seen["limit"] = limit
        return {
            "scanned_matches": 17,
            "scored_matches": 2,
            "passed_scorer": 1,
            "blocker_counts": [{"reason": "league_not_i2", "matches": 15}],
        }

    monkeypatch.setattr("football_agents.scheduler.settings", configured)
    monkeypatch.setattr("football_agents.scheduler.diagnose_official_profit_scorer_pool", fake_diagnose)
    scheduler = BackgroundAgentScheduler(
        Repository(database),
        TaskRunnerService(database),
        interval_seconds=60,
    )

    report = scheduler._diagnose_profit_scorer_official_pool()

    assert seen == {"database": database, "scorer_artifact": configured.profit_scorer_artifact_path, "limit": 17}
    assert report["matches"] == 17
    assert report["evaluated"] == 2
    assert report["predictions"] == 1
    output = Path(tmp_path) / "reports" / "pool.json"
    assert json.loads(output.read_text(encoding="utf-8"))["passed_scorer"] == 1


def test_health_exposes_profit_scorer_official_sp_validation_progress(tmp_path):
    database = Database(Path(tmp_path) / "health-profit.db")
    database.initialize()
    tasks = TaskRunnerService(database)
    pool = tasks.start_task_run("profit_scorer_official_pool_diagnosis")
    tasks.finish_task_run_success(
        pool["id"],
        affected_matches=100,
        created_snapshots=0,
        created_predictions=0,
        warnings=["league_not_i2"],
    )
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
    assert progress["poolDiagnosisStatus"] == "SUCCESS"
    assert progress["poolScannedMatches"] == 100
    assert progress["poolScoredMatches"] == 0
    assert progress["poolPassedScorer"] == 0
    assert progress["poolBlockers"] == ["league_not_i2"]
    assert progress["status"] == "SUCCESS"
    assert progress["openingPreMatchSnapshots"] == 28
    assert progress["selectedSnapshots"] == 3
    assert progress["settledSelectedSnapshots"] == 1
    assert progress["remainingSettledSelected"] == 199
    assert progress["decision"] == "OFFICIAL_SP_PROSPECTIVE_BLOCKED"
