from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from football_agents.db import Database
from football_agents.repository import Repository


class ManagementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        database = Database(Path(self.temp.name) / "management.db")
        database.initialize()
        self.repository = Repository(database)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_settings_are_persisted_and_audited(self) -> None:
        saved = self.repository.save_settings({"refresh_seconds": 300, "compact_table": True})
        self.assertEqual(saved["refresh_seconds"], 300)
        self.assertTrue(saved["compact_table"])
        logs = self.repository.list_audit_events()
        self.assertEqual(logs[0]["module"], "设置")

    def test_empty_management_views_are_real_empty_states(self) -> None:
        self.assertEqual(self.repository.list_backtest_reports(), [])
        self.assertEqual(self.repository.bankroll_history(), [])
        self.assertEqual(self.repository.data_counts()["matches"], 0)


if __name__ == "__main__":
    unittest.main()
