from __future__ import annotations

import csv
import json
import threading
from pathlib import Path
from typing import Any, Callable

from .backtesting import BacktestEngine
from .config import settings
from .features import build_features_for_official_matches
from .external_consensus_challenger import ExternalConsensusChallengerService
from .historical_agent import HistoricalCollectionAgent
from .integrations import DataEnrichmentService
from .international_history_agent import InternationalHistoryAgent
from .llm import LLMNewsAgent
from .market_bias_monitor import MarketBiasMonitorService
from .official_data import OfficialDataService, OfficialResultService
from .official_sp_evidence_quality import build_official_sp_evidence_quality
from .profit_allocation_readiness import build_profit_allocation_readiness
from .paper_portfolio import PaperPortfolioService
from .profit_scorer_official import diagnose_official_profit_scorer_pool
from .profit_scorer_prospective import validate_profit_scorer_on_official_sp
from .repository import Repository
from .services.model_governance_persistence_service import ModelGovernancePersistenceService
from .services.task_runner_service import TaskRunnerService
from .research.prospective import ProspectiveResearchService


TaskAction = Callable[[], dict[str, Any]]


class BackgroundAgentScheduler:
    """Runs production data agents once on startup and then on a fixed interval."""

    def __init__(self, repository: Repository | None = None,
                 task_runner: TaskRunnerService | None = None,
                 interval_seconds: int | None = None) -> None:
        self.repository = repository or Repository()
        self.task_runner = task_runner or TaskRunnerService()
        self.interval_override_seconds = interval_seconds
        self.interval_seconds = max(60, interval_seconds or settings.background_agent_interval_seconds)
        self.stop_event = threading.Event()
        self.initial_official_sync_complete = threading.Event()
        self.threads: list[threading.Thread] = []

    def start(self) -> None:
        if self.threads:
            return
        tasks = self._tasks()
        official_task = next(item for item in tasks if item[0] == "official_sp_sync")
        official_thread = threading.Thread(
            target=self._loop,
            name="background-official_sp_sync",
            args=(*official_task, self._interval_for(official_task[0])),
            daemon=True,
        )
        official_thread.start()
        self.threads.append(official_thread)

        hourly_tasks = [item for item in tasks if item[0] != "official_sp_sync"]
        hourly_thread = threading.Thread(
            target=self._pipeline_loop,
            name="background-hourly-agent-pipeline",
            args=(hourly_tasks, self.interval_seconds, True),
            daemon=True,
        )
        hourly_thread.start()
        self.threads.append(hourly_thread)

    def stop(self) -> None:
        self.stop_event.set()

    def _loop(self, task_name: str, action: TaskAction, interval_seconds: int) -> None:
        while not self.stop_event.is_set():
            self._run_task(task_name, action)
            if task_name == "official_sp_sync":
                self.initial_official_sync_complete.set()
            if self.stop_event.wait(interval_seconds):
                break

    def _pipeline_loop(self, tasks: list[tuple[str, TaskAction]], interval_seconds: int,
                       wait_for_official: bool = False) -> None:
        if wait_for_official:
            while not self.stop_event.is_set():
                if self.initial_official_sync_complete.wait(1):
                    break
        while not self.stop_event.is_set():
            for task_name, action in tasks:
                if self.stop_event.is_set():
                    return
                self._run_task(task_name, action)
            if self.stop_event.wait(interval_seconds):
                break

    def _interval_for(self, task_name: str) -> int:
        if self.interval_override_seconds is not None:
            return self.interval_seconds
        if task_name in {"official_sp_sync", "official_sp_evidence_quality"}:
            return max(60, settings.official_sp_refresh_minutes * 60)
        return self.interval_seconds

    def _run_task(self, task_name: str, action: TaskAction) -> None:
        run = self.task_runner.start_task_run(task_name)
        try:
            report = action()
            affected_matches = report.get("matches", report.get("affected_matches"))
            if affected_matches is None:
                affected_matches = report.get("records")
            if affected_matches is None:
                affected_matches = int(report.get("created", 0) or 0) + int(report.get("updated", 0) or 0)
            self.task_runner.finish_task_run_success(
                run["id"],
                affected_matches=int(affected_matches or 0),
                created_snapshots=int(report.get("market_odds", report.get("hourly_observations", report.get("odds_snapshots", report.get("snapshots", 0)))) or 0),
                created_predictions=int(report.get("predictions", report.get("evaluated", 0)) or 0),
                warnings=self._warnings(report),
            )
        except Exception as exc:
            self.task_runner.finish_task_run_failed(run["id"], str(exc))

    def _tasks(self) -> list[tuple[str, TaskAction]]:
        tasks = [
            ("official_sp_sync", self._sync_official),
            ("external_odds_news_weather_sync", self._sync_external_news_weather),
            ("historical_data_sync", self._sync_history),
            ("feature_build", self._build_features),
        ]
        if settings.enable_prospective_research:
            tasks.append(("prospective_research_capture", self._capture_prospective_research))
            tasks.append(("external_consensus_challenger_capture", self._capture_external_consensus_challenger))
        tasks.extend([
            ("qwen_news_analysis", self._analyze_news),
            ("market_bias_shadow_monitor", self._refresh_market_bias_monitor),
            ("profit_scorer_official_pool_diagnosis", self._diagnose_profit_scorer_official_pool),
            ("profit_scorer_official_sp_validation", self._validate_profit_scorer_official_sp),
            ("backtest_run", self._run_backtest),
            ("model_governance_check", self._check_model_governance),
        ])
        return tasks

    def _sync_official(self) -> dict[str, Any]:
        report = OfficialDataService(self.repository).sync()
        self._run_task("official_results_sync", self._sync_official_results)
        self._run_task("paper_portfolio_settlement", self._settle_paper_portfolio)
        self._run_task("official_sp_evidence_quality", self._check_official_sp_evidence_quality)
        if settings.enable_prospective_research:
            self._run_task("prospective_research_critical_capture", self._capture_prospective_research)
            self._run_task(
                "external_consensus_challenger_critical_capture",
                self._capture_external_consensus_challenger,
            )
            self._run_task(
                "profit_allocation_readiness_critical",
                self._refresh_profit_allocation_readiness,
            )
        return report

    def _sync_official_results(self) -> dict[str, Any]:
        report = OfficialResultService(self.repository).sync()
        local_rows = sum(int(report.get(key, 0) or 0) for key in (
            "settled", "confirmed", "duplicates", "conflicts", "unmatched", "ambiguous", "skipped",
        ))
        return {
            "matches": local_rows,
            "evaluated": report.get("settled", 0) + report.get("confirmed", 0),
            "warnings": report.get("warnings", []),
            **report,
        }

    def _check_official_sp_evidence_quality(self) -> dict[str, Any]:
        report = build_official_sp_evidence_quality(self.repository.db)
        self._write_report(settings.official_sp_evidence_quality_report_path, report)
        return {
            "matches": report["summary"]["pre_match_matches"],
            "snapshots": report["summary"]["observations"],
            "decision": report["decision"],
            "warnings": report["warnings"],
            "report": report,
        }

    def _sync_external_news_weather(self) -> dict[str, Any]:
        report = DataEnrichmentService(self.repository).sync(
            settings.agent_match_limit, evaluate=False
        )
        if settings.enable_prospective_research and int(report.get("market_target_matches", 0) or 0) > 0:
            self._run_task(
                "feature_build_post_external",
                self._build_features,
            )
            self._run_task(
                "prospective_research_post_external_capture",
                self._capture_prospective_research,
            )
            self._run_task(
                "external_consensus_challenger_post_external_capture",
                self._capture_external_consensus_challenger,
            )
            self._run_task(
                "profit_allocation_readiness_post_external",
                self._refresh_profit_allocation_readiness,
            )
        return report

    def _build_features(self) -> dict[str, Any]:
        report = build_features_for_official_matches(
            self.repository,
            limit=settings.agent_match_limit,
            include_finished=False,
            min_matches=10,
        )
        return {"matches": report.get("matches", 0), **report}

    def _analyze_news(self) -> dict[str, Any]:
        agent = LLMNewsAgent(self.repository)
        matches = self._target_matches(settings.agent_match_limit)
        summary: dict[str, Any] = {
            "matches": len(matches), "configured": agent.configured(), "analyzed": 0,
            "cached": 0, "skipped_no_news": 0, "errors": [],
        }
        if not agent.configured():
            summary["errors"].append("Qwen API is not configured")
            return summary
        for match in matches:
            if not self.repository.list_news(match["id"], 1):
                summary["skipped_no_news"] += 1
                continue
            try:
                result = agent.analyze(match["id"], force=False)
                summary["cached" if result["status"] == "cached" else "analyzed"] += 1
            except Exception as exc:
                message = f'{match["official_match_id"]}: {exc}'
                summary["errors"].append(message)
                if self._terminal_qwen_error(str(exc)):
                    raise RuntimeError(f"Qwen authentication or quota unavailable; {message}") from exc
        return summary

    @staticmethod
    def _terminal_qwen_error(message: str) -> bool:
        return any(marker in message for marker in (
            "AllocationQuota.",
            "Qwen API HTTP 401",
            "Qwen API HTTP 403",
        ))

    def _sync_history(self) -> dict[str, Any]:
        history = HistoricalCollectionAgent(self.repository)
        international = InternationalHistoryAgent(self.repository)
        regular = history.sync(settings.historical_data_years_back)
        worldwide = history.sync_worldwide()
        national = international.sync()
        return {
            "matches": regular.get("database_matches", 0),
            "regular": regular,
            "worldwide": worldwide,
            "international": national,
            "errors": self._source_errors(regular) + self._source_errors(worldwide) + self._source_errors(national),
        }

    def _run_backtest(self) -> dict[str, Any]:
        path = Path(settings.auto_backtest_csv_path)
        if not path.is_absolute():
            path = settings.project_dir / path
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        report = BacktestEngine(settings.min_ev).run(rows, settings.bankroll)
        self.repository.save_backtest(
            report["id"], f"scheduled-{path.name}", report["parameters"], report["metrics"], report["equity"]
        )
        return {"matches": report["metrics"].get("matches", 0), "predictions": report["metrics"].get("bets", 0),
                "report_id": report["id"], "metrics": report["metrics"]}

    def _check_model_governance(self) -> dict[str, Any]:
        governance = ModelGovernancePersistenceService(self.repository.db)
        champion = governance.get_current_champion_model()
        challengers = governance.list_challenger_models()
        warnings: list[str] = []
        if not champion:
            warnings.append("champion model metadata is not available")
        decision = governance.save_model_promotion_decision({
            "model_id": champion["model_id"] if champion else "none",
            "decision": "KEEP_CHAMPION",
            "summary": "Scheduled governance check completed; no automatic promotion is allowed.",
            "champion_version": champion["version"] if champion else None,
            "challenger_count": len(challengers),
            "warnings": warnings,
            "actor": "background-model-governance-agent",
        })
        return {"matches": 1, "decision_id": decision["id"], "warnings": warnings}

    def _refresh_market_bias_monitor(self) -> dict[str, Any]:
        return MarketBiasMonitorService(self.repository.db).refresh(run_shadow=True)

    def _diagnose_profit_scorer_official_pool(self) -> dict[str, Any]:
        report = diagnose_official_profit_scorer_pool(
            self.repository.db,
            settings.profit_scorer_artifact_path,
            settings.agent_match_limit,
        )
        self._write_report(settings.profit_scorer_official_pool_report_path, report)
        top_blockers = [str(item.get("reason")) for item in report.get("blocker_counts", [])[:3]]
        return {
            "matches": report.get("scanned_matches", 0),
            "evaluated": report.get("scored_matches", 0),
            "predictions": report.get("passed_scorer", 0),
            "warnings": top_blockers,
            "report_path": settings.profit_scorer_official_pool_report_path,
            "report": report,
        }

    def _validate_profit_scorer_official_sp(self) -> dict[str, Any]:
        report = validate_profit_scorer_on_official_sp(self.repository.db, settings.profit_scorer_artifact_path)
        self._write_report(settings.profit_scorer_official_sp_validation_report_path, report)
        self._run_task("profit_allocation_readiness", self._refresh_profit_allocation_readiness)
        return {
            "matches": report.get("opening_pre_match_snapshots", 0),
            "evaluated": report.get("scored_snapshots", 0),
            "predictions": report.get("selected_snapshots", 0),
            "snapshots": report.get("settled_selected_snapshots", 0),
            "settled_selected": report.get("settled_selected_snapshots", 0),
            "decision": report.get("decision"),
            "warnings": report.get("decision_reasons", []),
            "report": report,
        }

    def _refresh_profit_allocation_readiness(self) -> dict[str, Any]:
        report = build_profit_allocation_readiness(settings.profit_daily_budget)
        self._write_report(settings.profit_allocation_readiness_report_path, report)
        self._run_task("paper_portfolio_allocation", self._allocate_paper_portfolio)
        return {
            "matches": len(report.get("strategies", [])),
            "predictions": len(report.get("allocations", [])),
            "decision": report.get("decision"),
            "warnings": [] if report.get("decision") == "PAPER_ALLOCATION_READY" else [str(report.get("decision"))],
            "report": report,
        }

    def _allocate_paper_portfolio(self) -> dict[str, Any]:
        service = PaperPortfolioService(self.repository.db)
        report = service.allocate(daily_budget=settings.profit_daily_budget)
        self._write_report(settings.paper_portfolio_report_path, service.summary())
        return {
            "matches": report.get("positions_created", 0),
            "predictions": report.get("positions_created", 0),
            "warnings": [] if report.get("status") in {"allocated", "duplicate"} else [str(report.get("status"))],
            **report,
        }

    def _settle_paper_portfolio(self) -> dict[str, Any]:
        service = PaperPortfolioService(self.repository.db)
        report = service.settle()
        self._write_report(settings.paper_portfolio_report_path, service.summary())
        return report

    def _capture_prospective_research(self) -> dict[str, Any]:
        report = ProspectiveResearchService(self.repository.db, self.repository).capture(
            settings.agent_match_limit
        )
        actionable_skips = [
            f"{reason}:{count}"
            for reason, count in (report.get("skip_reasons") or {}).items()
            if reason not in {"ineligible_status", "kickoff_not_in_future"} and int(count or 0) > 0
        ]
        return {**report, "warnings": list(report.get("warnings", [])) + actionable_skips}

    def _capture_external_consensus_challenger(self) -> dict[str, Any]:
        result = ExternalConsensusChallengerService(self.repository.db, self.repository).capture(
            settings.agent_match_limit
        )
        self._write_report(settings.external_consensus_challenger_report_path, result["report"])
        input_blockers = [
            f'{item.get("reason")}:{int(item.get("matches") or 0)}'
            for item in result.get("blocker_counts", [])
            if int(item.get("matches") or 0) > 0
        ]
        return {
            **result,
            "snapshots": result.get("decisions", 0),
            "warnings": list(result.get("warnings", [])) + input_blockers,
        }

    def _target_matches(self, limit: int) -> list[dict[str, Any]]:
        return self.repository.list_active_official_matches(max(1, min(limit, 100)))

    @staticmethod
    def _write_report(path_text: str, report: dict[str, Any]) -> None:
        path = Path(path_text)
        if not path.is_absolute():
            path = settings.project_dir / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _warnings(report: dict[str, Any]) -> list[str]:
        warnings = list(report.get("warnings", []))
        if report.get("errors"):
            warnings.extend(str(item) for item in report["errors"][:10])
        return warnings

    @staticmethod
    def _source_errors(report: dict[str, Any]) -> list[str]:
        errors = list(report.get("errors", []))
        errors.extend(str(item.get("error")) for item in report.get("sources", []) if item.get("status") == "failed")
        return [item for item in errors if item]
