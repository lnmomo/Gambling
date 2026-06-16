from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any


def with_retry(fn: Callable[[], Any], options: dict[str, Any] | None = None) -> dict[str, Any]:
    options = options or {}
    max_attempts = int(options.get("max_attempts", 3))
    base_delay = float(options.get("base_delay_seconds", 1))
    backoff = float(options.get("backoff", 2))
    sleeper = options.get("sleep", time.sleep)
    attempts = 0
    last_error: str | None = None
    for index in range(max_attempts):
        attempts = index + 1
        try:
            return {"success": True, "result": fn(), "attempts": attempts}
        except Exception as exc:  # noqa: BLE001 - task boundary converts failures to structured results.
            last_error = str(exc)
            if attempts >= max_attempts:
                break
            sleeper(base_delay * (backoff ** index))
    return {"success": False, "error": last_error or "unknown error", "attempts": attempts}
