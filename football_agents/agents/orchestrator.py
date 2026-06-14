from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..config import settings
from ..historical_agent import HistoricalCollectionAgent
from ..integrations import DataEnrichmentService
from ..international_history_agent import InternationalHistoryAgent
from ..llm import LLMNewsAgent, QwenOpsAgent
from ..official_data import OfficialDataService
from ..repository import Repository
from .workflow import DecisionWorkflow


class AgentOrchestrator:
    """Runs the real data, Qwen, model, and critic agents with persisted step results."""

    def __init__(self, repository: Repository | None = None) -> None:
        self.repository = repository or Repository()
        self.official = OfficialDataService(self.repository)
        self.history = HistoricalCollectionAgent(self.repository)
        self.international_history = InternationalHistoryAgent(self.repository)
        self.enrichment = DataEnrichmentService(self.repository)
        self.qwen = LLMNewsAgent(self.repository)
        self.qwen_ops = QwenOpsAgent()
        self.workflow = DecisionWorkflow(self.repository)

    def run(self, limit: int | None = None, include_history: bool = False,
            force_official: bool = False, force_qwen: bool = False,
            trigger_name: str = "api") -> dict[str, Any]:
        match_limit = max(1, min(limit or settings.agent_match_limit, 100))
        run_id = self.repository.start_agent_run(trigger_name)
        failures = 0

        def step(name: str, inputs: dict[str, Any], action: Callable[[], dict[str, Any]]) -> dict[str, Any]:
            nonlocal failures
            step_id = self.repository.start_agent_step(run_id, name, inputs)
            try:
                output = self.qwen_ops.attach(name, action())
                step_status = "partial" if output.get("errors") else "success"
                if output.get("qwen_review_error"):
                    step_status = "partial"
                if step_status == "partial":
                    failures += 1
                self.repository.finish_agent_step(step_id, step_status, output)
                return output
            except Exception as exc:
                failures += 1
                self.repository.finish_agent_step(step_id, "error", error_message=str(exc))
                return {"error": str(exc)}

        step("official-data-agent", {"force": force_official},
             lambda: self.official.sync(force=force_official))
        if include_history:
            step("historical-data-agent", {"years_back": settings.historical_data_years_back},
                 lambda: self.history.sync(settings.historical_data_years_back))
            step("international-history-agent", {"source": settings.international_data_url},
                 self.international_history.sync)
        step("market-news-weather-agent", {"limit": match_limit},
             lambda: self.enrichment.sync(match_limit, evaluate=False))

        matches = self._target_matches(match_limit)
        qwen_summary: dict[str, Any] = {"configured": self.qwen.configured(), "analyzed": 0,
                                       "cached": 0, "skipped_no_news": 0, "errors": []}

        def run_qwen() -> dict[str, Any]:
            if not self.qwen.configured():
                raise RuntimeError("Qwen API is not configured in root .env or api.env")
            for match in matches:
                if not self.repository.list_news(match["id"], 1):
                    qwen_summary["skipped_no_news"] += 1
                    continue
                try:
                    result = self.qwen.analyze(match["id"], force=force_qwen)
                    qwen_summary["cached" if result["status"] == "cached" else "analyzed"] += 1
                except Exception as exc:
                    qwen_summary["errors"].append({"match_id": match["id"], "error": str(exc)})
            return qwen_summary

        step("qwen-news-agent", {"model": settings.llm_model, "matches": len(matches)}, run_qwen)

        decision_summary: dict[str, Any] = {"evaluated": 0, "bet": 0, "watch": 0,
                                            "no_bet": 0, "errors": []}

        def run_decisions() -> dict[str, Any]:
            for match in matches:
                try:
                    result = self.workflow.evaluate(match["id"])
                    status = result["signal"]["status"]
                    decision_summary["evaluated"] += 1
                    decision_summary[status.lower()] += 1
                except Exception as exc:
                    decision_summary["errors"].append({"match_id": match["id"], "error": str(exc)})
            return decision_summary

        step("model-critic-agent", {"matches": len(matches)}, run_decisions)
        status = "success" if failures == 0 else "partial"
        summary = {"matches": len(matches), "failed_steps": failures,
                   "qwen": qwen_summary, "decisions": decision_summary}
        self.repository.finish_agent_run(run_id, status, summary)
        return self.repository.get_agent_run(run_id) or {"id": run_id, "status": status, "summary": summary}

    def status(self, limit: int = 20) -> dict[str, Any]:
        return {"qwen": self.qwen.status(), "runs": self.repository.list_agent_runs(limit)}

    def _target_matches(self, limit: int) -> list[dict[str, Any]]:
        rows = self.repository.list_official_matches()
        return sorted(rows, key=lambda item: (
            item["status"] not in {"scheduled", "live"}, item["kickoff_time"]
        ))[:limit]
