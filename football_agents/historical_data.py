from __future__ import annotations

from pathlib import Path
from typing import Any

from .pandas_pipeline import normalize_historical_matches, read_csv_text
from .repository import Repository


class HistoricalDataService:
    def __init__(self, repository: Repository | None = None) -> None:
        self.repository = repository or Repository()

    @staticmethod
    def parse_csv(text: str) -> list[dict[str, Any]]:
        rows, _report = normalize_historical_matches(read_csv_text(text))
        return rows

    def import_csv_text(self, text: str, source: str = "csv") -> dict[str, int]:
        rows, report = normalize_historical_matches(read_csv_text(text), source=source)
        result = self.repository.upsert_historical_matches(rows, source)
        return {**result, "pandas_rows": report.rows, "pandas_dropped": report.dropped}

    def bootstrap_sample(self) -> dict[str, int]:
        if self.repository.historical_match_count() > 0:
            return {"imported": 0, "updated": 0, "dropped": 0}
        path = Path(__file__).with_name("sample_data") / "historical_matches.csv"
        if not path.exists():
            return {"imported": 0, "updated": 0, "dropped": 0}
        return self.import_csv_text(path.read_text(encoding="utf-8-sig"), "bundled-sample")
