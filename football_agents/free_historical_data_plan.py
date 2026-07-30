from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .international_history_agent import InternationalHistoryAgent
from .international_odds_agent import InternationalOddsHistoryAgent
from .repository import Repository


class FreeHistoricalDataPlan:
    """Synchronize only reproducible no-cost international football evidence."""

    def __init__(
        self,
        repository: Repository | None = None,
        international_results: InternationalHistoryAgent | None = None,
        international_odds: InternationalOddsHistoryAgent | None = None,
        manifest_path: Path | None = None,
    ) -> None:
        self.repository = repository or Repository()
        self.international_results = international_results or InternationalHistoryAgent(self.repository)
        self.international_odds = international_odds or InternationalOddsHistoryAgent(self.repository)
        self.manifest_path = manifest_path or Path("data") / "historical_csv" / "free_plan_manifest.json"

    def sync(self, use_footiqo_fallback: bool = False) -> dict[str, Any]:
        steps: dict[str, dict[str, Any]] = {}

        try:
            steps["international_results"] = {
                "status": "success",
                "evidence_class": "features_only",
                "report": self.international_results.sync(),
            }
        except Exception as exc:
            steps["international_results"] = {
                "status": "failed", "evidence_class": "features_only", "error": str(exc),
            }

        try:
            report = self.international_odds.sync_football_data_world_cup()
            steps["world_cup_odds"] = {
                "status": "success" if report.get("conversion", {}).get("matched", 0) else "partial",
                "evidence_class": "market_calibration_research",
                "price_execution_status": "not_executable_average_or_max_price",
                "report": report,
            }
        except Exception as exc:
            steps["world_cup_odds"] = {
                "status": "failed", "evidence_class": "market_calibration_research", "error": str(exc),
            }

        if use_footiqo_fallback and steps["world_cup_odds"]["status"] == "failed":
            try:
                report = self.international_odds.sync_world_cup()
                steps["footiqo_world_cup_fallback"] = {
                    "status": "success" if report.get("conversion", {}).get("matched", 0) else "partial",
                    "evidence_class": "market_calibration_research",
                    "price_execution_status": "not_executable_closing_price_only",
                    "report": report,
                }
            except Exception as exc:
                steps["footiqo_world_cup_fallback"] = {
                    "status": "failed", "evidence_class": "market_calibration_research", "error": str(exc),
                }

        calibration_ready = any(
            item["status"] == "success" and item["evidence_class"] == "market_calibration_research"
            for item in steps.values()
        )
        feature_ready = steps["international_results"]["status"] == "success"
        status = "success" if calibration_ready and feature_ready else "partial" if calibration_ready or feature_ready else "failed"
        manifest = {
            "plan": "free-international-historical-data-v1",
            "status": status,
            "synced_at": datetime.now(timezone.utc).isoformat(),
            "steps": steps,
            "rules": [
                "Use World Cup and World Cup qualifier average/maximum closing-price rows for market calibration research only.",
                "Use broad international results without odds only for team features and form estimates.",
                "Do not simulate executable profit or claim an odds edge from average, maximum, or results-only data.",
                "Do not use a price snapshot captured at or after kickoff in a pre-match backtest.",
            ],
            "limitations": [
                "The World Cup workbook supplies average/max closing prices, not a named bookmaker's executable price.",
                "Free sources do not provide broad, timestamped multi-bookmaker international odds coverage.",
                "This plan does not replace a licensed historical odds feed for Euro, Copa America, or Nations League edge validation.",
            ],
        }
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        self.repository.add_audit_event(
            "free-historical-data-plan", "Free international historical data", "sync",
            json.dumps({"status": status, "calibration_ready": calibration_ready, "feature_ready": feature_ready}, ensure_ascii=False),
            status,
        )
        return {**manifest, "manifest_path": str(self.manifest_path)}
