from __future__ import annotations

import math

import numpy as np
import pandas as pd

from football_agents.models.poisson import PoissonModel


OUTCOMES = ("home", "draw", "away")


def _softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - logits.max(axis=1, keepdims=True)
    values = np.exp(shifted)
    return values / values.sum(axis=1, keepdims=True)


class TimeDecayDixonColes:
    """Time-weighted attack/defence Poisson model with Dixon-Coles score correction."""

    def __init__(self, half_life_days: float = 365.0, rho: float = -0.08, ridge: float = 0.01) -> None:
        self.half_life_days = half_life_days
        self.rho = rho
        self.ridge = ridge
        self.teams: dict[str, int] = {}
        self.attack = np.zeros(0)
        self.defence = np.zeros(0)
        self.intercept = math.log(1.2)
        self.home_advantage = math.log(1.15)

    def fit(self, frame: pd.DataFrame, cutoff: pd.Timestamp | None = None, *, iterations: int = 350,
            learning_rate: float = 0.08) -> "TimeDecayDixonColes":
        required = {"match_date", "home_team", "away_team", "home_goals", "away_goals"}
        if not required.issubset(frame.columns) or frame.empty:
            raise ValueError("Dixon-Coles training data is empty or missing required columns")
        data = frame.copy()
        cutoff = pd.Timestamp(cutoff or data["match_date"].max() + pd.Timedelta(days=1))
        data = data[pd.to_datetime(data["match_date"]) < cutoff]
        if data.empty:
            raise ValueError("No training match occurs before the cutoff")
        names = sorted(set(data["home_team"].astype(str)) | set(data["away_team"].astype(str)))
        self.teams = {team: index for index, team in enumerate(names)}
        home = data["home_team"].map(self.teams).to_numpy(int)
        away = data["away_team"].map(self.teams).to_numpy(int)
        home_goals = data["home_goals"].to_numpy(float)
        away_goals = data["away_goals"].to_numpy(float)
        age = (cutoff - pd.to_datetime(data["match_date"])).dt.total_seconds().to_numpy() / 86400
        weights = np.exp(-math.log(2) * np.maximum(age, 0) / self.half_life_days)
        weights /= weights.sum()
        self.attack = np.zeros(len(names))
        self.defence = np.zeros(len(names))
        mean_goals = max(0.2, float(np.average(np.r_[home_goals, away_goals], weights=np.r_[weights, weights])))
        self.intercept = math.log(mean_goals)
        self.home_advantage = math.log(max(0.7, float(np.average(home_goals, weights=weights)) /
                                           max(float(np.average(away_goals, weights=weights)), 0.2)))
        for iteration in range(iterations):
            log_home = np.clip(self.intercept + self.home_advantage + self.attack[home] + self.defence[away], -2.5, 2.0)
            log_away = np.clip(self.intercept + self.attack[away] + self.defence[home], -2.5, 2.0)
            error_home = weights * (home_goals - np.exp(log_home))
            error_away = weights * (away_goals - np.exp(log_away))
            grad_attack = np.zeros(len(names))
            grad_defence = np.zeros(len(names))
            np.add.at(grad_attack, home, error_home)
            np.add.at(grad_attack, away, error_away)
            np.add.at(grad_defence, away, error_home)
            np.add.at(grad_defence, home, error_away)
            rate = learning_rate / math.sqrt(1 + iteration / 100)
            team_scale = max(1.0, len(names) / 2)
            self.attack += rate * team_scale * (grad_attack - self.ridge * self.attack / len(names))
            self.defence += rate * team_scale * (grad_defence - self.ridge * self.defence / len(names))
            self.intercept += rate * float((error_home + error_away).sum())
            self.home_advantage += rate * float(error_home.sum())
            self.attack -= self.attack.mean()
            self.defence -= self.defence.mean()
        return self

    def expected_goals(self, home_team: str, away_team: str) -> tuple[float, float]:
        home = self.teams.get(str(home_team))
        away = self.teams.get(str(away_team))
        home_attack = self.attack[home] if home is not None else 0.0
        home_defence = self.defence[home] if home is not None else 0.0
        away_attack = self.attack[away] if away is not None else 0.0
        away_defence = self.defence[away] if away is not None else 0.0
        return (
            float(np.exp(np.clip(self.intercept + self.home_advantage + home_attack + away_defence, -2.5, 2.0))),
            float(np.exp(np.clip(self.intercept + away_attack + home_defence, -2.5, 2.0))),
        )

    def predict(self, home_team: str, away_team: str) -> dict[str, float]:
        home_rate, away_rate = self.expected_goals(home_team, away_team)
        return PoissonModel(rho=self.rho).predict(home_rate, away_rate)


class HierarchicalLeagueDixonColes:
    """Joint team model with shrunk league goal-level and home-advantage effects."""

    def __init__(self, half_life_days: float = 365.0, rho: float = -0.08,
                 team_ridge: float = 0.02, league_ridge: float = 0.20) -> None:
        self.half_life_days = half_life_days
        self.rho = rho
        self.team_ridge = team_ridge
        self.league_ridge = league_ridge
        self.teams: dict[str, int] = {}
        self.leagues: dict[str, int] = {}
        self.attack = np.zeros(0)
        self.defence = np.zeros(0)
        self.league_level = np.zeros(0)
        self.league_home = np.zeros(0)
        self.intercept = math.log(1.2)
        self.home_advantage = math.log(1.15)

    @staticmethod
    def _team_key(league: str, team: str) -> str:
        return f"{league}::{team}"

    def fit(self, frame: pd.DataFrame, cutoff: pd.Timestamp | None = None, *, iterations: int = 350,
            learning_rate: float = 0.08) -> "HierarchicalLeagueDixonColes":
        data = frame.copy()
        cutoff = pd.Timestamp(cutoff or data["match_date"].max() + pd.Timedelta(days=1))
        data = data[pd.to_datetime(data["match_date"]) < cutoff]
        if data.empty:
            raise ValueError("No hierarchical Dixon-Coles training match occurs before the cutoff")
        league_names = sorted(data["league"].astype(str).unique())
        self.leagues = {name: index for index, name in enumerate(league_names)}
        keys = sorted(set(self._team_key(str(row.league), str(row.home_team)) for row in data.itertuples()) |
                      set(self._team_key(str(row.league), str(row.away_team)) for row in data.itertuples()))
        self.teams = {key: index for index, key in enumerate(keys)}
        league = data["league"].astype(str).map(self.leagues).to_numpy(int)
        home = np.array([self.teams[self._team_key(str(row.league), str(row.home_team))]
                         for row in data.itertuples()])
        away = np.array([self.teams[self._team_key(str(row.league), str(row.away_team))]
                         for row in data.itertuples()])
        home_goals = data["home_goals"].to_numpy(float)
        away_goals = data["away_goals"].to_numpy(float)
        age = (cutoff - pd.to_datetime(data["match_date"])).dt.total_seconds().to_numpy() / 86400
        weights = np.exp(-math.log(2) * np.maximum(age, 0) / self.half_life_days)
        weights /= weights.sum()
        self.attack, self.defence = np.zeros(len(keys)), np.zeros(len(keys))
        self.league_level, self.league_home = np.zeros(len(league_names)), np.zeros(len(league_names))
        mean_goals = max(0.2, float(np.average(np.r_[home_goals, away_goals], weights=np.r_[weights, weights])))
        self.intercept = math.log(mean_goals)
        self.home_advantage = math.log(max(0.7, float(np.average(home_goals, weights=weights)) /
                                           max(float(np.average(away_goals, weights=weights)), 0.2)))
        for iteration in range(iterations):
            log_home = np.clip(self.intercept + self.home_advantage + self.league_level[league] +
                               self.league_home[league] + self.attack[home] + self.defence[away], -2.5, 2.0)
            log_away = np.clip(self.intercept + self.league_level[league] + self.attack[away] +
                               self.defence[home], -2.5, 2.0)
            error_home = weights * (home_goals - np.exp(log_home))
            error_away = weights * (away_goals - np.exp(log_away))
            grad_attack, grad_defence = np.zeros(len(keys)), np.zeros(len(keys))
            grad_level, grad_home = np.zeros(len(league_names)), np.zeros(len(league_names))
            np.add.at(grad_attack, home, error_home)
            np.add.at(grad_attack, away, error_away)
            np.add.at(grad_defence, away, error_home)
            np.add.at(grad_defence, home, error_away)
            np.add.at(grad_level, league, error_home + error_away)
            np.add.at(grad_home, league, error_home)
            rate = learning_rate / math.sqrt(1 + iteration / 100)
            team_scale = max(1.0, len(keys) / 2)
            league_scale = max(1.0, len(league_names) / 2)
            self.attack += rate * team_scale * (grad_attack - self.team_ridge * self.attack / len(keys))
            self.defence += rate * team_scale * (grad_defence - self.team_ridge * self.defence / len(keys))
            self.league_level += rate * league_scale * (
                grad_level - self.league_ridge * self.league_level / len(league_names)
            )
            self.league_home += rate * league_scale * (
                grad_home - self.league_ridge * self.league_home / len(league_names)
            )
            self.intercept += rate * float((error_home + error_away).sum())
            self.home_advantage += rate * float(error_home.sum())
            self.attack -= self.attack.mean()
            self.defence -= self.defence.mean()
            self.league_level -= self.league_level.mean()
            self.league_home -= self.league_home.mean()
        return self

    def expected_goals(self, home_team: str, away_team: str, league: str) -> tuple[float, float]:
        league_name = str(league)
        league_index = self.leagues.get(league_name)
        home = self.teams.get(self._team_key(league_name, str(home_team)))
        away = self.teams.get(self._team_key(league_name, str(away_team)))
        level = self.league_level[league_index] if league_index is not None else 0.0
        league_home = self.league_home[league_index] if league_index is not None else 0.0
        return (
            float(np.exp(np.clip(self.intercept + self.home_advantage + level + league_home +
                                 (self.attack[home] if home is not None else 0.0) +
                                 (self.defence[away] if away is not None else 0.0), -2.5, 2.0))),
            float(np.exp(np.clip(self.intercept + level +
                                 (self.attack[away] if away is not None else 0.0) +
                                 (self.defence[home] if home is not None else 0.0), -2.5, 2.0))),
        )

    def predict(self, home_team: str, away_team: str, league: str) -> dict[str, float]:
        home_rate, away_rate = self.expected_goals(home_team, away_team, league)
        return PoissonModel(rho=self.rho).predict(home_rate, away_rate)


class MarketAnchoredResidualModel:
    """Multinomial residual model anchored to market log probabilities."""

    def __init__(self, ridge: float = 2.0, league_shrinkage: float = 200.0) -> None:
        self.ridge = ridge
        self.league_shrinkage = league_shrinkage
        self.coefficients = np.zeros((0, 3))
        self.league_offsets: dict[str, np.ndarray] = {}
        self.temperature = 1.0
        self.feature_mean = np.zeros(0)
        self.feature_scale = np.ones(0)
        self.uses_extra_features = False

    def design(self, market: np.ndarray, football: np.ndarray, extra_features: np.ndarray | None = None,
               *, fit_features: bool = False) -> np.ndarray:
        market = np.clip(np.asarray(market, float), 1e-8, 1)
        football = np.clip(np.asarray(football, float), 1e-8, 1)
        columns = [np.ones(len(market)), np.log(football / market)]
        if extra_features is not None:
            extra = np.asarray(extra_features, float)
            if fit_features:
                self.feature_mean = extra.mean(axis=0)
                self.feature_scale = extra.std(axis=0)
                self.feature_scale[self.feature_scale < 1e-8] = 1.0
            extra = (extra - self.feature_mean) / self.feature_scale
            columns.append(extra)
        return np.column_stack(columns)

    def fit(self, market: np.ndarray, football: np.ndarray, outcomes: np.ndarray, leagues: np.ndarray,
            extra_features: np.ndarray | None = None,
            *, iterations: int = 1200, learning_rate: float = 0.08) -> "MarketAnchoredResidualModel":
        self.uses_extra_features = extra_features is not None
        x = self.design(market, football, extra_features, fit_features=True)
        market_logits = np.log(np.clip(market, 1e-8, 1))
        y = np.column_stack([np.asarray(outcomes) == outcome for outcome in OUTCOMES]).astype(float)
        self.coefficients = np.zeros((x.shape[1], 3))
        for iteration in range(iterations):
            probability = _softmax(market_logits + x @ self.coefficients)
            gradient = x.T @ (probability - y) / len(x) + self.ridge * self.coefficients / len(x)
            gradient[0] -= self.ridge * self.coefficients[0] / len(x)
            self.coefficients -= learning_rate / math.sqrt(1 + iteration / 200) * gradient
            self.coefficients -= self.coefficients.mean(axis=1, keepdims=True)
        global_probability = _softmax(market_logits + x @ self.coefficients)
        league_values = np.asarray(leagues).astype(str)
        for league in np.unique(league_values):
            mask = league_values == league
            residual = (y[mask] - global_probability[mask]).mean(axis=0)
            reliability = mask.sum() / (mask.sum() + self.league_shrinkage)
            offset = reliability * residual / np.clip(global_probability[mask].mean(axis=0), 0.05, 1)
            self.league_offsets[league] = offset - offset.mean()
        return self

    def calibrate(self, market: np.ndarray, football: np.ndarray, outcomes: np.ndarray,
                  leagues: np.ndarray, extra_features: np.ndarray | None = None) -> "MarketAnchoredResidualModel":
        logits = self._logits(market, football, leagues, extra_features)
        labels = np.column_stack([np.asarray(outcomes) == outcome for outcome in OUTCOMES]).astype(float)
        candidates = np.linspace(0.6, 1.8, 121)
        losses = [-np.mean(np.sum(labels * np.log(np.clip(_softmax(logits / value), 1e-12, 1)), axis=1))
                  for value in candidates]
        best = int(np.argmin(losses))
        unit = int(np.argmin(np.abs(candidates - 1.0)))
        # Avoid enabling a calibration layer for a negligible in-sample gain.
        self.temperature = float(candidates[best] if losses[unit] - losses[best] >= 1e-4 else 1.0)
        return self

    def _logits(self, market: np.ndarray, football: np.ndarray, leagues: np.ndarray,
                extra_features: np.ndarray | None = None) -> np.ndarray:
        logits = np.log(np.clip(market, 1e-8, 1)) + self.design(market, football, extra_features) @ self.coefficients
        for index, league in enumerate(np.asarray(leagues).astype(str)):
            logits[index] += self.league_offsets.get(league, 0.0)
        return logits

    def predict(self, market: np.ndarray, football: np.ndarray, leagues: np.ndarray,
                extra_features: np.ndarray | None = None) -> np.ndarray:
        return _softmax(self._logits(market, football, leagues, extra_features) / self.temperature)
