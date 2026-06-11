from __future__ import annotations

import uuid
from dataclasses import asdict
from typing import Any, Iterable

from ..models import EloModel, EnsembleModel, PoissonModel
from ..models.ensemble import market_probabilities
from ..risk import RiskLimits, calculate_stake
from .metrics import brier_score, expected_calibration_error, log_loss, max_drawdown


class BacktestEngine:
    def __init__(self, min_ev: float = 0.05) -> None:
        self.limits = RiskLimits(min_ev=min_ev)

    def run(self, rows: Iterable[dict[str, Any]], bankroll: float = 10_000) -> dict[str, Any]:
        ordered = sorted(list(rows), key=lambda row: str(row["date"]))
        if not ordered:
            raise ValueError("Backtest requires at least one historical match")
        elo, poisson, ensemble = EloModel(), PoissonModel(), EnsembleModel()
        starting_bankroll = bankroll
        equity = [bankroll]
        predictions: list[dict[str, float]] = []
        outcomes: list[str] = []
        bets: list[dict[str, Any]] = []
        daily_staked: dict[str, float] = {}
        weekly_staked: dict[str, float] = {}

        for row in ordered:
            date_text = str(row["date"])
            day = date_text[:10]
            week = day[:7] + "-" + str(int(day[-2:]) // 7)
            elo_p = elo.predict(row["home_team"], row["away_team"])
            lambda_home = float(row.get("lambda_home") or max(0.45, 1.35 + (elo.rating(row["home_team"]) - elo.rating(row["away_team"])) / 700))
            lambda_away = float(row.get("lambda_away") or max(0.35, 1.05 - (elo.rating(row["home_team"]) - elo.rating(row["away_team"])) / 900))
            poisson_p = poisson.predict(lambda_home, lambda_away)
            market_odds = {
                "home": float(row.get("market_home") or row["sp_home"]),
                "draw": float(row.get("market_draw") or row["sp_draw"]),
                "away": float(row.get("market_away") or row["sp_away"]),
            }
            prediction = ensemble.predict({"elo": elo_p, "poisson": poisson_p, "market": market_probabilities(market_odds)})
            home_score, away_score = int(row["home_score"]), int(row["away_score"])
            outcome = "home" if home_score > away_score else "draw" if home_score == away_score else "away"
            predictions.append(prediction)
            outcomes.append(outcome)
            official = {"home": float(row["sp_home"]), "draw": float(row["sp_draw"]), "away": float(row["sp_away"])}
            candidates = [{"option": option, "p": prediction[option], "odds": official[option],
                           "ev": prediction[option] * official[option] - 1} for option in prediction]
            best = max(candidates, key=lambda item: item["ev"])
            if best["ev"] >= self.limits.min_ev:
                stake = calculate_stake(bankroll, best["p"], best["odds"], self.limits,
                                        daily_staked.get(day, 0), weekly_staked.get(week, 0))
                if stake > 0:
                    profit = stake * (best["odds"] - 1) if best["option"] == outcome else -stake
                    bankroll += profit
                    daily_staked[day] = daily_staked.get(day, 0) + stake
                    weekly_staked[week] = weekly_staked.get(week, 0) + stake
                    bets.append({**best, "stake": stake, "profit": profit, "date": day})
            equity.append(round(bankroll, 2))
            elo.update(row["home_team"], row["away_team"], home_score, away_score)

        total_staked = sum(bet["stake"] for bet in bets)
        profit = bankroll - starting_bankroll
        metrics = {
            "matches": len(ordered), "bets": len(bets), "bet_rate": len(bets) / len(ordered),
            "starting_bankroll": starting_bankroll, "ending_bankroll": round(bankroll, 2),
            "profit": round(profit, 2), "roi": profit / total_staked if total_staked else 0.0,
            "max_drawdown": max_drawdown(equity), "brier_score": brier_score(predictions, outcomes),
            "log_loss": log_loss(predictions, outcomes),
            "ece": expected_calibration_error(predictions, outcomes),
            "win_rate": sum(bet["profit"] > 0 for bet in bets) / len(bets) if bets else 0.0,
        }
        return {"id": str(uuid.uuid4()), "parameters": {"min_ev": self.limits.min_ev, "bankroll": starting_bankroll},
                "metrics": metrics, "equity": equity, "bets": bets}
