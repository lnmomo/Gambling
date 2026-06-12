from __future__ import annotations

import hashlib
import json
from typing import Any
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field

from ..config import settings
from ..repository import Repository


class NewsAnalysis(BaseModel):
    summary: str
    home_team_impact: float = Field(ge=-0.2, le=0.2)
    away_team_impact: float = Field(ge=-0.2, le=0.2)
    lineup_confidence: float = Field(ge=0, le=1)
    news_confidence: float = Field(ge=0, le=1)
    injuries: list[str] = []
    risks: list[str] = []
    evidence: list[str] = []


class LLMNewsAgent:
    def __init__(self, repository: Repository | None = None) -> None:
        self.repository = repository or Repository()

    def configured(self) -> bool:
        return all((settings.llm_api_key, settings.llm_base_url, settings.llm_model))

    def analyze(self, match_id: int, force: bool = False) -> dict[str, Any]:
        if not self.configured():
            raise RuntimeError("LLM API 尚未配置")
        match = self.repository.get_match(match_id)
        if not match:
            raise KeyError(f"Match {match_id} not found")
        news = self.repository.list_news(match_id, settings.llm_max_news_items)
        if not news:
            raise RuntimeError("该比赛没有可分析的新闻")
        evidence = [{"title": item.get("raw_text", ""), "published_at": item.get("published_at"),
                     "source_url": item.get("source_url")} for item in news]
        input_hash = hashlib.sha256(json.dumps(evidence, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        cached = self.repository.find_llm_analysis(match_id, settings.llm_provider, settings.llm_model, input_hash)
        if cached and not force:
            normalized = self._conservative(cached["analysis"])
            if normalized != cached["analysis"]:
                cached = self.repository.save_llm_analysis(match_id, settings.llm_provider, settings.llm_model,
                                                           input_hash, normalized)
            return {"status": "cached", **cached}
        prompt = self._prompt(match, evidence)
        payload = {"model": settings.llm_model, "temperature": 0.1, "max_tokens": 900,
                   "response_format": {"type": "json_object"},
                   "messages": [{"role": "system", "content": "你是足球情报结构化分析器。只依据给定新闻，禁止补充未知事实，输出严格 JSON。"},
                                {"role": "user", "content": prompt}]}
        request = Request(f"{settings.llm_base_url}/chat/completions", data=json.dumps(payload).encode(),
                          headers={"Authorization": f"Bearer {settings.llm_api_key}",
                                   "Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=settings.llm_timeout_seconds) as response:
            body = json.loads(response.read().decode("utf-8"))
        content = body["choices"][0]["message"]["content"]
        analysis = self._conservative(NewsAnalysis.model_validate(json.loads(content)).model_dump())
        saved = self.repository.save_llm_analysis(match_id, settings.llm_provider, settings.llm_model,
                                                   input_hash, analysis)
        return {"status": "created", **saved}

    @staticmethod
    def _prompt(match: dict[str, Any], evidence: list[dict[str, Any]]) -> str:
        schema = {"summary":"不超过120字", "home_team_impact":0.0, "away_team_impact":0.0,
                  "lineup_confidence":0.0, "news_confidence":0.0, "injuries":[], "risks":[], "evidence":[]}
        return (f'比赛：{match["home_team"]} vs {match["away_team"]}\n'
                f'新闻：{json.dumps(evidence, ensure_ascii=False)}\n'
                f'按此结构输出：{json.dumps(schema, ensure_ascii=False)}\n'
                "impact 表示新闻对对应球队胜率的方向性微调，范围 -0.2 到 0.2；证据不足必须为 0。")

    def status(self) -> dict[str, Any]:
        return {"configured": self.configured(), "provider": settings.llm_provider,
                "model": settings.llm_model, "base_host": settings.llm_base_url.split("//")[-1].split("/")[0]}

    @staticmethod
    def _conservative(analysis: dict[str, Any]) -> dict[str, Any]:
        result = dict(analysis)
        if result.get("news_confidence", 0) < 0.4 or not result.get("evidence"):
            result["home_team_impact"] = 0.0
            result["away_team_impact"] = 0.0
        return result
