from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any, TypeVar

from ..db import Database, db

T = TypeVar("T")
_MEMORY_KEYS: dict[str, Any] = {}


def hash_payload(payload: Any) -> str:
    normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def make_snapshot_id(official_match_id: str, captured_at: str, payload_hash: str) -> str:
    return hash_payload({"official_match_id": official_match_id, "captured_at": captured_at, "payload_hash": payload_hash})[:32]


def is_duplicate_snapshot(official_match_id: str, payload_hash: str, snapshot_type: str, database: Database = db) -> bool:
    table = "external_odds_snapshots" if snapshot_type == "external" else "official_sp_snapshots"
    with database.connect() as c:
        row = c.execute(f"SELECT 1 FROM {table} WHERE official_match_id=? AND raw_payload_hash=? LIMIT 1",
                        (official_match_id, payload_hash)).fetchone()
        return row is not None


def save_once(key: str, callback: Callable[[], T]) -> T:
    if key in _MEMORY_KEYS:
        return _MEMORY_KEYS[key]
    value = callback()
    _MEMORY_KEYS[key] = value
    return value


def clear_memory_keys() -> None:
    _MEMORY_KEYS.clear()
