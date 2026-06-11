from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


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


settings = Settings()

