from __future__ import annotations

import re
import threading
from datetime import datetime, timezone
from typing import Any

from ..agents.workflow import DecisionWorkflow
from ..config import settings
from ..features import HistoricalFeatureBuilder
from ..repository import Repository, utcnow
from .news import GdeltNewsClient
from .odds import OddsApiClient
from .weather import OpenMeteoClient


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _odds_capture_targets(matches: list[dict[str, Any]], now: datetime,
                          window_minutes: int, minimum_minutes: int = 0) -> list[dict[str, Any]]:
    return [
        match for match in matches
        if minimum_minutes <= (
            _parse_time(match["kickoff_time"]) - now
        ).total_seconds() / 60 <= window_minutes
    ]


def _requests_remaining(provider_rows: list[dict[str, Any]]) -> int | None:
    latest = next((row for row in provider_rows if row.get("provider") == "the_odds_api"), None)
    match = re.search(r"requests_remaining=(\d+)", str((latest or {}).get("message") or ""))
    return int(match.group(1)) if match else None


class DataEnrichmentService:
    _odds_sync_lock = threading.Lock()

    def __init__(self, repository: Repository | None = None) -> None:
        self.repository = repository or Repository()
        self.odds = OddsApiClient()
        self.news = GdeltNewsClient()
        self.weather = OpenMeteoClient()
        self.features = HistoricalFeatureBuilder(self.repository)
        self.workflow = DecisionWorkflow(self.repository)

    def sync(self, limit: int = 40, evaluate: bool = True, *,
             include_news_weather: bool = True,
             odds_minimum_minutes: int = 0,
             odds_window_minutes: int | None = None,
             skip_existing_horizon_capture: bool = False) -> dict[str, Any]:
        matches = self.repository.list_active_official_matches(limit)
        capture_window = odds_window_minutes or settings.external_odds_capture_window_minutes
        summary: dict[str, Any] = {
            "matches": len(matches), "market_events_fetched": 0, "market_odds": 0,
            "market_candidate_matches": 0, "market_target_matches": 0,
            "market_already_captured": 0,
            "market_capture_minimum_minutes": odds_minimum_minutes,
            "market_capture_window_minutes": capture_window,
            "market_unmatched": 0, "news_articles_fetched": 0, "news": 0,
            "news_duplicates": 0, "news_existing": 0, "weather": 0,
            "weather_missing_metadata": 0, "predictions": 0, "evaluated": 0,
            "features_built": 0, "features_skipped": 0, "model_blocked": 0,
            "model_blocked_missing_official_odds": 0, "errors": [],
        }
        with self._odds_sync_lock:
            self._capture_odds(
                matches, summary, odds_minimum_minutes, capture_window,
                skip_existing_horizon_capture,
            )

        if include_news_weather:
            self._sync_context(matches, summary, evaluate)
        else:
            summary["news_status"] = "not_requested"
            summary["weather_status"] = "not_requested"
            summary["model_status"] = "not_requested"

        return summary

    def _sync_context(self, matches: list[dict[str, Any]], summary: dict[str, Any],
                      evaluate: bool) -> None:
        for match in matches:
            try:
                articles = self.news.fetch(match, max_records=3)
                summary["news_articles_fetched"] += len(articles)
                for article in articles:
                    inserted = self.repository.add_news_event(match["id"], article)
                    summary["news"] += int(inserted)
                    summary["news_duplicates"] += int(not inserted)
            except Exception as exc:
                summary["errors"].append(f'{match["official_match_id"]} news: {exc}')
            try:
                metadata = self.repository.get_match_metadata(match["id"])
                if not metadata:
                    summary["weather_missing_metadata"] += 1
                weather = self.weather.fetch(match, metadata) if metadata else None
                if weather:
                    self.repository.add_weather(match["id"], weather)
                    summary["weather"] += 1
            except Exception as exc:
                summary["errors"].append(f'{match["official_match_id"]} weather: {exc}')
            if evaluate:
                try:
                    feature_result = self.features.build(match)
                    summary["features_built"] += int(feature_result["built"])
                    summary["features_skipped"] += int(not feature_result["built"])
                    if len(self.repository.latest_odds(match["id"])["odds"]) != 3:
                        summary["model_blocked_missing_official_odds"] += 1
                    result = self.workflow.evaluate(match["id"])
                    if result.get("baseline") or result.get("ensemble"):
                        summary["predictions"] += 1
                    if result.get("market_calibrated"):
                        summary["evaluated"] += 1
                    if not result.get("baseline") and not result.get("ensemble"):
                        summary["model_blocked"] += 1
                except Exception as exc:
                    summary["errors"].append(f'{match["official_match_id"]} model: {exc}')
        summary["news_existing"] = sum(len(self.repository.list_news(match["id"], 100)) for match in matches)
        if summary["news"]:
            summary["news_status"] = "updated"
        elif summary["news_articles_fetched"] and summary["news_duplicates"] == summary["news_articles_fetched"]:
            summary["news_status"] = "up_to_date"
        else:
            summary["news_status"] = "no_articles"
        summary["weather_status"] = (
            "available" if summary["weather"] else
            "blocked_missing_metadata" if summary["weather_missing_metadata"] else "unavailable"
        )
        summary["model_status"] = (
            "partially_market_evaluated" if summary["evaluated"] and summary["model_blocked"] else
            "market_evaluated" if summary["evaluated"] else
            "baseline_only" if summary["predictions"] else
            "blocked_missing_features" if summary["features_skipped"] else "blocked_other_inputs"
        )
        self.repository.log_provider_sync("news_aggregator", "success" if not summary["errors"] else "partial",
                                          summary["news"], "Google News RSS with GDELT fallback")
        self.repository.log_provider_sync("open_meteo", "success" if summary["weather"] else "waiting_metadata",
                                          summary["weather"], "Venue coordinates required")

    def _capture_odds(self, matches: list[dict[str, Any]], summary: dict[str, Any],
                      minimum_minutes: int, window_minutes: int,
                      skip_existing_horizon_capture: bool) -> None:
        now = datetime.now(timezone.utc)
        candidates = _odds_capture_targets(matches, now, window_minutes, minimum_minutes)
        summary["market_candidate_matches"] = len(candidates)
        odds_matches = candidates
        if skip_existing_horizon_capture:
            odds_matches = [
                match for match in candidates
                if not self.repository.has_external_odds_capture_in_horizon(
                    int(match["id"]), minimum_minutes, window_minutes
                )
            ]
        summary["market_already_captured"] = len(candidates) - len(odds_matches)
        summary["market_target_matches"] = len(odds_matches)
        remaining = _requests_remaining(self.repository.provider_status())
        summary["odds_requests_remaining_before"] = remaining
        quota_reserved = (
            remaining is not None
            and remaining <= settings.odds_api_min_requests_remaining
            and bool(odds_matches)
        )
        events: list[dict[str, Any]] = []
        if quota_reserved:
            message = (
                f"requests_remaining={remaining}; reserve={settings.odds_api_min_requests_remaining}; "
                f"target_matches={len(odds_matches)}"
            )
            self.repository.log_provider_sync("the_odds_api", "quota_reserved", message=message)
            summary["errors"].append("external_odds: request quota reserve reached")
        elif self.odds.configured() and odds_matches:
            try:
                events, headers = self.odds.events({
                    str(match.get("league") or "") for match in odds_matches
                })
                summary["market_events_fetched"] = len(events)
                self.repository.log_provider_sync("the_odds_api", "success", len(events),
                    f'requests_remaining={headers.get("x-requests-remaining", "unknown")}')
                summary["odds_requests_remaining_after"] = headers.get("x-requests-remaining")
                summary["odds_warnings"] = list(self.odds.warnings)
            except Exception as exc:
                self.repository.log_provider_sync("the_odds_api", "error", message=str(exc))
                summary["errors"].append(f"external_odds: {exc}")
        elif not self.odds.configured():
            self.repository.log_provider_sync("the_odds_api", "not_configured", message="THE_ODDS_API_KEY is missing")
        elif candidates and not odds_matches:
            self.repository.log_provider_sync(
                "the_odds_api", "horizon_captured", message=(
                    f"requests_remaining={remaining if remaining is not None else 'unknown'}; "
                    f"captured_matches={len(candidates)}; horizon_minutes={minimum_minutes}-{window_minutes}"
                )
            )
        else:
            self.repository.log_provider_sync(
                "the_odds_api", "waiting_horizon", message=(
                    f"requests_remaining={remaining if remaining is not None else 'unknown'}; "
                    f"target_matches=0; horizon_minutes={minimum_minutes}-{window_minutes}"
                )
            )

        for match in odds_matches:
            try:
                event = self.odds.match_event(match, events) if events else None
                consensus = self.odds.consensus(event) if event else None
                if consensus:
                    fetched_at = utcnow()
                    self.repository.add_odds(match["id"], consensus, "The Odds API consensus", fetched_at, external=True)
                    self.repository.add_external_bookmaker_odds(
                        match["id"], self.odds.bookmaker_odds(event), fetched_at
                    )
                    summary["market_odds"] += 1
                else:
                    summary["market_unmatched"] += 1
            except Exception as exc:
                summary["errors"].append(f'{match["official_match_id"]} external_odds: {exc}')
        summary["market_status"] = (
            "quota_reserved" if quota_reserved else
            "not_configured" if not self.odds.configured() else
            "horizon_captured" if candidates and not odds_matches else
            "waiting_horizon" if not odds_matches else
            "matched" if summary["market_odds"] else "no_matches"
        )

    def status(self) -> dict[str, Any]:
        return {"providers": self.repository.provider_status(), "odds_api_configured": bool(settings.odds_api_key)}
