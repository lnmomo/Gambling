from __future__ import annotations

import argparse
import itertools
import json
import math
import sys
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from football_agents.models import EloModel, EnsembleModel, PoissonModel
from football_agents.models.ensemble import market_probabilities
from football_agents.real_ev import anchor_real_probability
from monthly_shadow_backtest import OUTCOMES, actual_outcome, load_matches

DEFAULT_SEASONS = ("2122", "2223", "2324", "2425", "2526")


@dataclass(frozen=True)
class PortfolioConfig:
    min_lower_ev: float
    max_odds: float
    kelly_fraction: float
    min_stake: float = 1.0
    max_stake: float = 20.0
    daily_limit: float = 100.0
    league_limit: float = 40.0
    bucket_key: tuple[str, ...] = ()
    allowed_buckets: tuple[tuple[str, ...], ...] = ()
    min_odds: float = 1.5
    allowed_outcomes: tuple[str, ...] = OUTCOMES
    stop_loss: float | None = None
    quality_gate: dict | None = None
    candidate_limit_per_day: int | None = None
    ranking_key: str = "lower_ev"


EXPERIMENT_PROFILES = {
    "strict": {
        "validation_min_bets": 20,
        "min_positive_validation_months": 1,
        "uncertainty_scale": 1.0,
        "ev_thresholds": (0.00, 0.01, 0.02, 0.03),
        "max_odds": (4.0, 5.0, 6.0),
        "kelly_fractions": (0.10, 0.25),
    },
    "relaxed": {
        "validation_min_bets": 15,
        "min_positive_validation_months": 2,
        "uncertainty_scale": 0.75,
        "ev_thresholds": (-0.01, 0.00, 0.01, 0.02),
        "max_odds": (5.0, 6.0, 7.0),
        "kelly_fractions": (0.10, 0.25),
    },
    "bucketed": {
        "validation_min_bets": 6,
        "min_positive_validation_months": 1,
        "uncertainty_scale": 0.85,
        "ev_thresholds": (0.00, 0.01),
        "max_odds": (3.5, 4.0),
        "kelly_fractions": (0.05, 0.10),
        "bucket_keys": (("outcome", "odds_bucket"), ("league", "outcome")),
        "min_bucket_samples": (3,),
        "min_bucket_roi": (0.10,),
    },
    "stability": {
        "validation_min_bets": 25,
        "min_positive_validation_months": 2,
        "min_validation_roi": 0.08,
        "min_validation_profit": 3.0,
        "max_drawdown_profit_ratio": 1.25,
        "uncertainty_scale": 0.75,
        "ev_thresholds": (0.00, 0.01, 0.02),
        "max_odds": (5.0, 6.0),
        "kelly_fractions": (0.10, 0.25),
    },
    "guarded": {
        "validation_min_bets": 20,
        "min_positive_validation_months": 2,
        "min_validation_roi": 0.10,
        "min_validation_profit": 5.0,
        "max_drawdown_profit_ratio": 0.90,
        "uncertainty_scale": 1.0,
        "ev_thresholds": (0.01, 0.02, 0.03),
        "max_odds": (4.0, 5.0),
        "kelly_fractions": (0.10,),
    },
    "draw_value": {
        "validation_min_bets": 15,
        "min_positive_validation_months": 2,
        "min_validation_roi": 0.05,
        "min_validation_profit": 2.0,
        "max_drawdown_profit_ratio": 1.50,
        "uncertainty_scale": 0.85,
        "ev_thresholds": (0.00, 0.01, 0.02),
        "min_odds": (2.2, 2.8),
        "max_odds": (3.5, 4.0),
        "kelly_fractions": (0.05, 0.10),
        "allowed_outcomes": (("draw",),),
    },
    "draw_value_stop": {
        "validation_min_bets": 15,
        "min_positive_validation_months": 2,
        "min_validation_roi": 0.05,
        "min_validation_profit": 2.0,
        "max_drawdown_profit_ratio": 1.50,
        "uncertainty_scale": 0.85,
        "ev_thresholds": (0.00, 0.01, 0.02),
        "min_odds": (2.2, 2.8),
        "max_odds": (3.5, 4.0),
        "kelly_fractions": (0.05, 0.10),
        "allowed_outcomes": (("draw",),),
        "stop_losses": (3.0, 5.0),
    },
    "draw_regime": {
        "validation_min_bets": 12,
        "min_positive_validation_months": 2,
        "min_validation_roi": 0.05,
        "min_validation_profit": 2.0,
        "max_drawdown_profit_ratio": 1.50,
        "uncertainty_scale": 0.85,
        "ev_thresholds": (0.00, 0.01, 0.02),
        "min_odds": (2.2, 2.8),
        "max_odds": (3.5, 4.0),
        "kelly_fractions": (0.05, 0.10),
        "allowed_outcomes": (("draw",),),
        "bucket_keys": (
            ("odds_bucket", "market_draw_bucket"),
            ("odds_bucket", "league_draw_rate_bucket"),
            ("odds_bucket", "strength_gap_bucket"),
            ("odds_bucket", "goal_env_bucket"),
        ),
        "min_bucket_samples": (8,),
        "min_bucket_roi": (0.10,),
    },
    "draw_regime_strict": {
        "validation_min_bets": 15,
        "min_positive_validation_months": 2,
        "min_validation_roi": 0.08,
        "min_validation_profit": 3.0,
        "max_drawdown_profit_ratio": 1.20,
        "uncertainty_scale": 0.85,
        "ev_thresholds": (0.01, 0.02),
        "min_odds": (2.8,),
        "max_odds": (3.5,),
        "kelly_fractions": (0.05,),
        "allowed_outcomes": (("draw",),),
        "bucket_keys": (
            ("odds_bucket", "market_draw_bucket"),
            ("odds_bucket", "league_draw_rate_bucket"),
            ("odds_bucket", "strength_gap_bucket"),
            ("odds_bucket", "goal_env_bucket"),
        ),
        "min_bucket_samples": (12,),
        "min_bucket_roi": (0.15,),
    },
    "draw_regime_persistent": {
        "validation_months": 12,
        "training_months": 18,
        "validation_min_bets": 10,
        "min_positive_validation_months": 2,
        "min_validation_roi": 0.05,
        "min_validation_profit": 1.0,
        "max_drawdown_profit_ratio": 1.50,
        "uncertainty_scale": 0.85,
        "ev_thresholds": (0.01,),
        "min_odds": (2.8,),
        "max_odds": (3.5,),
        "kelly_fractions": (0.05,),
        "allowed_outcomes": (("draw",),),
        "bucket_keys": (
            ("odds_bucket", "market_draw_bucket"),
            ("odds_bucket", "league_draw_rate_bucket"),
            ("odds_bucket", "strength_gap_bucket"),
            ("odds_bucket", "goal_env_bucket"),
        ),
        "min_bucket_samples": (15,),
        "min_bucket_roi": (0.05,),
        "persistent_buckets": True,
        "min_bucket_active_months": 4,
        "min_bucket_positive_months": 3,
    },
    "draw_quality": {
        "validation_min_bets": 8,
        "min_positive_validation_months": 1,
        "min_validation_roi": 0.05,
        "min_validation_profit": 1.0,
        "max_drawdown_profit_ratio": 1.50,
        "uncertainty_scale": 0.85,
        "ev_thresholds": (0.00, 0.01, 0.02),
        "min_odds": (2.2, 2.8),
        "max_odds": (3.5, 4.0),
        "kelly_fractions": (0.05, 0.10),
        "allowed_outcomes": (("draw",),),
        "quality_gate": True,
        "quality_quantiles": (0.50, 0.65),
        "quality_min_samples": 18,
    },
    "draw_quality_pooled": {
        "validation_months": 12,
        "training_months": 18,
        "validation_min_bets": 15,
        "min_positive_validation_months": 1,
        "min_validation_roi": 0.05,
        "min_validation_profit": 1.0,
        "max_drawdown_profit_ratio": 1.50,
        "uncertainty_scale": 0.85,
        "ev_thresholds": (0.00, 0.01, 0.02),
        "min_odds": (2.2, 2.8),
        "max_odds": (3.5, 4.0),
        "kelly_fractions": (0.05, 0.10),
        "allowed_outcomes": (("draw",),),
        "quality_gate": True,
        "quality_quantiles": (0.50, 0.65, 0.75),
        "quality_min_samples": 60,
    },
    "draw_quality_pooled_full": {
        "validation_months": 12,
        "training_months": 18,
        "validation_min_bets": 15,
        "min_positive_validation_months": 2,
        "min_validation_roi": 0.05,
        "min_validation_profit": 2.0,
        "max_drawdown_profit_ratio": 1.50,
        "uncertainty_scale": 0.85,
        "ev_thresholds": (0.00, 0.01, 0.02),
        "min_odds": (2.2, 2.8),
        "max_odds": (3.5, 4.0),
        "kelly_fractions": (0.05, 0.10),
        "allowed_outcomes": (("draw",),),
        "quality_gate": True,
        "quality_holdout": False,
        "quality_quantiles": (0.50, 0.65, 0.75),
        "quality_min_samples": 60,
    },
    "draw_quality_pooled_lite": {
        "validation_months": 12,
        "training_months": 18,
        "validation_min_bets": 10,
        "min_positive_validation_months": 1,
        "min_validation_roi": 0.03,
        "min_validation_profit": 1.0,
        "max_drawdown_profit_ratio": 2.00,
        "uncertainty_scale": 0.85,
        "ev_thresholds": (0.01,),
        "min_odds": (2.8,),
        "max_odds": (3.5,),
        "kelly_fractions": (0.05,),
        "allowed_outcomes": (("draw",),),
        "quality_gate": True,
        "quality_holdout": False,
        "quality_quantiles": (0.50,),
        "quality_min_samples": 60,
    },
    "real_ev_probe_draw": {
        "validation_months": 12,
        "training_months": 18,
        "validation_min_bets": 3,
        "min_positive_validation_months": 1,
        "min_validation_roi": 0.0,
        "min_validation_profit": 0.0,
        "max_drawdown_profit_ratio": 3.0,
        "uncertainty_scale": 0.75,
        "ev_thresholds": (-0.01, 0.0),
        "min_odds": (2.4, 2.8),
        "max_odds": (3.5, 4.0),
        "kelly_fractions": (0.05,),
        "allowed_outcomes": (("draw",),),
        "research_only": True,
    },
    "real_ev_draw_regime_features": {
        "validation_months": 12,
        "training_months": 18,
        "validation_min_bets": 6,
        "min_positive_validation_months": 2,
        "min_validation_roi": 0.03,
        "min_validation_profit": 1.0,
        "max_drawdown_profit_ratio": 2.0,
        "uncertainty_scale": 0.75,
        "ev_thresholds": (-0.01, 0.0),
        "min_odds": (2.4, 2.8),
        "max_odds": (3.5, 4.0),
        "kelly_fractions": (0.05,),
        "allowed_outcomes": (("draw",),),
        "bucket_keys": (
            ("odds_bucket", "recent_draw_bucket"),
            ("odds_bucket", "recent_low_score_bucket"),
            ("odds_bucket", "draw_market_gap_bucket"),
            ("market_draw_bucket", "recent_draw_bucket"),
            ("league_draw_rate_bucket", "recent_low_score_bucket"),
        ),
        "min_bucket_samples": (6, 10),
        "min_bucket_roi": (0.05,),
        "research_only": True,
    },
    "real_ev_draw_regime_features_fast": {
        "validation_months": 12,
        "training_months": 18,
        "validation_min_bets": 4,
        "min_positive_validation_months": 1,
        "min_validation_roi": 0.0,
        "min_validation_profit": 0.0,
        "max_drawdown_profit_ratio": 3.0,
        "uncertainty_scale": 0.75,
        "ev_thresholds": (-0.01,),
        "min_odds": (2.4,),
        "max_odds": (3.5,),
        "kelly_fractions": (0.05,),
        "allowed_outcomes": (("draw",),),
        "bucket_keys": (
            ("market_draw_bucket", "recent_draw_bucket"),
            ("league_draw_rate_bucket", "recent_low_score_bucket"),
        ),
        "min_bucket_samples": (4,),
        "min_bucket_roi": (0.0,),
        "research_only": True,
    },
    "real_ev_draw_ranked": {
        "validation_months": 12,
        "training_months": 18,
        "validation_min_bets": 8,
        "min_positive_validation_months": 2,
        "min_validation_roi": 0.03,
        "min_validation_profit": 1.0,
        "max_drawdown_profit_ratio": 2.0,
        "uncertainty_scale": 0.75,
        "ev_thresholds": (-0.01, 0.0),
        "min_odds": (2.4, 2.8),
        "max_odds": (3.5,),
        "kelly_fractions": (0.05,),
        "allowed_outcomes": (("draw",),),
        "candidate_limits_per_day": (1, 2),
        "ranking_keys": ("lower_ev", "quality_score"),
        "quality_gate": True,
        "quality_holdout": False,
        "quality_quantiles": (0.0,),
        "quality_min_samples": 20,
        "research_only": True,
    },
    "real_ev_draw_ranked_fast": {
        "validation_months": 12,
        "training_months": 18,
        "validation_min_bets": 5,
        "min_positive_validation_months": 1,
        "min_validation_roi": 0.0,
        "min_validation_profit": 0.0,
        "max_drawdown_profit_ratio": 3.0,
        "uncertainty_scale": 0.75,
        "ev_thresholds": (-0.01, 0.0),
        "min_odds": (2.4, 2.8),
        "max_odds": (3.5,),
        "kelly_fractions": (0.05,),
        "allowed_outcomes": (("draw",),),
        "candidate_limits_per_day": (1,),
        "ranking_keys": ("lower_ev",),
        "research_only": True,
    },
}

QUALITY_FEATURE_COLUMNS = (
    "lower_ev",
    "probability",
    "uncertainty",
    "odds",
    "market_draw",
    "league_draw_rate",
    "combined_recent_draw_rate",
    "combined_recent_low_score_rate",
    "draw_market_vs_league",
    "abs_elo_delta",
    "lambda_total",
)


class IsotonicPAV:
    def __init__(self) -> None:
        self.upper: np.ndarray = np.array([1.0])
        self.values: np.ndarray = np.array([0.5])

    def fit(self, x: np.ndarray, y: np.ndarray) -> "IsotonicPAV":
        order = np.argsort(x)
        blocks: list[dict[str, float]] = []
        for xv, yv in zip(x[order], y[order]):
            blocks.append({"lower": float(xv), "upper": float(xv), "weight": 1.0, "sum": float(yv)})
            while len(blocks) >= 2 and blocks[-2]["sum"] / blocks[-2]["weight"] > blocks[-1]["sum"] / blocks[-1]["weight"]:
                right, left = blocks.pop(), blocks.pop()
                blocks.append({
                    "lower": left["lower"], "upper": right["upper"],
                    "weight": left["weight"] + right["weight"], "sum": left["sum"] + right["sum"],
                })
        self.upper = np.array([block["upper"] for block in blocks])
        self.values = np.array([block["sum"] / block["weight"] for block in blocks])
        return self

    def predict(self, values: np.ndarray) -> np.ndarray:
        indices = np.searchsorted(self.upper, values, side="left")
        return self.values[np.clip(indices, 0, len(self.values) - 1)]


class ResidualProbabilityModel:
    def __init__(self, ridge: float = 8.0, uncertainty_scale: float = 1.0,
                 use_real_ev_anchor: bool = True) -> None:
        self.ridge = ridge
        self.uncertainty_scale = uncertainty_scale
        self.use_real_ev_anchor = use_real_ev_anchor
        self.coefficients: dict[str, np.ndarray] = {}
        self.calibrators: dict[str, IsotonicPAV] = {}
        self.rmse: dict[str, float] = {}
        self.league_counts: dict[str, int] = {}

    @staticmethod
    def design(frame: pd.DataFrame, outcome: str) -> np.ndarray:
        market = frame[f"market_{outcome}"].to_numpy(float)
        pure = frame[f"pure_{outcome}"].to_numpy(float)
        odds = frame[f"odds_{outcome}"].to_numpy(float)
        optional_columns = [
            "form_points_diff",
            "form_goal_diff_delta",
            "form_goals_for_delta",
            "form_goals_against_delta",
            "season_points_per_match_delta",
            "season_goal_diff_per_match_delta",
            "rest_days_delta",
            "combined_recent_draw_rate",
            "combined_recent_low_score_rate",
            "draw_market_vs_league",
        ]
        extras = [
            frame[column].fillna(0).to_numpy(float)
            for column in optional_columns
            if column in frame.columns
        ]
        return np.column_stack([np.ones(len(frame)), pure - market, market - 1 / 3, np.log(odds), *extras])

    def fit(self, frame: pd.DataFrame) -> "ResidualProbabilityModel":
        if len(frame) < 300:
            raise ValueError("Residual model requires at least 300 prior matches")
        self.league_counts = frame.groupby("league").size().astype(int).to_dict()
        for outcome in OUTCOMES:
            x = self.design(frame, outcome)
            market = frame[f"market_{outcome}"].to_numpy(float)
            y = (frame["actual_result"] == outcome).to_numpy(float)
            target = y - market
            penalty = np.eye(x.shape[1]) * self.ridge
            penalty[0, 0] = 0.0
            beta = np.linalg.solve(x.T @ x + penalty, x.T @ target)
            raw = np.clip(market + x @ beta, 0.01, 0.98)
            calibrator = IsotonicPAV().fit(raw, y)
            calibrated = calibrator.predict(raw)
            self.coefficients[outcome] = beta
            self.calibrators[outcome] = calibrator
            self.rmse[outcome] = float(np.sqrt(np.mean((calibrated - y) ** 2)))
        return self

    def predict(self, frame: pd.DataFrame) -> pd.DataFrame:
        output = frame.copy()
        calibrated: dict[str, np.ndarray] = {}
        model_probability: dict[str, np.ndarray] = {}
        uncertainty_by_outcome: dict[str, np.ndarray] = {}
        for outcome in OUTCOMES:
            market = frame[f"market_{outcome}"].to_numpy(float)
            raw = np.clip(market + self.design(frame, outcome) @ self.coefficients[outcome], 0.01, 0.98)
            calibrated[outcome] = self.calibrators[outcome].predict(raw)
        total = sum(calibrated.values())
        counts = frame["league"].map(self.league_counts).fillna(0).to_numpy(float)
        reliability = counts / (counts + 200.0)
        for outcome in OUTCOMES:
            market = frame[f"market_{outcome}"].to_numpy(float)
            normalized = calibrated[outcome] / total
            probability = market + reliability * (normalized - market)
            uncertainty = np.maximum(0.0075, self.uncertainty_scale * self.rmse[outcome] / np.sqrt(np.maximum(counts, 30.0)))
            model_probability[outcome] = probability
            uncertainty_by_outcome[outcome] = uncertainty
            output[f"model_probability_{outcome}"] = probability
            output[f"model_lower_ev_{outcome}"] = (probability - uncertainty) * frame[f"odds_{outcome}"].to_numpy(float) - 1
            output[f"uncertainty_{outcome}"] = uncertainty
        if self.use_real_ev_anchor:
            real_rows = {outcome: [] for outcome in OUTCOMES}
            for row_index in range(len(frame)):
                model = {outcome: float(model_probability[outcome][row_index]) for outcome in OUTCOMES}
                market = {outcome: float(frame.iloc[row_index][f"market_{outcome}"]) for outcome in OUTCOMES}
                odds = {outcome: float(frame.iloc[row_index][f"odds_{outcome}"]) for outcome in OUTCOMES}
                anchored, _ = anchor_real_probability(
                    model, market, odds, reliability=float(reliability[row_index])
                )
                for outcome in OUTCOMES:
                    real_rows[outcome].append(anchored[outcome])
            for outcome in OUTCOMES:
                probability = np.array(real_rows[outcome], dtype=float)
                output[f"probability_{outcome}"] = probability
                output[f"lower_ev_{outcome}"] = (
                    probability - uncertainty_by_outcome[outcome]
                ) * frame[f"odds_{outcome}"].to_numpy(float) - 1
        else:
            for outcome in OUTCOMES:
                probability = model_probability[outcome]
                output[f"probability_{outcome}"] = probability
                output[f"lower_ev_{outcome}"] = (
                    probability - uncertainty_by_outcome[outcome]
                ) * frame[f"odds_{outcome}"].to_numpy(float) - 1
        return output


def build_feature_history(matches: pd.DataFrame) -> pd.DataFrame:
    elo, poisson = EloModel(), PoissonModel()
    pure_ensemble = EnsembleModel({"elo": 0.30, "poisson": 0.70})
    league_draws: dict[str, int] = {}
    league_matches: dict[str, int] = {}
    team_history: dict[str, list[dict[str, float]]] = {}
    season_stats: dict[tuple[str, str], dict[str, float]] = {}
    last_played: dict[str, pd.Timestamp] = {}
    rows: list[dict] = []
    for date, day in matches.groupby("match_date", sort=True):
        for _, match in day.iterrows():
            league = str(match["league"])
            home, away = str(match["HomeTeam"]), str(match["AwayTeam"])
            delta = elo.rating(home) - elo.rating(away)
            lambda_home = max(.45, 1.35 + delta / 700)
            lambda_away = max(.35, 1.05 - delta / 900)
            pure = pure_ensemble.predict({
                "elo": elo.predict(home, away),
                "poisson": poisson.predict(lambda_home, lambda_away),
            })
            odds = {outcome: float(match[f"odds_{outcome}"]) for outcome in OUTCOMES}
            market = market_probabilities(odds)
            prior_league_matches = league_matches.get(league, 0)
            prior_league_draws = league_draws.get(league, 0)
            home_form = _recent_team_form(team_history.get(home, []))
            away_form = _recent_team_form(team_history.get(away, []))
            home_season = _season_rate(season_stats.get((league, home), {}))
            away_season = _season_rate(season_stats.get((league, away), {}))
            home_rest = _rest_days(last_played.get(home), date)
            away_rest = _rest_days(last_played.get(away), date)
            rows.append({
                "match_date": date, "league": league,
                "home_team": home, "away_team": away, "actual_result": actual_outcome(match),
                "elo_delta": round(delta, 6),
                "lambda_home": round(lambda_home, 6),
                "lambda_away": round(lambda_away, 6),
                "lambda_total": round(lambda_home + lambda_away, 6),
                "lambda_diff": round(abs(lambda_home - lambda_away), 6),
                "league_prior_matches": prior_league_matches,
                "league_draw_rate": round(prior_league_draws / prior_league_matches, 6) if prior_league_matches else 0.27,
                "home_form_points": home_form["points"],
                "away_form_points": away_form["points"],
                "home_recent_draw_rate": home_form["draw_rate"],
                "away_recent_draw_rate": away_form["draw_rate"],
                "combined_recent_draw_rate": round((home_form["draw_rate"] + away_form["draw_rate"]) / 2, 6),
                "home_recent_low_score_rate": home_form["low_score_rate"],
                "away_recent_low_score_rate": away_form["low_score_rate"],
                "combined_recent_low_score_rate": round((home_form["low_score_rate"] + away_form["low_score_rate"]) / 2, 6),
                "form_points_diff": round(home_form["points"] - away_form["points"], 6),
                "form_goals_for_delta": round(home_form["goals_for"] - away_form["goals_for"], 6),
                "form_goals_against_delta": round(home_form["goals_against"] - away_form["goals_against"], 6),
                "form_goal_diff_delta": round(home_form["goal_diff"] - away_form["goal_diff"], 6),
                "season_points_per_match_delta": round(home_season["points_per_match"] - away_season["points_per_match"], 6),
                "season_goal_diff_per_match_delta": round(home_season["goal_diff_per_match"] - away_season["goal_diff_per_match"], 6),
                "home_rest_days": home_rest,
                "away_rest_days": away_rest,
                "rest_days_delta": round(home_rest - away_rest, 6),
                "draw_market_vs_league": round(market["draw"] - (prior_league_draws / prior_league_matches if prior_league_matches else 0.27), 6),
                **{f"odds_{outcome}": odds[outcome] for outcome in OUTCOMES},
                **{f"market_{outcome}": market[outcome] for outcome in OUTCOMES},
                **{f"pure_{outcome}": pure[outcome] for outcome in OUTCOMES},
            })
        for _, match in day.iterrows():
            home, away = str(match["HomeTeam"]), str(match["AwayTeam"])
            home_goals, away_goals = int(match["home_goals"]), int(match["away_goals"])
            elo.update(home, away, home_goals, away_goals)
            league = str(match["league"])
            league_matches[league] = league_matches.get(league, 0) + 1
            if home_goals == away_goals:
                league_draws[league] = league_draws.get(league, 0) + 1
            _update_team_history(team_history, home, goals_for=home_goals, goals_against=away_goals)
            _update_team_history(team_history, away, goals_for=away_goals, goals_against=home_goals)
            _update_season_stats(season_stats, league, home, goals_for=home_goals, goals_against=away_goals)
            _update_season_stats(season_stats, league, away, goals_for=away_goals, goals_against=home_goals)
            last_played[home] = date
            last_played[away] = date
    return pd.DataFrame(rows).sort_values("match_date").reset_index(drop=True)


def _points_for(goals_for: int, goals_against: int) -> int:
    return 3 if goals_for > goals_against else 1 if goals_for == goals_against else 0


def _recent_team_form(history: list[dict[str, float]], window: int = 5) -> dict[str, float]:
    recent = history[-window:]
    if not recent:
        return {
            "points": 1.0,
            "goals_for": 1.2,
            "goals_against": 1.2,
            "goal_diff": 0.0,
            "draw_rate": 0.27,
            "low_score_rate": 0.50,
        }
    count = len(recent)
    goals_for = sum(row["goals_for"] for row in recent) / count
    goals_against = sum(row["goals_against"] for row in recent) / count
    return {
        "points": sum(row["points"] for row in recent) / count,
        "goals_for": goals_for,
        "goals_against": goals_against,
        "goal_diff": goals_for - goals_against,
        "draw_rate": sum(1 for row in recent if row["goals_for"] == row["goals_against"]) / count,
        "low_score_rate": sum(1 for row in recent if row["goals_for"] + row["goals_against"] <= 2) / count,
    }


def _rest_days(last_date: pd.Timestamp | None, current_date: pd.Timestamp) -> float:
    if last_date is None:
        return 7.0
    return float(max(0, min(21, (current_date - last_date).days)))


def _season_rate(stats: dict[str, float]) -> dict[str, float]:
    matches = float(stats.get("matches", 0) or 0)
    if matches <= 0:
        return {"points_per_match": 1.0, "goal_diff_per_match": 0.0}
    return {
        "points_per_match": float(stats.get("points", 0)) / matches,
        "goal_diff_per_match": float(stats.get("goal_diff", 0)) / matches,
    }


def _update_team_history(history: dict[str, list[dict[str, float]]], team: str, *,
                         goals_for: int, goals_against: int) -> None:
    history.setdefault(team, []).append({
        "points": float(_points_for(goals_for, goals_against)),
        "goals_for": float(goals_for),
        "goals_against": float(goals_against),
    })


def _update_season_stats(stats: dict[tuple[str, str], dict[str, float]], league: str, team: str, *,
                         goals_for: int, goals_against: int) -> None:
    item = stats.setdefault((league, team), {"matches": 0.0, "points": 0.0, "goal_diff": 0.0})
    item["matches"] += 1.0
    item["points"] += float(_points_for(goals_for, goals_against))
    item["goal_diff"] += float(goals_for - goals_against)


def choose_candidates(predictions: pd.DataFrame, config: PortfolioConfig) -> pd.DataFrame:
    candidates: list[dict] = []
    for index, row in predictions.iterrows():
        choices = [{
            "outcome": outcome, "probability": float(row[f"probability_{outcome}"]),
            "uncertainty": float(row[f"uncertainty_{outcome}"]), "lower_ev": float(row[f"lower_ev_{outcome}"]),
            "odds": float(row[f"odds_{outcome}"]),
            "model_probability": float(row.get(f"model_probability_{outcome}", row[f"probability_{outcome}"])),
            "model_lower_ev": float(row.get(f"model_lower_ev_{outcome}", row[f"lower_ev_{outcome}"])),
        } for outcome in OUTCOMES if outcome in config.allowed_outcomes]
        if not choices:
            continue
        best = max(choices, key=lambda item: item["lower_ev"])
        if best["lower_ev"] < config.min_lower_ev or not config.min_odds <= best["odds"] <= config.max_odds:
            continue
        odds_bucket = _odds_bucket(best["odds"])
        candidate = {
            **best,
            "row_index": index,
            "league": row["league"],
            "date": row["match_date"],
            "odds_bucket": odds_bucket,
            "market_draw": float(row.get("market_draw", 0.0)),
            "league_draw_rate": float(row.get("league_draw_rate", 0.0)),
            "combined_recent_draw_rate": float(row.get("combined_recent_draw_rate", 0.0)),
            "combined_recent_low_score_rate": float(row.get("combined_recent_low_score_rate", 0.0)),
            "draw_market_vs_league": float(row.get("draw_market_vs_league", 0.0)),
            "abs_elo_delta": abs(float(row.get("elo_delta", 0.0))),
            "lambda_total": float(row.get("lambda_total", 0.0)),
            "market_draw_bucket": _market_draw_bucket(float(row.get("market_draw", 0.0))),
            "league_draw_rate_bucket": _league_draw_rate_bucket(float(row.get("league_draw_rate", 0.0))),
            "recent_draw_bucket": _recent_draw_bucket(float(row.get("combined_recent_draw_rate", 0.0))),
            "recent_low_score_bucket": _recent_low_score_bucket(float(row.get("combined_recent_low_score_rate", 0.0))),
            "draw_market_gap_bucket": _draw_market_gap_bucket(float(row.get("draw_market_vs_league", 0.0))),
            "strength_gap_bucket": _strength_gap_bucket(float(row.get("elo_delta", 0.0))),
            "goal_env_bucket": _goal_env_bucket(float(row.get("lambda_total", 0.0))),
        }
        if "quality_score" in row and pd.notna(row["quality_score"]):
            candidate["quality_score"] = float(row["quality_score"])
        if config.allowed_buckets:
            key = tuple(str(candidate[column]) for column in config.bucket_key)
            if key not in set(config.allowed_buckets):
                continue
        if config.quality_gate is not None:
            score = _quality_score(candidate, config.quality_gate)
            candidate["quality_score"] = score
            if score < float(config.quality_gate["threshold"]):
                continue
        candidates.append(candidate)
    return pd.DataFrame(candidates)


def _quality_score(candidate: dict, gate: dict) -> float:
    means = gate["means"]
    scales = gate["scales"]
    coefficients = gate["coefficients"]
    score = float(gate["intercept"])
    for column, coefficient in zip(gate["feature_columns"], coefficients):
        scale = float(scales.get(column, 1.0)) or 1.0
        score += ((float(candidate.get(column, 0.0)) - float(means.get(column, 0.0))) / scale) * float(coefficient)
    return score


def _odds_bucket(odds: float) -> str:
    bands = ((1.0, 1.8), (1.8, 2.2), (2.2, 2.8), (2.8, 3.5), (3.5, 4.0), (4.0, 5.0), (5.0, 7.0))
    for lower, upper in bands:
        if lower <= odds < upper:
            return f"[{lower},{upper})"
    return "[7.0,inf)"


def _market_draw_bucket(probability: float) -> str:
    if probability < 0.24:
        return "market_draw_low"
    if probability < 0.29:
        return "market_draw_mid"
    return "market_draw_high"


def _league_draw_rate_bucket(rate: float) -> str:
    if rate < 0.24:
        return "league_draw_low"
    if rate < 0.29:
        return "league_draw_mid"
    return "league_draw_high"


def _recent_draw_bucket(rate: float) -> str:
    if rate < 0.20:
        return "recent_draw_low"
    if rate < 0.36:
        return "recent_draw_mid"
    return "recent_draw_high"


def _recent_low_score_bucket(rate: float) -> str:
    if rate < 0.40:
        return "low_score_low"
    if rate < 0.60:
        return "low_score_mid"
    return "low_score_high"


def _draw_market_gap_bucket(value: float) -> str:
    if value < -0.03:
        return "draw_under_league"
    if value < 0.03:
        return "draw_near_league"
    return "draw_over_league"


def _strength_gap_bucket(elo_delta: float) -> str:
    gap = abs(elo_delta)
    if gap < 45:
        return "strength_close"
    if gap < 120:
        return "strength_gap_mid"
    return "strength_gap_wide"


def _goal_env_bucket(lambda_total: float) -> str:
    if lambda_total < 2.35:
        return "goal_env_low"
    if lambda_total < 2.70:
        return "goal_env_mid"
    return "goal_env_high"


def _unit_profit(outcome: str, actual: str, odds: float) -> float:
    return odds - 1 if outcome == actual else -1.0


def select_allowed_buckets(predictions: pd.DataFrame, base_config: PortfolioConfig,
                           bucket_key: tuple[str, ...], min_samples: int,
                           min_roi: float) -> tuple[tuple[str, ...], ...]:
    candidates = choose_candidates(predictions, base_config)
    if candidates.empty:
        return ()
    rows: list[dict] = []
    for _, candidate in candidates.iterrows():
        source = predictions.loc[int(candidate["row_index"])]
        rows.append({
            **{column: str(candidate[column]) for column in bucket_key},
            "profit": _unit_profit(candidate["outcome"], source["actual_result"], float(candidate["odds"])),
            "won": candidate["outcome"] == source["actual_result"],
            "odds": float(candidate["odds"]),
        })
    frame = pd.DataFrame(rows)
    grouped = frame.groupby(list(bucket_key)).agg(
        samples=("profit", "size"), profit=("profit", "sum"), wins=("won", "sum"), avg_odds=("odds", "mean")
    ).reset_index()
    grouped["roi"] = grouped["profit"] / grouped["samples"]
    grouped["win_rate"] = grouped["wins"] / grouped["samples"]
    grouped["breakeven_rate"] = 1 / grouped["avg_odds"]
    accepted = grouped[
        (grouped["samples"] >= min_samples)
        & (grouped["profit"] > 0)
        & (grouped["roi"] >= min_roi)
        & (grouped["win_rate"] >= grouped["breakeven_rate"])
    ]
    return tuple(tuple(str(row[column]) for column in bucket_key) for _, row in accepted.iterrows())


def select_persistent_buckets(predictions: pd.DataFrame, base_config: PortfolioConfig,
                              bucket_key: tuple[str, ...], min_samples: int,
                              min_roi: float, min_active_months: int,
                              min_positive_months: int) -> tuple[tuple[str, ...], ...]:
    frame = build_candidate_outcomes(predictions, base_config)
    if frame.empty:
        return ()
    frame = frame.copy()
    frame["month"] = pd.to_datetime(frame["date"]).dt.to_period("M").astype(str)
    rows: list[dict] = []
    for key, group in frame.groupby(list(bucket_key), dropna=False):
        if not isinstance(key, tuple):
            key = (key,)
        month_rows = group.groupby("month").agg(
            samples=("unit_profit", "size"),
            profit=("unit_profit", "sum"),
        )
        samples = int(group["unit_profit"].size)
        profit = float(group["unit_profit"].sum())
        roi = profit / samples if samples else 0.0
        active_months = int((month_rows["samples"] > 0).sum())
        positive_months = int((month_rows["profit"] > 0).sum())
        rows.append({
            "key": tuple(str(value) for value in key),
            "samples": samples,
            "profit": profit,
            "roi": roi,
            "active_months": active_months,
            "positive_months": positive_months,
        })
    accepted = [
        row["key"] for row in rows
        if row["samples"] >= min_samples
        and row["profit"] > 0
        and row["roi"] >= min_roi
        and row["active_months"] >= min_active_months
        and row["positive_months"] >= min_positive_months
    ]
    return tuple(accepted)


def build_candidate_outcomes(predictions: pd.DataFrame, config: PortfolioConfig) -> pd.DataFrame:
    candidates = choose_candidates(predictions, config)
    if candidates.empty:
        return candidates
    rows: list[dict] = []
    for _, candidate in candidates.iterrows():
        source = predictions.loc[int(candidate["row_index"])]
        won = candidate["outcome"] == source["actual_result"]
        rows.append({
            **candidate.to_dict(),
            "actual_result": source["actual_result"],
            "won": won,
            "unit_profit": _unit_profit(candidate["outcome"], source["actual_result"], float(candidate["odds"])),
        })
    return pd.DataFrame(rows)


def fit_quality_gate(predictions: pd.DataFrame, base_config: PortfolioConfig, *,
                     quantile: float, min_samples: int, ridge: float = 4.0) -> dict | None:
    frame = build_candidate_outcomes(predictions, base_config)
    if len(frame) < min_samples:
        return None
    x_raw = frame.loc[:, QUALITY_FEATURE_COLUMNS].astype(float)
    means = x_raw.mean()
    scales = x_raw.std(ddof=0).replace(0, 1.0).fillna(1.0)
    x = ((x_raw - means) / scales).to_numpy(float)
    design = np.column_stack([np.ones(len(x)), x])
    y = frame["unit_profit"].to_numpy(float)
    penalty = np.eye(design.shape[1]) * ridge
    penalty[0, 0] = 0.0
    beta = np.linalg.solve(design.T @ design + penalty, design.T @ y)
    scores = design @ beta
    threshold = float(np.quantile(scores, quantile))
    return {
        "kind": "linear_unit_profit_quality",
        "feature_columns": list(QUALITY_FEATURE_COLUMNS),
        "intercept": float(beta[0]),
        "coefficients": [float(value) for value in beta[1:]],
        "means": {column: float(means[column]) for column in QUALITY_FEATURE_COLUMNS},
        "scales": {column: float(scales[column]) for column in QUALITY_FEATURE_COLUMNS},
        "threshold": threshold,
        "quantile": float(quantile),
        "training_samples": int(len(frame)),
    }


def simulate(predictions: pd.DataFrame, config: PortfolioConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    candidates = choose_candidates(predictions, config)
    bets: list[dict] = []
    days: list[dict] = []
    cumulative_profit = 0.0
    halted = False
    for date in pd.date_range(predictions["match_date"].min(), predictions["match_date"].max(), freq="D"):
        if halted:
            days.append({
                "date": date.strftime("%Y-%m-%d"), "bets": 0, "staked": 0.0,
                "profit": 0.0, "halted_by_stop_loss": True,
            })
            continue
        if not candidates.empty:
            ranking_key = config.ranking_key if config.ranking_key in candidates.columns else "lower_ev"
            day = candidates[candidates["date"] == date].sort_values(ranking_key, ascending=False)
            if config.candidate_limit_per_day is not None:
                day = day.head(max(0, int(config.candidate_limit_per_day)))
        else:
            day = candidates
        daily_used, league_used = 0.0, {}
        day_profit, day_bets = 0.0, 0
        for _, candidate in day.iterrows():
            if daily_used >= config.daily_limit - .01:
                break
            probability, odds = float(candidate["probability"]), float(candidate["odds"])
            full_kelly = max(0.0, (probability * odds - 1) / (odds - 1))
            stake = max(config.min_stake, config.daily_limit * full_kelly * config.kelly_fraction)
            stake = min(stake, config.max_stake, config.daily_limit - daily_used,
                        config.league_limit - league_used.get(candidate["league"], 0.0))
            if stake < config.min_stake:
                continue
            source = predictions.loc[int(candidate["row_index"])]
            won = candidate["outcome"] == source["actual_result"]
            profit = stake * (odds - 1) if won else -stake
            daily_used += stake
            league_used[candidate["league"]] = league_used.get(candidate["league"], 0.0) + stake
            day_profit += profit
            day_bets += 1
            bets.append({
                "date": date.strftime("%Y-%m-%d"), "league": candidate["league"],
                "home_team": source["home_team"], "away_team": source["away_team"],
                "outcome": candidate["outcome"], "actual_result": source["actual_result"],
                "probability": round(probability, 6), "uncertainty": round(float(candidate["uncertainty"]), 6),
                "lower_ev": round(float(candidate["lower_ev"]), 6), "odds": odds,
                "model_probability": round(float(candidate.get("model_probability", probability)), 6),
                "model_lower_ev": round(float(candidate.get("model_lower_ev", candidate["lower_ev"])), 6),
                "model_ev": round(float(candidate.get("model_probability", probability)) * odds - 1, 6),
                "stake": round(stake, 2), "won": won, "profit": round(profit, 2),
            })
        cumulative_profit += day_profit
        if config.stop_loss is not None and cumulative_profit <= -abs(float(config.stop_loss)):
            halted = True
        days.append({
            "date": date.strftime("%Y-%m-%d"), "bets": day_bets, "staked": round(daily_used, 2),
            "profit": round(day_profit, 2), "halted_by_stop_loss": halted,
        })
    return pd.DataFrame(days), pd.DataFrame(bets)


def metrics(days: pd.DataFrame, bets: pd.DataFrame) -> dict:
    total_staked = float(bets["stake"].sum()) if not bets.empty else 0.0
    profit = float(bets["profit"].sum()) if not bets.empty else 0.0
    equity = days["profit"].cumsum() if not days.empty else pd.Series(dtype=float)
    peaks = pd.concat([pd.Series([0.0]), equity]).cummax().iloc[1:] if not equity.empty else equity
    drawdown = float((peaks.to_numpy() - equity.to_numpy()).max()) if not equity.empty else 0.0
    return {
        "bets": int(len(bets)), "winning_bets": int(bets["won"].sum()) if not bets.empty else 0,
        "total_staked": round(total_staked, 2), "profit": round(profit, 2),
        "roi_pct": round(profit / total_staked * 100, 2) if total_staked else 0.0,
        "max_drawdown": round(drawdown, 2), "max_daily_stake": round(float(days["staked"].max()), 2) if not days.empty else 0.0,
        "active_days": int((days["staked"] > 0).sum()) if not days.empty else 0,
    }


def probability_metrics(predictions: pd.DataFrame) -> dict:
    if predictions.empty:
        return {"matches": 0, "brier_score": None, "log_loss": None, "ece": None}
    actual = predictions["actual_result"].to_numpy()
    probabilities = np.column_stack([predictions[f"probability_{outcome}"].to_numpy(float) for outcome in OUTCOMES])
    labels = np.column_stack([(actual == outcome).astype(float) for outcome in OUTCOMES])
    brier = float(np.mean(np.mean((probabilities - labels) ** 2, axis=1)))
    actual_indices = np.array([OUTCOMES.index(value) for value in actual])
    log_loss = float(np.mean(-np.log(np.clip(probabilities[np.arange(len(actual)), actual_indices], 1e-12, 1))))
    flat_p, flat_y = probabilities.ravel(), labels.ravel()
    ece = 0.0
    for lower in np.arange(0, 1, .1):
        mask = (flat_p >= lower) & (flat_p < lower + .1 if lower < .9 else flat_p <= 1)
        if mask.any():
            ece += float(mask.mean()) * abs(float(flat_p[mask].mean()) - float(flat_y[mask].mean()))
    return {"matches": int(len(predictions)), "brier_score": round(brier, 6), "log_loss": round(log_loss, 6), "ece": round(ece, 6)}


def promotion_decision(
    overall: dict,
    calibration: dict,
    profitable_invested_months: int,
    losing_invested_months: int,
) -> str:
    if overall["bets"] >= 50 and overall["roi_pct"] <= 0:
        return "REJECT_EXPERIMENT"
    drawdown_covered_by_profit = overall["profit"] > overall["max_drawdown"]
    if (
        overall["bets"] >= 100
        and overall["roi_pct"] > 0
        and (calibration["ece"] or 1) <= .05
        and drawdown_covered_by_profit
        and profitable_invested_months > losing_invested_months
    ):
        return "PROMOTE_TO_LARGER_SHADOW"
    return "NEED_MORE_DATA"


def select_portfolio_config(train: pd.DataFrame, validation: pd.DataFrame, profile: dict) -> tuple[PortfolioConfig | None, dict]:
    model = ResidualProbabilityModel(uncertainty_scale=profile["uncertainty_scale"]).fit(train)
    predicted = model.predict(validation)
    use_quality_gate = bool(profile.get("quality_gate"))
    quality_train = predicted
    quality_eval = predicted
    if use_quality_gate and profile.get("quality_holdout", True):
        validation_months = sorted(predicted["match_date"].dt.to_period("M").unique())
        if len(validation_months) < 2:
            return None, {"decision": "ABSTAIN", "reason": "Quality gate requires at least two validation months"}
        eval_month = validation_months[-1]
        quality_train = predicted[predicted["match_date"].dt.to_period("M") < eval_month].reset_index(drop=True)
        quality_eval = predicted[predicted["match_date"].dt.to_period("M") == eval_month].reset_index(drop=True)
        if quality_train.empty or quality_eval.empty:
            return None, {"decision": "ABSTAIN", "reason": "Quality gate validation split is empty"}
    candidates: list[PortfolioConfig] = []
    min_odds_values = profile.get("min_odds", (1.5,))
    allowed_outcomes_values = profile.get("allowed_outcomes", (OUTCOMES,))
    stop_loss_values = profile.get("stop_losses", (None,))
    quality_quantiles = profile.get("quality_quantiles", (None,))
    for ev, min_odds, odds, fraction, allowed_outcomes, stop_loss in itertools.product(
        profile["ev_thresholds"], min_odds_values, profile["max_odds"], profile["kelly_fractions"],
        allowed_outcomes_values, stop_loss_values,
    ):
        if float(min_odds) > float(odds):
            continue
        base_variants = [
            PortfolioConfig(
                ev,
                odds,
                fraction,
                min_odds=float(min_odds),
                allowed_outcomes=tuple(allowed_outcomes),
                stop_loss=stop_loss,
                candidate_limit_per_day=candidate_limit,
                ranking_key=str(ranking_key),
            )
            for candidate_limit, ranking_key in itertools.product(
                profile.get("candidate_limits_per_day", (None,)),
                profile.get("ranking_keys", ("lower_ev",)),
            )
        ]
        base_configs: list[PortfolioConfig] = []
        if not profile.get("bucket_keys"):
            base_configs.extend(base_variants)
        else:
            predicted_base = base_variants[0]
            for bucket_key, min_samples, min_roi in itertools.product(
                profile["bucket_keys"], profile["min_bucket_samples"], profile["min_bucket_roi"],
            ):
                if profile.get("persistent_buckets"):
                    allowed = select_persistent_buckets(
                        predicted,
                        predicted_base,
                        bucket_key,
                        min_samples,
                        min_roi,
                        int(profile.get("min_bucket_active_months", 1)),
                        int(profile.get("min_bucket_positive_months", 1)),
                    )
                else:
                    allowed = select_allowed_buckets(predicted, predicted_base, bucket_key, min_samples, min_roi)
                if allowed:
                    for base in base_variants:
                        base_configs.append(replace(
                            base,
                            bucket_key=tuple(bucket_key),
                            allowed_buckets=allowed,
                        ))
        if not use_quality_gate:
            candidates.extend(base_configs)
            continue
        for base_config, quantile in itertools.product(base_configs, quality_quantiles):
            gate = fit_quality_gate(
                quality_train,
                base_config,
                quantile=float(quantile),
                min_samples=int(profile.get("quality_min_samples", 20)),
            )
            if gate is None:
                continue
            candidates.append(replace(base_config, quality_gate=gate))
    rows = []
    for config in candidates:
        eval_frame = quality_eval if use_quality_gate else predicted
        day_rows, bets = simulate(eval_frame, config)
        result = metrics(day_rows, bets)
        monthly_results = []
        for _, month_frame in eval_frame.groupby(eval_frame["match_date"].dt.to_period("M")):
            month_days, month_bets = simulate(month_frame.reset_index(drop=True), config)
            monthly_results.append(metrics(month_days, month_bets))
        positive_months = sum(item["bets"] > 0 and item["roi_pct"] > 0 for item in monthly_results)
        rows.append({"config": config, "base_config": replace(config, quality_gate=None), "positive_validation_months": positive_months, **result})
    min_validation_roi = float(profile.get("min_validation_roi", 0.0))
    min_validation_profit = float(profile.get("min_validation_profit", 0.0))
    max_drawdown_profit_ratio = profile.get("max_drawdown_profit_ratio")
    eligible = []
    for row in rows:
        if row["bets"] < profile["validation_min_bets"]:
            continue
        if row["roi_pct"] < min_validation_roi * 100:
            continue
        if row["profit"] < min_validation_profit:
            continue
        if row["positive_validation_months"] < profile["min_positive_validation_months"]:
            continue
        if max_drawdown_profit_ratio is not None and row["max_drawdown"] > row["profit"] * float(max_drawdown_profit_ratio):
            continue
        eligible.append(row)
    if not eligible:
        return None, {"decision": "ABSTAIN", "reason": f"No stable configuration with at least {profile['validation_min_bets']} bets and {profile['min_positive_validation_months']} positive validation month(s)"}
    best = max(eligible, key=lambda row: (row["roi_pct"] - row["max_drawdown"] / max(row["total_staked"], 1) * 10, row["profit"]))
    selected_config = best["config"]
    if use_quality_gate:
        selected_gate = fit_quality_gate(
            predicted,
            best["base_config"],
            quantile=float(selected_config.quality_gate["quantile"]),
            min_samples=int(profile.get("quality_min_samples", 20)),
        )
        if selected_gate is not None:
            selected_config = replace(best["base_config"], quality_gate=selected_gate)
    return selected_config, {key: value for key, value in best.items() if key not in {"config", "base_config"}}


def nested_walk_forward(features: pd.DataFrame, first_month: str, months: int, profile_name: str = "strict") -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    profile = EXPERIMENT_PROFILES[profile_name]
    validation_months = int(profile.get("validation_months", 3))
    training_months = int(profile.get("training_months", 18))
    all_days: list[pd.DataFrame] = []
    all_bets: list[pd.DataFrame] = []
    all_predictions: list[pd.DataFrame] = []
    month_reports: list[dict] = []
    for period in pd.period_range(first_month, periods=months, freq="M"):
        test_start, test_end = period.start_time.normalize(), period.end_time.normalize()
        validation_start = test_start - pd.DateOffset(months=validation_months)
        training_start = validation_start - pd.DateOffset(months=training_months)
        inner_train = features[(features.match_date >= training_start) & (features.match_date < validation_start)]
        validation = features[(features.match_date >= validation_start) & (features.match_date < test_start)]
        test = features[(features.match_date >= test_start) & (features.match_date <= test_end)]
        if len(inner_train) < 300 or len(validation) < 100 or test.empty:
            month_reports.append({"month": str(period), "decision": "ABSTAIN", "reason": "Insufficient train/validation/test data"})
            continue
        config, validation_report = select_portfolio_config(inner_train, validation, profile)
        outer_train = features[(features.match_date >= test_start - pd.DateOffset(months=training_months)) & (features.match_date < test_start)]
        predicted = ResidualProbabilityModel(uncertainty_scale=profile["uncertainty_scale"]).fit(outer_train).predict(test)
        model_metrics = probability_metrics(predicted)
        all_predictions.append(predicted.assign(month=str(period)))
        if config is None:
            month_reports.append({"month": str(period), **validation_report, "probability_metrics": model_metrics})
            continue
        days, bets = simulate(predicted, config)
        result = metrics(days, bets)
        month_reports.append({"month": str(period), "decision": "INVEST", "config": config.__dict__, "validation": validation_report, "probability_metrics": model_metrics, "test": result})
        all_days.append(days.assign(month=str(period)))
        all_bets.append(bets.assign(month=str(period)))
    days = pd.concat(all_days, ignore_index=True) if all_days else pd.DataFrame(columns=["date", "bets", "staked", "profit", "month"])
    bets = pd.concat(all_bets, ignore_index=True) if all_bets else pd.DataFrame()
    predictions = pd.concat(all_predictions, ignore_index=True) if all_predictions else pd.DataFrame()
    overall = metrics(days, bets)
    calibration = probability_metrics(predictions)
    invested_months = [row for row in month_reports if row.get("decision") == "INVEST"]
    profitable_invested_months = sum(
        row.get("test", {}).get("bets", 0) > 0 and row.get("test", {}).get("profit", 0) > 0
        for row in invested_months
    )
    losing_invested_months = sum(
        row.get("test", {}).get("bets", 0) > 0 and row.get("test", {}).get("profit", 0) < 0
        for row in invested_months
    )
    months_with_bets = profitable_invested_months + losing_invested_months + sum(
        row.get("test", {}).get("bets", 0) > 0 and row.get("test", {}).get("profit", 0) == 0
        for row in invested_months
    )
    drawdown_covered_by_profit = overall["profit"] > overall["max_drawdown"]
    promotion = promotion_decision(overall, calibration, profitable_invested_months, losing_invested_months)
    if profile.get("research_only") and promotion == "PROMOTE_TO_LARGER_SHADOW":
        promotion = "RESEARCH_ONLY_NEEDS_CONFIRMATION"
    summary = {
        "method": "nested monthly walk-forward real-EV market anchor + residual isotonic + league shrinkage + constrained Kelly",
        "experiment_profile": profile_name, "profile_config": profile,
        "first_month": first_month, "months": months,
        "training_months": training_months,
        "validation_months": validation_months,
        "odds_timing": "pre_closing_without_exact_snapshot_timestamp",
        "same_day_results_hidden_until_settlement": True,
        "overall": overall, "probability_metrics": calibration, "promotion_decision": promotion,
        "months_invested": len(invested_months),
        "months_abstained": sum(row.get("decision") == "ABSTAIN" for row in month_reports),
        "months_with_bets": months_with_bets,
        "profitable_invested_months": profitable_invested_months,
        "losing_invested_months": losing_invested_months,
        "drawdown_covered_by_profit": drawdown_covered_by_profit,
        "monthly": month_reports,
    }
    return summary, days, bets


def load_season_matches(seasons: tuple[str, ...]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for season in seasons:
        season = str(season).strip()
        if not season:
            continue
        path = Path("data") / "historical_csv" / "football-data" / season
        if not path.exists():
            continue
        frames.append(load_matches(path))
    if not frames:
        raise ValueError(f"No usable season directories found for: {', '.join(seasons)}")
    return pd.concat(frames, ignore_index=True).sort_values("match_date").reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--first-month", default="2024-06")
    parser.add_argument("--months", type=int, default=12)
    parser.add_argument("--profile", choices=tuple(EXPERIMENT_PROFILES), default="strict")
    parser.add_argument("--seasons", default=",".join(DEFAULT_SEASONS))
    parser.add_argument("--output-dir", type=Path, default=Path("reports/residual_walk_forward"))
    args = parser.parse_args()
    seasons = tuple(item.strip() for item in args.seasons.split(",") if item.strip())
    matches = load_season_matches(seasons)
    features = build_feature_history(matches)
    summary, days, bets = nested_walk_forward(features, args.first_month, args.months, args.profile)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    days.to_csv(args.output_dir / "daily.csv", index=False, encoding="utf-8-sig")
    bets.to_csv(args.output_dir / "bets.csv", index=False, encoding="utf-8-sig")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
