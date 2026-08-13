from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from ..config import settings
from ..repository import Repository, utcnow
from .odds import OddsApiClient


SPORT_KEY_LEAGUE = {
    "soccer_epl": "E0",
    "soccer_efl_champ": "E1",
    "soccer_brazil_campeonato": "BRA",
}


def _remaining_from_provider(rows: list[dict[str, Any]]) -> int | None:
    latest = next((row for row in rows if row.get("provider") == "the_odds_api"), None)
    match = re.search(r"requests_remaining=(\d+)", str((latest or {}).get("message") or ""))
    return int(match.group(1)) if match else None


class ExternalMarketUniverseService:
    """Maintain a labelled research fixture universe without pretending it is official SP."""

    def __init__(
        self, repository: Repository | None = None, client: OddsApiClient | None = None,
    ) -> None:
        self.repository = repository or Repository()
        self.client = client or OddsApiClient()

    def sync(self, now: datetime | None = None) -> dict[str, Any]:
        observed = now or datetime.now(timezone.utc)
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        summary: dict[str, Any] = {
            "status": "success", "matches": 0, "fixture_events": 0,
            "created": 0, "updated": 0, "scores_requested": 0,
            "settled": 0, "confirmed": 0, "pending": 0, "conflicts": 0,
            "invalid": 0, "errors": [],
        }
        if not self.client.configured():
            summary.update(status="not_configured", errors=["THE_ODDS_API_KEY is missing"])
            return summary

        sport_keys = tuple(settings.external_fixture_sport_keys)[
            : max(1, int(settings.prospective_max_active_sports))
        ]
        events, headers = self.client.fixture_events(sport_keys)
        captured_at = observed.astimezone(timezone.utc).isoformat()
        for audit in self.client.request_audits:
            self.repository.record_odds_api_request(audit, captured_at)
        summary["fixture_events"] = len(events)
        horizon = observed + timedelta(days=45)
        for event in events:
            try:
                kickoff = datetime.fromisoformat(
                    str(event.get("commence_time") or "").replace("Z", "+00:00")
                )
                if kickoff.tzinfo is None:
                    kickoff = kickoff.replace(tzinfo=timezone.utc)
                if not observed - timedelta(hours=6) <= kickoff <= horizon:
                    continue
                if not all(event.get(key) for key in ("id", "sport_key", "home_team", "away_team")):
                    summary["invalid"] += 1
                    continue
                _match_id, created = self.repository.upsert_external_market_match(
                    event,
                    SPORT_KEY_LEAGUE.get(
                        str(event["sport_key"]), str(event.get("sport_title") or event["sport_key"])
                    ),
                )
                summary["created" if created else "updated"] += 1
            except (KeyError, TypeError, ValueError) as exc:
                summary["invalid"] += 1
                summary["errors"].append(f"fixture:{type(exc).__name__}:{exc}")
        summary["matches"] = summary["created"] + summary["updated"]
        self.repository.log_provider_sync(
            "the_odds_api_fixtures", "success", summary["matches"],
            f"requests_remaining={headers.get('x-requests-remaining', 'unknown')};cost=0",
        )

        if self._scores_due(observed):
            self._sync_scores(sport_keys, captured_at, summary)
        else:
            summary["scores_status"] = "minimum_interval"
        return summary

    def _scores_due(self, observed: datetime) -> bool:
        latest = next((
            row for row in self.repository.provider_status()
            if row.get("provider") == "the_odds_api_scores"
        ), None)
        if not latest:
            return True
        last = datetime.fromisoformat(str(latest["synced_at"]).replace("Z", "+00:00"))
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return observed - last >= timedelta(
            hours=max(1, int(settings.external_results_sync_interval_hours))
        )

    def _sync_scores(
        self, sport_keys: tuple[str, ...], captured_at: str, summary: dict[str, Any],
    ) -> None:
        quota = self.repository.free_prospective_odds_status()
        spent = int(quota["monthly_quota"].get("spent") or 0)
        remaining = _remaining_from_provider(self.repository.provider_status())
        estimated_cost = 2 * len(sport_keys)
        if (
            spent + estimated_cost > int(settings.prospective_monthly_credit_budget)
            or (remaining is not None and remaining - estimated_cost < int(settings.prospective_credit_reserve))
        ):
            summary["scores_status"] = "quota_reserved"
            self.repository.log_provider_sync(
                "the_odds_api_scores", "quota_reserved", message=(
                    f"requests_remaining={remaining};monthly_spent={spent};"
                    f"estimated_cost={estimated_cost}"
                ),
            )
            return
        known = self.repository.external_market_event_ids()
        for sport_key in sport_keys:
            try:
                rows, _headers, audit = self.client.scores(sport_key, days_from=3)
                self.repository.record_odds_api_request(audit, captured_at)
                summary["scores_requested"] += 1
                for event in rows:
                    if str(event.get("id") or "") not in known:
                        continue
                    result = self.repository.archive_external_market_result(event, captured_at)
                    key = {
                        "SETTLED": "settled", "CONFIRMED": "confirmed",
                        "PENDING": "pending", "CONFLICT": "conflicts",
                        "INVALID": "invalid",
                    }.get(str(result["status"]))
                    if key:
                        summary[key] += 1
            except Exception as exc:  # provider failures remain visible per sport
                summary["errors"].append(f"{sport_key} scores:{type(exc).__name__}:{exc}")
        summary["scores_status"] = "partial" if summary["errors"] else "success"
        self.repository.log_provider_sync(
            "the_odds_api_scores", summary["scores_status"],
            summary["settled"] + summary["confirmed"],
            f"sports={summary['scores_requested']};errors={len(summary['errors'])}",
        )
