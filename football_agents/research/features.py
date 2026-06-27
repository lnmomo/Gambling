from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd


FEATURE_COLUMNS = (
    "home_goal_balance", "away_goal_balance",
    "home_shot_balance", "away_shot_balance",
    "home_sot_balance", "away_sot_balance",
    "home_venue_goal_balance", "away_venue_goal_balance",
    "form_difference", "rest_difference", "sample_reliability",
)


@dataclass
class _TeamState:
    weight: float = 0.0
    values: dict[str, float] = field(default_factory=dict)
    matches: int = 0
    last_date: pd.Timestamp | None = None

    def snapshot(self, date: pd.Timestamp, half_life_days: float) -> dict[str, float]:
        if self.last_date is None:
            return {"goal_balance": 0.0, "shot_balance": 0.0, "sot_balance": 0.0,
                    "points": 1.35, "rest": 14.0, "matches": 0.0}
        decay = math.exp(-math.log(2) * max(0, (date - self.last_date).days) / half_life_days)
        weight = self.weight * decay
        denominator = max(weight, 1e-9)
        return {
            "goal_balance": self.values.get("goal_balance", 0.0) * decay / denominator,
            "shot_balance": self.values.get("shot_balance", 0.0) * decay / denominator,
            "sot_balance": self.values.get("sot_balance", 0.0) * decay / denominator,
            "points": self.values.get("points", 0.0) * decay / denominator,
            "rest": float(np.clip((date - self.last_date).days, 2, 30)),
            "matches": float(self.matches),
        }

    def update(self, date: pd.Timestamp, half_life_days: float, values: dict[str, float]) -> None:
        decay = 1.0 if self.last_date is None else math.exp(
            -math.log(2) * max(0, (date - self.last_date).days) / half_life_days
        )
        self.weight = self.weight * decay + 1.0
        for key, value in values.items():
            self.values[key] = self.values.get(key, 0.0) * decay + float(value)
        self.matches += 1
        self.last_date = date


def _number(value: object, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return number if math.isfinite(number) else fallback


def build_leakage_free_rolling_features(frame: pd.DataFrame, half_life_days: float = 180.0) -> pd.DataFrame:
    """Build pre-match features; all matches on a date are scored before state updates."""
    data = frame.sort_values(["match_date", "league", "home_team", "away_team"]).copy()
    general: dict[tuple[str, str], _TeamState] = {}
    venue: dict[tuple[str, str, str], _TeamState] = {}
    feature_rows: list[dict[str, float]] = []
    output_indices: list[int] = []
    for date, day in data.groupby("match_date", sort=True):
        pending: list[tuple[pd.Series, _TeamState, _TeamState, _TeamState, _TeamState]] = []
        for index, row in day.iterrows():
            league, home, away = str(row["league"]), str(row["home_team"]), str(row["away_team"])
            home_state = general.setdefault((league, home), _TeamState())
            away_state = general.setdefault((league, away), _TeamState())
            home_venue = venue.setdefault((league, home, "home"), _TeamState())
            away_venue = venue.setdefault((league, away, "away"), _TeamState())
            hs = home_state.snapshot(date, half_life_days)
            aws = away_state.snapshot(date, half_life_days)
            hvs = home_venue.snapshot(date, half_life_days)
            avs = away_venue.snapshot(date, half_life_days)
            reliability = min(hs["matches"], aws["matches"]) / (min(hs["matches"], aws["matches"]) + 10.0)
            feature_rows.append({
                "home_goal_balance": hs["goal_balance"], "away_goal_balance": aws["goal_balance"],
                "home_shot_balance": hs["shot_balance"], "away_shot_balance": aws["shot_balance"],
                "home_sot_balance": hs["sot_balance"], "away_sot_balance": aws["sot_balance"],
                "home_venue_goal_balance": hvs["goal_balance"],
                "away_venue_goal_balance": avs["goal_balance"],
                "form_difference": hs["points"] - aws["points"],
                "rest_difference": hs["rest"] - aws["rest"],
                "sample_reliability": reliability,
            })
            output_indices.append(index)
            pending.append((row, home_state, away_state, home_venue, away_venue))
        for row, home_state, away_state, home_venue, away_venue in pending:
            hg, ag = float(row["home_goals"]), float(row["away_goals"])
            hs = _number(row.get("home_shots"), 3.0 * hg + 7.0)
            aws = _number(row.get("away_shots"), 3.0 * ag + 7.0)
            hst = _number(row.get("home_shots_on_target"), 1.5 * hg + 2.0)
            ast = _number(row.get("away_shots_on_target"), 1.5 * ag + 2.0)
            home_values = {"goal_balance": hg - ag, "shot_balance": hs - aws,
                           "sot_balance": hst - ast, "points": 3 if hg > ag else 1 if hg == ag else 0}
            away_values = {"goal_balance": ag - hg, "shot_balance": aws - hs,
                           "sot_balance": ast - hst, "points": 3 if ag > hg else 1 if hg == ag else 0}
            home_state.update(date, half_life_days, home_values)
            away_state.update(date, half_life_days, away_values)
            home_venue.update(date, half_life_days, home_values)
            away_venue.update(date, half_life_days, away_values)
    features = pd.DataFrame(feature_rows, index=output_indices)
    for column in FEATURE_COLUMNS:
        data[column] = features[column]
    return data.sort_values(["match_date", "league", "home_team", "away_team"]).reset_index(drop=True)
