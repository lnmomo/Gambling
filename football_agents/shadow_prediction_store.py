from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from .db import Database, db
from .true_odds_config import TrueOddsFilterConfig
from .services.audit_log_persistence_service import AuditLogPersistenceService

DATABASE_REGISTRY: dict[str, Database] = {}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def loads(value: str | None, default: Any = None) -> Any:
    return json.loads(value) if value else default


@dataclass
class TrueOddsConfigVersion:
    config_version_id: str
    config_name: str
    config: TrueOddsFilterConfig
    source_optimization_run_id: str | None = None
    source_optimization_summary: dict[str, Any] | None = None
    created_at: str = field(default_factory=utcnow)
    created_by: str = "system"
    status: str = "DRAFT"
    shadow_started_at: str | None = None
    shadow_ended_at: str | None = None
    activated_at: str | None = None
    promotion_status: str = "NOT_EVALUATED"
    warnings: list[str] = field(default_factory=list)
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["config"] = self.config.to_dict()
        return data


class ShadowPredictionStore:
    def __init__(self, database: Database = db) -> None:
        self.db = database
        self.audit = AuditLogPersistenceService(database)

    def create_config_version(self, config: TrueOddsFilterConfig, source_optimization_run_id: str | None = None,
                              source_optimization_summary: dict[str, Any] | None = None, name: str | None = None,
                              notes: str | None = None, created_by: str = "system") -> TrueOddsConfigVersion:
        version = TrueOddsConfigVersion(uuid.uuid4().hex, name or config.name, config,
                                        source_optimization_run_id, source_optimization_summary,
                                        created_by=created_by, notes=notes)
        version._database = self.db
        DATABASE_REGISTRY[version.config_version_id] = self.db
        return self.save_config_version(version)

    def save_config_version(self, version: TrueOddsConfigVersion) -> TrueOddsConfigVersion:
        with self.db.connect() as c:
            c.execute("""INSERT INTO true_odds_config_versions
                (config_version_id,config_name,config_json,source_optimization_run_id,source_optimization_summary_json,
                 created_at,created_by,status,shadow_started_at,shadow_ended_at,activated_at,promotion_status,warnings_json,notes)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(config_version_id) DO UPDATE SET
                 config_name=excluded.config_name,config_json=excluded.config_json,status=excluded.status,
                 shadow_started_at=excluded.shadow_started_at,shadow_ended_at=excluded.shadow_ended_at,
                 activated_at=excluded.activated_at,promotion_status=excluded.promotion_status,
                 warnings_json=excluded.warnings_json,notes=excluded.notes""",
                (version.config_version_id, version.config_name, dumps(version.config.to_dict()),
                 version.source_optimization_run_id, dumps(version.source_optimization_summary),
                 version.created_at, version.created_by, version.status, version.shadow_started_at,
                 version.shadow_ended_at, version.activated_at, version.promotion_status,
                 dumps(version.warnings), version.notes))
        self._audit("create_shadow_config", version.config_version_id, after=version.to_dict())
        version._database = self.db
        DATABASE_REGISTRY[version.config_version_id] = self.db
        return version

    def get_config_version(self, config_version_id: str) -> TrueOddsConfigVersion | None:
        with self.db.connect() as c:
            row = c.execute("SELECT * FROM true_odds_config_versions WHERE config_version_id=?", (config_version_id,)).fetchone()
            version = self._decode_version(dict(row)) if row else None
            if version:
                version._database = self.db
                DATABASE_REGISTRY[version.config_version_id] = self.db
            return version

    def list_config_versions(self, where: str = "", params: tuple[Any, ...] = ()) -> list[TrueOddsConfigVersion]:
        query = "SELECT * FROM true_odds_config_versions"
        if where:
            query += " WHERE " + where
        query += " ORDER BY created_at DESC"
        with self.db.connect() as c:
            versions = [self._decode_version(dict(row)) for row in c.execute(query, params).fetchall()]
        for version in versions:
            version._database = self.db
            DATABASE_REGISTRY[version.config_version_id] = self.db
        return versions

    def get_active_shadow_config_versions(self) -> list[TrueOddsConfigVersion]:
        return self.list_config_versions("status='SHADOW_RUNNING'")

    def get_latest_recommended_config_version(self) -> TrueOddsConfigVersion | None:
        rows = self.list_config_versions("promotion_status='ENABLE_FILTER_ONLY_RECOMMENDED'")
        return rows[0] if rows else None

    def archive_config_version(self, config_version_id: str) -> None:
        version = self.get_config_version(config_version_id)
        if not version:
            return
        before = version.to_dict()
        version.status = "ARCHIVED"
        self.save_config_version(version)
        self._audit("archive_true_odds_config_version", config_version_id, before=before, after=version.to_dict())

    def start_shadow_validation(self, config_version_id: str) -> TrueOddsConfigVersion:
        version = self._require_version(config_version_id)
        before = version.to_dict()
        version.status = "SHADOW_RUNNING"
        version.shadow_started_at = utcnow()
        self.save_config_version(version)
        self._audit("start_shadow_validation", config_version_id, before=before, after=version.to_dict())
        return version

    def activate_filter_only(self, config_version_id: str, confirm: bool = False, force: bool = False) -> TrueOddsConfigVersion:
        if not confirm:
            raise PermissionError("activate-filter-only requires --confirm")
        version = self._require_version(config_version_id)
        if version.config.mode == "ADJUST_PROBABILITY":
            self._audit("activate_filter_only_rejected", config_version_id, after={"reason": "ADJUST_PROBABILITY blocked"}, severity="ERROR")
            raise ValueError("ADJUST_PROBABILITY cannot be activated")
        if version.promotion_status != "ENABLE_FILTER_ONLY_RECOMMENDED" and not force:
            raise PermissionError("promotion gate has not recommended activation; use --force for manual override")
        before = version.to_dict()
        version.status = "ACTIVE_FILTER_ONLY"
        version.promotion_status = "MANUALLY_ACTIVATED"
        version.activated_at = utcnow()
        self.save_config_version(version)
        self._audit("force_activate_filter_only" if force else "activate_filter_only", config_version_id, before=before, after=version.to_dict(), severity="WARNING" if force else "INFO")
        return version

    def save_shadow_prediction(self, record: dict[str, Any]) -> dict[str, Any]:
        record = {**record, "id": record.get("id") or uuid.uuid4().hex, "created_at": record.get("created_at") or utcnow()}
        with self.db.connect() as c:
            existing = c.execute("""SELECT * FROM live_shadow_predictions
                WHERE official_match_id=? AND config_version_id=? AND COALESCE(official_sp_snapshot_id,'')=COALESCE(?,'')
                AND COALESCE(external_odds_snapshot_id,'')=COALESCE(?,'')""",
                (record["official_match_id"], record["config_version_id"], record.get("official_sp_snapshot_id"),
                 record.get("external_odds_snapshot_id"))).fetchone()
            if existing:
                decoded = self._decode_shadow(dict(existing))
                decoded["_database"] = self.db
                return decoded
            c.execute("""INSERT INTO live_shadow_predictions
                (id,created_at,match_id,official_match_id,kickoff_time,league,config_version_id,true_odds_config_snapshot_json,
                 official_sp_snapshot_id,external_odds_snapshot_id,baseline_prediction_id,baseline_recommendation,
                 baseline_selected_outcome,baseline_ev,baseline_probability,baseline_official_sp,shadow_recommendation,
                 shadow_selected_outcome,shadow_ev,shadow_lower_bound_ev,shadow_edge_quality_score,shadow_edge_quality_level,
                 shadow_adaptive_threshold,shadow_passes_true_odds_filter,shadow_would_block_baseline,shadow_would_recommend_new,
                 no_bet_reason,true_odds_estimate_json,lifecycle_status,warnings_json)
                VALUES(:id,:created_at,:match_id,:official_match_id,:kickoff_time,:league,:config_version_id,
                 :true_odds_config_snapshot_json,:official_sp_snapshot_id,:external_odds_snapshot_id,:baseline_prediction_id,
                 :baseline_recommendation,:baseline_selected_outcome,:baseline_ev,:baseline_probability,:baseline_official_sp,
                 :shadow_recommendation,:shadow_selected_outcome,:shadow_ev,:shadow_lower_bound_ev,:shadow_edge_quality_score,
                 :shadow_edge_quality_level,:shadow_adaptive_threshold,:shadow_passes_true_odds_filter,
                 :shadow_would_block_baseline,:shadow_would_recommend_new,:no_bet_reason,:true_odds_estimate_json,
                 :lifecycle_status,:warnings_json)""", record)
        self._audit("run_live_shadow_prediction", record["config_version_id"], after=record)
        decoded = self._decode_shadow({
            **record,
            "true_odds_config_snapshot_json": record["true_odds_config_snapshot_json"],
            "true_odds_estimate_json": record.get("true_odds_estimate_json"),
            "warnings_json": record.get("warnings_json"),
        })
        decoded["_database"] = self.db
        return decoded

    def list_shadow_predictions(self, config_version_id: str | None = None, lifecycle_status: str | None = None) -> list[dict[str, Any]]:
        conditions, params = [], []
        if config_version_id:
            conditions.append("config_version_id=?")
            params.append(config_version_id)
        if lifecycle_status:
            conditions.append("lifecycle_status=?")
            params.append(lifecycle_status)
        query = "SELECT * FROM live_shadow_predictions"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY created_at DESC"
        with self.db.connect() as c:
            return [self._decode_shadow(dict(row)) for row in c.execute(query, tuple(params)).fetchall()]

    def save_post_match_result(self, result: dict[str, Any]) -> dict[str, Any]:
        result = {**result, "id": result.get("id") or uuid.uuid4().hex, "evaluated_at": result.get("evaluated_at") or utcnow()}
        with self.db.connect() as c:
            c.execute("""INSERT INTO shadow_post_match_results
                (id,shadow_prediction_id,match_id,official_match_id,evaluated_at,actual_result,closing_sp_json,
                 closing_probability_json,baseline_profit,shadow_profit,baseline_clv,shadow_clv,baseline_hit,shadow_hit,
                 baseline_would_have_bet,shadow_would_have_bet,shadow_blocked_baseline,shadow_added_new_recommendation,
                 evaluation_status,warnings_json)
                VALUES(:id,:shadow_prediction_id,:match_id,:official_match_id,:evaluated_at,:actual_result,
                 :closing_sp_json,:closing_probability_json,:baseline_profit,:shadow_profit,:baseline_clv,:shadow_clv,
                 :baseline_hit,:shadow_hit,:baseline_would_have_bet,:shadow_would_have_bet,:shadow_blocked_baseline,
                 :shadow_added_new_recommendation,:evaluation_status,:warnings_json)
                ON CONFLICT(shadow_prediction_id) DO UPDATE SET
                 evaluated_at=excluded.evaluated_at,actual_result=excluded.actual_result,closing_sp_json=excluded.closing_sp_json,
                 closing_probability_json=excluded.closing_probability_json,baseline_profit=excluded.baseline_profit,
                 shadow_profit=excluded.shadow_profit,baseline_clv=excluded.baseline_clv,shadow_clv=excluded.shadow_clv,
                 baseline_hit=excluded.baseline_hit,shadow_hit=excluded.shadow_hit,evaluation_status=excluded.evaluation_status,
                 warnings_json=excluded.warnings_json""", result)
            c.execute("UPDATE live_shadow_predictions SET lifecycle_status=? WHERE id=?",
                      ("EVALUATED" if result["evaluation_status"] == "EVALUATED" else "RESULT_AVAILABLE", result["shadow_prediction_id"]))
        self._audit("evaluate_shadow_prediction", result["shadow_prediction_id"], after=result)
        return result

    def list_post_match_results(self, config_version_id: str | None = None) -> list[dict[str, Any]]:
        query = """SELECT r.* FROM shadow_post_match_results r
            JOIN live_shadow_predictions p ON p.id=r.shadow_prediction_id"""
        params: tuple[Any, ...] = ()
        if config_version_id:
            query += " WHERE p.config_version_id=?"
            params = (config_version_id,)
        query += " ORDER BY r.evaluated_at DESC"
        with self.db.connect() as c:
            return [self._decode_result(dict(row)) for row in c.execute(query, params).fetchall()]

    def save_validation_run(self, run: dict[str, Any]) -> dict[str, Any]:
        run = {**run, "id": run.get("id") or uuid.uuid4().hex, "created_at": run.get("created_at") or utcnow()}
        with self.db.connect() as c:
            c.execute("""INSERT INTO shadow_validation_runs
                (id,config_version_id,created_at,from_date,to_date,metrics_json,promotion_gate_result_json,
                 decision,recommended_for_production,warnings_json)
                VALUES(:id,:config_version_id,:created_at,:from_date,:to_date,:metrics_json,
                 :promotion_gate_result_json,:decision,:recommended_for_production,:warnings_json)""", run)
        return run

    def latest_validation_run(self) -> dict[str, Any] | None:
        with self.db.connect() as c:
            row = c.execute("SELECT * FROM shadow_validation_runs ORDER BY created_at DESC LIMIT 1").fetchone()
        return dict(row) if row else None

    def _require_version(self, config_version_id: str) -> TrueOddsConfigVersion:
        version = self.get_config_version(config_version_id)
        if not version:
            raise KeyError(config_version_id)
        return version

    @staticmethod
    def _decode_version(row: dict[str, Any]) -> TrueOddsConfigVersion:
        config = TrueOddsFilterConfig(**loads(row.pop("config_json")))
        return TrueOddsConfigVersion(
            config_version_id=row["config_version_id"], config_name=row["config_name"], config=config,
            source_optimization_run_id=row["source_optimization_run_id"],
            source_optimization_summary=loads(row["source_optimization_summary_json"]),
            created_at=row["created_at"], created_by=row["created_by"], status=row["status"],
            shadow_started_at=row["shadow_started_at"], shadow_ended_at=row["shadow_ended_at"],
            activated_at=row["activated_at"], promotion_status=row["promotion_status"],
            warnings=loads(row["warnings_json"], []), notes=row["notes"])

    @staticmethod
    def _decode_shadow(row: dict[str, Any]) -> dict[str, Any]:
        row["true_odds_config_snapshot"] = loads(row.pop("true_odds_config_snapshot_json"), {})
        row["true_odds_estimate"] = loads(row.pop("true_odds_estimate_json"), None)
        row["warnings"] = loads(row.pop("warnings_json"), [])
        for key in ("shadow_passes_true_odds_filter", "shadow_would_block_baseline", "shadow_would_recommend_new"):
            row[key] = bool(row[key])
        return row

    @staticmethod
    def _decode_result(row: dict[str, Any]) -> dict[str, Any]:
        row["closing_sp"] = loads(row.pop("closing_sp_json"), None)
        row["closing_probability"] = loads(row.pop("closing_probability_json"), None)
        row["warnings"] = loads(row.pop("warnings_json"), [])
        for key in ("baseline_hit", "shadow_hit", "baseline_would_have_bet", "shadow_would_have_bet",
                    "shadow_blocked_baseline", "shadow_added_new_recommendation"):
            row[key] = None if row[key] is None else bool(row[key])
        return row

    def _audit(self, action: str, entity_id: str, before: Any = None, after: Any = None, severity: str = "INFO") -> None:
        self.audit.save_audit_log({"entity_type": "shadow_validation", "entity_id": entity_id, "action": action,
                                   "summary": action, "before": before, "after": after,
                                   "severity": severity, "actor": "shadow-validation"})
