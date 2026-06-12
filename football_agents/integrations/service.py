from __future__ import annotations

from typing import Any

from ..agents import DecisionWorkflow
from ..config import settings
from ..repository import Repository, utcnow
from .news import GdeltNewsClient
from .odds import OddsApiClient
from .weather import OpenMeteoClient


class DataEnrichmentService:
    def __init__(self, repository: Repository | None = None) -> None:
        self.repository = repository or Repository()
        self.odds = OddsApiClient()
        self.news = GdeltNewsClient()
        self.weather = OpenMeteoClient()
        self.workflow = DecisionWorkflow(self.repository)

    def sync(self, limit: int = 40) -> dict[str, Any]:
        all_matches = self.repository.list_official_matches()
        matches = sorted(all_matches, key=lambda item: (item["status"] not in {"scheduled", "live"}, item["kickoff_time"]))[:limit]
        summary: dict[str, Any] = {"matches": len(matches), "market_odds": 0, "news": 0,
                                  "weather": 0, "predictions": 0, "evaluated": 0, "errors": []}
        events: list[dict[str, Any]] = []
        if self.odds.configured():
            try:
                events, headers = self.odds.events()
                self.repository.log_provider_sync("the_odds_api", "success", len(events),
                    f'requests_remaining={headers.get("x-requests-remaining", "unknown")}')
            except Exception as exc:
                self.repository.log_provider_sync("the_odds_api", "error", message=str(exc))
                summary["errors"].append(f"external_odds: {exc}")
        else:
            self.repository.log_provider_sync("the_odds_api", "not_configured", message="THE_ODDS_API_KEY is missing")

        for match in matches:
            try:
                event = self.odds.match_event(match, events) if events else None
                consensus = self.odds.consensus(event) if event else None
                if consensus:
                    self.repository.add_odds(match["id"], consensus, "The Odds API consensus", utcnow(), external=True)
                    summary["market_odds"] += 1
            except Exception as exc:
                summary["errors"].append(f'{match["official_match_id"]} external_odds: {exc}')
            try:
                articles = self.news.fetch(match, max_records=3)
                for article in articles:
                    summary["news"] += int(self.repository.add_news_event(match["id"], article))
            except Exception as exc:
                summary["errors"].append(f'{match["official_match_id"]} news: {exc}')
            try:
                metadata = self.repository.get_match_metadata(match["id"])
                weather = self.weather.fetch(match, metadata) if metadata else None
                if weather:
                    self.repository.add_weather(match["id"], weather)
                    summary["weather"] += 1
            except Exception as exc:
                summary["errors"].append(f'{match["official_match_id"]} weather: {exc}')
            try:
                result = self.workflow.evaluate(match["id"])
                if result.get("baseline") or result.get("ensemble"):
                    summary["predictions"] += 1
                if result.get("market_calibrated"):
                    summary["evaluated"] += 1
            except Exception as exc:
                summary["errors"].append(f'{match["official_match_id"]} model: {exc}')
        self.repository.log_provider_sync("news_aggregator", "success" if not summary["errors"] else "partial",
                                          summary["news"], "Google News RSS with GDELT fallback")
        self.repository.log_provider_sync("open_meteo", "success" if summary["weather"] else "waiting_metadata",
                                          summary["weather"], "Venue coordinates required")
        return summary

    def status(self) -> dict[str, Any]:
        return {"providers": self.repository.provider_status(), "odds_api_configured": bool(settings.odds_api_key)}
