import json
from pathlib import Path
from types import SimpleNamespace

from football_agents.config import settings
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

    assert seen.index("external_market_fixture_sync") < seen.index("external_odds_news_weather_sync")
    assert seen.index("external_odds_news_weather_sync") < seen.index("historical_data_sync")
    assert seen.index("historical_data_sync") < seen.index("feature_build")
    assert seen.index("feature_build") < seen.index("prospective_research_capture")
    assert seen.index("prospective_research_capture") < seen.index("external_consensus_challenger_capture")
    assert seen.index("external_consensus_challenger_capture") < seen.index("profit_scorer_official_sp_validation")
    assert seen.index("prospective_research_capture") < seen.index("profit_scorer_official_sp_validation")


def test_startup_pipeline_waits_for_initial_official_sync(tmp_path, monkeypatch):
    database = Database(Path(tmp_path) / "scheduler-startup-order.db")
    database.initialize()
    scheduler = BackgroundAgentScheduler(
        Repository(database), TaskRunnerService(database), interval_seconds=60
    )
    events: list[str] = []

    def wait_for_official(_seconds):
        events.append("waited_for_official")
        return True

    scheduler.initial_official_sync_complete.wait = wait_for_official
    scheduler.stop_event.wait = lambda _seconds: True
    monkeypatch.setattr(
        scheduler,
        "_run_task",
        lambda task_name, _action: events.append(task_name),
    )

    scheduler._pipeline_loop([("external_odds_news_weather_sync", lambda: {})], 60, True)

    assert events == ["waited_for_official", "external_odds_news_weather_sync"]


def test_delayed_maintenance_does_not_run_during_startup(tmp_path, monkeypatch):
    database = Database(Path(tmp_path) / "scheduler-delayed-maintenance.db")
    database.initialize()
    scheduler = BackgroundAgentScheduler(
        Repository(database), TaskRunnerService(database), interval_seconds=60
    )
    events: list[str] = []
    scheduler.stop_event.wait = lambda seconds: events.append(f"wait:{seconds}") or True
    monkeypatch.setattr(
        scheduler, "_run_task", lambda task_name, _action: events.append(task_name)
    )

    scheduler._delayed_loop("db_retention_cleanup", lambda: {}, 3600)

    assert events == ["wait:3600"]


def test_capture_warnings_expose_actionable_input_blockers(tmp_path, monkeypatch):
    database = Database(Path(tmp_path) / "scheduler-capture-blockers.db")
    database.initialize()
    scheduler = BackgroundAgentScheduler(Repository(database), TaskRunnerService(database))
    monkeypatch.setattr(
        "football_agents.scheduler.ExternalConsensusChallengerService",
        lambda *_args: SimpleNamespace(capture=lambda _limit: {
            "decisions": 0,
            "warnings": ["settled_selections<200"],
            "blocker_counts": [{"reason": "stale_external_consensus", "matches": 6}],
            "report": {},
        }),
    )
    monkeypatch.setattr(scheduler, "_write_report", lambda *_args: None)

    report = scheduler._capture_external_consensus_challenger()

    assert report["warnings"] == ["settled_selections<200", "stale_external_consensus:6"]


def test_external_refresh_immediately_runs_consensus_and_allocation_checks(tmp_path, monkeypatch):
    database = Database(Path(tmp_path) / "scheduler-post-external.db")
    database.initialize()
    scheduler = BackgroundAgentScheduler(Repository(database), TaskRunnerService(database))
    child_tasks: list[str] = []
    monkeypatch.setattr(
        "football_agents.scheduler.DataEnrichmentService",
        lambda _repository: SimpleNamespace(
            sync=lambda _limit, evaluate: {
                "matches": 10, "market_odds": 7, "market_target_matches": 4,
                "evaluate": evaluate,
            }
        ),
    )
    monkeypatch.setattr(
        scheduler,
        "_run_task",
        lambda task_name, _action: child_tasks.append(task_name),
    )

    report = scheduler._sync_external_news_weather()

    assert report["market_odds"] == 7
    assert report["evaluate"] is False
    assert child_tasks == [
        "feature_build_post_external",
        "prospective_research_post_external_capture",
        "external_consensus_challenger_post_external_capture",
        "profit_allocation_readiness_post_external",
    ]


def test_external_refresh_skips_capture_chain_without_near_horizon_matches(tmp_path, monkeypatch):
    database = Database(Path(tmp_path) / "scheduler-no-horizon.db")
    database.initialize()
    scheduler = BackgroundAgentScheduler(Repository(database), TaskRunnerService(database))
    child_tasks: list[str] = []
    monkeypatch.setattr(
        "football_agents.scheduler.DataEnrichmentService",
        lambda _repository: SimpleNamespace(
            sync=lambda _limit, evaluate: {
                "matches": 10, "market_odds": 0, "market_target_matches": 0,
                "evaluate": evaluate,
            }
        ),
    )
    monkeypatch.setattr(
        scheduler,
        "_run_task",
        lambda task_name, _action: child_tasks.append(task_name),
    )

    scheduler._sync_external_news_weather()

    assert child_tasks == []


def test_primary_horizon_odds_capture_is_lightweight_and_runs_evidence_chain(tmp_path, monkeypatch):
    database = Database(Path(tmp_path) / "scheduler-primary-horizon.db")
    database.initialize()
    scheduler = BackgroundAgentScheduler(Repository(database), TaskRunnerService(database))
    seen: dict = {}
    child_tasks: list[str] = []

    def sync(limit, evaluate, **kwargs):
        seen.update({"limit": limit, "evaluate": evaluate, **kwargs})
        return {
            "matches": 10, "market_candidate_matches": 3,
            "market_odds": 2, "market_target_matches": 3,
        }

    monkeypatch.setattr(
        "football_agents.scheduler.DataEnrichmentService",
        lambda _repository: SimpleNamespace(sync=sync),
    )
    monkeypatch.setattr(
        scheduler,
        "_run_task",
        lambda task_name, _action: child_tasks.append(task_name),
    )

    report = scheduler._capture_primary_horizon_external_odds()

    assert report["market_odds"] == 2
    assert report["matches"] == 3
    assert report["matches_scanned"] == 10
    assert seen == {
        "limit": settings.agent_match_limit,
        "evaluate": False,
        "include_news_weather": False,
        "odds_minimum_minutes": 60,
        "odds_window_minutes": 120,
        "skip_existing_horizon_capture": True,
    }
    assert child_tasks == [
        "feature_build_primary_horizon",
        "prospective_research_primary_horizon_capture",
        "external_consensus_challenger_primary_horizon_capture",
        "named_book_gap_primary_horizon_capture",
        "profit_allocation_readiness_primary_horizon",
    ]


def test_primary_horizon_rechecks_fresh_existing_odds_without_new_fetch(tmp_path, monkeypatch):
    database = Database(Path(tmp_path) / "scheduler-primary-existing.db")
    database.initialize()
    scheduler = BackgroundAgentScheduler(Repository(database), TaskRunnerService(database))
    child_tasks: list[str] = []
    monkeypatch.setattr(
        "football_agents.scheduler.DataEnrichmentService",
        lambda _repository: SimpleNamespace(sync=lambda *_args, **_kwargs: {
            "matches": 3, "market_odds": 0, "market_target_matches": 0,
        }),
    )
    monkeypatch.setattr(
        scheduler,
        "_run_task",
        lambda task_name, _action: child_tasks.append(task_name),
    )

    scheduler._capture_primary_horizon_external_odds()

    assert child_tasks == [
        "external_consensus_challenger_primary_horizon_capture",
        "named_book_gap_primary_horizon_capture",
        "profit_allocation_readiness_primary_horizon",
    ]


def test_named_gap_scheduler_reports_waiting_window_once(tmp_path, monkeypatch):
    database = Database(Path(tmp_path) / "scheduler-named-gap-window.db")
    database.initialize()
    scheduler = BackgroundAgentScheduler(Repository(database), TaskRunnerService(database))
    result = {
        "matches": 20,
        "decisions": 0,
        "predictions": 0,
        "warnings": ["settled_selections<200"],
        "blocker_counts": [
            {"reason": "outside_primary_horizon", "matches": 20, "policies_affected": 25},
        ],
        "horizon_status": {
            "eligible_matches": 0,
            "before_window_matches": 20,
            "after_window_matches": 0,
            "window_minutes_to_kickoff": [60.0, 120.0],
            "next_primary_horizon_at": "2026-08-14T17:00:00+00:00",
        },
    }
    service = SimpleNamespace(
        capture_experiment=lambda _limit: result,
        experiment_report=lambda: {},
    )
    monkeypatch.setattr(
        "football_agents.scheduler.NamedBookGapResearchService",
        lambda *_args, **_kwargs: service,
    )
    monkeypatch.setattr(scheduler, "_write_report", lambda *_args: None)

    report = scheduler._capture_named_book_gap_research()

    assert report["warnings"] == [
        "settled_selections<200",
        "awaiting_primary_horizon:T-120..T-60;matches=20;"
        "next=2026-08-14T17:00:00+00:00",
    ]


def test_external_closing_capture_uses_last_fifteen_minutes_only(tmp_path, monkeypatch):
    database = Database(Path(tmp_path) / "scheduler-closing-horizon.db")
    database.initialize()
    scheduler = BackgroundAgentScheduler(Repository(database), TaskRunnerService(database))
    seen: dict = {}

    def sync(limit, evaluate, **kwargs):
        seen.update({"limit": limit, "evaluate": evaluate, **kwargs})
        return {"matches": 20, "market_candidate_matches": 2, "market_odds": 2}

    monkeypatch.setattr(
        "football_agents.scheduler.DataEnrichmentService",
        lambda _repository: SimpleNamespace(sync=sync),
    )

    report = scheduler._capture_external_closing_odds()

    assert report["market_odds"] == 2
    assert report["matches"] == 2
    assert report["matches_scanned"] == 20
    assert seen == {
        "limit": settings.agent_match_limit,
        "evaluate": False,
        "include_news_weather": False,
        "odds_minimum_minutes": 0,
        "odds_window_minutes": 15,
        "skip_existing_horizon_capture": True,
    }


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
        "external_consensus_challenger_critical_capture",
        "profit_allocation_readiness_critical",
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
