from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .config import settings
from .integrations.http import get_json


KNOWN_INTERNATIONAL_ODDS_KEYS = {
    "soccer_fifa_world_cup": "World Cup",
    "soccer_uefa_european_championship": "UEFA Euro",
    "soccer_conmebol_copa_america": "Copa America",
    "soccer_uefa_nations_league": "UEFA Nations League",
    "soccer_fifa_world_cup_qualifiers": "World Cup Qualifiers",
}

PUBLIC_SOURCES = [
    {
        "name": "Footiqo World Cup",
        "coverage": "World Cup only",
        "data": "historical results + 1X2 closing odds",
        "status": "usable_integrated",
        "path": "data/historical_csv/football-data/new/WORLD_CUP.csv",
        "note": "Already used by sync-international-odds-history.",
    },
    {
        "name": "martj42 international_results",
        "coverage": "senior international-team results",
        "data": "results only, no odds",
        "status": "features_only_not_edge_validation",
        "path": "data/historical_csv/international/results.csv",
        "note": "Useful for team features, not sufficient for betting-edge backtests.",
    },
    {
        "name": "openfootball national-team datasets",
        "coverage": "World Cup, Euro, qualifiers and other national-team competitions depending on repository",
        "data": "fixtures/results in open text/CSV-like formats, no bookmaker odds",
        "status": "features_only_candidate",
        "path": "https://github.com/openfootball",
        "note": "Good fallback for filling tournament history and team form features; not enough for edge validation without odds.",
    },
    {
        "name": "Kaggle/martj42 international football results",
        "coverage": "senior international-team results from 1872 onward",
        "data": "results only, no odds",
        "status": "features_only_candidate",
        "path": "https://www.kaggle.com/datasets/martj42/international-football-results-from-1872-to-2017",
        "note": "Same family of data as the configured martj42 CSV; useful for manual refresh checks.",
    },
    {
        "name": "football-data.co.uk",
        "coverage": "club/domestic leagues",
        "data": "historical results + bookmaker odds",
        "status": "not_broad_international",
        "path": "data/historical_csv/football-data",
        "note": "No broad national-team international CSV feed found in this project source.",
    },
]

COMMERCIAL_ODDS_SOURCES = [
    {
        "name": "The Odds API Historical Odds",
        "coverage": "international competitions returned by /v4/sports, including World Cup, Euro, Copa America and UEFA Nations League when listed",
        "data": "historical bookmaker odds snapshots, h2h market usable as 1X2",
        "status": "usable_with_paid_historical_access",
        "path": "https://the-odds-api.com/liveapi/guides/v4/#get-historical-odds",
        "note": "Best match for this project because the live odds integration already uses The Odds API.",
    },
    {
        "name": "API-Football / API-Sports",
        "coverage": "broad football fixtures, teams, leagues, cups and odds depending on subscription",
        "data": "fixtures/results plus odds endpoints",
        "status": "commercial_candidate",
        "path": "https://api-sports.io/documentation/football/v3",
        "note": "Potential fallback provider if The Odds API historical access is not sufficient.",
    },
    {
        "name": "Sportmonks Premium Odds Feed",
        "coverage": "football historical pre-match odds depending on subscription",
        "data": "historical pre-match odds",
        "status": "commercial_candidate",
        "path": "https://docs.sportmonks.com/football/endpoints-and-entities/endpoints/premium-odds-feed",
        "note": "Useful only with paid premium odds access; would require a new adapter.",
    },
]


def _configured_international_keys() -> list[str]:
    return [key.strip() for key in settings.international_odds_sport_keys if key.strip()]


def _sport_status(key: str, sports_by_key: dict[str, dict[str, Any]] | None) -> dict[str, Any]:
    sport = (sports_by_key or {}).get(key)
    if sport:
        status = "available_active" if sport.get("active") else "available_out_of_season"
        title = sport.get("title") or KNOWN_INTERNATIONAL_ODDS_KEYS.get(key) or key
        description = sport.get("description") or ""
    elif sports_by_key is None:
        status = "not_probed_missing_api_key"
        title = KNOWN_INTERNATIONAL_ODDS_KEYS.get(key) or key
        description = ""
    else:
        status = "not_returned_by_sports_endpoint"
        title = KNOWN_INTERNATIONAL_ODDS_KEYS.get(key) or key
        description = ""
    return {
        "sport_key": key,
        "title": title,
        "description": description,
        "status": status,
        "historical_odds_endpoint": f"/v4/historical/sports/{key}/odds",
        "markets": "h2h",
        "regions": "uk,eu",
    }


def find_international_odds_sources(probe_api: bool = True) -> dict[str, Any]:
    configured_keys = _configured_international_keys()
    sports_by_key: dict[str, dict[str, Any]] | None = None
    probe_error: str | None = None
    headers: dict[str, str] = {}

    if probe_api and settings.odds_api_key:
        try:
            sports, headers = get_json(
                f"{settings.odds_api_base_url}/sports",
                {"apiKey": settings.odds_api_key, "all": "true"},
                settings.enrichment_timeout_seconds,
            )
            sports_by_key = {
                str(item.get("key")): item
                for item in sports
                if item.get("key")
            }
        except Exception as exc:
            sports_by_key = {}
            probe_error = str(exc)

    odds_api_candidates = [_sport_status(key, sports_by_key) for key in configured_keys]
    usable_api_keys = [
        item for item in odds_api_candidates
        if item["status"] in {"available_active", "available_out_of_season", "not_probed_missing_api_key"}
    ]
    blockers: list[str] = []
    if not settings.odds_api_key:
        blockers.append("THE_ODDS_API_KEY is missing; cannot verify The Odds API sport-key coverage from this machine.")
    if probe_error:
        blockers.append(f"The Odds API sports probe failed: {probe_error}")
    if not usable_api_keys:
        blockers.append("No configured broad international sport keys are currently usable.")

    return {
        "method": "broad international football odds source discovery",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "public_csv_sources": PUBLIC_SOURCES,
        "commercial_odds_sources": COMMERCIAL_ODDS_SOURCES,
        "odds_api": {
            "configured": bool(settings.odds_api_key),
            "base_url": settings.odds_api_base_url,
            "probe_used": bool(probe_api and settings.odds_api_key),
            "quota_headers": {
                key: headers.get(key)
                for key in ("x-requests-remaining", "x-requests-used", "x-requests-last")
                if headers.get(key) is not None
            },
            "candidates": odds_api_candidates,
            "usable_or_configurable": usable_api_keys,
            "note": (
                "Use The Odds API historical endpoint for broad international 1X2 odds. "
                "Historical snapshots require a paid usage plan and start from 2020-06-06."
            ),
        },
        "recommended_env": {
            "THE_ODDS_API_KEY": "<your key>",
            "INTERNATIONAL_ODDS_SPORT_KEYS": ",".join(configured_keys),
        },
        "next_actions": [
            "Keep Footiqo WORLD_CUP.csv as the already-integrated free World Cup odds source.",
            "Use martj42/openfootball-style results data only for national-team feature coverage, not for betting-edge proof.",
            "Configure THE_ODDS_API_KEY with historical access, then rerun this command to verify broad international sport keys.",
            "Only after keys are verified, archive paid historical h2h snapshots and join them to settled international results.",
        ],
        "blockers": blockers,
    }
