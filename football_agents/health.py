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
    }
