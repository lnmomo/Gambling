from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


Option = Literal["home", "draw", "away"]


class Odds(BaseModel):
    home: float = Field(gt=1)
    draw: float = Field(gt=1)
    away: float = Field(gt=1)


class MatchCreate(BaseModel):
    official_match_id: str
    league: str
    home_team: str
    away_team: str
    kickoff_time: datetime
    status: Literal["scheduled", "closed", "finished", "cancelled"] = "scheduled"


class OddsCreate(BaseModel):
    odds: Odds
    source: str
    fetched_at: datetime = Field(default_factory=datetime.utcnow)
    source_confidence: float = Field(default=1.0, ge=0, le=1)


class FeatureCreate(BaseModel):
    home_rating: float
    away_rating: float
    lambda_home: float = Field(gt=0)
    lambda_away: float = Field(gt=0)
    source_confidence: float = Field(default=0.9, ge=0, le=1)
    lineup_confirmed: bool = False
    backtest_roi: float | None = None
    daily_exposure_fraction: float = Field(default=0, ge=0)
    weekly_exposure_fraction: float = Field(default=0, ge=0)
    consecutive_losses: int = Field(default=0, ge=0)


class EvaluateRequest(BaseModel):
    official_odds: Odds | None = None
    market_odds: Odds | None = None
    features: FeatureCreate | None = None
    official_source: str = "manual"
    market_source: str = "market_consensus"
    fetched_at: datetime | None = None


class ResultCreate(BaseModel):
    home_score: int = Field(ge=0)
    away_score: int = Field(ge=0)
    settled_at: datetime | None = None


class MatchMetadataCreate(BaseModel):
    venue: str | None = None
    city: str | None = None
    country: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    source: str = "manual"


class SettingsUpdate(BaseModel):
    values: dict[str, Any]


class HistoricalRow(BaseModel):
    date: datetime
    league: str
    home_team: str
    away_team: str
    home_score: int = Field(ge=0)
    away_score: int = Field(ge=0)
    sp_home: float = Field(gt=1)
    sp_draw: float = Field(gt=1)
    sp_away: float = Field(gt=1)
    market_home: float | None = Field(default=None, gt=1)
    market_draw: float | None = Field(default=None, gt=1)
    market_away: float | None = Field(default=None, gt=1)
    lambda_home: float | None = Field(default=None, gt=0)
    lambda_away: float | None = Field(default=None, gt=0)


class BacktestRequest(BaseModel):
    name: str = "API backtest"
    rows: list[HistoricalRow]
    bankroll: float = Field(default=10_000, gt=0)
    min_ev: float = Field(default=0.05, ge=0)

    @model_validator(mode="after")
    def enough_rows(self) -> "BacktestRequest":
        if not self.rows:
            raise ValueError("rows must not be empty")
        return self

