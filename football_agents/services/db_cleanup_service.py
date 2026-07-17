from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from ..config import settings
from ..db import Database, db
from ..repository import Repository


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Tables eligible for time-windowed retention cleanup.
# (table, time_column, retention_setting_key). Tables carrying a
# BEFORE DELETE -> RAISE(ABORT) immutability trigger (official_odds_observations,
# official_market_availability_observations, official_result_observations,
# profit_scorer_evidence, profit_scorer_freeze_attempts, prospective_predictions,
# external_consensus_decisions, paper_portfolio_*) are deliberately NOT listed
# here: they are permanent research/audit ledgers and are kept indefinitely.
RETENTION_TABLES: tuple[tuple[str, str, str], ...] = (
    # snapshots / odds time series
    ("odds_snapshots", "fetched_at", "db_retention_days"),
    ("market_odds_snapshots", "fetched_at", "db_retention_days"),
    ("external_bookmaker_odds", "fetched_at", "db_retention_days"),
    ("weather_snapshots", "fetched_at", "db_retention_days"),
    # fetch / sync logs (UI state only; health.py reads the latest row)
    ("official_fetch_logs", "fetched_at", "db_retention_days"),
    ("provider_sync_logs", "synced_at", "db_retention_days"),
    ("audit_events", "created_at", "db_retention_days"),
    ("audit_logs", "created_at", "db_retention_days"),
    ("task_runs", "started_at", "db_retention_days"),
    ("agent_runs", "started_at", "db_retention_days"),
    ("agent_run_steps", "started_at", "db_retention_days"),
    ("match_status_events", "detected_at", "db_retention_days"),
    ("match_features", "created_at", "db_retention_days"),
    ("model_predictions", "predicted_at", "db_retention_days"),
    ("critic_reports", "created_at", "db_retention_days"),
    ("bet_signals", "created_at", "db_retention_days"),
    ("llm_match_analyses", "created_at", "db_retention_days"),
    ("news_events", "published_at", "db_retention_days"),
    # shadow validation time series (cascade child first)
    ("shadow_post_match_results", "evaluated_at", "db_retention_days"),
    ("live_shadow_predictions", "created_at", "db_retention_days"),
    # backtest artifacts — longer window
    ("backtest_records", "created_at", "db_backtest_retention_days"),
    ("backtest_runs", "created_at", "db_backtest_retention_days"),
    ("backtest_reports", "created_at", "db_backtest_retention_days"),
)

# Tables where a child must be pruned before its parent to respect FK/logical order.
# Each entry maps parent -> ordered list of children that reference it.
CASCADE_ORDER: dict[str, tuple[str, ...]] = {
    "live_shadow_predictions": ("shadow_post_match_results",),
    "backtest_runs": ("backtest_records", "backtest_reports"),
}


class DbCleanupService:
    """Retention + VACUUM housekeeping for the SQLite runtime database.

    Deletes rows older than a configurable window from high-churn, mutable
    tables and then runs VACUUM on a fresh connection so the freed pages are
    returned to the OS. Immutable evidence ledgers are never touched.
    """

    def __init__(self, repository: Repository | None = None,
                 database: Database | None = None) -> None:
        self.repository = repository or Repository()
        self.database = database or self.repository.db

    def run_retention_cleanup(self) -> dict[str, Any]:
        now = utcnow()
        warnings: list[str] = []
        deleted: dict[str, int] = {}
        size_before = self._db_size_bytes()

        cutoffs = self._cutoffs(now)
        for table, column, setting_key in self._ordered_tables():
            days = cutoffs.get(setting_key)
            if not days or days <= 0:
                # retention disabled (0) -> keep everything in this table
                continue
            cutoff = (now - timedelta(days=days)).isoformat()
            count = self._delete_older(table, column, cutoff)
            deleted[table] = deleted.get(table, 0) + count

        vacuum_status, vacuum_detail = self._vacuum()
        if vacuum_status != "ok":
            warnings.append(vacuum_detail)

        return {
            "deleted": deleted,
            "total_deleted": sum(deleted.values()),
            "vacuum": vacuum_status,
            "vacuum_detail": vacuum_detail if vacuum_status != "ok" else None,
            "db_size_bytes_before": size_before,
            "db_size_bytes_after": self._db_size_bytes(),
            "retention_days": cutoffs,
            "warnings": warnings,
            "ran_at": now.isoformat(),
        }

    # -- internal helpers ------------------------------------------------

    def _cutoffs(self, now: datetime) -> dict[str, int]:
        return {
            "db_retention_days": int(settings.db_retention_days),
            "db_backtest_retention_days": int(settings.db_backtest_retention_days),
        }

    def _ordered_tables(self) -> list[tuple[str, str, str]]:
        """Yield retention tables in safe deletion order (children first)."""
        tables = list(RETENTION_TABLES)
        names = [t[0] for t in tables]
        ordered: list[tuple[str, str, str]] = []
        by_name = {t[0]: t for t in tables}
        visited: set[str] = set()

        def visit(name: str) -> None:
            if name in visited or name not in by_name:
                return
            visited.add(name)
            for child in CASCADE_ORDER.get(name, ()):
                visit(child)
            ordered.append(by_name[name])

        for name in names:
            visit(name)
        return ordered

    def _delete_older(self, table: str, column: str, cutoff: str) -> int:
        # Skip tables that don't exist in this schema (some are migration-gated).
        if not self._table_exists(table):
            return 0
        with self.database.connect() as connection:
            # Prune child rows that still reference parents we are about to
            # remove, so NO-ACTION FKs (e.g. agent_run_steps -> agent_runs) do
            # not raise. Only child tables whose own time column lags the parent
            # need this; independent tables delete their own rows directly.
            if table == "agent_runs":
                connection.execute(
                    'DELETE FROM agent_run_steps WHERE run_id IN '
                    '(SELECT id FROM agent_runs WHERE started_at < ?)',
                    (cutoff,),
                )
            elif table == "live_shadow_predictions":
                connection.execute(
                    'DELETE FROM shadow_post_match_results WHERE shadow_prediction_id IN '
                    '(SELECT id FROM live_shadow_predictions WHERE created_at < ?)',
                    (cutoff,),
                )
            cursor = connection.execute(
                f'DELETE FROM "{table}" WHERE "{column}" < ?', (cutoff,)
            )
            return int(cursor.rowcount or 0)

    def _table_exists(self, table: str) -> bool:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
        return row is not None

    def _vacuum(self) -> tuple[str, str]:
        """VACUUM cannot run inside a transaction; use a bare connection."""
        try:
            connection = sqlite3.connect(self.database.path, timeout=30)
            try:
                connection.execute("VACUUM")
                return ("ok", "")
            finally:
                connection.close()
        except sqlite3.OperationalError as exc:
            # common cause: another connection holds a lock. Skip this round.
            return ("skipped", f"VACUUM skipped: {exc}")
        except Exception as exc:  # noqa: BLE001 — housekeeping must not crash the scheduler
            return ("skipped", f"VACUUM skipped: {exc}")

    def _db_size_bytes(self) -> int:
        try:
            return self.database.path.stat().st_size
        except OSError:
            return 0
