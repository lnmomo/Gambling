from __future__ import annotations

from typing import Any

from ..db import Database, db
from .persistence_utils import new_id, utcnow


class BankrollPersistenceService:
    def __init__(self, database: Database = db) -> None:
        self.db = database

    def save_bankroll_transaction(self, transaction: dict[str, Any]) -> dict[str, Any]:
        record = {
            "id": transaction.get("id") or new_id(),
            "bankroll_id": transaction["bankroll_id"],
            "match_id": transaction.get("match_id"),
            "official_match_id": transaction.get("official_match_id"),
            "type": transaction["type"],
            "amount": transaction["amount"],
            "bankroll_before": transaction["bankroll_before"],
            "bankroll_after": transaction["bankroll_after"],
            "created_at": transaction.get("created_at") or utcnow(),
            "note": transaction.get("note"),
        }
        with self.db.connect() as c:
            c.execute("""INSERT INTO bankroll_transactions
                (id,bankroll_id,match_id,official_match_id,type,amount,bankroll_before,bankroll_after,created_at,note)
                VALUES(:id,:bankroll_id,:match_id,:official_match_id,:type,:amount,:bankroll_before,
                 :bankroll_after,:created_at,:note)""", record)
        return record

    def list_bankroll_transactions(self, bankroll_id: str) -> list[dict[str, Any]]:
        with self.db.connect() as c:
            return [dict(row) for row in c.execute("""SELECT * FROM bankroll_transactions
                WHERE bankroll_id=? ORDER BY created_at ASC""", (bankroll_id,)).fetchall()]

    def get_current_bankroll(self, bankroll_id: str) -> float | None:
        with self.db.connect() as c:
            row = c.execute("""SELECT bankroll_after FROM bankroll_transactions
                WHERE bankroll_id=? ORDER BY created_at DESC LIMIT 1""", (bankroll_id,)).fetchone()
        return float(row["bankroll_after"]) if row else None
