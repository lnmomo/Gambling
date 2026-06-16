from __future__ import annotations

from typing import Any

from ..db import Database, db
from .audit_log_persistence_service import AuditLogPersistenceService
from .persistence_utils import dumps, loads, utcnow


class ModelGovernancePersistenceService:
    def __init__(self, database: Database = db) -> None:
        self.db = database
        self.audit = AuditLogPersistenceService(database)

    def save_model_governance_record(self, record: dict[str, Any]) -> dict[str, Any]:
        item = {
            "model_id": record["model_id"],
            "model_name": record["model_name"],
            "model_type": record["model_type"],
            "version": record["version"],
            "role": record["role"],
            "created_at": record.get("created_at") or utcnow(),
            "activated_at": record.get("activated_at"),
            "archived_at": record.get("archived_at"),
            "training_match_count": record.get("training_match_count"),
            "validation_match_count": record.get("validation_match_count"),
            "test_match_count": record.get("test_match_count"),
            "metrics_json": dumps(record.get("metrics", record.get("metrics_json", {}))),
            "baseline_model_id": record.get("baseline_model_id"),
            "promotion_status": record.get("promotion_status", "PENDING"),
            "promotion_reason": record.get("promotion_reason"),
            "warnings_json": dumps(record.get("warnings", [])),
        }
        with self.db.connect() as c:
            if item["role"] == "CHAMPION" and not item["archived_at"]:
                c.execute("""UPDATE model_governance_records SET archived_at=?
                    WHERE role='CHAMPION' AND archived_at IS NULL AND model_id<>?""", (utcnow(), item["model_id"]))
            c.execute("""INSERT INTO model_governance_records
                (model_id,model_name,model_type,version,role,created_at,activated_at,archived_at,
                 training_match_count,validation_match_count,test_match_count,metrics_json,baseline_model_id,
                 promotion_status,promotion_reason,warnings_json)
                VALUES(:model_id,:model_name,:model_type,:version,:role,:created_at,:activated_at,:archived_at,
                 :training_match_count,:validation_match_count,:test_match_count,:metrics_json,:baseline_model_id,
                 :promotion_status,:promotion_reason,:warnings_json)
                ON CONFLICT(model_id) DO UPDATE SET metrics_json=excluded.metrics_json,
                 promotion_status=excluded.promotion_status,promotion_reason=excluded.promotion_reason,
                 warnings_json=excluded.warnings_json""", item)
        return item

    def get_current_champion_model(self) -> dict[str, Any] | None:
        with self.db.connect() as c:
            row = c.execute("""SELECT * FROM model_governance_records
                WHERE role='CHAMPION' AND archived_at IS NULL ORDER BY activated_at DESC LIMIT 1""").fetchone()
        return self._decode(dict(row)) if row else None

    def list_challenger_models(self) -> list[dict[str, Any]]:
        with self.db.connect() as c:
            rows = c.execute("""SELECT * FROM model_governance_records
                WHERE role='CHALLENGER' AND archived_at IS NULL ORDER BY created_at DESC""").fetchall()
        return [self._decode(dict(row)) for row in rows]

    def save_model_promotion_decision(self, decision: dict[str, Any]) -> dict[str, Any]:
        audit = self.audit.save_audit_log({
            "entity_type": "model_governance",
            "entity_id": decision.get("model_id", "unknown"),
            "action": "promotion_decision",
            "summary": decision.get("summary", decision.get("decision", "promotion decision recorded")),
            "after": decision,
            "severity": "INFO",
            "actor": decision.get("actor", "model-governance-agent"),
        })
        return audit

    @staticmethod
    def _decode(row: dict[str, Any]) -> dict[str, Any]:
        row["metrics"] = loads(row.pop("metrics_json"), {})
        row["warnings"] = loads(row.pop("warnings_json"), [])
        return row
