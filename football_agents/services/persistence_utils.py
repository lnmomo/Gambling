from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return uuid.uuid4().hex


def dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True, default=str)


def loads(value: str | None, default: Any = None) -> Any:
    if value is None:
        return default
    return json.loads(value)
