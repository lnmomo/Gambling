import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from football_agents.db import Database
from football_agents.health import build_health_report, _effective_external_refresh_minutes
from football_agents.services.audit_log_persistence_service import AuditLogPersistenceService
from football_agents.services.backtest_persistence_service import BacktestPersistenceService
from football_agents.services.bankroll_persistence_service import BankrollPersistenceService
from football_agents.services.data_quality_service import (
    validate_no_auto_betting_config,
    validate_official_match,
    validate_probability,
    validate_snapshot_freshness,
    validate_three_way_odds,
)
from football_agents.services.idempotency_service import clear_memory_keys, hash_payload, save_once
from football_agents.services.model_governance_persistence_service import ModelGovernancePersistenceService
from football_agents.services.recommendation_persistence_service import RecommendationPersistenceService
from football_agents.services.retry_policy import with_retry
from football_agents.services.snapshot_persistence_service import SnapshotPersistenceService
from football_agents.services.task_runner_service import TaskRunnerService


class Phase8GovernanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp.name) / "phase8.db")
        self.database.initialize()

    def tearDown(self):
        self.temp.cleanup()
        clear_memory_keys()

    def test_data_quality_checks(self):
        valid_match = {"official_match_id": "M1", "home_team": "A", "away_team": "B",
                       "kickoff_time": datetime.now(timezone.utc).isoformat(), "status": "NOT_STARTED"}
        self.assertTrue(validate_official_match(valid_match)["valid"])
        self.assertFalse(validate_official_match({**valid_match, "official_match_id": ""})["valid"])
        self.assertFalse(validate_three_way_odds({"home": 1, "draw": 3, "away": 4})["valid"])
        self.assertTrue(validate_probability({"home": .4, "draw": .3, "away": .3})["valid"])
        self.assertFalse(validate_probability({"home": .4, "draw": .4, "away": .4})["valid"])
        future = {"captured_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()}
        self.assertTrue(validate_snapshot_freshness(future)["warnings"])
        stale = {"captured_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()}
        self.assertTrue(validate_snapshot_freshness(stale)["warnings"])
        self.assertFalse(validate_no_auto_betting_config({"ENABLE_AUTO_BETTING": True})["valid"])

    def test_idempotency(self):
        self.assertEqual(hash_payload({"a": 1, "b": 2}), hash_payload({"b": 2, "a": 1}))
        self.assertNotEqual(hash_payload({"a": 1}), hash_payload({"a": 2}))
        calls = {"count": 0}
        def callback():
            calls["count"] += 1
            return {"ok": True}
        self.assertEqual(save_once("key", callback), {"ok": True})
        self.assertEqual(save_once("key", callback), {"ok": True})
        self.assertEqual(calls["count"], 1)

    def test_persistence_services(self):
        snapshots = SnapshotPersistenceService(self.database)
        official = {
            "match_id": "m1", "official_match_id": "M1", "captured_at": "2026-06-16T00:00:00+00:00",
            "home_sp": 2.0, "draw_sp": 3.2, "away_sp": 4.0,
            "market_home_prob": .45, "market_draw_prob": .28, "market_away_prob": .27,
            "market_home_fair_odds": 2.2222, "market_draw_fair_odds": 3.5714, "market_away_fair_odds": 3.7037,
            "raw_payload_hash": "official-hash",
        }
        first = snapshots.save_official_sp_snapshot(official)
        second = snapshots.save_official_sp_snapshot(official)
        self.assertEqual(first["id"], second["id"])
        external = snapshots.save_external_odds_snapshot({
            "match_id": "m1", "official_match_id": "M1", "captured_at": "2026-06-16T00:01:00+00:00",
            "external_home_prob": .44, "external_draw_prob": .29, "external_away_prob": .27,
            "external_home_fair_odds": 2.27, "external_draw_fair_odds": 3.45, "external_away_fair_odds": 3.70,
            "quality_score": .9, "quality_level": "HIGH", "raw_payload_hash": "external-hash",
        })
        self.assertEqual(snapshots.get_latest_external_odds_snapshot("M1")["id"], external["id"])

        recommendations = RecommendationPersistenceService(self.database)
        prediction = recommendations.save_prediction({
            "match_id": "m1", "official_match_id": "M1", "official_sp_snapshot_id": first["id"],
            "external_odds_snapshot_id": external["id"], "model_version": "v-test",
            "market_probability": {"home": .45, "draw": .28, "away": .27},
            "external_market_probability": {"home": .44, "draw": .29, "away": .27},
            "pure_model_probability": {"home": .43, "draw": .30, "away": .27},
            "final_probability": {"home": .44, "draw": .29, "away": .27},
            "market_fair_odds": {}, "external_market_fair_odds": {}, "pure_model_fair_odds": {},
            "final_fair_odds": {}, "ev": {"home": .01, "draw": -.1, "away": -.2},
            "recommendation": "NO_BET", "lifecycle_status": "NO_BET",
        })
        rec = recommendations.save_recommendation({"prediction_id": prediction["id"], "match_id": "m1",
                                                   "official_match_id": "M1", "recommendation": "NO_BET",
                                                   "lifecycle_status": "ACTIVE"})
        self.assertEqual(len(recommendations.get_active_recommendations()), 1)
        recommendations.update_recommendation_lifecycle("m1", "M1", "ACTIVE", "STALE", "snapshot stale")
        self.assertEqual(len(recommendations.get_active_recommendations()), 0)
        self.assertEqual(len(recommendations.list_recommendation_events("M1")), 1)

        audit = AuditLogPersistenceService(self.database)
        self.assertEqual(audit.save_audit_log({"entity_type": "match", "entity_id": "M1",
                                               "action": "test", "summary": "saved"})["severity"], "INFO")
        bankroll = BankrollPersistenceService(self.database)
        bankroll.save_bankroll_transaction({"bankroll_id": "main", "type": "SIMULATED_STAKE",
                                             "amount": -10, "bankroll_before": 1000, "bankroll_after": 990})
        self.assertEqual(bankroll.get_current_bankroll("main"), 990)
        governance = ModelGovernancePersistenceService(self.database)
        governance.save_model_governance_record({"model_id": "champion-test", "model_name": "Champion",
                                                 "model_type": "TEST", "version": "v1", "role": "CHAMPION",
                                                 "metrics": {}, "promotion_status": "APPROVED"})
        self.assertEqual(governance.get_current_champion_model()["version"], "v1")
        backtests = BacktestPersistenceService(self.database)
        run = backtests.save_backtest_run({"name": "test", "config": {}, "status": "SUCCESS", "metrics": {}})
        backtests.save_backtest_records(run["id"], [{"match_id": "m1", "official_match_id": "M1",
                                                     "kickoff_time": "2026-06-16T00:00:00+00:00",
                                                     "prediction": {}}])
        self.assertEqual(backtests.get_backtest_run(run["id"])["status"], "SUCCESS")

    def test_retry_policy(self):
        self.assertEqual(with_retry(lambda: "ok", {"sleep": lambda _: None})["attempts"], 1)
        calls = {"count": 0}
        def flaky():
            calls["count"] += 1
            if calls["count"] < 2:
                raise RuntimeError("temporary")
            return "ok"
        self.assertTrue(with_retry(flaky, {"sleep": lambda _: None})["success"])
        self.assertEqual(calls["count"], 2)
        failed = with_retry(lambda: (_ for _ in ()).throw(RuntimeError("boom")),
                            {"max_attempts": 3, "sleep": lambda _: None})
        self.assertFalse(failed["success"])
        self.assertEqual(failed["attempts"], 3)

    def test_scheduler_health_and_health_report(self):
        tasks = TaskRunnerService(self.database)
        running = tasks.start_task_run("official_sp_sync")
        tasks.finish_task_run_success(running["id"], attempts=2, affected_matches=3, created_snapshots=3)
        failed = tasks.start_task_run("external_odds_sync")
        tasks.finish_task_run_failed(failed["id"], "unauthorized", attempts=1)
        self.assertEqual(tasks.get_last_successful_run("official_sp_sync")["status"], "SUCCESS")
        self.assertEqual(tasks.list_recent_task_runs(2)[0]["status"], "FAILED")
        health = build_health_report(self.database)
        self.assertIn(health["status"], {"healthy", "degraded"})
        self.assertFalse(health["config"]["autoBettingEnabled"])
        self.assertNotIn("THE_ODDS_API_KEY=", str(health))

    def test_external_health_cadence_matches_hourly_scheduler(self):
        self.assertGreaterEqual(_effective_external_refresh_minutes(), 60)


if __name__ == "__main__":
    unittest.main()
