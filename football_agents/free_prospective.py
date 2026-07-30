from __future__ import annotations

from typing import Any

from .config import settings
from .integrations import DataEnrichmentService
from .repository import Repository


class FreeProspectiveOddsService:
    """Collect at most one immutable bookmaker snapshot per configured pre-match window."""

    def __init__(self, repository: Repository | None = None) -> None:
        self.repository = repository or Repository()

    @staticmethod
    def _window(offset_hours: int) -> tuple[int, int]:
        if offset_hours == 1:
            return 30, 120
        tolerance = 60
        center = max(1, offset_hours) * 60
        return max(1, center - tolerance), center + tolerance

    def capture(self, limit: int | None = None) -> dict[str, Any]:
        reports: list[dict[str, Any]] = []
        service = DataEnrichmentService(self.repository)
        for offset in settings.prospective_snapshot_offsets_hours:
            lower, upper = self._window(offset)
            report = service.sync(
                limit or settings.agent_match_limit,
                evaluate=False,
                include_news_weather=False,
                odds_minimum_minutes=lower,
                odds_window_minutes=upper,
                skip_existing_horizon_capture=True,
            )
            reports.append({"offset_hours": offset, "minimum_minutes": lower, "maximum_minutes": upper, **report})
            if report.get("market_status") == "quota_reserved":
                break
        status = self.repository.free_prospective_odds_status()
        errors = [error for report in reports for error in report.get("errors", [])]
        return {
            "status": "partial" if errors else "success",
            "matches": sum(int(report.get("market_candidate_matches", 0) or 0) for report in reports),
            "market_odds": sum(int(report.get("market_odds", 0) or 0) for report in reports),
            "snapshots": sum(int(report.get("prospective_snapshots", 0) or 0) for report in reports),
            "windows": reports,
            "quota": status["monthly_quota"],
            "evidence": status,
            "errors": errors,
            "guardrail": "Only pre-match named-bookmaker snapshots are immutable evidence; no real orders are placed.",
        }
