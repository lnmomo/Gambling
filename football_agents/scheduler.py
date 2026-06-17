from __future__ import annotations

import csv
import threading
from pathlib import Path
from typing import Any, Callable

from .backtesting import BacktestEngine
from .config import settings
from .features import build_features_for_official_matches
from .historical_agent import HistoricalCollectionAgent
from .integrations import DataEnrichmentService
from .international_history_agent import InternationalHistoryAgent
from .llm import LLMNewsAgent
from .official_data import OfficialDataService
from .repository import Repository
from .services.model_governance_persistence_service import ModelGovernancePersistenceService
from .services.task_runner_service import TaskRunnerService


TaskAction = Callable[[], dict[str, Any]]


class BackgroundAgentScheduler:
    """Runs production data agents once on startup and then on a fixed interval."""

    def __init__(self, repository: Repository | None = None,
                 task_runner: TaskRunnerService | None = None,
                 interval_seconds: int | None = None) -> None:
        self.repository = repository or Repository()
        self.task_runner = task_runner or TaskRunnerService()
        self.interval_seconds = max(60, interval_seconds or settings.background_agent_interval_seconds)
        self.stop_event = threading.Event()
        self.threads: list[threading.Thread] = []

    def start(self) -> None:
        if self.threads:
            return
        for task_name, action in self._tasks():
            thread = threading.Thread(
                target=self._loop,
                name=f"background-{task_name}",
                args=(task_name, action),
                daemon=True,
            )
            thread.start()
            self.threads.append(thread)

    def stop(self) -> None:
        self.stop_event.set()

    def _loop(self, task_name: str, action: TaskAction) -> None:
        while not self.stop_event.is_set():
            self._run_task(task_name, action)
            if self.stop_event.wait(self.interval_seconds):
                break

    def _run_task(self, task_name: str, action: TaskAction) -> None:
        run = self.task_runner.start_task_run(task_name)
        try:
            report = action()
            self.task_runner.finish_task_run_success(
                run["id"],
                affected_matches=int(report.get("matches", report.get("affected_matches", 0)) or 0),
                created_snapshots=int(report.get("market_odds", report.get("odds_snapshots", report.get("snapshots", 0))) or 0),
                created_predictions=int(report.get("predictions", report.get("evaluated", 0)) or 0),
                warnings=self._warnings(report),
            )
        except Exception as exc:
            self.task_runner.finish_task_run_failed(run["id"], str(exc))

    def _tasks(self) -> list[tuple[str, TaskAction]]:
        return [
            ("official_sp_sync", self._sync_official),
            ("external_odds_news_weather_sync", self._sync_external_news_weather),
            ("feature_build", self._build_features),
            ("qwen_news_analysis", self._analyze_news),
            ("historical_data_sync", self._sync_history),
            ("backtest_run", self._run_backtest),
            ("model_governance_check", self._check_model_governance),
        ]

    def _sync_official(self) -> dict[str, Any]:
        return OfficialDataService(self.repository).sync()

    def _sync_external_news_weather(self) -> dict[str, Any]:
        return DataEnrichmentService(self.repository).sync(settings.agent_match_limit, evaluate=False)

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
                summary["errors"].append(f'{match["official_match_id"]}: {exc}')
        return summary

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

    def _target_matches(self, limit: int) -> list[dict[str, Any]]:
        rows = self.repository.list_official_matches()
        return sorted(rows, key=lambda item: (
            item["status"] not in {"scheduled", "live"}, item["kickoff_time"]
        ))[:max(1, min(limit, 100))]

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
