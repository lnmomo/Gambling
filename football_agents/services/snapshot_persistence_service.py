from __future__ import annotations

from typing import Any

from ..db import Database, db
from .data_quality_service import validate_probability, validate_three_way_odds
from .idempotency_service import hash_payload, make_snapshot_id
from .persistence_utils import dumps, new_id, utcnow


class SnapshotPersistenceService:
    def __init__(self, database: Database = db) -> None:
        self.db = database

    def save_official_sp_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        odds = {"home": snapshot["home_sp"], "draw": snapshot["draw_sp"], "away": snapshot["away_sp"]}
        probability = {"home": snapshot["market_home_prob"], "draw": snapshot["market_draw_prob"], "away": snapshot["market_away_prob"]}
        quality = [validate_three_way_odds(odds), validate_probability(probability)]
        errors = [error for item in quality for error in item["errors"]]
        warnings = list(snapshot.get("warnings", [])) + [warning for item in quality for warning in item["warnings"]]
        payload_hash = snapshot.get("raw_payload_hash") or hash_payload(snapshot.get("raw_payload", snapshot))
        captured_at = snapshot.get("captured_at") or utcnow()
        record = {
            **snapshot,
            "id": snapshot.get("id") or make_snapshot_id(snapshot["official_match_id"], captured_at, payload_hash),
            "captured_at": captured_at,
            "snapshot_type": snapshot.get("snapshot_type", "OFFICIAL_SP"),
            "raw_payload_hash": payload_hash,
            "is_valid": int(not errors),
            "warnings_json": dumps(warnings + errors),
            "created_at": snapshot.get("created_at") or utcnow(),
        }
        with self.db.connect() as c:
            existing = c.execute("""SELECT * FROM official_sp_snapshots
                WHERE official_match_id=? AND raw_payload_hash=? LIMIT 1""",
                (record["official_match_id"], payload_hash)).fetchone()
            if existing:
                return dict(existing)
            c.execute("""INSERT INTO official_sp_snapshots
                (id,match_id,official_match_id,captured_at,snapshot_type,home_sp,draw_sp,away_sp,
                 market_home_prob,market_draw_prob,market_away_prob,market_home_fair_odds,
                 market_draw_fair_odds,market_away_fair_odds,raw_payload_hash,is_valid,warnings_json,created_at)
                VALUES(:id,:match_id,:official_match_id,:captured_at,:snapshot_type,:home_sp,:draw_sp,:away_sp,
                 :market_home_prob,:market_draw_prob,:market_away_prob,:market_home_fair_odds,
                 :market_draw_fair_odds,:market_away_fair_odds,:raw_payload_hash,:is_valid,:warnings_json,:created_at)""", record)
        return record

    def get_latest_official_sp_snapshot(self, official_match_id: str) -> dict[str, Any] | None:
        return self._latest("official_sp_snapshots", official_match_id)

    def list_official_sp_snapshots(self, official_match_id: str) -> list[dict[str, Any]]:
        return self._list("official_sp_snapshots", official_match_id)

    def save_external_odds_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        probability = {"home": snapshot["external_home_prob"], "draw": snapshot["external_draw_prob"], "away": snapshot["external_away_prob"]}
        quality = validate_probability(probability)
        warnings = list(snapshot.get("warnings", [])) + quality["warnings"] + quality["errors"]
        payload_hash = snapshot.get("raw_payload_hash") or hash_payload(snapshot.get("raw_payload", snapshot))
        captured_at = snapshot.get("captured_at") or utcnow()
        record = {
            **snapshot,
            "id": snapshot.get("id") or make_snapshot_id(snapshot["official_match_id"], captured_at, payload_hash),
            "captured_at": captured_at,
            "snapshot_type": snapshot.get("snapshot_type", "EXTERNAL_ODDS"),
            "raw_payload_hash": payload_hash,
            "is_valid": int(quality["valid"]),
            "warnings_json": dumps(warnings),
            "created_at": snapshot.get("created_at") or utcnow(),
        }
        with self.db.connect() as c:
            existing = c.execute("""SELECT * FROM external_odds_snapshots
                WHERE official_match_id=? AND raw_payload_hash=? LIMIT 1""",
                (record["official_match_id"], payload_hash)).fetchone()
            if existing:
                return dict(existing)
            c.execute("""INSERT INTO external_odds_snapshots
                (id,match_id,official_match_id,captured_at,snapshot_type,external_home_prob,external_draw_prob,
                 external_away_prob,external_home_fair_odds,external_draw_fair_odds,external_away_fair_odds,
                 quality_score,quality_level,raw_payload_hash,is_valid,warnings_json,created_at)
                VALUES(:id,:match_id,:official_match_id,:captured_at,:snapshot_type,:external_home_prob,
                 :external_draw_prob,:external_away_prob,:external_home_fair_odds,:external_draw_fair_odds,
                 :external_away_fair_odds,:quality_score,:quality_level,:raw_payload_hash,:is_valid,
                 :warnings_json,:created_at)""", record)
        return record

    def get_latest_external_odds_snapshot(self, official_match_id: str) -> dict[str, Any] | None:
        return self._latest("external_odds_snapshots", official_match_id)

    def list_external_odds_snapshots(self, official_match_id: str) -> list[dict[str, Any]]:
        return self._list("external_odds_snapshots", official_match_id)

    def save_normalized_bookmakers(self, external_snapshot_id: str, bookmakers: list[dict[str, Any]]) -> int:
        rows = [{
            "id": item.get("id") or new_id(),
            "external_snapshot_id": external_snapshot_id,
            "bookmaker": item["bookmaker"],
            "bookmaker_key": item.get("bookmaker_key"),
            "home_odds": item.get("home_odds"),
            "draw_odds": item.get("draw_odds"),
            "away_odds": item.get("away_odds"),
            "home_prob": item.get("home_prob"),
            "draw_prob": item.get("draw_prob"),
            "away_prob": item.get("away_prob"),
            "overround": item.get("overround"),
            "weight": item.get("weight"),
            "included": int(item.get("included", True)),
            "exclusion_reason": item.get("exclusion_reason"),
            "last_update": item.get("last_update"),
            "created_at": item.get("created_at") or utcnow(),
        } for item in bookmakers]
        with self.db.connect() as c:
            c.executemany("""INSERT OR IGNORE INTO normalized_bookmakers
                (id,external_snapshot_id,bookmaker,bookmaker_key,home_odds,draw_odds,away_odds,home_prob,
                 draw_prob,away_prob,overround,weight,included,exclusion_reason,last_update,created_at)
                VALUES(:id,:external_snapshot_id,:bookmaker,:bookmaker_key,:home_odds,:draw_odds,:away_odds,
                 :home_prob,:draw_prob,:away_prob,:overround,:weight,:included,:exclusion_reason,:last_update,:created_at)""", rows)
        return len(rows)

    def _latest(self, table: str, official_match_id: str) -> dict[str, Any] | None:
        with self.db.connect() as c:
            row = c.execute(f"SELECT * FROM {table} WHERE official_match_id=? ORDER BY captured_at DESC LIMIT 1",
                            (official_match_id,)).fetchone()
        return dict(row) if row else None

    def _list(self, table: str, official_match_id: str) -> list[dict[str, Any]]:
        with self.db.connect() as c:
            return [dict(row) for row in c.execute(f"SELECT * FROM {table} WHERE official_match_id=? ORDER BY captured_at DESC",
                                                   (official_match_id,)).fetchall()]
