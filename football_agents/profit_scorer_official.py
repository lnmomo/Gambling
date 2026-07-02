from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from .db import Database, db
from .features import canonical_team_name
from .market_bias_shadow_strategy import is_i2_league
from .pandas_pipeline import team_weighted_goal_stats
from .repository import Repository


DEFAULT_SCORER_ARTIFACT = Path("reports/feature_enriched_market_anchored_i2_scorer_v1/scorer.json")


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


def _league_context(repository: Repository, match: dict[str, Any]) -> tuple[dict[str, float], list[str]]:
    warnings: list[str] = []
    league_rows = repository.list_historical_matches(cutoff_time=match["kickoff_time"], league=match["league"], limit=100_000)
    if len(league_rows) < 120:
        warnings.append(f"league_prior_matches<{120}: {len(league_rows)}")
    draws = sum(1 for row in league_rows if int(row["home_goals"]) == int(row["away_goals"]))
    draw_rate = draws / len(league_rows) if league_rows else 0.0
    return {
        "league_prior_matches": float(len(league_rows)),
        "league_draw_rate": float(draw_rate),
        "league_prior_matches_scaled": float(len(league_rows)) / 1000.0,
    }, warnings


def map_official_match_to_scorer_features(
    repository: Repository,
    match: dict[str, Any],
    odds: dict[str, Any],
    artifact: dict[str, Any],
) -> tuple[dict[str, float] | None, list[str], list[str]]:
    missing: list[str] = []
    warnings: list[str] = []
    if not is_i2_league(match.get("league")):
        missing.append("league_not_i2")
    try:
        draw_odds = float(odds.get("draw") or 0)
    except (TypeError, ValueError):
        draw_odds = 0.0
    if not 2.8 <= draw_odds < 3.5:
        missing.append("draw_sp_outside_[2.8,3.5)")
    market = _devig_probabilities(odds)
    if market is None:
        missing.append("invalid_three_way_official_sp")

    live_features = repository.latest_features(int(match["id"]))
    required_live = (
        "lambda_home",
        "lambda_away",
        "home_weighted_points_per_match",
        "away_weighted_points_per_match",
        "home_weighted_goal_difference",
        "away_weighted_goal_difference",
    )
    for key in required_live:
        if live_features.get(key) is None:
            missing.append(f"missing_feature:{key}")

    league_context, league_warnings = _league_context(repository, match)
    warnings.extend(league_warnings)

    home = canonical_team_name(str(match.get("home_team") or ""))
    away = canonical_team_name(str(match.get("away_team") or ""))
    rows = repository.list_historical_matches(cutoff_time=match["kickoff_time"], teams=[home, away], limit=100_000)
    home_rows = [row for row in rows if home in {row["home_team"], row["away_team"]}]
    away_rows = [row for row in rows if away in {row["home_team"], row["away_team"]}]
    if len(home_rows) < 10:
        missing.append(f"home_history<10:{len(home_rows)}")
    if len(away_rows) < 10:
        missing.append(f"away_history<10:{len(away_rows)}")

    if missing or market is None:
        return None, missing, warnings

    home_recent = team_weighted_goal_stats(home_rows, home, match["kickoff_time"])
    away_recent = team_weighted_goal_stats(away_rows, away, match["kickoff_time"])
    form_points_diff = float(home_recent["points_per_match"] - away_recent["points_per_match"])
    form_goal_diff_delta = float(home_recent["goal_difference"] - away_recent["goal_difference"])
    season_points_delta = float(live_features["home_weighted_points_per_match"] - live_features["away_weighted_points_per_match"])
    season_goal_delta = float(live_features["home_weighted_goal_difference"] - live_features["away_weighted_goal_difference"])
    lambda_total = float(live_features["lambda_home"]) + float(live_features["lambda_away"])
    lambda_diff = abs(float(live_features["lambda_home"]) - float(live_features["lambda_away"]))
    mapped = {
        "market_probability": float(market["draw"]),
        "odds": draw_odds,
        "log_odds": math.log(draw_odds),
        "is_draw": 1.0,
        "is_home": 0.0,
        **league_context,
        "form_points_diff": form_points_diff,
        "abs_form_points_diff": abs(form_points_diff),
        "form_goal_diff_delta": form_goal_diff_delta,
        "abs_form_goal_diff_delta": abs(form_goal_diff_delta),
        "season_points_per_match_delta": season_points_delta,
        "abs_season_points_per_match_delta": abs(season_points_delta),
        "season_goal_diff_per_match_delta": season_goal_delta,
        "abs_season_goal_diff_per_match_delta": abs(season_goal_delta),
        "rest_days_delta": 0.0,
        "lambda_total": lambda_total,
        "lambda_diff": lambda_diff,
    }
    missing_columns = [column for column in artifact["selection"]["feature_columns"] if column not in mapped]
    if missing_columns:
        return None, [f"missing_scorer_column:{column}" for column in missing_columns], warnings
    warnings.append("feature_mapping_approximation: season deltas use current weighted historical features")
    warnings.append("feature_mapping_approximation: rest_days_delta defaults to 0 until live rest-day features are stored")
    return mapped, [], warnings


def diagnose_official_profit_scorer_pool(
    database: Database = db,
    scorer_artifact: Path | str = DEFAULT_SCORER_ARTIFACT,
    limit: int = 500,
) -> dict[str, Any]:
    artifact_path = Path(scorer_artifact)
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    repository = Repository(database)
    rows: list[dict[str, Any]] = []
    blocker_counts: dict[str, int] = {}
    for match in repository.list_official_matches()[:max(1, min(limit, 5000))]:
        latest = repository.latest_odds(int(match["id"]))
        odds = latest.get("odds") or {}
        mapped, missing, warnings = map_official_match_to_scorer_features(repository, match, odds, artifact)
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
            "outcome": "DRAW",
            "selected_sp": round(mapped["odds"], 4),
            "market_probability": round(mapped["market_probability"], 6),
            "predicted_probability": round(probability, 6),
            "predicted_ev": round(ev, 6),
            "warnings": warnings,
        })
    scored = [row for row in rows if row.get("scored")]
    passed = [row for row in scored if row.get("passes_scorer")]
    return {
        "method": "official pool readiness for market-anchored I2 profit scorer",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scorer_artifact": str(artifact_path),
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
            "Feature mapping is approximate until official live features exactly match the research scorer schema.",
        ],
    }
