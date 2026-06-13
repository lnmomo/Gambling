from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

from .repository import Repository


class HistoricalDataService:
    def __init__(self, repository: Repository | None = None) -> None:
        self.repository = repository or Repository()

    @staticmethod
    def parse_csv(text: str) -> list[dict[str, Any]]:
        rows = list(csv.DictReader(io.StringIO(text)))
        if not rows:
            raise ValueError("历史 CSV 不包含数据")
        required_groups = [
            ("date", "played_at", "playedAt"),
            ("league",),
            ("home_team", "homeTeam"),
            ("away_team", "awayTeam"),
            ("home_score", "home_goals", "homeGoals"),
            ("away_score", "away_goals", "awayGoals"),
        ]
        columns = set(rows[0])
        missing = ["/".join(group) for group in required_groups if not columns.intersection(group)]
        if missing:
            raise ValueError(f"历史 CSV 缺少字段: {', '.join(missing)}")
        return rows

    def import_csv_text(self, text: str, source: str = "csv") -> dict[str, int]:
        return self.repository.upsert_historical_matches(self.parse_csv(text), source)

    def bootstrap_sample(self) -> dict[str, int]:
        if self.repository.historical_match_count() > 0:
            return {"imported": 0, "updated": 0, "dropped": 0}
        path = Path(__file__).with_name("sample_data") / "historical_matches.csv"
        if not path.exists():
            return {"imported": 0, "updated": 0, "dropped": 0}
        return self.import_csv_text(path.read_text(encoding="utf-8-sig"), "bundled-sample")
