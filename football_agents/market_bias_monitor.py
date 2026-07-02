from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from .config import settings
from .db import Database, db
from .live_shadow_validation import run_shadow_for_active_matches
from .market_bias_official_validation import diagnose_market_bias_official_sp_funnel, validate_market_bias_on_official_sp
from .market_bias_pool_relevance import diagnose_market_bias_official_pool_relevance
from .market_bias_shadow_strategy import (
    I2_DRAW_STRATEGY_ID,
    find_market_bias_research_candidates,
    find_market_bias_shadow_candidates,
)
from .repository import Repository
from .shadow_evaluator import build_shadow_validation_metrics, evaluate_pending_shadow_predictions
from .shadow_prediction_store import ShadowPredictionStore
from .true_odds_config import get_default_true_odds_filter_config


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from market_bias_promotion_gate import evaluate_market_bias_promotion  # noqa: E402
from market_bias_profit_algorithm_scorecard import evaluate_profit_algorithm_scorecard  # noqa: E402


DEFAULT_REPORT_PATHS = {
    "robustness": Path("reports/market_bias_robustness_gate_i2_draw/summary.json"),
    "portfolio": Path("reports/market_bias_portfolio_simulation_i2_draw_avg_open_default/summary.json"),
    "official_sp": Path("reports/official_sp_market_bias_validation/summary.json"),
    "official_sp_funnel": Path("reports/official_sp_market_bias_funnel_i2_draw/summary.json"),
    "official_pool_relevance": Path("reports/market_bias_official_pool_relevance/summary.json"),
    "promotion": Path("reports/market_bias_promotion_gate_i2_draw/summary.json"),
    "scorecard": Path("reports/market_bias_profit_algorithm_scorecard_i2_draw/summary.json"),
    "multi_window": Path("reports/market_bias_multi_window_optimizer_i2_sp1_default/summary.json"),
    "shadow_metrics": Path("reports/market_bias_shadow_metrics_i2_draw/summary.json"),
}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class MarketBiasMonitorService:
    """Refreshes the leading market-bias strategy's prospective validation artifacts."""

    def __init__(self, database: Database = db, report_paths: dict[str, Path] | None = None,
                 strategy_id: str = I2_DRAW_STRATEGY_ID) -> None:
        self.db = database
        self.report_paths = {**DEFAULT_REPORT_PATHS, **(report_paths or {})}
        if report_paths is not None and "scorecard" not in report_paths:
            self.report_paths["scorecard"] = self.report_paths["promotion"].with_name("scorecard.json")
        if report_paths is not None and "multi_window" not in report_paths:
            self.report_paths["multi_window"] = self.report_paths["promotion"].with_name("multi_window.json")
        self.strategy_id = strategy_id

    def _ensure_shadow_config(self, store: ShadowPredictionStore) -> tuple[list[Any], list[str]]:
        warnings: list[str] = []
        active_versions = store.get_active_shadow_config_versions()
        if active_versions:
            return active_versions, warnings
        config = get_default_true_odds_filter_config()
        config.mode = "SHADOW"
        version = store.create_config_version(
            config,
            name="market-bias-i2-draw-shadow-monitor",
            notes="Automatically maintained by MarketBiasMonitorService for prospective I2 draw market-bias validation.",
            created_by="market-bias-monitor",
        )
        active = store.start_shadow_validation(version.config_version_id)
        warnings.append(f"created and started shadow config version {active.config_version_id}")
        return [active], warnings

    def _scan_live_candidates(self, repository: Repository) -> dict[str, Any]:
        matches = repository.list_official_matches()
        candidate_rows: list[dict[str, Any]] = []
        research_rows: list[dict[str, Any]] = []
        missing_odds = 0
        for match in matches:
            official = repository.latest_odds(match["id"])
            odds = official.get("odds") or {}
            if not all(float(odds.get(key) or 0) > 1 for key in ("home", "draw", "away")):
                missing_odds += 1
                continue
            for candidate in find_market_bias_shadow_candidates(match, odds):
                candidate_rows.append({
                    "match_id": match["id"],
                    "official_match_id": match.get("official_match_id"),
                    "league": match.get("league"),
                    "home_team": match.get("home_team"),
                    "away_team": match.get("away_team"),
                    "kickoff_time": match.get("kickoff_time"),
                    "strategy_id": candidate.strategy_id,
                    "outcome": candidate.outcome,
                    "selected_sp": candidate.selected_sp,
                    "selected_market_probability": candidate.selected_market_probability,
                })
            for candidate in find_market_bias_research_candidates(match, odds):
                research_rows.append({
                    "match_id": match["id"],
                    "official_match_id": match.get("official_match_id"),
                    "league": match.get("league"),
                    "home_team": match.get("home_team"),
                    "away_team": match.get("away_team"),
                    "kickoff_time": match.get("kickoff_time"),
                    "strategy_id": candidate.strategy_id,
                    "validation_stage": candidate.validation_stage,
                    "outcome": candidate.outcome,
                    "selected_sp": candidate.selected_sp,
                    "selected_market_probability": candidate.selected_market_probability,
                    "warnings": list(candidate.warnings),
                })
        counts: dict[str, int] = {}
        for row in candidate_rows:
            counts[row["strategy_id"]] = counts.get(row["strategy_id"], 0) + 1
        research_counts: dict[str, int] = {}
        for row in research_rows:
            research_counts[row["strategy_id"]] = research_counts.get(row["strategy_id"], 0) + 1
        return {
            "scanned_matches": len(matches),
            "missing_odds": missing_odds,
            "candidate_count": len(candidate_rows),
            "candidate_counts_by_strategy": counts,
            "candidates": candidate_rows[:100],
            "research_watchlist": {
                "candidate_count": len(research_rows),
                "candidate_counts_by_strategy": research_counts,
                "candidates": research_rows[:100],
                "note": "Research-watch candidates are not written as shadow or production recommendations.",
            },
        }

    def refresh(self, run_shadow: bool = True, ensure_shadow_config: bool = True) -> dict[str, Any]:
        warnings: list[str] = []
        shadow_runs: list[dict[str, Any]] = []
        shadow_metrics: list[dict[str, Any]] = []
        store = ShadowPredictionStore(self.db)
        repository = Repository(self.db)
        active_versions = store.get_active_shadow_config_versions()
        live_candidate_scan = self._scan_live_candidates(repository)
        if run_shadow and ensure_shadow_config and not active_versions:
            active_versions, created_warnings = self._ensure_shadow_config(store)
            warnings.extend(created_warnings)
        if run_shadow and active_versions:
            for version in active_versions:
                result = run_shadow_for_active_matches(version.config_version_id, repository)
                shadow_runs.append(result)
        elif run_shadow:
            warnings.append("no active shadow config version; market-bias live shadow samples were not refreshed")

        shadow_evaluations = []
        for version in active_versions:
            shadow_evaluations.append({
                "config_version_id": version.config_version_id,
                **evaluate_pending_shadow_predictions(version.config_version_id, self.db),
            })

        for version in active_versions:
            metrics = build_shadow_validation_metrics(version.config_version_id).to_dict()
            shadow_metrics.append(metrics)
        metrics_payload = {
            "strategy_id": self.strategy_id,
            "active_config_versions": [version.config_version_id for version in active_versions],
            "shadow_runs": shadow_runs,
            "shadow_evaluations": shadow_evaluations,
            "live_candidate_scan": live_candidate_scan,
            "metrics": shadow_metrics,
            "warnings": warnings,
        }
        _write_json(self.report_paths["shadow_metrics"], metrics_payload)

        official = validate_market_bias_on_official_sp(self.db, strategy_id=self.strategy_id).to_dict()
        _write_json(self.report_paths["official_sp"], official)
        official_funnel = diagnose_market_bias_official_sp_funnel(self.db)
        _write_json(self.report_paths["official_sp_funnel"], official_funnel)
        pool_relevance = diagnose_market_bias_official_pool_relevance(self.db)
        _write_json(self.report_paths["official_pool_relevance"], pool_relevance)

        promotion = None
        scorecard = None
        if self.report_paths["robustness"].exists() and self.report_paths["portfolio"].exists():
            robustness = _read_json(self.report_paths["robustness"])
            portfolio = _read_json(self.report_paths["portfolio"])
            multi_window_path = self.report_paths.get("multi_window")
            multi_window = _read_json(multi_window_path) if multi_window_path and multi_window_path.exists() else None
            promotion = evaluate_market_bias_promotion(
                robustness,
                portfolio,
                official,
                {"strategy_id": self.strategy_id},
            )
            _write_json(self.report_paths["promotion"], promotion)
            scorecard = evaluate_profit_algorithm_scorecard(
                strategy_id=self.strategy_id,
                rule=None,
                robustness=robustness,
                portfolio=portfolio,
                official_sp=official,
                promotion=promotion,
                multi_window=multi_window,
            )
            _write_json(self.report_paths["scorecard"], scorecard)
        else:
            missing = [
                str(path)
                for key in ("robustness", "portfolio")
                for path in [self.report_paths[key]]
                if not path.exists()
            ]
            warnings.append(f"market-bias promotion gate skipped; missing reports: {', '.join(missing)}")
            metrics_payload["warnings"] = warnings
            _write_json(self.report_paths["shadow_metrics"], metrics_payload)

        return {
            "strategy_id": self.strategy_id,
            "matches": sum(int(run.get("created", 0) or 0) for run in shadow_runs),
            "shadow_runs": shadow_runs,
            "shadow_evaluations": shadow_evaluations,
            "live_candidate_scan": live_candidate_scan,
            "active_shadow_configs": len(active_versions),
            "shadow_metrics_report": str(self.report_paths["shadow_metrics"]),
            "official_sp_report": str(self.report_paths["official_sp"]),
            "official_sp_funnel_report": str(self.report_paths["official_sp_funnel"]),
            "official_sp_funnel_blocker": official_funnel.get("blocker"),
            "official_pool_relevance_report": str(self.report_paths["official_pool_relevance"]),
            "official_pool_validated_candidates": pool_relevance.get("validated_shadow_candidates", 0),
            "official_pool_recommended_next_experiment": pool_relevance.get("recommended_next_experiment"),
            "promotion_report": str(self.report_paths["promotion"]) if promotion else None,
            "profit_algorithm_scorecard_report": str(self.report_paths["scorecard"]) if scorecard else None,
            "promotion_decision": promotion.get("decision") if promotion else None,
            "profit_algorithm_score": scorecard.get("score") if scorecard else None,
            "profit_algorithm_tier": scorecard.get("deployment_tier") if scorecard else None,
            "recommended_for_shadow": promotion.get("recommended_for_shadow") if promotion else None,
            "recommended_for_production": promotion.get("recommended_for_production") if promotion else None,
            "official_candidate_count": official.get("candidate_count", 0),
            "warnings": warnings,
        }
