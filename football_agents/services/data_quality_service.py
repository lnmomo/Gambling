from __future__ import annotations

import math
from datetime import datetime, timezone, timedelta
from typing import Any

from ..config import settings


ALLOWED_MATCH_STATUSES = {"SCHEDULED", "NOT_STARTED", "LIVE", "FINISHED", "CANCELLED", "POSTPONED", "STOPPED", "scheduled"}
ALLOWED_RECOMMENDATIONS = {"HOME", "DRAW", "AWAY", "BET", "WATCH", "NO_BET"}
ALLOWED_LIFECYCLE = {"ACTIVE", "STALE", "WITHDRAWN", "NO_BET", None}


def _result(valid: bool, errors: list[str] | None = None, warnings: list[str] | None = None) -> dict[str, Any]:
    return {"valid": valid, "errors": errors or [], "warnings": warnings or []}


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def validate_official_match(match: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if not str(match.get("official_match_id") or "").strip():
        errors.append("official_match_id is required")
    if not str(match.get("home_team") or "").strip():
        errors.append("home_team is required")
    if not str(match.get("away_team") or "").strip():
        errors.append("away_team is required")
    if match.get("home_team") and match.get("home_team") == match.get("away_team"):
        errors.append("home_team and away_team must differ")
    if not _parse_time(match.get("kickoff_time")):
        errors.append("kickoff_time must be a valid datetime")
    if match.get("status") not in ALLOWED_MATCH_STATUSES:
        errors.append("status is not allowed")
    return _result(not errors, errors)


def validate_three_way_odds(odds: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    for key in ("home", "draw", "away"):
        value = odds.get(key)
        if not _finite_number(value):
            errors.append(f"{key} odds must be a finite number")
        elif not 1.01 < float(value) < 100:
            errors.append(f"{key} odds must be between 1.01 and 100")
    return _result(not errors, errors)


def validate_probability(probability: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    values: list[float] = []
    for key in ("home", "draw", "away"):
        value = probability.get(key)
        if not _finite_number(value):
            errors.append(f"{key} probability must be a finite number")
            continue
        number = float(value)
        values.append(number)
        if number < 0 or number > 1:
            errors.append(f"{key} probability must be between 0 and 1")
    if len(values) == 3 and not 0.999 <= sum(values) <= 1.001:
        errors.append("probability sum must be approximately 1")
    return _result(not errors, errors)


def validate_snapshot_freshness(snapshot: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    errors: list[str] = []
    warnings: list[str] = []
    captured_at = _parse_time(snapshot.get("captured_at"))
    if not captured_at:
        errors.append("captured_at must be a valid datetime")
    else:
        if captured_at > now + timedelta(minutes=5):
            warnings.append("captured_at is more than 5 minutes in the future")
        if now - captured_at > timedelta(minutes=settings.snapshot_stale_minutes):
            warnings.append("snapshot is stale")
    kickoff = _parse_time(snapshot.get("kickoff_time"))
    if kickoff and now > kickoff - timedelta(minutes=settings.pre_match_close_minutes):
        warnings.append("kickoff is too close or already passed for ACTIVE recommendations")
    return _result(not errors, errors, warnings)


def validate_prediction(prediction: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    probability = prediction.get("finalProbability") or prediction.get("final_probability") or prediction.get("final_probability_json")
    if isinstance(probability, str):
        import json
        probability = json.loads(probability)
    prob_result = validate_probability(probability or {})
    errors.extend(prob_result["errors"])
    official_sp = prediction.get("officialSp") or prediction.get("official_sp") or prediction.get("official_sp_json") or {}
    odds_result = validate_three_way_odds(official_sp) if official_sp else _result(False, ["official SP odds are required"])
    errors.extend(odds_result["errors"])
    ev = prediction.get("ev") or prediction.get("ev_json") or {}
    if isinstance(ev, str):
        import json
        ev = json.loads(ev)
    if not isinstance(ev, dict) or not ev:
        errors.append("ev_json is required")
    elif any(not _finite_number(value) for value in ev.values()):
        errors.append("ev_json must contain finite numbers")
    recommendation = prediction.get("recommendation")
    if recommendation not in ALLOWED_RECOMMENDATIONS:
        errors.append("recommendation is not allowed")
    if recommendation and recommendation != "NO_BET":
        if prediction.get("selected_probability") is None and prediction.get("selectedProbability") is None:
            errors.append("selected probability is required for non-NO_BET recommendations")
        if prediction.get("selected_official_sp") is None and prediction.get("selectedOfficialSp") is None:
            errors.append("selected official SP is required for non-NO_BET recommendations")
    lifecycle = prediction.get("lifecycle_status") or prediction.get("lifecycleStatus")
    if lifecycle not in ALLOWED_LIFECYCLE:
        errors.append("lifecycle_status is not allowed")
    freshness = validate_snapshot_freshness(prediction) if prediction.get("captured_at") else _result(True)
    warnings.extend(freshness["warnings"])
    if lifecycle == "ACTIVE" and freshness["warnings"]:
        errors.append("ACTIVE prediction cannot use stale or unsafe snapshot timing")
    return _result(not errors, errors, warnings)


def validate_no_auto_betting_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or {}
    enabled = bool(config.get("ENABLE_AUTO_BETTING", settings.enable_auto_betting))
    warnings = ["automatic betting is disabled by project policy"] if enabled else []
    return _result(not enabled, ["ENABLE_AUTO_BETTING must remain false"] if enabled else [], warnings)
