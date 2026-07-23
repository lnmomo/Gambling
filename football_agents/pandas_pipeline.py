from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

import numpy as np
import pandas as pd


REQUIRED_GROUPS = {
    "played_at": ("date", "played_at", "playedAt", "Date"),
    "league": ("league", "League", "Div"),
    "home_team": ("home_team", "homeTeam", "HomeTeam", "Home"),
    "away_team": ("away_team", "awayTeam", "AwayTeam", "Away"),
    "home_goals": ("home_score", "home_goals", "homeGoals", "FTHG", "HG"),
    "away_goals": ("away_score", "away_goals", "awayGoals", "FTAG", "AG"),
}


@dataclass(frozen=True)
class PandasImportReport:
    rows: int
    dropped: int
    columns: list[str]


def read_csv_text(text: str) -> pd.DataFrame:
    frame = pd.read_csv(io.StringIO(text.lstrip("\ufeff")))
    if frame.empty:
        raise ValueError("历史 CSV 不包含数据")
    return frame


def normalize_historical_matches(frame: pd.DataFrame, *, source: str = "csv",
                                 division_names: dict[str, str] | None = None,
                                 league_override: str | None = None) -> tuple[list[dict[str, Any]], PandasImportReport]:
    columns = set(frame.columns)
    missing = [
        canonical for canonical, aliases in REQUIRED_GROUPS.items()
        if canonical != "league" or not league_override
        if not columns.intersection(aliases)
    ]
    if missing:
        raise ValueError(f"历史 CSV 缺少字段: {', '.join(missing)}")

    normalized = pd.DataFrame()
    for canonical, aliases in REQUIRED_GROUPS.items():
        source_column = next((column for column in aliases if column in frame.columns), None)
        if source_column:
            normalized[canonical] = frame[source_column]
        elif canonical == "league" and league_override:
            normalized[canonical] = league_override

    normalized["league"] = normalized["league"].astype("string").str.strip()
    if division_names:
        normalized["league"] = normalized["league"].map(lambda value: division_names.get(str(value), str(value)))
    normalized["home_team"] = normalized["home_team"].astype("string").str.strip()
    normalized["away_team"] = normalized["away_team"].astype("string").str.strip()
    normalized["played_at"] = pd.to_datetime(normalized["played_at"], dayfirst=True, errors="coerce").dt.date.astype("string")
    normalized["home_goals"] = pd.to_numeric(normalized["home_goals"], errors="coerce")
    normalized["away_goals"] = pd.to_numeric(normalized["away_goals"], errors="coerce")
    normalized["match_type"] = frame["match_type"] if "match_type" in frame.columns else frame.get("matchType", "LEAGUE")
    normalized["match_type"] = normalized["match_type"].fillna("LEAGUE").astype("string").str.upper()
    normalized["source"] = source

    valid_mask = (
        normalized["league"].notna()
        & normalized["home_team"].notna()
        & normalized["away_team"].notna()
        & (normalized["home_team"] != normalized["away_team"])
        & normalized["played_at"].notna()
        & normalized["home_goals"].notna()
        & normalized["away_goals"].notna()
        & (normalized["home_goals"] >= 0)
        & (normalized["away_goals"] >= 0)
        & normalized["match_type"].isin(["LEAGUE", "CUP", "FRIENDLY"])
    )
    cleaned = normalized.loc[valid_mask].copy()
    cleaned["home_goals"] = cleaned["home_goals"].astype(int)
    cleaned["away_goals"] = cleaned["away_goals"].astype(int)
    cleaned = cleaned.drop_duplicates(["league", "home_team", "away_team", "played_at"], keep="last")
    report = PandasImportReport(rows=len(cleaned), dropped=int(len(normalized) - len(cleaned)), columns=list(frame.columns))
    return cleaned[["league", "home_team", "away_team", "home_goals", "away_goals", "played_at", "match_type"]].to_dict("records"), report


def parse_cutoff(value: str) -> pd.Timestamp:
    parsed = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"invalid cutoff time: {value}")
    return parsed


def team_weighted_goal_stats(rows: Iterable[dict[str, Any]], team: str, cutoff_time: str | datetime,
                             half_life_days: int = 90) -> dict[str, float]:
    frame = pd.DataFrame(list(rows))
    if frame.empty:
        return {"goals_for": 0.0, "goals_against": 0.0, "effective_matches": 0.0, "points_per_match": 0.0,
                "win_rate": 0.0, "goal_difference": 0.0}

    kickoff = parse_cutoff(cutoff_time.isoformat() if isinstance(cutoff_time, datetime) else cutoff_time)
    frame["played_at_ts"] = pd.to_datetime(frame["played_at"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["played_at_ts"]).copy()
    frame = frame[frame["played_at_ts"] < kickoff]
    if frame.empty:
        return {"goals_for": 0.0, "goals_against": 0.0, "effective_matches": 0.0, "points_per_match": 0.0,
                "win_rate": 0.0, "goal_difference": 0.0}

    is_home = frame["home_team"] == team
    goals_for = np.where(is_home, frame["home_goals"], frame["away_goals"]).astype(float)
    goals_against = np.where(is_home, frame["away_goals"], frame["home_goals"]).astype(float)
    points = np.where(goals_for > goals_against, 3.0, np.where(goals_for == goals_against, 1.0, 0.0))
    wins = (goals_for > goals_against).astype(float)
    days = ((kickoff - frame["played_at_ts"]).dt.total_seconds() / 86400).clip(lower=0)
    weights = np.exp(-np.log(2) * days / max(1, half_life_days))
    total_weight = float(weights.sum())
    if total_weight <= 0:
        return {"goals_for": 0.0, "goals_against": 0.0, "effective_matches": 0.0, "points_per_match": 0.0,
                "win_rate": 0.0, "goal_difference": 0.0}
    weighted_for = float(np.dot(goals_for, weights) / total_weight)
    weighted_against = float(np.dot(goals_against, weights) / total_weight)
    return {
        "goals_for": weighted_for,
        "goals_against": weighted_against,
        "effective_matches": total_weight,
        "points_per_match": float(np.dot(points, weights) / total_weight),
        "win_rate": float(np.dot(wins, weights) / total_weight),
        "goal_difference": weighted_for - weighted_against,
    }
