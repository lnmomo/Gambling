from __future__ import annotations

import json
from typing import Any
from urllib.request import ProxyHandler, Request, build_opener

from ..config import settings


class QwenClient:
    """Small OpenAI-compatible client shared by every Qwen-assisted agent."""

    def configured(self) -> bool:
        return settings.llm_provider.lower() == "qwen" and all(
            (settings.llm_api_key, settings.llm_base_url, settings.llm_model)
        )

    def chat_json(self, system: str, user: str, *, max_tokens: int = 900,
                  temperature: float = 0.1) -> dict[str, Any]:
        if not self.configured():
            raise RuntimeError("Qwen API 尚未在根目录 .env 或 api.env 中配置")
        payload = {
            "model": settings.llm_model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        request = Request(
            f"{settings.llm_base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {settings.llm_api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        # Windows Internet Options may expose a stale local proxy to urllib.
        # DashScope is reachable directly, so bypass system proxy discovery here.
        with build_opener(ProxyHandler({})).open(request, timeout=settings.llm_timeout_seconds) as response:
            body = json.loads(response.read().decode("utf-8"))
        content = body["choices"][0]["message"]["content"]
        return json.loads(content)

    def status(self) -> dict[str, Any]:
        return {"configured": self.configured(), "provider": settings.llm_provider,
                "model": settings.llm_model,
                "base_host": settings.llm_base_url.split("//")[-1].split("/")[0]}
