from __future__ import annotations

import json
import tempfile
from pathlib import Path

from football_agents.db import Database
from football_agents.free_historical_data_plan import FreeHistoricalDataPlan
from football_agents.repository import Repository


class ResultsAgent:
    def sync(self):
        return {"imported": 10}


class OddsAgent:
    def sync_football_data_world_cup(self):
        return {"conversion": {"matched": 20}}


def test_free_plan_marks_results_and_odds_evidence_separately():
    with tempfile.TemporaryDirectory() as temp:
        database = Database(Path(temp) / "test.db")
        database.initialize()
        plan = FreeHistoricalDataPlan(
            Repository(database), ResultsAgent(), OddsAgent(), Path(temp) / "manifest.json"
        )

        report = plan.sync()

        assert report["status"] == "success"
        assert report["steps"]["international_results"]["evidence_class"] == "features_only"
        assert report["steps"]["world_cup_odds"]["evidence_class"] == "market_calibration_research"
        assert report["steps"]["world_cup_odds"]["price_execution_status"] == "not_executable_average_or_max_price"
        assert json.loads(Path(report["manifest_path"]).read_text(encoding="utf-8"))["status"] == "success"
