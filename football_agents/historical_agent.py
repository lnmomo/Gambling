from __future__ import annotations

import csv
import io
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from .repository import Repository
from .config import settings


DIVISIONS = {
    "E0": "English Premier League", "E1": "English Championship",
    "E2": "English League One", "E3": "English League Two",
    "SC0": "Scottish Premiership", "D1": "German Bundesliga",
    "D2": "German 2. Bundesliga", "I1": "Italian Serie A",
    "I2": "Italian Serie B", "SP1": "Spanish La Liga",
    "SP2": "Spanish Segunda Division", "F1": "French Ligue 1",
    "F2": "French Ligue 2", "N1": "Dutch Eredivisie",
    "B1": "Belgian First Division A", "P1": "Portuguese Primeira Liga",
    "T1": "Turkish Super Lig", "G1": "Greek Super League",
}


@dataclass(frozen=True)
class HistoricalSource:
    season: str
    division: str

    @property
    def url(self) -> str:
        return f"{settings.historical_data_base_url}/{self.season}/{self.division}.csv"


class HistoricalCollectionAgent:
    def __init__(self, repository: Repository | None = None, archive_dir: Path | None = None) -> None:
        self.repository = repository or Repository()
        self.archive_dir = archive_dir or Path("data") / "historical_csv" / "football-data"

    @staticmethod
    def season_codes(years_back: int = 3, today: date | None = None) -> list[str]:
        today = today or date.today()
        start = today.year if today.month >= 7 else today.year - 1
        return [f"{str(start - offset)[-2:]}{str(start - offset + 1)[-2:]}" for offset in range(max(1, years_back))]

    def sources(self, years_back: int = 3, divisions: list[str] | None = None) -> list[HistoricalSource]:
        selected = divisions or list(settings.historical_data_divisions)
        return [HistoricalSource(season, division) for season in self.season_codes(years_back) for division in selected if division in DIVISIONS]

    @staticmethod
    def _parse_date(value: str) -> str:
        value = value.strip()
        for pattern in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
            try:
                return datetime.strptime(value, pattern).date().isoformat()
            except ValueError:
                continue
        raise ValueError(f"unsupported date: {value}")

    def normalize_csv(self, text: str, source: HistoricalSource) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for item in csv.DictReader(io.StringIO(text.lstrip("\ufeff"))):
            if not item.get("Date") or not item.get("HomeTeam") or not item.get("AwayTeam"):
                continue
            if item.get("FTHG") in (None, "") or item.get("FTAG") in (None, ""):
                continue
            try:
                rows.append({
                    "league": DIVISIONS.get(item.get("Div") or source.division, source.division),
                    "home_team": item["HomeTeam"].strip(), "away_team": item["AwayTeam"].strip(),
                    "home_goals": int(item["FTHG"]), "away_goals": int(item["FTAG"]),
                    "played_at": self._parse_date(item["Date"]), "match_type": "LEAGUE",
                })
            except (KeyError, TypeError, ValueError):
                continue
        return rows

    def fetch(self, source: HistoricalSource, timeout: int | None = None) -> str:
        request = Request(source.url, headers={"User-Agent": "football-agents-history/1.0"})
        with urlopen(request, timeout=timeout or settings.historical_data_timeout_seconds) as response:
            data = response.read()
        for encoding in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
        raise UnicodeDecodeError("utf-8", data, 0, 1, "unsupported CSV encoding")

    def sync(self, years_back: int = 3, divisions: list[str] | None = None) -> dict[str, Any]:
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        totals = {"imported": 0, "updated": 0, "dropped": 0, "downloaded": 0, "failed": 0}
        reports: list[dict[str, Any]] = []
        sources = self.sources(years_back, divisions)
        fetched: dict[HistoricalSource, str | Exception] = {}
        with ThreadPoolExecutor(max_workers=min(settings.historical_data_workers, len(sources) or 1)) as executor:
            futures = {executor.submit(self.fetch, source): source for source in sources}
            for future in as_completed(futures):
                source = futures[future]
                try:
                    fetched[source] = future.result()
                except Exception as exc:
                    fetched[source] = exc
        for source in sources:
            try:
                result_or_error = fetched[source]
                if isinstance(result_or_error, Exception):
                    raise result_or_error
                text = result_or_error
                rows = self.normalize_csv(text, source)
                archive = self.archive_dir / source.season
                archive.mkdir(parents=True, exist_ok=True)
                (archive / f"{source.division}.csv").write_text(text, encoding="utf-8")
                result = self.repository.upsert_historical_matches(rows, source.url)
                totals["downloaded"] += 1
                for key in ("imported", "updated", "dropped"):
                    totals[key] += result[key]
                reports.append({"url": source.url, "rows": len(rows), **result, "status": "success"})
            except Exception as exc:
                totals["failed"] += 1
                reports.append({"url": source.url, "status": "failed", "error": str(exc)})
        self.repository.add_audit_event("history-agent", "历史数据", "增量同步",
                                        json.dumps(totals, ensure_ascii=False),
                                        "success" if totals["downloaded"] else "failed")
        return {**totals, "database_matches": self.repository.historical_match_count(),
                "synced_at": datetime.now(timezone.utc).isoformat(), "sources": reports}
