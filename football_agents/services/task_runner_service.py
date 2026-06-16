from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from ..db import Database, db


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskRunnerService:
    def __init__(self, database: Database = db) -> None:
        self.db = database

    def start_task_run(self, task_name: str) -> dict[str, Any]:
        record = {
            "id": uuid.uuid4().hex,
            "task_name": task_name,
            "started_at": utcnow(),
            "finished_at": None,
            "status": "RUNNING",
            "attempts": 1,
            "error_message": None,
            "affected_matches": 0,
            "created_snapshots": 0,
            "created_predictions": 0,
            "warnings_json": "[]",
        }
        with self.db.connect() as c:
            c.execute("""INSERT INTO task_runs
                (id,task_name,started_at,finished_at,status,attempts,error_message,affected_matches,
                 created_snapshots,created_predictions,warnings_json)
                VALUES(:id,:task_name,:started_at,:finished_at,:status,:attempts,:error_message,
                 :affected_matches,:created_snapshots,:created_predictions,:warnings_json)""", record)
        return record

    def finish_task_run_success(self, run_id: str, *, attempts: int = 1, affected_matches: int = 0,
                                created_snapshots: int = 0, created_predictions: int = 0,
                                warnings: list[str] | None = None) -> dict[str, Any]:
        return self._finish(run_id, "SUCCESS", attempts, None, affected_matches, created_snapshots,
                            created_predictions, warnings or [])

    def finish_task_run_failed(self, run_id: str, error_message: str, *, attempts: int = 1,
                               warnings: list[str] | None = None) -> dict[str, Any]:
        return self._finish(run_id, "FAILED", attempts, error_message, 0, 0, 0, warnings or [])

    def _finish(self, run_id: str, status: str, attempts: int, error_message: str | None,
                affected_matches: int, created_snapshots: int, created_predictions: int,
                warnings: list[str]) -> dict[str, Any]:
        with self.db.connect() as c:
            c.execute("""UPDATE task_runs SET finished_at=?,status=?,attempts=?,error_message=?,
                affected_matches=?,created_snapshots=?,created_predictions=?,warnings_json=? WHERE id=?""",
                (utcnow(), status, attempts, error_message, affected_matches, created_snapshots,
                 created_predictions, json.dumps(warnings, ensure_ascii=False), run_id))
        return self.get_task_run(run_id) or {}

    def get_task_run(self, run_id: str) -> dict[str, Any] | None:
        with self.db.connect() as c:
            row = c.execute("SELECT * FROM task_runs WHERE id=?", (run_id,)).fetchone()
        return self._decode(dict(row)) if row else None

    def list_recent_task_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.db.connect() as c:
            rows = c.execute("SELECT * FROM task_runs ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()
        return [self._decode(dict(row)) for row in rows]

    def get_last_successful_run(self, task_name: str) -> dict[str, Any] | None:
        with self.db.connect() as c:
            row = c.execute("""SELECT * FROM task_runs WHERE task_name=? AND status='SUCCESS'
                ORDER BY finished_at DESC LIMIT 1""", (task_name,)).fetchone()
        return self._decode(dict(row)) if row else None

    @staticmethod
    def _decode(row: dict[str, Any]) -> dict[str, Any]:
        row["warnings"] = json.loads(row.pop("warnings_json") or "[]")
        return row
