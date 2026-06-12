from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .config import settings


class Database:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path or settings.database_path)

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        schema = Path(__file__).with_name("database").joinpath("schema.sql").read_text(encoding="utf-8")
        with self.connect() as connection:
            connection.executescript(schema)
            self._migrate(connection)

    @staticmethod
    def _migrate(connection: sqlite3.Connection) -> None:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(matches)")}
        additions = {
            "match_no": "TEXT", "source_url": "TEXT", "first_seen_at": "TEXT",
            "last_seen_at": "TEXT", "data_quality_score": "REAL", "raw_hash": "TEXT",
        }
        for name, definition in additions.items():
            if name not in columns:
                connection.execute(f"ALTER TABLE matches ADD COLUMN {name} {definition}")
        odds_columns = {row[1] for row in connection.execute("PRAGMA table_info(odds_snapshots)")}
        for name, definition in {"source_url": "TEXT", "raw_hash": "TEXT", "parse_version": "TEXT"}.items():
            if name not in odds_columns:
                connection.execute(f"ALTER TABLE odds_snapshots ADD COLUMN {name} {definition}")
        prediction_columns = {row[1] for row in connection.execute("PRAGMA table_info(model_predictions)")}
        for name in ("fair_odds_home", "fair_odds_draw", "fair_odds_away"):
            if name not in prediction_columns:
                connection.execute(f"ALTER TABLE model_predictions ADD COLUMN {name} REAL")
        connection.execute("""UPDATE model_predictions SET
            fair_odds_home=CASE WHEN p_home > 0 THEN 1.0/p_home END,
            fair_odds_draw=CASE WHEN p_draw > 0 THEN 1.0/p_draw END,
            fair_odds_away=CASE WHEN p_away > 0 THEN 1.0/p_away END
            WHERE fair_odds_home IS NULL OR fair_odds_draw IS NULL OR fair_odds_away IS NULL""")
        connection.execute("""DELETE FROM model_predictions WHERE match_id IN (
            SELECT m.id FROM matches m WHERE m.source_url IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM match_features f WHERE f.match_id=m.id)
        )""")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


db = Database()

