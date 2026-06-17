from __future__ import annotations

from typing import Any

from .repository import Repository
from .db import db
from .shadow_prediction_store import ShadowPredictionStore, TrueOddsConfigVersion, dumps
from .true_odds_engine import calculate_true_odds_estimate


def _action_to_key(action: str | None) -> str | None:
    if not action or action == "NO_BET":
        return None
    return {"HOME": "home", "DRAW": "draw", "AWAY": "away"}.get(action.upper(), action.lower())


def run_live_shadow_prediction(match: dict[str, Any], baseline_prediction: dict[str, Any],
                               config_version: TrueOddsConfigVersion, snapshots: dict[str, Any] | None = None,
                               options: dict[str, Any] | None = None) -> dict[str, Any]:
    snapshots = snapshots or {}
    official_sp = baseline_prediction.get("officialSp") or baseline_prediction.get("official_sp") or snapshots.get("official_sp") or {}
    final_probability = baseline_prediction.get("finalProbability") or baseline_prediction.get("final_probability") or {}
    baseline_rec = str(baseline_prediction.get("recommendation") or baseline_prediction.get("status") or "NO_BET").upper()
    baseline_key = _action_to_key(baseline_rec)
    selected_key = baseline_key or max(final_probability, key=final_probability.get) if final_probability else "home"
    estimate = calculate_true_odds_estimate(
        match,
        {"officialSp": official_sp, "finalProbability": final_probability,
         "pureModelProbability": baseline_prediction.get("pureModelProbability") or final_probability,
         "externalMarketProbability": baseline_prediction.get("externalMarketProbability"),
         "features": baseline_prediction.get("features") or {}},
        {"selected_outcome": selected_key.upper(), "selected_odds": official_sp.get(selected_key, 0),
         "model_disagreement": baseline_prediction.get("modelDisagreement", "LOW"),
         "external_market_quality": baseline_prediction.get("externalMarketQuality", "MEDIUM")},
    )
    edge = estimate.edge_quality_by_outcome.get(selected_key.upper()) or estimate.selected_edge
    passes = bool(edge.passes_true_odds_filter)
    shadow_rec = baseline_rec if baseline_rec != "NO_BET" and passes else "NO_BET"
    would_block = baseline_rec != "NO_BET" and shadow_rec == "NO_BET"
    would_recommend_new = baseline_rec == "NO_BET" and estimate.selected_edge.passes_true_odds_filter
    record = {
        "match_id": str(match.get("id")),
        "official_match_id": str(match.get("official_match_id") or match.get("officialMatchId")),
        "kickoff_time": str(match.get("kickoff_time") or match.get("kickoffTime")),
        "league": match.get("league"),
        "config_version_id": config_version.config_version_id,
        "true_odds_config_snapshot_json": dumps(config_version.config.to_dict()),
        "official_sp_snapshot_id": snapshots.get("official_sp_snapshot_id"),
        "external_odds_snapshot_id": snapshots.get("external_odds_snapshot_id"),
        "baseline_prediction_id": baseline_prediction.get("id"),
        "baseline_recommendation": baseline_rec,
        "baseline_selected_outcome": baseline_key.upper() if baseline_key else None,
        "baseline_ev": baseline_prediction.get("recommendedEv") or baseline_prediction.get("ev"),
        "baseline_probability": baseline_prediction.get("recommendedProbability") or (final_probability.get(baseline_key) if baseline_key else None),
        "baseline_official_sp": baseline_prediction.get("recommendedSp") or (official_sp.get(baseline_key) if baseline_key else None),
        "shadow_recommendation": shadow_rec,
        "shadow_selected_outcome": selected_key.upper() if shadow_rec != "NO_BET" else None,
        "shadow_ev": edge.expected_ev if shadow_rec != "NO_BET" else None,
        "shadow_lower_bound_ev": edge.lower_bound_ev,
        "shadow_edge_quality_score": edge.edge_quality_score,
        "shadow_edge_quality_level": edge.edge_quality_level,
        "shadow_adaptive_threshold": edge.adaptive_threshold,
        "shadow_passes_true_odds_filter": int(passes),
        "shadow_would_block_baseline": int(would_block),
        "shadow_would_recommend_new": int(would_recommend_new),
        "no_bet_reason": "; ".join(edge.reasons) if edge.reasons else None,
        "true_odds_estimate_json": dumps(estimate.to_dict()),
        "lifecycle_status": "PENDING_RESULT",
        "warnings_json": dumps(estimate.warnings),
    }
    return ShadowPredictionStore(getattr(config_version, "_database", db)).save_shadow_prediction(record)


def run_shadow_for_active_matches(config_version_id: str) -> dict[str, Any]:
    repo = Repository()
    store = ShadowPredictionStore(repo.db)
    version = store.get_config_version(config_version_id)
    if not version:
        raise KeyError(config_version_id)
    created = skipped = errors = 0
    for match in repo.list_official_matches():
        try:
            official = repo.latest_odds(match["id"])
            prediction = repo.latest_signal(match["id"]) or {"status": "NO_BET"}
            if len(official["odds"]) != 3:
                skipped += 1
                continue
            baseline = {"officialSp": official["odds"], "finalProbability": repo.latest_prediction(match["id"]) and {
                "home": repo.latest_prediction(match["id"])["p_home"],
                "draw": repo.latest_prediction(match["id"])["p_draw"],
                "away": repo.latest_prediction(match["id"])["p_away"],
            } or {"home": 1/3, "draw": 1/3, "away": 1/3},
                "recommendation": (prediction.get("option") or "NO_BET").upper() if prediction.get("status") in {"BET", "WATCH"} else "NO_BET",
                "recommendedEv": prediction.get("ev"), "recommendedProbability": prediction.get("probability"),
                "recommendedSp": prediction.get("sp"), "features": repo.latest_features(match["id"])}
            run_live_shadow_prediction(match, baseline, version, {"official_sp_snapshot_id": official.get("fetched_at")})
            created += 1
        except Exception:
            errors += 1
    return {"created": created, "skipped": skipped, "errors": errors, "config_version_id": config_version_id}
