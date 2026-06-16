from __future__ import annotations

from typing import Any

from ..db import Database, db
from .persistence_utils import dumps, loads, new_id, utcnow


class AuditLogPersistenceService:
    def __init__(self, database: Database = db) -> None:
        self.db = database

    def save_audit_log(self, entry: dict[str, Any]) -> dict[str, Any]:
        record = {
            "id": entry.get("id") or new_id(),
            "created_at": entry.get("created_at") or utcnow(),
            "entity_type": entry["entity_type"],
            "entity_id": entry["entity_id"],
            "action": entry["action"],
            "summary": entry["summary"],
            "before_json": dumps(entry.get("before")) if "before" in entry else entry.get("before_json"),
            "after_json": dumps(entry.get("after")) if "after" in entry else entry.get("after_json"),
            "trigger_json": dumps(entry.get("trigger")) if "trigger" in entry else entry.get("trigger_json"),
            "severity": entry.get("severity", "INFO"),
            "actor": entry.get("actor", "system"),
        }
        with self.db.connect() as c:
            c.execute("""INSERT INTO audit_logs
                (id,created_at,entity_type,entity_id,action,summary,before_json,after_json,trigger_json,severity,actor)
                VALUES(:id,:created_at,:entity_type,:entity_id,:action,:summary,:before_json,:after_json,
                 :trigger_json,:severity,:actor)""", record)
        return record

    def list_audit_logs(self, filters: dict[str, Any] | None = None, limit: int = 200) -> list[dict[str, Any]]:
        filters = filters or {}
        conditions: list[str] = []
        params: list[Any] = []
        for key in ("entity_type", "entity_id", "severity", "action"):
            if filters.get(key):
                conditions.append(f"{key}=?")
                params.append(filters[key])
        query = "SELECT * FROM audit_logs"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self.db.connect() as c:
            return [self._decode(dict(row)) for row in c.execute(query, params).fetchall()]

    def get_audit_logs_by_entity(self, entity_type: str, entity_id: str) -> list[dict[str, Any]]:
        return self.list_audit_logs({"entity_type": entity_type, "entity_id": entity_id})

    @staticmethod
    def _decode(row: dict[str, Any]) -> dict[str, Any]:
        for key in ("before_json", "after_json", "trigger_json"):
            row[key[:-5]] = loads(row.pop(key), None)
        return row
