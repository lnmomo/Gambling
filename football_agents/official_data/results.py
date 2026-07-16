from __future__ import annotations

import hashlib
import json
import re
import threading
from datetime import date, datetime, timedelta, timezone
from typing import Any

from ..config import settings
from ..repository import Repository
from .browser import SportteryBrowserClient


FINAL_RESULT_STATUS = "2"
SCORE_PATTERN = re.compile(r"^(\d{1,2})\s*:\s*(\d{1,2})$")
CHINA_TZ = timezone(timedelta(hours=8))


class OfficialResultService:
    """Backfill auditable 90-minute scores from the official result archive."""

    _lock = threading.Lock()

    def __init__(
        self,
        repository: Repository | None = None,
        client: SportteryBrowserClient | None = None,
    ) -> None:
        self.repository = repository or Repository()
        self.client = client or SportteryBrowserClient(
            settings.official_browser_path, settings.official_fetch_timeout_seconds
        )

    @staticmethod
    def _date_windows(end: date, lookback_days: int) -> list[tuple[str, str]]:
        start = end - timedelta(days=max(1, lookback_days))
        windows: list[tuple[str, str]] = []
        cursor = start
        while cursor <= end:
            window_end = min(end, cursor + timedelta(days=29))
            windows.append((cursor.isoformat(), window_end.isoformat()))
            cursor = window_end + timedelta(days=1)
        return windows

    @staticmethod
    def _normalize(raw: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
        source_id = raw.get("matchId")
        if source_id in {None, ""}:
            return dict(raw), "missing_match_id"
        item = {
            "official_match_id": f"sporttery-{source_id}",
            "match_id": str(source_id),
            "match_date": str(raw.get("matchDate") or ""),
            "match_no": str(raw.get("matchNumStr") or raw.get("matchNum") or ""),
            "league": str(raw.get("leagueName") or raw.get("leagueNameAbbr") or ""),
            "home_team": str(raw.get("allHomeTeam") or raw.get("homeTeam") or ""),
            "away_team": str(raw.get("allAwayTeam") or raw.get("awayTeam") or ""),
            "source_result_status": str(raw.get("matchResultStatus") or ""),
            "pool_status": str(raw.get("poolStatus") or ""),
            "full_time_score": str(raw.get("sectionsNo999") or ""),
        }
        if item["source_result_status"] != FINAL_RESULT_STATUS:
            return item, "result_not_final"
        score = SCORE_PATTERN.fullmatch(item["full_time_score"])
        if not score:
            return item, "missing_or_invalid_90_minute_score"
        item["home_score"] = int(score.group(1))
        item["away_score"] = int(score.group(2))
        if not item["match_date"]:
            return item, "missing_match_date"
        return item, None

    @staticmethod
    def _hash(item: dict[str, Any]) -> str:
        canonical = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def sync(self, now: datetime | None = None) -> dict[str, Any]:
        with self._lock:
            current = now or datetime.now(timezone.utc)
            if current.tzinfo is None:
                current = current.replace(tzinfo=timezone.utc)
            observed_at = current.astimezone(timezone.utc).isoformat()
            windows = self._date_windows(
                current.astimezone(CHINA_TZ).date(), settings.official_results_lookback_days
            )
            try:
                payload = self.client.fetch_results(settings.official_results_source_url, windows)
                rows = payload.get("results") or []
                payload_hash = self._hash({"results": rows, "windows": payload.get("windows") or []})
                summary: dict[str, Any] = {
                    "status": "success",
                    "records": len(rows),
                    "settled": 0,
                    "confirmed": 0,
                    "duplicates": 0,
                    "conflicts": 0,
                    "unmatched": 0,
                    "out_of_scope": 0,
                    "ambiguous": 0,
                    "skipped": 0,
                    "windows": payload.get("windows") or [],
                    "raw_hash": payload_hash,
                    "fetched_at": observed_at,
                }
                known_match_ids = self.repository.official_match_ids()
                for raw in rows:
                    item, skip_reason = self._normalize(raw)
                    if item.get("official_match_id") not in known_match_ids:
                        summary["out_of_scope"] += 1
                        continue
                    raw_hash = self._hash(item)
                    if skip_reason:
                        result = self.repository.archive_skipped_official_result(
                            item, observed_at, settings.official_results_source_url,
                            raw_hash, skip_reason,
                        )
                    else:
                        result = self.repository.settle_official_result(
                            item, observed_at, settings.official_results_source_url, raw_hash
                        )
                    key = {
                        "SETTLED": "settled",
                        "CONFIRMED": "confirmed",
                        "DUPLICATE": "duplicates",
                        "CONFLICT": "conflicts",
                        "UNMATCHED": "unmatched",
                        "AMBIGUOUS": "ambiguous",
                        "SKIPPED": "skipped",
                    }[result["status"]]
                    summary[key] += 1

                self.repository.save_fetch_log(
                    "sporttery_official_results",
                    settings.official_results_source_url,
                    True,
                    payload_hash,
                    len(rows),
                    status_code=200,
                )
                summary["evidence"] = self.repository.official_result_evidence_status()
                summary["warnings"] = []
                if summary["conflicts"]:
                    summary["warnings"].append(
                        f"{summary['conflicts']} official result conflicts were quarantined"
                    )
                if summary["ambiguous"]:
                    summary["warnings"].append(
                        f"{summary['ambiguous']} official result rows failed date consistency"
                    )
                return summary
            except Exception as exc:
                self.repository.save_fetch_log(
                    "sporttery_official_results",
                    settings.official_results_source_url,
                    False,
                    error_message=str(exc),
                )
                raise
