from __future__ import annotations

import csv
import hashlib
import io
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from .config import settings
from .repository import Repository


class InternationalHistoryAgent:
    """Incrementally archives and imports CC0 senior international results."""

    def __init__(self, repository: Repository | None = None, archive_path: Path | None = None) -> None:
        self.repository = repository or Repository()
        self.archive_path = archive_path or Path("data") / "historical_csv" / "international" / "results.csv"

    def fetch(self) -> str:
        attempts = max(1, settings.historical_data_retries + 1)
        for attempt in range(attempts):
            try:
                request = Request(settings.international_data_url,
                                  headers={"User-Agent": "football-agents-international-history/1.0"})
                with urlopen(request, timeout=settings.international_data_timeout_seconds) as response:
                    return response.read().decode("utf-8-sig")
            except Exception:
                if attempt + 1 >= attempts:
                    raise
                time.sleep(settings.historical_data_retry_backoff_seconds * (2 ** attempt))
        raise RuntimeError("international results download failed")

    @staticmethod
    def normalize_csv(text: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for item in csv.DictReader(io.StringIO(text.lstrip("\ufeff"))):
            try:
                played_at = datetime.strptime(item["date"].strip(), "%Y-%m-%d").date().isoformat()
                tournament = item["tournament"].strip() or "International"
                home_team, away_team = item["home_team"].strip(), item["away_team"].strip()
                home_goals, away_goals = int(item["home_score"]), int(item["away_score"])
                if not home_team or not away_team or home_team == away_team:
                    continue
                natural_key = f"international|{played_at}|{home_team}|{away_team}|{tournament}"
                rows.append({
                    "id": "intl-" + hashlib.sha256(natural_key.encode("utf-8")).hexdigest()[:24],
                    "league": tournament,
                    "home_team": home_team,
                    "away_team": away_team,
                    "home_goals": home_goals,
                    "away_goals": away_goals,
                    "played_at": played_at,
                    "match_type": "FRIENDLY" if tournament.lower() == "friendly" else "CUP",
                })
            except (KeyError, TypeError, ValueError):
                continue
        return rows

    def sync(self) -> dict[str, Any]:
        network_error: Exception | None = None
        try:
            text = self.fetch()
            status = "success"
            self.archive_path.parent.mkdir(parents=True, exist_ok=True)
            self.archive_path.write_text(text, encoding="utf-8")
        except Exception as exc:
            network_error = exc
            if not self.archive_path.exists():
                raise
            text = self.archive_path.read_text(encoding="utf-8-sig")
            status = "cached"
        rows = self.normalize_csv(text)
        result = self.repository.upsert_historical_matches(rows, settings.international_data_url)
        report = {**result, "rows": len(rows), "status": status,
                  "database_matches": self.repository.historical_match_count(),
                  "archive": str(self.archive_path), "source_url": settings.international_data_url,
                  "synced_at": datetime.now(timezone.utc).isoformat()}
        if network_error:
            report["warning"] = str(network_error)
        self.repository.add_audit_event("international-history-agent", "国家队历史数据", "增量同步",
                                        json.dumps(report, ensure_ascii=False),
                                        "success" if status == "success" else "partial")
        return report
