from __future__ import annotations

import csv
import io
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from .repository import Repository
from .config import settings
from .pandas_pipeline import normalize_historical_matches, read_csv_text


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

WORLDWIDE_DIVISIONS = {
    "ARG": "Argentina Liga Profesional",
    "AUT": "Austrian Bundesliga",
    "BRA": "Brazil Serie A",
    "CHN": "Chinese Super League",
    "DNK": "Danish Superliga",
    "FIN": "Finnish Veikkausliiga",
    "IRL": "Irish Premier Division",
    "JPN": "Japanese J1 League",
    "MEX": "Mexican Liga MX",
    "NOR": "Norwegian Eliteserien",
    "POL": "Polish Ekstraklasa",
    "ROU": "Romanian Liga I",
    "RUS": "Russian Premier League",
    "SWE": "Swedish Allsvenskan",
    "SWZ": "Swiss Super League",
    "USA": "USA MLS",
}

DIVISION_NAMES = {**DIVISIONS, **WORLDWIDE_DIVISIONS}


@dataclass(frozen=True)
class HistoricalSource:
    season: str
    division: str

    @property
    def url(self) -> str:
        if self.season == "new":
            root_url = settings.historical_data_base_url.removesuffix("/mmz4281")
            return f"{root_url}/new/{self.division}.csv"
        return f"{settings.historical_data_base_url}/{self.season}/{self.division}.csv"


@dataclass(frozen=True)
class ExtraHistoricalSource:
    """An authorized, externally hosted CSV with optional fixed league name."""

    name: str
    url: str
    league: str = ""


class HistoricalCollectionAgent:
    def __init__(self, repository: Repository | None = None, archive_dir: Path | None = None) -> None:
        self.repository = repository or Repository()
        self.archive_dir = archive_dir or Path("data") / "historical_csv" / "football-data"

    @staticmethod
    def season_codes(years_back: int = 3, today: date | None = None) -> list[str]:
        today = today or date.today()
        # football-data.co.uk publishes a season file after the season has
        # started.  In July the next European season is normally not present
        # yet, so start from the season that just ended instead of repeatedly
        # requesting a predictable 404 such as ``2627``.
        start = today.year if today.month >= 8 else today.year - 1
        return [f"{str(start - offset)[-2:]}{str(start - offset + 1)[-2:]}" for offset in range(max(1, years_back))]

    def sources(self, years_back: int = 3, divisions: list[str] | None = None) -> list[HistoricalSource]:
        selected = divisions or list(settings.historical_data_divisions)
        return [HistoricalSource(season, division) for season in self.season_codes(years_back) for division in selected if division in DIVISIONS]

    def worldwide_sources(self, divisions: list[str] | None = None) -> list[HistoricalSource]:
        selected = divisions or list(settings.historical_data_worldwide_divisions)
        return [HistoricalSource("new", division) for division in selected if division in WORLDWIDE_DIVISIONS]

    @staticmethod
    def _parse_date(value: str) -> str:
        value = value.strip()
        for pattern in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
            try:
                return datetime.strptime(value, pattern).date().isoformat()
            except ValueError:
                continue
        raise ValueError(f"unsupported date: {value}")

    def normalize_csv(self, text: str, source: HistoricalSource | ExtraHistoricalSource) -> list[dict[str, Any]]:
        division_names = DIVISION_NAMES if isinstance(source, HistoricalSource) else None
        league_override = source.league if isinstance(source, ExtraHistoricalSource) else None
        rows, _report = normalize_historical_matches(
            read_csv_text(text), source=source.url, division_names=division_names,
            league_override=league_override,
        )
        return rows

    def fetch(self, source: HistoricalSource | ExtraHistoricalSource, timeout: int | None = None) -> str:
        attempts = max(1, settings.historical_data_retries + 1)
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                request = Request(source.url, headers={"User-Agent": "football-agents-history/1.0"})
                with urlopen(request, timeout=timeout or settings.historical_data_timeout_seconds) as response:
                    data = response.read()
                break
            except Exception as exc:
                last_error = exc
                if attempt + 1 >= attempts:
                    raise
                time.sleep(settings.historical_data_retry_backoff_seconds * (2 ** attempt))
        else:
            raise last_error or RuntimeError("historical CSV download failed")
        for encoding in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
        raise UnicodeDecodeError("utf-8", data, 0, 1, "unsupported CSV encoding")

    def archive_path(self, source: HistoricalSource | ExtraHistoricalSource) -> Path:
        if isinstance(source, ExtraHistoricalSource):
            safe_name = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in source.name)
            return self.archive_dir / "extra" / f"{safe_name}.csv"
        return self.archive_dir / source.season / f"{source.division}.csv"

    def sync(self, years_back: int = 3, divisions: list[str] | None = None) -> dict[str, Any]:
        return self._sync_sources(self.sources(years_back, divisions))

    def sync_worldwide(self, divisions: list[str] | None = None) -> dict[str, Any]:
        return self._sync_sources(self.worldwide_sources(divisions))

    def extra_sources(self) -> list[ExtraHistoricalSource]:
        return [
            ExtraHistoricalSource(item["name"], item["url"], item.get("league", ""))
            for item in settings.historical_data_extra_csv_sources
        ]

    def sync_extra(self) -> dict[str, Any]:
        return self._sync_sources(self.extra_sources())

    def _sync_sources(self, sources: list[HistoricalSource | ExtraHistoricalSource]) -> dict[str, Any]:
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        totals = {"imported": 0, "updated": 0, "dropped": 0, "downloaded": 0,
                  "cached": 0, "stale": 0, "failed": 0}
        reports: list[dict[str, Any]] = []
        fetched: dict[HistoricalSource | ExtraHistoricalSource, str | Exception] = {}
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
                network_error: Exception | None = None
                if isinstance(result_or_error, Exception):
                    network_error = result_or_error
                    archive_path = self.archive_path(source)
                    if not archive_path.exists():
                        raise result_or_error
                    text = archive_path.read_text(encoding="utf-8-sig")
                    source_status = "cached"
                else:
                    text = result_or_error
                    source_status = "success"
                rows = self.normalize_csv(text, source)
                archive_path = self.archive_path(source)
                archive_path.parent.mkdir(parents=True, exist_ok=True)
                if source_status == "success":
                    archive_path.write_text(text, encoding="utf-8")
                result = self.repository.upsert_historical_matches(rows, source.url)
                if source_status == "success":
                    totals["downloaded"] += 1
                else:
                    totals["cached"] += 1
                    totals["stale"] += 1
                for key in ("imported", "updated", "dropped"):
                    totals[key] += result[key]
                report = {"url": source.url, "rows": len(rows), **result, "status": source_status}
                if network_error:
                    report["warning"] = str(network_error)
                    report["archive"] = str(archive_path)
                reports.append(report)
            except Exception as exc:
                totals["failed"] += 1
                reports.append({"url": source.url, "status": "failed", "error": str(exc)})
        self.repository.add_audit_event("history-agent", "历史数据", "增量同步",
                                        json.dumps(totals, ensure_ascii=False),
                                        "success" if totals["downloaded"] and not totals["stale"] else
                                        "partial" if totals["cached"] else "failed")
        return {**totals, "database_matches": self.repository.historical_match_count(),
                "synced_at": datetime.now(timezone.utc).isoformat(), "sources": reports}
