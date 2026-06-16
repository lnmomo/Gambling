from __future__ import annotations

from typing import Any

from ..db import Database, db
from .data_quality_service import validate_prediction
from .persistence_utils import dumps, loads, new_id, utcnow


class RecommendationPersistenceService:
    def __init__(self, database: Database = db) -> None:
        self.db = database

    def save_prediction(self, prediction: dict[str, Any]) -> dict[str, Any]:
        validation = validate_prediction(prediction) if prediction.get("officialSp") else {"valid": True, "errors": [], "warnings": []}
        record = {
            "id": prediction.get("id") or new_id(),
            "match_id": prediction["match_id"],
            "official_match_id": prediction["official_match_id"],
            "created_at": prediction.get("created_at") or utcnow(),
            "official_sp_snapshot_id": prediction.get("official_sp_snapshot_id"),
            "external_odds_snapshot_id": prediction.get("external_odds_snapshot_id"),
            "recalculation_id": prediction.get("recalculation_id"),
            "market_probability_json": dumps(prediction.get("market_probability", prediction.get("marketProbability", {}))),
            "external_market_probability_json": dumps(prediction.get("external_market_probability", prediction.get("externalMarketProbability", {}))),
            "pure_model_probability_json": dumps(prediction.get("pure_model_probability", prediction.get("pureModelProbability", {}))),
            "final_probability_json": dumps(prediction.get("final_probability", prediction.get("finalProbability", {}))),
            "market_fair_odds_json": dumps(prediction.get("market_fair_odds", prediction.get("marketFairOdds", {}))),
            "external_market_fair_odds_json": dumps(prediction.get("external_market_fair_odds", prediction.get("externalMarketFairOdds", {}))),
            "pure_model_fair_odds_json": dumps(prediction.get("pure_model_fair_odds", prediction.get("pureModelFairOdds", {}))),
            "final_fair_odds_json": dumps(prediction.get("final_fair_odds", prediction.get("finalFairOdds", {}))),
            "pure_model_edge_json": dumps(prediction.get("pure_model_edge", prediction.get("pureModelEdge", {}))),
            "final_edge_json": dumps(prediction.get("final_edge", prediction.get("finalEdge", {}))),
            "ev_json": dumps(prediction.get("ev", {})),
            "recommendation": prediction.get("recommendation", "NO_BET"),
            "critic_report_json": dumps(prediction.get("critic_report", prediction.get("criticReport", {}))),
            "stake_recommendation_json": dumps(prediction.get("stake_recommendation", prediction.get("stakeRecommendation", {}))),
            "probability_source": prediction.get("probability_source", prediction.get("probabilitySource")),
            "model_version": prediction.get("model_version", prediction.get("modelVersion", "unknown")),
            "lifecycle_status": prediction.get("lifecycle_status", prediction.get("lifecycleStatus", "NO_BET")),
            "warnings_json": dumps(validation["warnings"] + validation["errors"]),
        }
        with self.db.connect() as c:
            existing = c.execute("""SELECT * FROM predictions
                WHERE official_match_id=? AND COALESCE(official_sp_snapshot_id,'')=COALESCE(?,'')
                  AND COALESCE(external_odds_snapshot_id,'')=COALESCE(?,'') AND COALESCE(model_version,'')=COALESCE(?,'')
                LIMIT 1""", (record["official_match_id"], record["official_sp_snapshot_id"],
                              record["external_odds_snapshot_id"], record["model_version"])).fetchone()
            if existing:
                return self._decode_prediction(dict(existing))
            c.execute("""INSERT INTO predictions
                (id,match_id,official_match_id,created_at,official_sp_snapshot_id,external_odds_snapshot_id,
                 recalculation_id,market_probability_json,external_market_probability_json,pure_model_probability_json,
                 final_probability_json,market_fair_odds_json,external_market_fair_odds_json,pure_model_fair_odds_json,
                 final_fair_odds_json,pure_model_edge_json,final_edge_json,ev_json,recommendation,critic_report_json,
                 stake_recommendation_json,probability_source,model_version,lifecycle_status,warnings_json)
                VALUES(:id,:match_id,:official_match_id,:created_at,:official_sp_snapshot_id,:external_odds_snapshot_id,
                 :recalculation_id,:market_probability_json,:external_market_probability_json,:pure_model_probability_json,
                 :final_probability_json,:market_fair_odds_json,:external_market_fair_odds_json,:pure_model_fair_odds_json,
                 :final_fair_odds_json,:pure_model_edge_json,:final_edge_json,:ev_json,:recommendation,:critic_report_json,
                 :stake_recommendation_json,:probability_source,:model_version,:lifecycle_status,:warnings_json)""", record)
        return record

    def get_latest_prediction(self, official_match_id: str) -> dict[str, Any] | None:
        with self.db.connect() as c:
            row = c.execute("SELECT * FROM predictions WHERE official_match_id=? ORDER BY created_at DESC LIMIT 1",
                            (official_match_id,)).fetchone()
        return self._decode_prediction(dict(row)) if row else None

    def list_predictions(self, official_match_id: str) -> list[dict[str, Any]]:
        with self.db.connect() as c:
            rows = c.execute("SELECT * FROM predictions WHERE official_match_id=? ORDER BY created_at DESC",
                             (official_match_id,)).fetchall()
        return [self._decode_prediction(dict(row)) for row in rows]

    def save_recommendation(self, recommendation: dict[str, Any]) -> dict[str, Any]:
        status = recommendation.get("lifecycle_status", "ACTIVE")
        record = {
            "id": recommendation.get("id") or new_id(),
            "prediction_id": recommendation["prediction_id"],
            "match_id": recommendation["match_id"],
            "official_match_id": recommendation["official_match_id"],
            "created_at": recommendation.get("created_at") or utcnow(),
            "updated_at": recommendation.get("updated_at") or utcnow(),
            "recommendation": recommendation.get("recommendation", "NO_BET"),
            "lifecycle_status": status,
            "selected_probability": recommendation.get("selected_probability"),
            "selected_official_sp": recommendation.get("selected_official_sp"),
            "ev": recommendation.get("ev"),
            "final_stake": recommendation.get("final_stake"),
            "stake_status": recommendation.get("stake_status"),
            "capped_by": recommendation.get("capped_by"),
            "reason_json": dumps(recommendation.get("reason", recommendation.get("reason_json", {}))),
            "warnings_json": dumps(recommendation.get("warnings", [])),
        }
        with self.db.connect() as c:
            if status == "ACTIVE":
                existing = c.execute("""SELECT * FROM recommendations
                    WHERE official_match_id=? AND lifecycle_status='ACTIVE' LIMIT 1""",
                    (record["official_match_id"],)).fetchone()
                if existing:
                    return self._decode_recommendation(dict(existing))
            c.execute("""INSERT INTO recommendations
                (id,prediction_id,match_id,official_match_id,created_at,updated_at,recommendation,lifecycle_status,
                 selected_probability,selected_official_sp,ev,final_stake,stake_status,capped_by,reason_json,warnings_json)
                VALUES(:id,:prediction_id,:match_id,:official_match_id,:created_at,:updated_at,:recommendation,
                 :lifecycle_status,:selected_probability,:selected_official_sp,:ev,:final_stake,:stake_status,
                 :capped_by,:reason_json,:warnings_json)""", record)
        return record

    def get_active_recommendations(self) -> list[dict[str, Any]]:
        with self.db.connect() as c:
            rows = c.execute("SELECT * FROM recommendations WHERE lifecycle_status='ACTIVE' ORDER BY created_at DESC").fetchall()
        return [self._decode_recommendation(dict(row)) for row in rows]

    def update_recommendation_lifecycle(self, match_id: str, official_match_id: str, previous_status: str | None,
                                        new_status: str, reason: str, **kwargs: Any) -> dict[str, Any]:
        now = utcnow()
        event = {
            "id": kwargs.get("id") or new_id(),
            "match_id": match_id,
            "official_match_id": official_match_id,
            "occurred_at": now,
            "previous_status": previous_status,
            "new_status": new_status,
            "previous_recommendation": kwargs.get("previous_recommendation"),
            "new_recommendation": kwargs.get("new_recommendation"),
            "reason": reason,
            "trigger_type": kwargs.get("trigger_type", "SYSTEM"),
            "previous_ev": kwargs.get("previous_ev"),
            "new_ev": kwargs.get("new_ev"),
            "audit_log_id": kwargs.get("audit_log_id"),
        }
        with self.db.connect() as c:
            c.execute("UPDATE recommendations SET lifecycle_status=?,updated_at=? WHERE official_match_id=? AND lifecycle_status=?",
                      (new_status, now, official_match_id, previous_status or "ACTIVE"))
            c.execute("""INSERT INTO recommendation_lifecycle_events
                (id,match_id,official_match_id,occurred_at,previous_status,new_status,previous_recommendation,
                 new_recommendation,reason,trigger_type,previous_ev,new_ev,audit_log_id)
                VALUES(:id,:match_id,:official_match_id,:occurred_at,:previous_status,:new_status,
                 :previous_recommendation,:new_recommendation,:reason,:trigger_type,:previous_ev,:new_ev,:audit_log_id)""", event)
        return event

    def list_recommendation_events(self, official_match_id: str) -> list[dict[str, Any]]:
        with self.db.connect() as c:
            return [dict(row) for row in c.execute("""SELECT * FROM recommendation_lifecycle_events
                WHERE official_match_id=? ORDER BY occurred_at DESC""", (official_match_id,)).fetchall()]

    @staticmethod
    def _decode_prediction(row: dict[str, Any]) -> dict[str, Any]:
        for key in list(row):
            if key.endswith("_json"):
                row[key[:-5]] = loads(row.pop(key), {})
        return row

    @staticmethod
    def _decode_recommendation(row: dict[str, Any]) -> dict[str, Any]:
        row["reason"] = loads(row.pop("reason_json"), {})
        row["warnings"] = loads(row.pop("warnings_json"), [])
        return row
