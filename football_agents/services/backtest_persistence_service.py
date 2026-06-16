from __future__ import annotations

from typing import Any

from ..db import Database, db
from .persistence_utils import dumps, loads, new_id, utcnow


class BacktestPersistenceService:
    def __init__(self, database: Database = db) -> None:
        self.db = database

    def save_backtest_run(self, run: dict[str, Any]) -> dict[str, Any]:
        record = {
            "id": run.get("id") or new_id(),
            "created_at": run.get("created_at") or utcnow(),
            "started_at": run.get("started_at"),
            "finished_at": run.get("finished_at"),
            "name": run.get("name"),
            "config_json": dumps(run.get("config", run.get("config_json", {}))),
            "metrics_json": dumps(run.get("metrics", run.get("metrics_json", {}))) if run.get("metrics") is not None or run.get("metrics_json") is not None else None,
            "status": run.get("status", "CREATED"),
            "model_version": run.get("model_version"),
            "notes": run.get("notes"),
        }
        with self.db.connect() as c:
            c.execute("""INSERT INTO backtest_runs
                (id,created_at,started_at,finished_at,name,config_json,metrics_json,status,model_version,notes)
                VALUES(:id,:created_at,:started_at,:finished_at,:name,:config_json,:metrics_json,
                 :status,:model_version,:notes)
                ON CONFLICT(id) DO UPDATE SET finished_at=excluded.finished_at,metrics_json=excluded.metrics_json,
                 status=excluded.status,notes=excluded.notes""", record)
        return record

    def save_backtest_records(self, run_id: str, records: list[dict[str, Any]]) -> int:
        rows = []
        for record in records:
            rows.append({
                "id": record.get("id") or new_id(),
                "backtest_run_id": run_id,
                "match_id": record["match_id"],
                "official_match_id": record["official_match_id"],
                "kickoff_time": record["kickoff_time"],
                "league": record.get("league"),
                "prediction_json": dumps(record.get("prediction", record.get("prediction_json", {}))),
                "actual_result": record.get("actual_result"),
                "recommendation": record.get("recommendation"),
                "stake": record.get("stake"),
                "profit": record.get("profit"),
                "bankroll_before": record.get("bankroll_before"),
                "bankroll_after": record.get("bankroll_after"),
                "clv": record.get("clv"),
                "brier_score": record.get("brier_score"),
                "log_loss": record.get("log_loss"),
                "created_at": record.get("created_at") or utcnow(),
            })
        with self.db.connect() as c:
            c.executemany("""INSERT OR IGNORE INTO backtest_records
                (id,backtest_run_id,match_id,official_match_id,kickoff_time,league,prediction_json,actual_result,
                 recommendation,stake,profit,bankroll_before,bankroll_after,clv,brier_score,log_loss,created_at)
                VALUES(:id,:backtest_run_id,:match_id,:official_match_id,:kickoff_time,:league,:prediction_json,
                 :actual_result,:recommendation,:stake,:profit,:bankroll_before,:bankroll_after,:clv,
                 :brier_score,:log_loss,:created_at)""", rows)
        return len(rows)

    def get_backtest_run(self, run_id: str) -> dict[str, Any] | None:
        with self.db.connect() as c:
            row = c.execute("SELECT * FROM backtest_runs WHERE id=?", (run_id,)).fetchone()
        return self._decode_run(dict(row)) if row else None

    def list_backtest_runs(self) -> list[dict[str, Any]]:
        with self.db.connect() as c:
            rows = c.execute("SELECT * FROM backtest_runs ORDER BY created_at DESC").fetchall()
        return [self._decode_run(dict(row)) for row in rows]

    @staticmethod
    def _decode_run(row: dict[str, Any]) -> dict[str, Any]:
        row["config"] = loads(row.pop("config_json"), {})
        row["metrics"] = loads(row.pop("metrics_json"), None)
        return row
