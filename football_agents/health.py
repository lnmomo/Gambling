from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

from .config import settings
from .db import Database, db
from .repository import Repository
from .services.model_governance_persistence_service import ModelGovernancePersistenceService
from .services.scheduler_health_service import SchedulerHealthService


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _sync_status(last_success_at: str | None, refresh_minutes: int, failed: bool = False) -> str:
    if failed:
        return "FAILED"
    parsed = _parse_time(last_success_at)
    if not parsed:
        return "UNKNOWN"
    return "STALE" if datetime.now(timezone.utc) - parsed > timedelta(minutes=max(1, refresh_minutes * 2)) else "OK"


def build_health_report(database: Database = db) -> dict[str, Any]:
    warnings: list[str] = []
    connected = False
    recent_errors = 0
    official_last_success: str | None = None
    external_last_success: str | None = None
    official_status = "UNKNOWN"
    external_status = "UNKNOWN"
    recent_task_runs: list[dict[str, Any]] = []
    data_quality = {"invalidSnapshots": 0, "duplicateSkipped": 0, "staleSnapshots": 0}
    champion_version: str | None = None
    challenger_available = False
    shadow_validation = {
        "activeShadowConfigCount": 0,
        "pendingShadowPredictions": 0,
        "evaluatedShadowPredictions": 0,
        "latestPromotionDecision": None,
        "latestShadowRunAt": None,
        "warnings": [],
    }
    prospective_research = {
        "enabled": settings.enable_prospective_research, "status": "NOT_REGISTERED",
        "studyId": None, "freezeId": None, "predictions": 0, "settledMatches": 0,
        "minimumSettledMatches": settings.prospective_research_min_settled,
        "minimumCalendarDays": settings.prospective_research_min_days,
        "remainingMatches": settings.prospective_research_min_settled,
        "remainingDays": settings.prospective_research_min_days, "confirmationDecision": None,
    }
    profit_scorer_official_sp = {
        "status": "NOT_RUN",
        "openingPreMatchSnapshots": 0,
        "scoredSnapshots": 0,
        "selectedSnapshots": 0,
        "settledSelectedSnapshots": 0,
        "minimumSettledSelected": 200,
        "minimumMonths": 6,
        "remainingSettledSelected": 200,
        "decision": None,
        "decisionReasons": [],
        "lastRunAt": None,
    }

    try:
        with database.connect() as c:
            c.execute("SELECT 1").fetchone()
            connected = True
            official = c.execute("""SELECT fetched_at FROM official_fetch_logs
                WHERE success=1 ORDER BY fetched_at DESC LIMIT 1""").fetchone()
            official_last_success = official["fetched_at"] if official else None
            official_failed = c.execute("""SELECT 1 FROM official_fetch_logs
                WHERE success=0 ORDER BY fetched_at DESC LIMIT 1""").fetchone() is not None
            external = c.execute("""SELECT synced_at FROM provider_sync_logs
                WHERE provider='the_odds_api' AND status='success' ORDER BY synced_at DESC LIMIT 1""").fetchone()
            external_last_success = external["synced_at"] if external else None
            external_failed = c.execute("""SELECT 1 FROM provider_sync_logs
                WHERE provider='the_odds_api' AND status NOT IN ('success','not_configured')
                ORDER BY synced_at DESC LIMIT 1""").fetchone() is not None
            recent_errors = int(c.execute("""SELECT
                (SELECT COUNT(*) FROM official_fetch_logs WHERE success=0)
                + (SELECT COUNT(*) FROM provider_sync_logs WHERE status NOT IN ('success','not_configured','waiting_metadata'))
                + (SELECT COUNT(*) FROM task_runs WHERE status='FAILED')""").fetchone()[0])
            data_quality["invalidSnapshots"] = int(c.execute("""SELECT
                (SELECT COUNT(*) FROM official_sp_snapshots WHERE is_valid=0)
                + (SELECT COUNT(*) FROM external_odds_snapshots WHERE is_valid=0)""").fetchone()[0])
            data_quality["duplicateSkipped"] = int(c.execute("SELECT COUNT(*) FROM audit_logs WHERE action='duplicate_skipped'").fetchone()[0])
            cutoff = (datetime.now(timezone.utc) - timedelta(minutes=settings.snapshot_stale_minutes)).isoformat()
            data_quality["staleSnapshots"] = int(c.execute("""SELECT
                (SELECT COUNT(*) FROM official_sp_snapshots WHERE captured_at<?)
                + (SELECT COUNT(*) FROM external_odds_snapshots WHERE captured_at<?)""", (cutoff, cutoff)).fetchone()[0])
            official_status = _sync_status(official_last_success, settings.official_sp_refresh_minutes, official_failed)
            external_status = _sync_status(external_last_success, settings.external_odds_refresh_minutes, external_failed)
            shadow_validation["activeShadowConfigCount"] = int(c.execute("SELECT COUNT(*) FROM true_odds_config_versions WHERE status='SHADOW_RUNNING'").fetchone()[0])
            shadow_validation["pendingShadowPredictions"] = int(c.execute("SELECT COUNT(*) FROM live_shadow_predictions WHERE lifecycle_status='PENDING_RESULT'").fetchone()[0])
            shadow_validation["evaluatedShadowPredictions"] = int(c.execute("SELECT COUNT(*) FROM shadow_post_match_results WHERE evaluation_status='EVALUATED'").fetchone()[0])
            latest_shadow = c.execute("SELECT created_at FROM live_shadow_predictions ORDER BY created_at DESC LIMIT 1").fetchone()
            shadow_validation["latestShadowRunAt"] = latest_shadow["created_at"] if latest_shadow else None
            latest_gate = c.execute("SELECT decision FROM shadow_validation_runs ORDER BY created_at DESC LIMIT 1").fetchone()
            shadow_validation["latestPromotionDecision"] = latest_gate["decision"] if latest_gate else None
            study = c.execute("SELECT * FROM prospective_research_studies ORDER BY registered_at DESC LIMIT 1").fetchone()
            if study:
                counts = c.execute("""SELECT COUNT(*) predictions,
                    COUNT(DISTINCT CASE WHEN r.outcome IN ('home','draw','away')
                        AND o.minutes_to_kickoff BETWEEN ? AND ? THEN p.match_id END) settled
                    FROM prospective_predictions p
                    JOIN official_odds_observations o ON o.id=p.official_odds_observation_id
                    LEFT JOIN results r ON r.match_id=p.match_id WHERE p.study_id=?""",
                    (study["primary_horizon_minutes"],
                     study["primary_horizon_minutes"] + study["horizon_tolerance_minutes"],
                     study["study_id"])).fetchone()
                run = c.execute("SELECT decision FROM prospective_confirmation_runs WHERE study_id=?",
                                (study["study_id"],)).fetchone()
                elapsed = max(0, (datetime.now(timezone.utc) - (_parse_time(study["starts_at"]) or datetime.now(timezone.utc))).days)
                settled = int(counts["settled"] or 0)
                ready = settled >= study["min_settled_matches"] and elapsed >= study["min_calendar_days"]
                prospective_research.update({
                    "status": "COMPLETED" if run else "READY" if ready else "COLLECTING",
                    "studyId": study["study_id"], "freezeId": study["freeze_id"],
                    "predictions": int(counts["predictions"] or 0), "settledMatches": settled,
                    "minimumSettledMatches": study["min_settled_matches"],
                    "minimumCalendarDays": study["min_calendar_days"],
                    "remainingMatches": max(0, study["min_settled_matches"] - settled),
                    "remainingDays": max(0, study["min_calendar_days"] - elapsed),
                    "confirmationDecision": run["decision"] if run else None,
                })
            validation_run = c.execute("""SELECT * FROM task_runs
                WHERE task_name='profit_scorer_official_sp_validation'
                ORDER BY started_at DESC LIMIT 1""").fetchone()
            if validation_run:
                reasons = json_loads(validation_run["warnings_json"])
                settled_selected = int(validation_run["created_snapshots"] or 0)
                # The task runner stores only compact counters. Use them for health without
                # reading generated report files, so /health stays database-backed.
                profit_scorer_official_sp.update({
                    "status": validation_run["status"],
                    "openingPreMatchSnapshots": int(validation_run["affected_matches"] or 0),
                    "scoredSnapshots": 0,
                    "selectedSnapshots": int(validation_run["created_predictions"] or 0),
                    "settledSelectedSnapshots": settled_selected,
                    "remainingSettledSelected": max(0, 200 - settled_selected),
                    "decision": (
                        None if validation_run["status"] == "FAILED"
                        else "OFFICIAL_SP_PROSPECTIVE_BLOCKED" if reasons
                        else "OFFICIAL_SP_PROSPECTIVE_PASS"
                    ),
                    "decisionReasons": reasons,
                    "lastRunAt": validation_run["finished_at"] or validation_run["started_at"],
                })
        scheduler = SchedulerHealthService()
        recent_task_runs = scheduler.list_recent_task_runs(20)
        governance = ModelGovernancePersistenceService(database)
        champion = governance.get_current_champion_model()
        champion_version = champion["version"] if champion else None
        challenger_available = bool(governance.list_challenger_models())
    except Exception as exc:  # noqa: BLE001 - health should report instead of crash.
        warnings.append(f"database health check failed: {exc}")

    if not settings.odds_api_key and settings.enable_real_sync:
        warnings.append("THE_ODDS_API_KEY is not configured while real sync is enabled")
    elif not settings.odds_api_key:
        warnings.append("THE_ODDS_API_KEY is not configured; real sync should remain disabled")
    if settings.enable_auto_betting:
        warnings.append("ENABLE_AUTO_BETTING=true is blocked by project policy")
    if official_status == "STALE":
        warnings.append("official SP sync is stale")
    if external_status == "STALE":
        warnings.append("external odds sync is stale")
    if not champion_version:
        warnings.append("champion model metadata is not available")
    if shadow_validation["activeShadowConfigCount"] and not shadow_validation["latestShadowRunAt"]:
        shadow_validation["warnings"].append("active shadow config has not run yet")
    if shadow_validation["pendingShadowPredictions"] > 200:
        shadow_validation["warnings"].append("many shadow predictions are pending evaluation")
    if shadow_validation["latestPromotionDecision"] == "REJECT_CONFIG":
        shadow_validation["warnings"].append("latest shadow promotion decision rejected config")

    if not connected:
        status = "unhealthy"
    elif settings.enable_auto_betting or official_status in {"STALE", "FAILED"} or external_status in {"STALE", "FAILED"}:
        status = "degraded"
    else:
        status = "healthy"

    return {
        "status": status,
        "appEnv": settings.app_env,
        "database": {"connected": connected, "urlConfigured": bool(settings.database_url)},
        "officialSpSync": {"lastSuccessAt": official_last_success, "status": official_status},
        "externalOddsSync": {"lastSuccessAt": external_last_success, "status": external_status},
        "model": {
            "championVersion": champion_version,
            "stackingEnabled": settings.enable_stacking_model,
            "challengerAvailable": challenger_available,
        },
        "config": {
            "realSyncEnabled": settings.enable_real_sync,
            "autoBettingEnabled": False,
            "autoBettingRequested": settings.enable_auto_betting,
            "oddsApiKeyConfigured": bool(settings.odds_api_key),
            "databaseUrlConfigured": bool(settings.database_url),
            "logLevel": settings.log_level,
        },
        "recentErrors": recent_errors,
        "warnings": warnings,
        "recentTaskRuns": recent_task_runs,
        "dataQuality": data_quality,
        "shadowValidation": shadow_validation,
        "prospectiveResearch": prospective_research,
        "profitScorerOfficialSp": profit_scorer_official_sp,
    }


def json_loads(value: Any) -> list[str]:
    import json

    try:
        parsed = json.loads(value or "[]")
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []
