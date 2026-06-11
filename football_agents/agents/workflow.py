from __future__ import annotations

from dataclasses import asdict
from typing import Any

from ..config import settings
from ..models import EloModel, EnsembleModel, PoissonModel
from ..models.ensemble import market_probabilities
from ..repository import Repository
from ..risk import CriticPolicy, RiskLimits, calculate_stake


class DecisionWorkflow:
    """Deterministic multi-agent state machine with an auditable evidence trail."""

    def __init__(self, repository: Repository | None = None, limits: RiskLimits | None = None) -> None:
        self.repository = repository or Repository()
        self.limits = limits or RiskLimits(
            min_ev=settings.min_ev,
            max_odds_age_minutes=settings.odds_max_age_minutes,
            max_single_fraction=settings.max_single_stake,
            max_daily_fraction=settings.max_daily_exposure,
            max_weekly_fraction=settings.max_weekly_exposure,
        )
        self.elo = EloModel()
        self.poisson = PoissonModel()
        self.ensemble = EnsembleModel()
        self.critic = CriticPolicy(self.limits)

    def evaluate(self, match_id: int, bankroll: float | None = None) -> dict[str, Any]:
        match = self.repository.get_match(match_id)
        if not match:
            raise KeyError(f"Match {match_id} not found")
        official = self.repository.latest_odds(match_id)
        market = self.repository.latest_odds(match_id, external=True)
        features = self.repository.latest_features(match_id)
        if len(official["odds"]) != 3:
            return self._blocked(match_id, "缺少完整的官方胜平负 SP 快照")
        if len(market["odds"]) != 3:
            return self._blocked(match_id, "缺少完整的外部市场赔率，无法进行市场校准")

        elo_prediction = self.elo.predict(
            match["home_team"], match["away_team"], features.get("home_rating"), features.get("away_rating")
        )
        poisson_prediction = self.poisson.predict(
            features.get("lambda_home", 1.45), features.get("lambda_away", 1.10)
        )
        market_prediction = market_probabilities(market["odds"])
        component_predictions = {
            "elo": elo_prediction,
            "poisson": poisson_prediction,
            "market": market_prediction,
        }
        ensemble_prediction = self.ensemble.predict(component_predictions)
        disagreement = self.ensemble.disagreement(component_predictions)
        for name, prediction in component_predictions.items():
            self.repository.add_prediction(match_id, name, prediction)
        self.repository.add_prediction(match_id, "ensemble", ensemble_prediction, {
            "weights": self.ensemble.weights, "disagreement": disagreement
        })

        candidates = []
        for option, probability in ensemble_prediction.items():
            sp = official["odds"][option]
            candidates.append({
                "option": option,
                "probability": probability,
                "sp": sp,
                "fair_odds": 1 / probability,
                "ev": probability * sp - 1,
            })
        best = max(candidates, key=lambda item: item["ev"])
        critic = self.critic.evaluate(
            odds_fetched_at=official["fetched_at"],
            source_confidence=features.get("source_confidence", 0.9),
            disagreement=disagreement,
            ev=best["ev"],
            match_status=match["status"],
            backtest_roi=features.get("backtest_roi"),
            daily_exposure_fraction=features.get("daily_exposure_fraction", 0),
            weekly_exposure_fraction=features.get("weekly_exposure_fraction", 0),
            consecutive_losses=features.get("consecutive_losses", 0),
        )
        self.repository.add_critic(match_id, critic)

        if critic["passed"]:
            status = "BET"
            confidence = "A" if best["ev"] >= 0.10 and disagreement <= 0.04 else "B"
            stake = calculate_stake(
                bankroll or settings.bankroll, best["probability"], best["sp"], self.limits,
                features.get("daily_exposure_fraction", 0) * (bankroll or settings.bankroll),
                features.get("weekly_exposure_fraction", 0) * (bankroll or settings.bankroll),
            )
        elif best["ev"] > 0 and critic["checks"].get("match_open", False):
            status, confidence, stake = "WATCH", "C", 0.0
        else:
            status, confidence, stake = "NO_BET", "NO_BET", 0.0
        reasons = critic["reasons"] or ["所有硬规则通过；仍需用户独立判断并理性预算"]
        signal = {**best, "status": status, "confidence": confidence, "stake": stake, "reasons": reasons}
        signal_id = self.repository.add_signal(match_id, signal)
        return {
            "signal_id": signal_id,
            "match": match,
            "models": component_predictions,
            "ensemble": ensemble_prediction,
            "model_disagreement": disagreement,
            "candidates": candidates,
            "critic": critic,
            "signal": signal,
            "risk_limits": asdict(self.limits),
        }

    def _blocked(self, match_id: int, reason: str) -> dict[str, Any]:
        critic = {"passed": False, "risk_level": "HIGH", "checks": {"required_data": False}, "reasons": [reason]}
        self.repository.add_critic(match_id, critic)
        signal = {"status": "NO_BET", "confidence": "NO_BET", "stake": 0.0, "reasons": [reason]}
        signal_id = self.repository.add_signal(match_id, signal)
        return {"signal_id": signal_id, "critic": critic, "signal": signal}

