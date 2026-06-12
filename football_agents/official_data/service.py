from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from typing import Any

from ..config import settings
from ..repository import Repository
from .browser import SportteryBrowserClient

STATUS_MAP = {
    "已开售": "scheduled", "待开售": "scheduled", "未开赛": "scheduled",
    "进行中": "live", "比赛中": "live", "已完成": "finished",
    "已取消": "cancelled", "取消": "cancelled", "延期": "postponed",
    "已延期": "postponed", "停售": "closed", "已停售": "closed",
}

class OfficialDataService:
    _lock = threading.Lock()
    def __init__(self, repository: Repository | None = None, client: SportteryBrowserClient | None = None) -> None:
        self.repository = repository or Repository()
        self.client = client or SportteryBrowserClient(
            settings.official_browser_path, settings.official_fetch_timeout_seconds)

    def sync(self, force: bool = False) -> dict[str, Any]:
        with self._lock:
            latest = self.repository.latest_fetch_log()
            if latest and latest["success"] and not force:
                age = datetime.now(timezone.utc) - datetime.fromisoformat(latest["fetched_at"])
                if age.total_seconds() < settings.official_min_sync_interval_seconds:
                    return {"status": "skipped", "reason": "minimum_sync_interval", "latest": latest}
            try:
                payload = self.client.fetch(settings.official_source_url)
                raw_hash = hashlib.sha256(payload["html"].encode("utf-8")).hexdigest()
                fetched_at = datetime.now(timezone.utc).isoformat()
                summary = {"created": 0, "updated": 0, "odds_snapshots": 0, "incomplete_odds": 0,
                           "invalid": 0, "records": len(payload["matches"]), "raw_hash": raw_hash}
                for raw in payload["matches"]:
                    item = self._normalize(raw, raw_hash)
                    if not item:
                        summary["invalid"] += 1
                        continue
                    match_id, created, _ = self.repository.upsert_official_match(item)
                    summary["created" if created else "updated"] += 1
                    odds = raw.get("odds") or {}
                    if set(odds) == {"home", "draw", "away"} and all(float(v) > 1 for v in odds.values()):
                        odds_hash = hashlib.sha256(json.dumps({"id": item["official_match_id"], "odds": odds},
                                                             sort_keys=True).encode()).hexdigest()
                        if self.repository.add_official_odds(match_id, odds, "中国竞彩网",
                                                             fetched_at, settings.official_source_url, odds_hash):
                            summary["odds_snapshots"] += 1
                    else:
                        summary["incomplete_odds"] += 1
                valid_records = summary["created"] + summary["updated"]
                if valid_records == 0:
                    raise RuntimeError("Official source returned no valid match records")
                self.repository.save_fetch_log("中国竞彩网", settings.official_source_url, True,
                                               raw_hash, summary["records"], status_code=200)
                return {"status": "success", **summary, "fetched_at": fetched_at}
            except Exception as exc:
                self.repository.save_fetch_log("中国竞彩网", settings.official_source_url, False,
                                               error_message=str(exc))
                raise

    @staticmethod
    def _normalize(raw: dict[str, Any], raw_hash: str) -> dict[str, Any] | None:
        required = [raw.get("source_match_id"), raw.get("league"), raw.get("home_team"),
                    raw.get("away_team"), raw.get("match_date"), raw.get("match_time")]
        if not all(required):
            return None
        try:
            kickoff = datetime.fromisoformat(f'{raw["match_date"]}T{raw["match_time"]}:00+08:00').isoformat()
        except ValueError:
            return None
        quality = sum(bool(value) for value in required) / len(required)
        return {
            "official_match_id": f'sporttery-{raw["source_match_id"]}', "match_no": raw.get("match_no"),
            "league": raw["league"], "home_team": raw["home_team"], "away_team": raw["away_team"],
            "kickoff_time": kickoff, "status": STATUS_MAP.get(raw.get("sale_status"), "unknown"),
            "source_url": settings.official_source_url, "data_quality_score": quality, "raw_hash": raw_hash,
        }

    def status(self) -> dict[str, Any]:
        latest = self.repository.latest_fetch_log()
        return {"source": "中国竞彩网", "source_url": settings.official_source_url,
                "browser_path": settings.official_browser_path, "latest": latest,
                "recent_logs": self.repository.list_fetch_logs(10)}
