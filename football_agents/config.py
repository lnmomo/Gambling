from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    def load_dotenv(*_args: object, **_kwargs: object) -> bool:
        return False


PROJECT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_DIR / ".env")
load_dotenv(PROJECT_DIR / "api.env")
load_dotenv(PROJECT_DIR.parent / "api.env")


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, default))


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _database_path_from_url(database_url: str) -> Path:
    prefix = "sqlite:///"
    if database_url.startswith(prefix):
        raw_path = database_url[len(prefix):]
        return Path(raw_path)
    if database_url.startswith("sqlite://"):
        raw_path = database_url[len("sqlite://"):]
        return Path(raw_path)
    return Path(database_url)


@dataclass(frozen=True)
class Settings:
    project_dir: Path = PROJECT_DIR
    app_env: str = os.getenv("APP_ENV", "development")
    app_host: str = os.getenv("APP_HOST", "127.0.0.1")
    app_port: int = int(os.getenv("APP_PORT", "8000"))
    database_url: str = os.getenv("DATABASE_URL", os.getenv("DATABASE_PATH", "sqlite:///./data/runtime/football_agents.db"))
    database_path: Path = _database_path_from_url(database_url)
    enable_real_sync: bool = _bool("ENABLE_REAL_SYNC", False)
    enable_stacking_model: bool = _bool("ENABLE_STACKING_MODEL", False)
    enable_auto_betting: bool = _bool("ENABLE_AUTO_BETTING", False)
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    snapshot_stale_minutes: int = int(os.getenv("SNAPSHOT_STALE_MINUTES", "30"))
    pre_match_close_minutes: int = int(os.getenv("PRE_MATCH_CLOSE_MINUTES", "5"))
    official_sp_refresh_minutes: int = int(os.getenv("OFFICIAL_SP_REFRESH_MINUTES", "15"))
    external_odds_refresh_minutes: int = int(os.getenv("EXTERNAL_ODDS_REFRESH_MINUTES", "15"))
    live_fast_refresh_minutes: int = int(os.getenv("LIVE_FAST_REFRESH_MINUTES", "5"))
    bankroll: float = _float("BANKROLL", 10_000.0)
    min_ev: float = _float("MIN_EV", 0.05)
    max_single_stake: float = _float("MAX_SINGLE_STAKE", 0.01)
    max_daily_exposure: float = _float("MAX_DAILY_EXPOSURE", 0.03)
    max_weekly_exposure: float = _float("MAX_WEEKLY_EXPOSURE", 0.08)
    profit_daily_budget: float = _float("PROFIT_DAILY_BUDGET", 100.0)
    odds_max_age_minutes: int = int(os.getenv("ODDS_MAX_AGE_MINUTES", "10"))
    official_source_url: str = os.getenv("OFFICIAL_SOURCE_URL", "https://m.sporttery.cn/mjc/zqsj/?tab=schedule")
    official_browser_path: str = os.getenv(
        "OFFICIAL_BROWSER_PATH", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    )
    official_fetch_timeout_seconds: int = int(os.getenv("OFFICIAL_FETCH_TIMEOUT_SECONDS", "25"))
    official_min_sync_interval_seconds: int = int(os.getenv("OFFICIAL_MIN_SYNC_INTERVAL_SECONDS", "60"))
    official_auto_sync_interval_seconds: int = int(os.getenv("OFFICIAL_AUTO_SYNC_INTERVAL_SECONDS", "3600"))
    background_agent_interval_seconds: int = int(os.getenv(
        "BACKGROUND_AGENT_INTERVAL_SECONDS", os.getenv("OFFICIAL_AUTO_SYNC_INTERVAL_SECONDS", "3600")
    ))
    auto_backtest_csv_path: str = os.getenv(
        "AUTO_BACKTEST_CSV_PATH", "football_agents/sample_data/historical_matches.csv"
    )
    profit_scorer_artifact_path: str = os.getenv(
        "PROFIT_SCORER_ARTIFACT_PATH",
        "reports/market_anchored_sp1_home_avg_close_shadow_scorer_v1/scorer.json",
    )
    profit_scorer_official_pool_report_path: str = os.getenv(
        "PROFIT_SCORER_OFFICIAL_POOL_REPORT_PATH",
        "reports/profit_scorer_official_pool/summary.json",
    )
    profit_scorer_official_sp_validation_report_path: str = os.getenv(
        "PROFIT_SCORER_OFFICIAL_SP_VALIDATION_REPORT_PATH",
        "reports/profit_scorer_official_sp_validation/summary.json",
    )
    odds_api_key: str = os.getenv("THE_ODDS_API_KEY", "")
    odds_api_base_url: str = os.getenv("ODDS_API_BASE_URL", "https://api.the-odds-api.com/v4")
    odds_api_sport_keys: tuple[str, ...] = tuple(filter(None, os.getenv(
        "ODDS_API_SPORT_KEYS", "soccer_fifa_world_cup,soccer_finland_veikkausliiga"
    ).split(",")))
    international_odds_sport_keys: tuple[str, ...] = tuple(filter(None, os.getenv(
        "INTERNATIONAL_ODDS_SPORT_KEYS",
        "soccer_fifa_world_cup,soccer_uefa_european_championship,soccer_conmebol_copa_america,"
        "soccer_uefa_nations_league,soccer_fifa_world_cup_qualifiers",
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
    agent_match_limit: int = int(os.getenv("AGENT_MATCH_LIMIT", "20"))
    historical_data_base_url: str = os.getenv(
        "HISTORICAL_DATA_BASE_URL", "https://www.football-data.co.uk/mmz4281"
    ).rstrip("/")
    historical_data_years_back: int = int(os.getenv("HISTORICAL_DATA_YEARS_BACK", "3"))
    historical_data_divisions: tuple[str, ...] = tuple(filter(None, os.getenv(
        "HISTORICAL_DATA_DIVISIONS", "E0,E1,E2,E3,SC0,D1,D2,I1,I2,SP1,SP2,F1,F2,N1,B1,P1,T1,G1"
    ).split(",")))
    historical_data_worldwide_divisions: tuple[str, ...] = tuple(filter(None, os.getenv(
        "HISTORICAL_DATA_WORLDWIDE_DIVISIONS",
        "ARG,AUT,BRA,CHN,DNK,FIN,IRL,JPN,MEX,NOR,POL,ROU,RUS,SWE,SWZ,USA"
    ).split(",")))
    historical_data_timeout_seconds: int = int(os.getenv("HISTORICAL_DATA_TIMEOUT_SECONDS", "12"))
    historical_data_workers: int = int(os.getenv("HISTORICAL_DATA_WORKERS", "8"))
    historical_data_retries: int = int(os.getenv("HISTORICAL_DATA_RETRIES", "3"))
    historical_data_retry_backoff_seconds: float = float(os.getenv("HISTORICAL_DATA_RETRY_BACKOFF_SECONDS", "1"))
    enable_prospective_research: bool = _bool("ENABLE_PROSPECTIVE_RESEARCH", True)
    prospective_research_study_name: str = os.getenv(
        "PROSPECTIVE_RESEARCH_STUDY_NAME", "frozen-ensemble-market-anchor-v2-t60-confirmation-2026"
    )
    prospective_research_min_settled: int = int(os.getenv("PROSPECTIVE_RESEARCH_MIN_SETTLED", "5000"))
    prospective_research_min_days: int = int(os.getenv("PROSPECTIVE_RESEARCH_MIN_DAYS", "365"))
    international_data_url: str = os.getenv(
        "INTERNATIONAL_DATA_URL",
        "https://raw.githubusercontent.com/martj42/international_results/master/results.csv",
    )
    international_data_timeout_seconds: int = int(os.getenv("INTERNATIONAL_DATA_TIMEOUT_SECONDS", "30"))
    international_football_data_world_cup_url: str = os.getenv(
        "INTERNATIONAL_FOOTBALL_DATA_WORLD_CUP_URL",
        "https://www.football-data.co.uk/WorldCup2026.xlsx",
    )


settings = Settings()

