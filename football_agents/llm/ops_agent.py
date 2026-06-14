from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from .client import QwenClient


class AgentReview(BaseModel):
    summary: str
    status: str = Field(pattern="^(healthy|warning|error)$")
    data_quality_score: float = Field(ge=0, le=1)
    risks: list[str] = []
    actions: list[str] = []


class QwenOpsAgent:
    """Audits deterministic agent output without replacing its source-of-truth result."""

    def __init__(self, client: QwenClient | None = None) -> None:
        self.client = client or QwenClient()

    def review(self, agent_name: str, output: dict[str, Any]) -> dict[str, Any]:
        compact = self._compact(output)
        compact["_authoritative_status_semantics"] = {
            "rule": "The deterministic status fields are authoritative and must not be reinterpreted.",
            "news_status=up_to_date": "Deduplication succeeded; every fetched article already existed.",
            "news_duplicates": "Fetched articles already in storage; this is normal idempotent skipping, not duplicate rows or a failure.",
            "model_status=baseline_only": "Predictions exist, but external market calibration is unavailable.",
        }
        response = self.client.chat_json(
            "你是足球数据系统的审计 Agent。只分析给定 JSON，不补充未知事实。"
            "输出严格 JSON：summary、status(healthy/warning/error)、data_quality_score(0到1)、risks、actions。"
            "不能修改原始结果，不能给投注建议。所有数值必须逐字服从输入，禁止把正数说成0。"
            "字段 news 表示本轮新增新闻数，不代表新闻总量；news_existing 才表示库中已有新闻总数。"
            "weather_missing_metadata 表示因缺少球场经纬度而跳过天气；model_blocked 表示因必要输入不足而未产出预测。"
            "当 errors 为空时不得将执行描述为失败或 error，但可根据缺失情况标记 warning。",
            f"Agent: {agent_name}\n确定性执行结果（唯一事实来源）: {json.dumps(compact, ensure_ascii=False)}",
            max_tokens=600,
            temperature=0,
        )
        return AgentReview.model_validate(response).model_dump()

    def attach(self, agent_name: str, output: dict[str, Any]) -> dict[str, Any]:
        result = dict(output)
        try:
            review = self.review(agent_name, output)
            review["verified_facts"] = self._verified_facts(output)
            result["qwen_review"] = review
        except Exception as exc:
            result["qwen_review_error"] = str(exc)
        return result

    @staticmethod
    def _verified_facts(output: dict[str, Any]) -> dict[str, Any]:
        keys = ("matches", "market_events_fetched", "market_odds", "market_unmatched",
                "news_articles_fetched", "news", "news_duplicates", "news_existing",
                "weather", "weather_missing_metadata", "predictions", "evaluated",
                "features_built", "features_skipped", "model_blocked",
                "model_blocked_missing_official_odds", "market_status",
                "news_status", "weather_status", "model_status", "errors")
        return {key: output[key] for key in keys if key in output}

    @staticmethod
    def _compact(value: Any, depth: int = 0) -> Any:
        if depth >= 3:
            return "[truncated]"
        if isinstance(value, dict):
            return {str(key): QwenOpsAgent._compact(item, depth + 1)
                    for key, item in list(value.items())[:30]}
        if isinstance(value, list):
            return [QwenOpsAgent._compact(item, depth + 1) for item in value[:10]]
        if isinstance(value, str) and len(value) > 500:
            return value[:500] + "..."
        return value
