from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from .adaptive_threshold import calculate_adaptive_ev_threshold
from .closing_line_proxy import ClosingLineProxy, build_closing_line_proxy
from .draw_calibrator import calibrate_draw_probability
from .edge_quality import EdgeQualityOutput, calculate_edge_quality
from .market_bias import MarketBiasBucket, apply_market_bias_correction, build_market_bias_buckets
from .multi_devig import OUTCOMES, MultiDevigResult, Probability, _fair_odds, _normalize, calculate_multi_devig_probabilities
from .probability_uncertainty import ProbabilityUncertainty, estimate_probability_uncertainty
from .real_ev import anchor_real_probability, diagnostics_to_dict, real_ev_by_outcome


@dataclass
class TrueOddsEstimate:
    match_id: str
    official_match_id: str
    created_at: str
    market_multi_devig: MultiDevigResult
    external_multi_devig: MultiDevigResult | None
    base_probability: Probability
    bias_corrected_probability: Probability
    uncertainty: ProbabilityUncertainty
    true_probability_estimate: Probability
    true_fair_odds: dict[str, float]
    edge_quality_by_outcome: dict[str, EdgeQualityOutput]
    selected_edge: EdgeQualityOutput
    closing_line_proxy: ClosingLineProxy | None
    market_bias_bucket: MarketBiasBucket | None
    draw_calibration: dict[str, Any] | None
    real_ev: dict[str, float]
    real_ev_calibration: dict[str, Any]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _outcome_to_key(outcome: str) -> str:
    upper = outcome.upper()
    return {"HOME": "home", "DRAW": "draw", "AWAY": "away"}.get(upper, outcome.lower())


def _no_bet_edge(threshold: float, reason: str) -> EdgeQualityOutput:
    return EdgeQualityOutput("NO_BET", 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, None, None, 0.0, "NO_EDGE", "HIGH", threshold, False, [reason], [])


def calculate_true_odds_estimate(match: dict[str, Any], prediction: dict[str, Any], context: dict[str, Any] | None = None, historical_records: list[dict[str, Any]] | None = None, closing_context: dict[str, Any] | None = None, options: dict[str, Any] | None = None) -> TrueOddsEstimate:
    context = context or {}
    options = options or {}
    warnings: list[str] = []
    official_sp = prediction.get("officialSp") or prediction.get("official_sp") or prediction.get("official_odds") or {}
    market_multi = calculate_multi_devig_probabilities(official_sp, {"source": "official_sp"})
    external_multi = None
    external_odds = prediction.get("externalOdds") or prediction.get("external_odds")
    if external_odds:
        external_multi = calculate_multi_devig_probabilities(external_odds, {"source": "external_market"})
    base = _normalize(prediction.get("finalProbability") or prediction.get("final_probability") or prediction.get("ensemble") or market_multi.recommended_probability) or market_multi.recommended_probability
    features = prediction.get("features") or {}
    draw_features = {
        "lambda_home": features.get("lambda_home"),
        "lambda_away": features.get("lambda_away"),
        "league_draw_rate": features.get("league_draw_rate"),
        "sample_count": features.get("league_match_count") or features.get("sample_count") or 0,
    }
    draw_calibrated, draw_details = calibrate_draw_probability(base, draw_features)
    bias_bucket = None
    bias_buckets = build_market_bias_buckets(historical_records or []) if historical_records else []
    bias_corrected, bias_bucket, bias_warnings = apply_market_bias_correction(draw_calibrated, {"league": match.get("league"), "outcome": context.get("selected_outcome"), "odds": context.get("selected_odds", 2)}, bias_buckets)
    warnings.extend(bias_warnings)
    sample_reliability = min(1.0, max(0.0, float(features.get("source_confidence") or features.get("sample_reliability") or 0.5)))
    market_prior = market_multi.recommended_probability
    if external_multi:
        external = external_multi.recommended_probability
        market_prior = _normalize({
            key: 0.55 * market_prior[key] + 0.45 * external[key]
            for key in OUTCOMES
        }) or market_prior
    true_probability, real_diagnostics = anchor_real_probability(
        bias_corrected, market_prior, market_multi.odds, reliability=sample_reliability
    )
    warnings.extend(real_diagnostics.warnings)
    uncertainty = estimate_probability_uncertainty({
        "marketProbability": market_multi.recommended_probability,
        "externalMarketProbability": (external_multi.recommended_probability if external_multi else prediction.get("externalMarketProbability") or prediction.get("external_market_probability")),
        "pureModelProbability": prediction.get("pureModelProbability") or prediction.get("pure_model_probability"),
        "finalProbability": true_probability,
    }, market_multi, {
        "sample_reliability": sample_reliability,
        "lineup_risk": context.get("lineup_risk"),
        "fatigue_risk": context.get("fatigue_risk"),
    })
    closing_proxy = None
    if closing_context and closing_context.get("allow_closing_proxy"):
        closing_proxy = build_closing_line_proxy({"sp": official_sp}, closing_context.get("closing_snapshot"), str(context.get("selected_outcome") or "HOME"))
    elif closing_context and closing_context.get("closing_snapshot"):
        warnings.append("closing line provided but ignored because allow_closing_proxy is false")
    edge_by_outcome: dict[str, EdgeQualityOutput] = {}
    for key in OUTCOMES:
        outcome = key.upper()
        threshold = calculate_adaptive_ev_threshold(
            {"outcome": outcome, "odds": official_sp.get(key, 0), "leagueSample": context.get("league_sample")},
            {
                "modelDisagreement": context.get("model_disagreement"),
                "pureModelReliability": context.get("pure_model_reliability"),
                "lineupRisk": context.get("lineup_risk"),
                "fatigueRisk": context.get("fatigue_risk"),
            },
            {"externalMarketQuality": context.get("external_market_quality"), "clvHistory": context.get("clv_history")},
        )
        edge_by_outcome[outcome] = calculate_edge_quality(
            outcome,
            float(official_sp.get(key, 0) or 0),
            true_probability,
            uncertainty,
            closing_proxy,
            {
                "method_agreement_score": market_multi.method_agreement_score,
                "external_market_quality": context.get("external_market_quality"),
                "model_disagreement": context.get("model_disagreement"),
                "pure_model_reliability": context.get("pure_model_reliability"),
                "lineup_risk": context.get("lineup_risk"),
                "fatigue_risk": context.get("fatigue_risk"),
                "sample_size": context.get("sample_size"),
                "draw_calibrator_support": draw_details.get("applied") if key == "draw" else True,
                "critic_blocked": context.get("critic_blocked", False),
            },
            threshold,
        )
    passed = [edge for edge in edge_by_outcome.values() if edge.passes_true_odds_filter]
    selected = sorted(passed, key=lambda edge: (edge.edge_quality_score, edge.expected_ev), reverse=True)[0] if passed else _no_bet_edge(min(edge.adaptive_threshold for edge in edge_by_outcome.values()), "no outcome passed true odds filter")
    return TrueOddsEstimate(
        match_id=str(match.get("id") or prediction.get("match_id") or ""),
        official_match_id=str(match.get("official_match_id") or match.get("officialMatchId") or ""),
        created_at=datetime.now(timezone.utc).isoformat(),
        market_multi_devig=market_multi,
        external_multi_devig=external_multi,
        base_probability=base,
        bias_corrected_probability=bias_corrected,
        uncertainty=uncertainty,
        true_probability_estimate=true_probability,
        true_fair_odds=_fair_odds(true_probability),
        edge_quality_by_outcome=edge_by_outcome,
        selected_edge=selected,
        closing_line_proxy=closing_proxy,
        market_bias_bucket=bias_bucket,
        draw_calibration=draw_details,
        real_ev=real_ev_by_outcome(true_probability, market_multi.odds),
        real_ev_calibration=diagnostics_to_dict(real_diagnostics),
        warnings=[*warnings, *uncertainty.warnings],
    )


def selected_outcome_passes(estimate: TrueOddsEstimate, outcome: str) -> bool:
    key = _outcome_to_key(outcome).upper()
    return bool(estimate.edge_quality_by_outcome.get(key) and estimate.edge_quality_by_outcome[key].passes_true_odds_filter)
