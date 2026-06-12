from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_DIR / ".env")
load_dotenv(PROJECT_DIR / "api.env")
load_dotenv(PROJECT_DIR.parent / "api.env")


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, default))


@dataclass(frozen=True)
class Settings:
    app_env: str = os.getenv("APP_ENV", "development")
    database_path: Path = Path(os.getenv("DATABASE_PATH", "./data/football_agents.db"))
    bankroll: float = _float("BANKROLL", 10_000.0)
    min_ev: float = _float("MIN_EV", 0.05)
    max_single_stake: float = _float("MAX_SINGLE_STAKE", 0.01)
    max_daily_exposure: float = _float("MAX_DAILY_EXPOSURE", 0.03)
    max_weekly_exposure: float = _float("MAX_WEEKLY_EXPOSURE", 0.08)
    odds_max_age_minutes: int = int(os.getenv("ODDS_MAX_AGE_MINUTES", "10"))
    official_source_url: str = os.getenv("OFFICIAL_SOURCE_URL", "https://m.sporttery.cn/mjc/zqsj/?tab=schedule")
    official_browser_path: str = os.getenv(
        "OFFICIAL_BROWSER_PATH", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    )
    official_fetch_timeout_seconds: int = int(os.getenv("OFFICIAL_FETCH_TIMEOUT_SECONDS", "25"))
    official_min_sync_interval_seconds: int = int(os.getenv("OFFICIAL_MIN_SYNC_INTERVAL_SECONDS", "60"))
    odds_api_key: str = os.getenv("THE_ODDS_API_KEY", "")
    odds_api_base_url: str = os.getenv("ODDS_API_BASE_URL", "https://api.the-odds-api.com/v4")
    odds_api_sport_keys: tuple[str, ...] = tuple(filter(None, os.getenv(
        "ODDS_API_SPORT_KEYS", "soccer_fifa_world_cup,soccer_international_friendlies"
    ).split(",")))
    gdelt_api_url: str = os.getenv("GDELT_API_URL", "https://api.gdeltproject.org/api/v2/doc/doc")
    open_meteo_geocoding_url: str = os.getenv(
        "OPEN_METEO_GEOCODING_URL", "https://geocoding-api.open-meteo.com/v1/search"
    )
    open_meteo_forecast_url: str = os.getenv(
        "OPEN_METEO_FORECAST_URL", "https://api.open-meteo.com/v1/forecast"
    )
    enrichment_timeout_seconds: int = int(os.getenv("ENRICHMENT_TIMEOUT_SECONDS", "15"))
    llm_provider: str = os.getenv("LLM_PROVIDER", "")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "").rstrip("/")
    llm_model: str = os.getenv("LLM_MODEL", "")
    llm_timeout_seconds: int = int(os.getenv("LLM_TIMEOUT_SECONDS", "45"))
    llm_max_news_items: int = int(os.getenv("LLM_MAX_NEWS_ITEMS", "5"))


settings = Settings()

