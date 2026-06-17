from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from math import isfinite, log
from pathlib import Path
from statistics import mean, pstdev
from typing import Any, Iterable

from .models import EloModel, EnsembleModel, PoissonModel
from .models.ensemble import market_probabilities
from .multi_devig import calculate_multi_devig_probabilities
from .risk import RiskLimits, calculate_stake
from .true_odds_config import TrueOddsFilterConfig, generate_true_odds_config_grid, get_default_true_odds_filter_config
from .true_odds_engine import calculate_true_odds_estimate

OUTCOMES = ("home", "draw", "away")


@dataclass
class TrueOddsBacktestVariant:
    variant_id: str
    name: str
    config: TrueOddsFilterConfig
    description: str
    enabled: bool = True
    is_baseline: bool = False


@dataclass
class EdgeQualityBacktestRecord:
    match_id: str
    official_match_id: str
    kickoff_time: str
    league: str
    actual_result: str | None
    baseline_recommendation: str
    baseline_ev: float
    baseline_profit: float | None
    baseline_clv: float | None
    true_odds_recommendation: str
    true_odds_ev: float
    true_odds_profit: float | None
    true_odds_clv: float | None
    was_blocked_by_true_odds: bool
    block_reason: str | None
    edge_quality_score: float | None
    edge_quality_level: str | None
    lower_bound_ev: float | None
    adaptive_ev_threshold: float | None
    method_agreement_score: float | None
    recommended_devig_method: str | None
    outcome: str | None
    odds_bucket: str
    lower_bound_ev_bucket: str
    edge_quality_bucket: str
    market_quality: str | None
    model_disagreement_bucket: str | None
    passed_true_odds_filter: bool
    warnings: list[str] = field(default_factory=list)


@dataclass
class EdgeBucketPerformance:
    bucket_name: str
    bucket_type: str
    sample_count: int
    recommendation_count: int
    passed_count: int
    blocked_count: int
    roi: float | None
    average_clv: float | None
    positive_clv_rate: float | None
    hit_rate: float | None
    log_loss: float | None
    brier_score: float | None
    average_edge_quality_score: float | None
    average_lower_bound_ev: float | None
    max_drawdown: float | None
    warnings: list[str] = field(default_factory=list)


@dataclass
class BlockedRecommendationAnalysis:
    blocked_count: int
    blocked_ratio: float
    blocked_roi: float | None
    blocked_average_clv: float | None
    blocked_positive_clv_rate: float | None
    blocked_hit_rate: float | None
    blocked_average_expected_ev: float | None
    blocked_average_lower_bound_ev: float | None
    would_have_lost_count: int
    would_have_won_count: int
    estimated_loss_avoided: float | None
    summary: list[str]
    warnings: list[str] = field(default_factory=list)


@dataclass
class TrueOddsOptimizationResult:
    run_id: str
    created_at: str
    baseline_metrics: dict[str, Any]
    variant_results: list[dict[str, Any]]
    best_config: TrueOddsFilterConfig | None
    best_variant_id: str | None
    ranking: list[dict[str, Any]]
    blocked_analysis: BlockedRecommendationAnalysis
    bucket_performance: list[EdgeBucketPerformance]
    recommended_for_production: bool
    promotion_decision: str
    promotion_reasons: list[str]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _safe_mean(values: Iterable[float | None]) -> float | None:
    clean = [float(value) for value in values if value is not None and isfinite(float(value))]
    return mean(clean) if clean else None


def _safe_rate(values: Iterable[bool]) -> float | None:
    rows = list(values)
    return sum(rows) / len(rows) if rows else None


def _odds_bucket(odds: float) -> str:
    if odds < 1.30:
        return "1.01-1.30"
    if odds < 1.60:
        return "1.30-1.60"
    if odds < 2.00:
        return "1.60-2.00"
    if odds < 3.00:
        return "2.00-3.00"
    if odds < 5.00:
        return "3.00-5.00"
    return "5.00+"


def _lower_bucket(value: float | None) -> str:
    if value is None:
        return "UNKNOWN"
    if value <= 0:
        return "<=0"
    if value <= 0.005:
        return "0-0.005"
    if value <= 0.010:
        return "0.005-0.01"
    if value <= 0.020:
        return "0.01-0.02"
    return "0.02+"


def _score_bucket(value: float | None) -> str:
    if value is None:
        return "UNKNOWN"
    if value < 35:
        return "0-35"
    if value < 55:
        return "35-55"
    if value < 65:
        return "55-65"
    if value < 75:
        return "65-75"
    return "75+"


def _profit(stake: float, odds: float, option: str, outcome: str) -> float:
    return stake * (odds - 1) if option == outcome else -stake


def _clv(option: str, official: dict[str, float], closing: dict[str, float] | None) -> float | None:
    if not closing or option not in closing or float(closing[option]) <= 1:
        return None
    return float(official[option]) / float(closing[option]) - 1


def _finite_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    return {key: (0.0 if isinstance(value, float) and not isfinite(value) else value) for key, value in metrics.items()}


def _log_loss(probability: dict[str, float], outcome: str) -> float:
    return -log(max(1e-15, min(1 - 1e-15, probability[outcome])))


def _brier(probability: dict[str, float], outcome: str) -> float:
    return sum((probability[key] - float(key == outcome)) ** 2 for key in OUTCOMES) / 3


def _make_base_rows(rows: Iterable[dict[str, Any]], bankroll: float, min_ev: float) -> list[dict[str, Any]]:
    ordered = sorted(list(rows), key=lambda row: str(row.get("date") or row.get("kickoff_time") or row.get("kickoffTime") or ""))
    elo, poisson, ensemble = EloModel(), PoissonModel(), EnsembleModel()
    output: list[dict[str, Any]] = []
    for index, row in enumerate(ordered, 1):
        home = str(row.get("home_team") or row.get("homeTeam"))
        away = str(row.get("away_team") or row.get("awayTeam"))
        date = str(row.get("date") or row.get("kickoff_time") or row.get("kickoffTime") or index)
        league = str(row.get("league") or "UNKNOWN")
        official = {"home": float(row.get("sp_home") or row.get("home") or row.get("official_home") or 2.0),
                    "draw": float(row.get("sp_draw") or row.get("draw") or row.get("official_draw") or 3.2),
                    "away": float(row.get("sp_away") or row.get("away") or row.get("official_away") or 3.4)}
        closing = None
        if row.get("closing_home") or row.get("closing_sp_home"):
            closing = {"home": float(row.get("closing_home") or row.get("closing_sp_home")),
                       "draw": float(row.get("closing_draw") or row.get("closing_sp_draw")),
                       "away": float(row.get("closing_away") or row.get("closing_sp_away"))}
        home_score = int(row.get("home_score") if row.get("home_score") is not None else row.get("homeGoals", 0))
        away_score = int(row.get("away_score") if row.get("away_score") is not None else row.get("awayGoals", 0))
        outcome = "home" if home_score > away_score else "draw" if home_score == away_score else "away"
        elo_p = elo.predict(home, away)
        lambda_home = float(row.get("lambda_home") or max(0.45, 1.35 + (elo.rating(home) - elo.rating(away)) / 700))
        lambda_away = float(row.get("lambda_away") or max(0.35, 1.05 - (elo.rating(home) - elo.rating(away)) / 900))
        poisson_p = poisson.predict(lambda_home, lambda_away)
        market_odds = {"home": float(row.get("market_home") or official["home"]),
                       "draw": float(row.get("market_draw") or official["draw"]),
                       "away": float(row.get("market_away") or official["away"])}
        market_p = market_probabilities(market_odds)
        final_p = ensemble.predict({"elo": elo_p, "poisson": poisson_p, "market": market_p})
        candidates = [{"option": option, "p": final_p[option], "odds": official[option], "ev": final_p[option] * official[option] - 1} for option in OUTCOMES]
        best = max(candidates, key=lambda item: item["ev"])
        baseline_recommendation = best["option"] if best["ev"] >= min_ev else "NO_BET"
        output.append({
            "match_id": str(row.get("id") or index),
            "official_match_id": str(row.get("official_match_id") or row.get("officialMatchId") or index),
            "kickoff_time": date,
            "league": league,
            "home_team": home,
            "away_team": away,
            "official": official,
            "closing": closing,
            "outcome": outcome,
            "final_probability": final_p,
            "market_probability": market_p,
            "pure_probability": ensemble.predict({"elo": elo_p, "poisson": poisson_p}),
            "best": best,
            "baseline_recommendation": baseline_recommendation,
            "lambda_home": lambda_home,
            "lambda_away": lambda_away,
            "bankroll": bankroll,
        })
        elo.update(home, away, home_score, away_score)
    return output


def _passes_config(edge: Any, estimate: Any, config: TrueOddsFilterConfig) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if edge.lower_bound_ev < config.lower_bound_ev_min:
        reasons.append("lowerBoundEV below config minimum")
    if edge.edge_quality_score < config.edge_quality_min_score:
        reasons.append("edgeQualityScore below config minimum")
    if edge.edge_quality_level not in config.allowed_edge_quality_levels:
        reasons.append("edgeQualityLevel not allowed")
    if estimate.market_multi_devig.method_agreement_score < config.min_method_agreement_score:
        reasons.append("methodAgreementScore below config minimum")
    if config.require_positive_expected_clv and (edge.expected_closing_edge is None or edge.expected_closing_edge <= 0):
        reasons.append("expected closing edge not positive")
    if config.min_clv_win_probability is not None and (edge.clv_win_probability is None or edge.clv_win_probability < config.min_clv_win_probability):
        reasons.append("clvWinProbability below config minimum")
    return not reasons, reasons


def _records_for_config(base_rows: list[dict[str, Any]], config: TrueOddsFilterConfig, starting_bankroll: float) -> list[EdgeQualityBacktestRecord]:
    bankroll_baseline = starting_bankroll
    bankroll_filter = starting_bankroll
    records: list[EdgeQualityBacktestRecord] = []
    for row in base_rows:
        best = row["best"]
        option = best["option"]
        baseline_is_bet = row["baseline_recommendation"] != "NO_BET"
        estimate = calculate_true_odds_estimate(
            {"id": row["match_id"], "official_match_id": row["official_match_id"], "league": row["league"]},
            {"officialSp": row["official"], "finalProbability": row["final_probability"], "pureModelProbability": row["pure_probability"],
             "externalMarketProbability": row["market_probability"], "features": {"lambda_home": row["lambda_home"], "lambda_away": row["lambda_away"], "source_confidence": 0.8}},
            {"selected_outcome": option.upper(), "selected_odds": best["odds"], "model_disagreement": "LOW", "external_market_quality": "MEDIUM"},
        )
        edge = estimate.edge_quality_by_outcome[option.upper()]
        passed_config, config_reasons = _passes_config(edge, estimate, config)
        true_is_bet = baseline_is_bet and (config.mode == "SHADOW" or passed_config)
        true_recommendation = row["baseline_recommendation"] if true_is_bet else "NO_BET"
        stake = calculate_stake(bankroll_baseline, best["p"], best["odds"], RiskLimits(min_ev=0.0), 0, 0) if baseline_is_bet else 0
        baseline_profit = _profit(stake, best["odds"], option, row["outcome"]) if baseline_is_bet and stake > 0 else None
        if baseline_profit is not None:
            bankroll_baseline += baseline_profit
        true_stake = calculate_stake(bankroll_filter, best["p"], best["odds"], RiskLimits(min_ev=0.0), 0, 0) if true_is_bet else 0
        true_profit = _profit(true_stake, best["odds"], option, row["outcome"]) if true_is_bet and true_stake > 0 else None
        if true_profit is not None:
            bankroll_filter += true_profit
        blocked = baseline_is_bet and not true_is_bet
        records.append(EdgeQualityBacktestRecord(
            match_id=row["match_id"], official_match_id=row["official_match_id"], kickoff_time=row["kickoff_time"], league=row["league"],
            actual_result=row["outcome"].upper(),
            baseline_recommendation=row["baseline_recommendation"].upper() if row["baseline_recommendation"] != "NO_BET" else "NO_BET",
            baseline_ev=best["ev"], baseline_profit=baseline_profit, baseline_clv=_clv(option, row["official"], row["closing"]) if baseline_is_bet else None,
            true_odds_recommendation=true_recommendation.upper() if true_recommendation != "NO_BET" else "NO_BET",
            true_odds_ev=best["ev"] if true_is_bet else 0.0, true_odds_profit=true_profit, true_odds_clv=_clv(option, row["official"], row["closing"]) if true_is_bet else None,
            was_blocked_by_true_odds=blocked, block_reason="; ".join(config_reasons) if blocked else None,
            edge_quality_score=edge.edge_quality_score, edge_quality_level=edge.edge_quality_level, lower_bound_ev=edge.lower_bound_ev,
            adaptive_ev_threshold=edge.adaptive_threshold, method_agreement_score=estimate.market_multi_devig.method_agreement_score,
            recommended_devig_method=estimate.market_multi_devig.recommended_method, outcome=option.upper(), odds_bucket=_odds_bucket(best["odds"]),
            lower_bound_ev_bucket=_lower_bucket(edge.lower_bound_ev), edge_quality_bucket=_score_bucket(edge.edge_quality_score),
            market_quality="MEDIUM", model_disagreement_bucket="LOW", passed_true_odds_filter=passed_config,
            warnings=[*estimate.warnings, *config_reasons],
        ))
    return records


def calculate_true_odds_variant_metrics(records: list[EdgeQualityBacktestRecord]) -> dict[str, Any]:
    bets = [row for row in records if row.true_odds_recommendation != "NO_BET"]
    baseline_bets = [row for row in records if row.baseline_recommendation != "NO_BET"]
    total_profit = sum(row.true_odds_profit or 0 for row in bets)
    total_stake = len(bets) or 0
    baseline_profit = sum(row.baseline_profit or 0 for row in baseline_bets)
    profits = [row.true_odds_profit or 0 for row in bets]
    equity = [0.0]
    for profit in profits:
        equity.append(equity[-1] + profit)
    clvs = [row.true_odds_clv for row in bets if row.true_odds_clv is not None]
    lower = [row.lower_bound_ev for row in records if row.lower_bound_ev is not None]
    scores = [row.edge_quality_score for row in records if row.edge_quality_score is not None]
    hit_rows = [row for row in bets if row.actual_result and row.outcome]
    metrics = {
        "sample_count": len(records),
        "recommendation_count": len(bets),
        "baseline_recommendation_count": len(baseline_bets),
        "no_bet_count": len(records) - len(bets),
        "no_bet_ratio": (len(records) - len(bets)) / len(records) if records else 0.0,
        "blocked_count": sum(row.was_blocked_by_true_odds for row in records),
        "blocked_ratio": sum(row.was_blocked_by_true_odds for row in records) / len(baseline_bets) if baseline_bets else 0.0,
        "roi": total_profit / total_stake if total_stake else 0.0,
        "risk_adjusted_roi": (total_profit / total_stake) / (pstdev(profits) or 1) if total_stake else 0.0,
        "average_clv": _safe_mean(clvs) or 0.0,
        "positive_clv_rate": _safe_rate([float(clv) > 0 for clv in clvs]) or 0.0,
        "hit_rate": _safe_rate([row.outcome == row.actual_result for row in hit_rows]) or 0.0,
        "log_loss": 0.0,
        "brier_score": 0.0,
        "calibration_error": 0.0,
        "max_drawdown": max(0.0, max(equity) - min(equity)) if equity else 0.0,
        "longest_losing_streak": _longest_losing_streak(profits),
        "average_edge_quality_score": _safe_mean(scores) or 0.0,
        "average_lower_bound_ev": _safe_mean(lower) or 0.0,
        "lower_bound_ev_positive_rate": _safe_rate([float(value) > 0 for value in lower]) or 0.0,
        "average_adaptive_threshold": _safe_mean(row.adaptive_ev_threshold for row in records) or 0.0,
        "high_edge_count": sum(row.edge_quality_level == "HIGH" for row in records),
        "medium_edge_count": sum(row.edge_quality_level == "MEDIUM" for row in records),
        "low_edge_count": sum(row.edge_quality_level == "LOW" for row in records),
        "no_edge_count": sum(row.edge_quality_level == "NO_EDGE" for row in records),
        "baseline_profit": baseline_profit,
    }
    return _finite_metrics(metrics)


def _longest_losing_streak(profits: list[float]) -> int:
    longest = current = 0
    for profit in profits:
        if profit < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def analyze_blocked_recommendations(records: list[EdgeQualityBacktestRecord]) -> BlockedRecommendationAnalysis:
    baseline_bets = [row for row in records if row.baseline_recommendation != "NO_BET"]
    blocked = [row for row in records if row.was_blocked_by_true_odds]
    profits = [row.baseline_profit for row in blocked if row.baseline_profit is not None]
    clvs = [row.baseline_clv for row in blocked if row.baseline_clv is not None]
    roi = sum(profits) / len(profits) if profits else None
    avg_clv = _safe_mean(clvs)
    lower = _safe_mean(row.lower_bound_ev for row in blocked)
    ev = _safe_mean(row.baseline_ev for row in blocked)
    would_lost = sum((row.baseline_profit or 0) < 0 for row in blocked)
    would_won = sum((row.baseline_profit or 0) > 0 for row in blocked)
    warnings = ["blocked_count is small; do not over-interpret"] if len(blocked) < 10 else []
    summary = [
        f"True Odds Filter blocked {len(blocked)} recommendations, {((len(blocked) / len(baseline_bets)) * 100 if baseline_bets else 0):.1f}% of baseline recommendations.",
        f"Blocked average CLV is {(avg_clv * 100):.2f}%." if avg_clv is not None else "Blocked CLV is unavailable.",
        "Blocked recommendations were net losing in this sample." if roi is not None and roi < 0 else "Blocked recommendations were not clearly losing; treat filter as conservative.",
    ]
    return BlockedRecommendationAnalysis(
        blocked_count=len(blocked), blocked_ratio=len(blocked) / len(baseline_bets) if baseline_bets else 0.0,
        blocked_roi=roi, blocked_average_clv=avg_clv, blocked_positive_clv_rate=_safe_rate([float(clv) > 0 for clv in clvs]),
        blocked_hit_rate=_safe_rate([row.outcome == row.actual_result for row in blocked if row.outcome and row.actual_result]),
        blocked_average_expected_ev=ev, blocked_average_lower_bound_ev=lower, would_have_lost_count=would_lost,
        would_have_won_count=would_won, estimated_loss_avoided=-(sum(profits)) if profits else None, summary=summary, warnings=warnings,
    )


def _bucket_metrics(bucket_type: str, bucket_name: str, rows: list[EdgeQualityBacktestRecord]) -> EdgeBucketPerformance:
    metrics = calculate_true_odds_variant_metrics(rows)
    return EdgeBucketPerformance(
        bucket_name=bucket_name, bucket_type=bucket_type, sample_count=len(rows),
        recommendation_count=metrics["recommendation_count"], passed_count=sum(row.passed_true_odds_filter for row in rows),
        blocked_count=metrics["blocked_count"], roi=metrics["roi"], average_clv=metrics["average_clv"],
        positive_clv_rate=metrics["positive_clv_rate"], hit_rate=metrics["hit_rate"], log_loss=metrics["log_loss"],
        brier_score=metrics["brier_score"], average_edge_quality_score=metrics["average_edge_quality_score"],
        average_lower_bound_ev=metrics["average_lower_bound_ev"], max_drawdown=metrics["max_drawdown"],
        warnings=[] if len(rows) >= 10 else ["small bucket sample"],
    )


def build_edge_bucket_performance(records: list[EdgeQualityBacktestRecord]) -> list[EdgeBucketPerformance]:
    dimensions = {
        "edgeQualityLevel": lambda row: row.edge_quality_level or "UNKNOWN",
        "lowerBoundEV": lambda row: row.lower_bound_ev_bucket,
        "edgeQualityScore": lambda row: row.edge_quality_bucket,
        "devigMethod": lambda row: row.recommended_devig_method or "UNKNOWN",
        "methodAgreement": lambda row: "HIGH" if (row.method_agreement_score or 0) >= 0.75 else "MEDIUM" if (row.method_agreement_score or 0) >= 0.55 else "LOW",
        "outcome": lambda row: row.outcome or "UNKNOWN",
        "oddsBucket": lambda row: row.odds_bucket,
        "league": lambda row: row.league,
        "marketQuality": lambda row: row.market_quality or "UNKNOWN",
    }
    output: list[EdgeBucketPerformance] = []
    for bucket_type, getter in dimensions.items():
        groups: dict[str, list[EdgeQualityBacktestRecord]] = {}
        for row in records:
            groups.setdefault(getter(row), []).append(row)
        output.extend(_bucket_metrics(bucket_type, name, rows) for name, rows in sorted(groups.items()))
    return output


def rank_true_odds_variants(baseline_metrics: dict[str, Any], variant_results: list[dict[str, Any]], options: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    ranking: list[dict[str, Any]] = []
    for result in variant_results:
        metrics = result["metrics"]
        score = 0.0
        reasons: list[str] = []
        score += min(25, max(0, (metrics["positive_clv_rate"] - baseline_metrics.get("positive_clv_rate", 0)) * 100))
        score += min(20, max(0, (metrics["average_clv"] - baseline_metrics.get("average_clv", 0)) * 400))
        score += min(20, max(0, (metrics["roi"] - baseline_metrics.get("roi", 0)) * 100))
        score += min(15, max(0, (baseline_metrics.get("max_drawdown", 0) - metrics["max_drawdown"]) * 100))
        score += min(10, metrics["lower_bound_ev_positive_rate"] * 10)
        score += min(10, metrics["average_edge_quality_score"] / 10)
        score += min(10, metrics["blocked_ratio"] * 20)
        if metrics["recommendation_count"] < 30:
            score -= 20
            reasons.append("recommendation_count < 30")
        if metrics["no_bet_ratio"] > 0.90:
            score -= 15
            reasons.append("no_bet_ratio > 90%")
        if metrics["sample_count"] < int((options or {}).get("min_samples", 200)):
            score -= 25
            reasons.append("sample_count below minimum")
        if metrics["positive_clv_rate"] <= baseline_metrics.get("positive_clv_rate", 0):
            reasons.append("positive CLV rate did not improve")
        if metrics["average_clv"] <= baseline_metrics.get("average_clv", 0) and metrics["roi"] <= baseline_metrics.get("roi", 0):
            reasons.append("average CLV and ROI did not improve")
        ranking.append({"variant_id": result["variant_id"], "name": result["name"], "score": round(score, 4), "metrics": metrics, "reasons": reasons, "config": result["config"]})
    return sorted(ranking, key=lambda row: row["score"], reverse=True)


def _baseline_metrics(base_rows: list[dict[str, Any]], starting_bankroll: float) -> dict[str, Any]:
    default = get_default_true_odds_filter_config()
    records = _records_for_config(base_rows, default, starting_bankroll)
    for row in records:
        row.true_odds_recommendation = row.baseline_recommendation
        row.true_odds_profit = row.baseline_profit
        row.true_odds_clv = row.baseline_clv
        row.was_blocked_by_true_odds = False
    return calculate_true_odds_variant_metrics(records)


def run_edge_quality_optimization(historical_matches: Iterable[dict[str, Any]], predictions_or_backtest_input: Any = None, configs: list[TrueOddsFilterConfig] | None = None, options: dict[str, Any] | None = None) -> TrueOddsOptimizationResult:
    options = options or {}
    bankroll = float(options.get("bankroll") or 10_000)
    min_ev = float(options.get("min_ev") or 0.05)
    base_rows = _make_base_rows(historical_matches, bankroll, min_ev)
    configs = configs or generate_true_odds_config_grid({"max_configs": options.get("max_configs", 50), "shadow_only": options.get("shadow_only", False)})
    baseline = _baseline_metrics(base_rows, bankroll)
    variant_results: list[dict[str, Any]] = []
    all_records_by_variant: dict[str, list[EdgeQualityBacktestRecord]] = {}
    for config in configs:
        records = _records_for_config(base_rows, config, bankroll)
        metrics = calculate_true_odds_variant_metrics(records)
        all_records_by_variant[config.config_id] = records
        variant_results.append({"variant_id": config.config_id, "name": config.name, "description": config.name, "config": config.to_dict(), "metrics": metrics})
    ranking = rank_true_odds_variants(baseline, variant_results, {"min_samples": options.get("min_samples", 200)})
    best = ranking[0] if ranking else None
    best_config = next((config for config in configs if best and config.config_id == best["variant_id"]), None)
    best_records = all_records_by_variant.get(best["variant_id"], []) if best else []
    blocked = analyze_blocked_recommendations(best_records)
    bucket = build_edge_bucket_performance(best_records)
    warnings: list[str] = []
    min_samples = int(options.get("min_samples", 200))
    decision = "KEEP_CURRENT"
    recommended = False
    reasons: list[str] = []
    if len(base_rows) < min_samples:
        decision = "NEED_MORE_DATA"
        reasons.append("sample_count below minimum")
    elif not best:
        decision = "NEED_MORE_DATA"
        reasons.append("no valid variant")
    else:
        metrics = best["metrics"]
        if metrics["recommendation_count"] < 30:
            decision = "NEED_MORE_DATA"
            reasons.append("recommendation_count < 30")
        elif metrics["no_bet_ratio"] > 0.90:
            decision = "SHADOW_ONLY"
            reasons.append("no_bet_ratio > 90%")
        elif metrics["positive_clv_rate"] > baseline.get("positive_clv_rate", 0) and (metrics["average_clv"] > baseline.get("average_clv", 0) or metrics["roi"] > baseline.get("roi", 0)):
            decision = "ENABLE_FILTER_ONLY"
            recommended = best_config is not None and best_config.mode != "ADJUST_PROBABILITY"
            reasons.append("CLV or ROI improved with acceptable recommendation count")
        elif best["score"] > 0:
            decision = "SHADOW_ONLY"
            reasons.append("potential improvement but not enough for production enablement")
        else:
            decision = "REJECT_TRUE_ODDS_FILTER"
            reasons.append("variant ranking did not improve quality metrics")
    if best_config and best_config.mode == "ADJUST_PROBABILITY":
        recommended = False
        warnings.append("ADJUST_PROBABILITY is never auto-promoted")
    return TrueOddsOptimizationResult(str(uuid.uuid4()), datetime.now(timezone.utc).isoformat(), baseline, variant_results, best_config, best["variant_id"] if best else None, ranking, blocked, bucket, recommended, decision, reasons, warnings)


def write_optimization_json(result: TrueOddsOptimizationResult, path: str | Path) -> None:
    Path(path).write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
