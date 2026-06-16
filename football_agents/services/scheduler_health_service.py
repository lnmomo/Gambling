from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .task_runner_service import TaskRunnerService


TASK_NAMES = {
    "official_sp_sync",
    "external_odds_sync",
    "live_recalculation",
    "recommendation_lifecycle_check",
    "backtest_run",
    "model_governance_check",
}


class SchedulerHealthService:
    def __init__(self, task_runner: TaskRunnerService | None = None) -> None:
        self.task_runner = task_runner or TaskRunnerService()

    def list_recent_task_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.task_runner.list_recent_task_runs(limit)

    def get_last_successful_run(self, task_name: str) -> dict[str, Any] | None:
        return self.task_runner.get_last_successful_run(task_name)

    def summarize(self) -> dict[str, Any]:
        recent = self.list_recent_task_runs(20)
        failures_today = 0
        today = datetime.now(timezone.utc).date()
        for row in recent:
            started = datetime.fromisoformat(str(row["started_at"]).replace("Z", "+00:00")).date()
            if started == today and row["status"] == "FAILED":
                failures_today += 1
        return {
            "known_tasks": sorted(TASK_NAMES),
            "recentTaskRuns": recent,
            "todayFailures": failures_today,
        }
