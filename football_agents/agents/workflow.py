from __future__ import annotations

from dataclasses import asdict
from typing import Any

from ..config import settings
from ..models import EloModel, EnsembleModel, PoissonModel
from ..models.ensemble import market_probabilities
from ..repository import Repository
from ..risk import CriticPolicy, RiskLimits, calculate_stake
from ..true_odds_engine import calculate_true_odds_estimate, selected_outcome_passes


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
        limits = self._current_limits()
        match = self.repository.get_match(match_id)
        if not match:
            raise KeyError(f"Match {match_id} not found")
        official = self.repository.latest_odds(match_id)
        market = self.repository.latest_odds(match_id, external=True)
        features = self.repository.latest_features(match_id)
        if len(official["odds"]) != 3:
            return self._blocked(match_id, "缺少完整的官方胜平负 SP 快照")
        required_features = {"home_rating", "away_rating", "lambda_home", "lambda_away"}
        missing_features = sorted(required_features - features.keys())
        if missing_features:
            return self._blocked(match_id, f"缺少真实球队特征：{', '.join(missing_features)}；禁止使用默认参数生成同质化预测")

        elo_prediction = self.elo.predict(
            match["home_team"], match["away_team"], features["home_rating"], features["away_rating"]
        )
        poisson_prediction = self.poisson.predict(
            features["lambda_home"], features["lambda_away"]
        )
        self.repository.add_prediction(match_id, "elo", elo_prediction)
        self.repository.add_prediction(match_id, "poisson", poisson_prediction)
        baseline = self.ensemble.predict({"elo": elo_prediction, "poisson": poisson_prediction})
        baseline_fair_odds = {option: 1 / probability for option, probability in baseline.items()}
        self.repository.add_prediction(match_id, "baseline", baseline, {
            "market_calibrated": False, "fair_odds": baseline_fair_odds,
        })
        if len(market["odds"]) != 3:
            blocked = self._blocked(match_id, "缺少完整的外部市场赔率，基线模型已生成但禁止计算 EV 与推荐")
            return {**blocked, "models": {"elo": elo_prediction, "poisson": poisson_prediction},
                    "baseline": baseline, "fair_odds": baseline_fair_odds, "market_calibrated": False}

        market_prediction = market_probabilities(market["odds"])
        component_predictions = {
            "elo": elo_prediction,
            "poisson": poisson_prediction,
            "market": market_prediction,
        }
        ensemble_prediction = self.ensemble.predict(component_predictions)
        disagreement = self.ensemble.disagreement(component_predictions)
        self.repository.add_prediction(match_id, "market", market_prediction)
        llm_analysis = self.repository.latest_llm_analysis(match_id)
        contextual_prediction, context_metadata = self._apply_llm_context(ensemble_prediction, llm_analysis)
        self.repository.add_prediction(match_id, "ensemble", ensemble_prediction, {
            "weights": self.ensemble.weights, "disagreement": disagreement,
            "fair_odds": {option: 1 / probability for option, probability in ensemble_prediction.items()},
        })
        if context_metadata["applied"]:
            ensemble_prediction = contextual_prediction
            self.repository.add_prediction(match_id, "contextual_ensemble", ensemble_prediction, {
                "weights": self.ensemble.weights, "disagreement": disagreement,
                "fair_odds": {option: 1 / probability for option, probability in ensemble_prediction.items()},
                "qwen_context": context_metadata,
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
        critic = CriticPolicy(limits).evaluate(
            odds_fetched_at=official["fetched_at"],
            source_confidence=features.get("source_confidence", 0.9),
            disagreement=disagreement,
            ev=best["ev"],
            match_status=match["status"],
            kickoff_time=match["kickoff_time"],
            backtest_roi=features.get("backtest_roi"),
            daily_exposure_fraction=features.get("daily_exposure_fraction", 0),
            weekly_exposure_fraction=features.get("weekly_exposure_fraction", 0),
            consecutive_losses=features.get("consecutive_losses", 0),
        )
        true_odds = calculate_true_odds_estimate(match, {
            "officialSp": official["odds"],
            "externalOdds": market["odds"],
            "finalProbability": ensemble_prediction,
            "pureModelProbability": baseline,
            "externalMarketProbability": market_prediction,
            "features": features,
        }, {
            "selected_outcome": best["option"].upper(),
            "selected_odds": best["sp"],
            "model_disagreement": "HIGH" if disagreement > 0.08 else "MEDIUM" if disagreement > 0.04 else "LOW",
            "external_market_quality": "MEDIUM",
            "pure_model_reliability": "LOW" if min(features.get("home_recent_matches", 0), features.get("away_recent_matches", 0)) < 10 else "MEDIUM",
            "sample_size": "LOW" if min(features.get("home_recent_matches", 0), features.get("away_recent_matches", 0)) < 10 else "MEDIUM",
        })
        true_edge = true_odds.edge_quality_by_outcome.get(best["option"].upper())
        if true_edge and not true_edge.passes_true_odds_filter:
            critic = {
                **critic,
                "passed": False,
                "reasons": list(dict.fromkeys([*critic.get("reasons", []), *true_edge.reasons, "True Odds 过滤未通过"])),
                "checks": {**critic.get("checks", {}), "true_odds_filter": False},
            }
        else:
            critic = {**critic, "checks": {**critic.get("checks", {}), "true_odds_filter": True}}
        self.repository.add_critic(match_id, critic)

        if critic["passed"] and selected_outcome_passes(true_odds, best["option"]):
            status = "BET"
            confidence = "A" if best["ev"] >= 0.10 and disagreement <= 0.04 else "B"
            stake = calculate_stake(
                bankroll or settings.bankroll, best["probability"], best["sp"], limits,
                features.get("daily_exposure_fraction", 0) * (bankroll or settings.bankroll),
                features.get("weekly_exposure_fraction", 0) * (bankroll or settings.bankroll),
            )
        elif best["ev"] > 0 and critic["checks"].get("match_open", False):
            status, confidence, stake = "WATCH", "C", 0.0
        else:
            status, confidence, stake = "NO_BET", "NO_BET", 0.0
        reasons = critic["reasons"] or ["所有硬规则通过；仍需用户独立判断并理性预算"]
        signal = {**best, "status": status, "confidence": confidence, "stake": stake, "reasons": reasons,
                  "true_odds_estimate": true_odds.to_dict(),
                  "edge_quality": asdict(true_edge) if true_edge else None,
                  "lower_bound_ev": true_edge.lower_bound_ev if true_edge else None,
                  "adaptive_ev_threshold": true_edge.adaptive_threshold if true_edge else None,
                  "passes_true_odds_filter": bool(true_edge and true_edge.passes_true_odds_filter)}
        signal_id = self.repository.add_signal(match_id, signal)
        return {
            "signal_id": signal_id,
            "match": match,
            "models": component_predictions,
            "ensemble": ensemble_prediction,
            "fair_odds": {option: 1 / probability for option, probability in ensemble_prediction.items()},
            "market_calibrated": True,
            "model_disagreement": disagreement,
            "candidates": candidates,
            "critic": critic,
            "signal": signal,
            "true_odds_estimate": true_odds.to_dict(),
            "risk_limits": asdict(limits),
            "qwen_context": context_metadata,
        }

    @staticmethod
    def _apply_llm_context(probabilities: dict[str, float], llm_analysis: dict[str, Any] | None
                           ) -> tuple[dict[str, float], dict[str, Any]]:
        if not llm_analysis:
            return probabilities, {"applied": False, "reason": "no_analysis"}
        analysis = llm_analysis.get("analysis", {})
        confidence = float(analysis.get("news_confidence", 0))
        evidence = analysis.get("evidence") or []
        if confidence < 0.4 or not evidence:
            return probabilities, {"applied": False, "reason": "insufficient_evidence",
                                   "confidence": confidence}
        home_delta = max(-0.08, min(0.08, float(analysis.get("home_team_impact", 0)))) * confidence
        away_delta = max(-0.08, min(0.08, float(analysis.get("away_team_impact", 0)))) * confidence
        adjusted = {
            "home": max(0.01, probabilities["home"] + home_delta),
            "draw": max(0.01, probabilities["draw"]),
            "away": max(0.01, probabilities["away"] + away_delta),
        }
        total = sum(adjusted.values())
        normalized = {key: value / total for key, value in adjusted.items()}
        return normalized, {"applied": True, "provider": llm_analysis.get("provider"),
                            "model": llm_analysis.get("model"), "confidence": confidence,
                            "home_delta": home_delta, "away_delta": away_delta,
                            "analysis_id": llm_analysis.get("id")}

    def _current_limits(self) -> RiskLimits:
        saved = self.repository.get_settings().get("rules", {})
        return RiskLimits(
            min_ev=float(saved.get("min_ev", self.limits.min_ev)),
            max_odds_age_minutes=int(saved.get("odds_max_age_minutes", self.limits.max_odds_age_minutes)),
            max_single_fraction=float(saved.get("max_single_stake", self.limits.max_single_fraction)),
            max_daily_fraction=float(saved.get("max_daily_exposure", self.limits.max_daily_fraction)),
            max_weekly_fraction=float(saved.get("max_weekly_exposure", self.limits.max_weekly_fraction)),
        )

    def _blocked(self, match_id: int, reason: str) -> dict[str, Any]:
        critic = {"passed": False, "risk_level": "HIGH", "checks": {"required_data": False}, "reasons": [reason]}
        self.repository.add_critic(match_id, critic)
        signal = {"status": "NO_BET", "confidence": "NO_BET", "stake": 0.0, "reasons": [reason]}
        signal_id = self.repository.add_signal(match_id, signal)
        return {"signal_id": signal_id, "critic": critic, "signal": signal}

