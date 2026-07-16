from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from .db import Database, db
from .config import settings
from .market_bias_shadow_strategy import is_i2_league, is_sp1_league
from .profit_scorer_features import (
    FEATURE_ENGINE,
    ResearchParityFeatureCache,
    build_research_parity_features,
)
from .repository import Repository


DEFAULT_SCORER_ARTIFACT = Path(settings.profit_scorer_artifact_path)

I2_DRAW_RULE = "I2_draw_2p8_3p5"
SP1_HOME_RULE = "SP1_home_market_ge_55"


def _artifact_selection(artifact: dict[str, Any]) -> dict[str, Any] | None:
    rules = set(artifact.get("selection", {}).get("selected_rules") or ())
    if rules == {I2_DRAW_RULE}:
        return {
            "league_family": "I2",
            "league_matches": is_i2_league,
            "outcome": "draw",
            "min_market_probability": None,
            "min_odds": 2.8,
            "max_odds": 3.5,
        }
    if rules == {SP1_HOME_RULE}:
        return {
            "league_family": "SP1",
            "league_matches": is_sp1_league,
            "outcome": "home",
            "min_market_probability": 0.55,
            "min_odds": None,
            "max_odds": None,
        }
    return None


def _devig_probabilities(odds: dict[str, Any]) -> dict[str, float] | None:
    try:
        values = {key: float(odds.get(key) or 0) for key in ("home", "draw", "away")}
    except (TypeError, ValueError):
        return None
    if any(value <= 1 for value in values.values()):
        return None
    inverse = {key: 1.0 / value for key, value in values.items()}
    total = sum(inverse.values())
    return {key: inverse[key] / total for key in inverse} if total > 0 else None


def _score_from_artifact(features: dict[str, float], artifact: dict[str, Any]) -> tuple[float, float]:
    selection = artifact["selection"]
    model = artifact["model"]
    columns = selection["feature_columns"]
    means = model["feature_means"]
    stds = model["feature_stds"]
    coefficients = np.array(model["intercept_and_coefficients"], dtype=float)
    values = np.array([float(features[column]) for column in columns], dtype=float)
    mean_values = np.array([float(means[column]) for column in columns], dtype=float)
    std_values = np.array([float(stds[column]) or 1.0 for column in columns], dtype=float)
    design = np.concatenate([[1.0], (values - mean_values) / std_values])
    residual = float(np.clip(design @ coefficients, -float(selection["residual_cap"]), float(selection["residual_cap"])))
    probability = float(np.clip(float(features["market_probability"]) + residual, 0.01, 0.98))
    ev = probability * float(features["odds"]) - 1.0
    return probability, ev


def map_official_match_to_scorer_features(
    repository: Repository,
    match: dict[str, Any],
    odds: dict[str, Any],
    artifact: dict[str, Any],
    feature_cache: ResearchParityFeatureCache | None = None,
) -> tuple[dict[str, float] | None, list[str], list[str]]:
    missing: list[str] = []
    warnings: list[str] = []
    scope = _artifact_selection(artifact)
    if scope is None:
        return None, ["unsupported_artifact_selection"], warnings
    if not scope["league_matches"](match.get("league")):
        missing.append(f"league_not_{scope['league_family'].lower()}")
    selected_outcome = str(scope["outcome"])
    try:
        selected_odds = float(odds.get(selected_outcome) or 0)
    except (TypeError, ValueError):
        selected_odds = 0.0
    if scope["min_odds"] is not None and not float(scope["min_odds"]) <= selected_odds:
        missing.append(f"{selected_outcome}_sp_below_{scope['min_odds']}")
    if scope["max_odds"] is not None and not selected_odds < float(scope["max_odds"]):
        missing.append(f"{selected_outcome}_sp_at_or_above_{scope['max_odds']}")
    market = _devig_probabilities(odds)
    if market is None:
        missing.append("invalid_three_way_official_sp")
    elif (
        scope["min_market_probability"] is not None
        and market[selected_outcome] < float(scope["min_market_probability"])
    ):
        missing.append(
            f"{selected_outcome}_market_probability_below_{scope['min_market_probability']}"
        )

    historical, history_notes = (
        feature_cache.features_for(match)
        if feature_cache is not None
        else build_research_parity_features(
            repository,
            match,
            scope["league_matches"],
            min_team_matches=10,
        )
    )
    if historical is None:
        missing.extend(history_notes)
    else:
        warnings.extend(history_notes)
    if missing or market is None or historical is None:
        return None, missing, warnings
    mapped = {
        "market_probability": float(market[selected_outcome]),
        "odds": selected_odds,
        "log_odds": math.log(selected_odds),
        "is_draw": float(selected_outcome == "draw"),
        "is_home": float(selected_outcome == "home"),
        **historical,
        "abs_form_points_diff": abs(historical["form_points_diff"]),
        "abs_form_goal_diff_delta": abs(historical["form_goal_diff_delta"]),
        "abs_season_points_per_match_delta": abs(historical["season_points_per_match_delta"]),
        "abs_season_goal_diff_per_match_delta": abs(historical["season_goal_diff_per_match_delta"]),
    }
    missing_columns = [column for column in artifact["selection"]["feature_columns"] if column not in mapped]
    if missing_columns:
        return None, [f"missing_scorer_column:{column}" for column in missing_columns], warnings
    warnings.append(f"feature_engine:{FEATURE_ENGINE}")
    return mapped, [], warnings


def diagnose_official_profit_scorer_pool(
    database: Database = db,
    scorer_artifact: Path | str = DEFAULT_SCORER_ARTIFACT,
    limit: int = 500,
) -> dict[str, Any]:
    artifact_path = Path(scorer_artifact)
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    scope = _artifact_selection(artifact)
    repository = Repository(database)
    feature_cache = ResearchParityFeatureCache(repository, scope["league_matches"]) if scope else None
    rows: list[dict[str, Any]] = []
    blocker_counts: dict[str, int] = {}
    for match in repository.list_official_matches()[:max(1, min(limit, 5000))]:
        latest = repository.latest_odds(int(match["id"]))
        odds = latest.get("odds") or {}
        mapped, missing, warnings = map_official_match_to_scorer_features(
            repository, match, odds, artifact, feature_cache
        )
        if mapped is None:
            for reason in missing:
                blocker_counts[reason] = blocker_counts.get(reason, 0) + 1
            rows.append({
                "match_id": match["id"],
                "official_match_id": match.get("official_match_id"),
                "league": match.get("league"),
                "home_team": match.get("home_team"),
                "away_team": match.get("away_team"),
                "kickoff_time": match.get("kickoff_time"),
                "scored": False,
                "missing": missing,
                "warnings": warnings,
            })
            continue
        probability, ev = _score_from_artifact(mapped, artifact)
        passes = ev >= float(artifact["selection"]["min_predicted_ev"])
        rows.append({
            "match_id": match["id"],
            "official_match_id": match.get("official_match_id"),
            "league": match.get("league"),
            "home_team": match.get("home_team"),
            "away_team": match.get("away_team"),
            "kickoff_time": match.get("kickoff_time"),
            "scored": True,
            "passes_scorer": passes,
            "outcome": str(scope["outcome"]).upper() if scope else None,
            "selected_sp": round(mapped["odds"], 4),
            "market_probability": round(mapped["market_probability"], 6),
            "predicted_probability": round(probability, 6),
            "predicted_ev": round(ev, 6),
            "warnings": warnings,
        })
    scored = [row for row in rows if row.get("scored")]
    passed = [row for row in scored if row.get("passes_scorer")]
    return {
        "method": "official pool readiness for market-anchored profit scorer",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scorer_artifact": str(artifact_path),
        "feature_engine": FEATURE_ENGINE,
        "scanned_matches": len(rows),
        "scored_matches": len(scored),
        "passed_scorer": len(passed),
        "blocker_counts": [
            {"reason": reason, "matches": count}
            for reason, count in sorted(blocker_counts.items(), key=lambda item: item[1], reverse=True)
        ],
        "candidates": passed[:100],
        "rows": rows[:200],
        "warnings": [
            "This report does not create recommendations or bets.",
            "Features reproduce the research definitions from history available before kickoff.",
        ],
    }
