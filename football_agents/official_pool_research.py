from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db import Database, db
from .market_bias_shadow_strategy import is_i2_league, is_jpn_league, is_sp1_league
from .repository import Repository


@dataclass(frozen=True)
class OfficialPoolResearchLeague:
    league: str
    matches: int
    with_latest_odds: int
    mapped_history_code: str | None
    historical_odds_available: bool
    historical_rows: int
    evidence_status: str
    blocker: str
    research_priority: str
    suggested_commands: list[str]
    evidence_reports: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _valid_three_way_odds(odds: dict[str, Any]) -> bool:
    try:
        return all(float(odds.get(key) or 0) > 1 for key in ("home", "draw", "away"))
    except (TypeError, ValueError):
        return False


def _normalize_league(league: Any) -> str:
    return str(league or "").strip()


def map_league_to_history_code(league: Any) -> str | None:
    raw = _normalize_league(league)
    folded = raw.casefold()
    if is_i2_league(raw):
        return "I2"
    if is_sp1_league(raw):
        return "SP1"
    if is_jpn_league(raw):
        return "JPN"
    if raw == "\u82ac\u8d85" or "finland" in folded or "veikkausliiga" in folded or folded == "fin":
        return "FIN"
    if raw == "\u745e\u8d85" or "sweden" in folded or "allsvenskan" in folded or folded == "swe":
        return "SWE"
    if raw == "\u4e16\u754c\u676f" or "world cup" in folded:
        return "WORLD_CUP"
    if raw == "\u56fd\u9645\u8d5b" or "international" in folded:
        return "INTERNATIONAL"
    return None


def _history_paths(code: str) -> list[Path]:
    root = Path("data/historical_csv/football-data")
    if code == "WORLD_CUP":
        path = root / "new" / "WORLD_CUP.csv"
        return [path] if path.exists() else []
    if code == "INTERNATIONAL":
        path = root / "new" / "INTERNATIONAL.csv"
        return [path] if path.exists() else []
    paths = sorted(root.glob(f"*/{code}.csv"))
    worldwide = root / "new" / f"{code}.csv"
    if worldwide.exists():
        paths.append(worldwide)
    return paths


def _count_csv_rows(paths: list[Path]) -> int:
    count = 0
    for path in paths:
        try:
            with path.open(encoding="utf-8-sig", newline="") as handle:
                count += sum(1 for _ in csv.DictReader(handle))
        except OSError:
            continue
    return count


def _existing(paths: list[str]) -> list[str]:
    return [path for path in paths if Path(path).exists()]


def _world_cup_validation_evidence() -> dict[str, Any] | None:
    for path in (
        Path("reports/world_cup_portfolio_grid_current_research/summary.json"),
        Path("reports/world_cup_portfolio_validation_max_close_draw_filtered_current_research/summary.json"),
        Path("reports/world_cup_portfolio_validation_avg_close_nonlongshot_current_research/summary.json"),
        Path("reports/world_cup_rolling_validation_avg_close_current_research/summary.json"),
        Path("reports/world_cup_rolling_validation_max_close_current_research/summary.json"),
        Path("reports/world_cup_rolling_validation_avg_close_newdata_v1/summary.json"),
        Path("reports/world_cup_rolling_validation_max_close_newdata_v1/summary.json"),
        Path("reports/world_cup_tournament_validation_current/summary.json"),
        Path("reports/world_cup_tournament_validation/summary.json"),
    ):
        if not path.exists():
            continue
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        decision = str(report.get("decision") or "")
        promotion = str(report.get("promotion_decision") or "")
        if decision.startswith("REJECT") or promotion.startswith("REJECT") or promotion.startswith("BLOCK"):
            verdict = "; ".join(item for item in (decision, promotion) if item) or "rejected"
            return {
                "status": "rejected_by_world_cup_tournament_holdout",
                "blocker": (
                    "World Cup 1X2 odds are archived, but no-lookahead validation rejected "
                    f"the reusable allocation rule search ({verdict})"
                ),
                "priority": "LOW_DO_NOT_LOOSEN",
                "reports": [str(path)],
                "commands": [
                    "python scripts/world_cup_tournament_validation.py --output-dir reports\\world_cup_tournament_validation_current",
                    "Collect broader paid international 1X2 odds history before retrying an international allocation rule.",
                ],
            }
        if "POSITIVE" in decision:
            return {
                "status": "research_only_world_cup_holdout_positive_sample_too_small",
                "blocker": (
                    "World Cup holdout produced a research-only positive result, but tournament sample size remains "
                    "too small for production allocation"
                ),
                "priority": "MEDIUM_RESEARCH",
                "reports": [str(path)],
                "commands": [
                    "Run broader international historical-odds validation before any promotion.",
                ],
            }
    return None


def _league_evidence(code: str | None) -> dict[str, Any]:
    if code == "I2":
        return {
            "status": "validated_profit_scorer_waiting_for_official_pool_coverage",
            "blocker": "validated algorithm exists, but current official fixtures must match I2 draw odds band and feature schema",
            "priority": "HIGH_WHEN_PRESENT",
            "reports": _existing([
                "reports/feature_enriched_market_anchored_i2_stop3_cool3_v1/summary.json",
                "reports/strategy_statistical_audit_market_anchored_i2_stop3_cool3_v1/summary.json",
                "reports/strategy_edge_calibration_market_anchored_i2_stop3_cool3_v1/summary.json",
                "reports/profit_scorer_official_pool/summary.json",
            ]),
            "commands": [
                "python -m football_agents.cli diagnose-profit-scorer-official-pool --limit 500 --output reports\\profit_scorer_official_pool\\summary.json",
            ],
        }
    if code == "SP1":
        return {
            "status": "research_only_unstable_windows",
            "blocker": "SP1 historical signal exists, but rolling-window stability is below promotion threshold",
            "priority": "MEDIUM_RESEARCH",
            "reports": _existing([
                "reports/market_bias_robustness_gate_sp1_home_prob55_100_pure/summary.json",
                "reports/market_bias_profit_algorithm_scorecard_i2_sp1_combo/summary.json",
                "reports/market_bias_promotion_gate_sp1_home_prob55_100_pure/summary.json",
            ]),
            "commands": [
                "python scripts/market_bias_multi_window_optimizer.py --rule \"league|outcome|market_prob_bucket=SP1|home|[0.55,1.00]\" --output-dir reports\\market_bias_multi_window_optimizer_sp1_home_recheck",
            ],
        }
    if code == "JPN":
        return {
            "status": "research_watch_only_source_diversity_weak",
            "blocker": "JPN away candidate has historical signal but failed source-diversity promotion gates",
            "priority": "MEDIUM_RESEARCH",
            "reports": _existing([
                "reports/market_bias_research_candidate_jpn_away_prob28_34/summary.json",
                "reports/market_bias_robustness_gate_worldwide_jpn_away_prob28_34/summary.json",
            ]),
            "commands": [
                "python scripts/market_bias_robustness_gate.py --seasons JPN --rule \"league|outcome|market_prob_bucket=JPN|away|[0.28,0.34)\" --odds-sources AVG_CLOSE,MAX_CLOSE,PS_CLOSE --output-dir reports\\market_bias_robustness_gate_jpn_recheck",
            ],
        }
    if code == "FIN":
        return {
            "status": "rejected_by_existing_market_bias_and_residual_tests",
            "blocker": "FIN is covered by historical odds, but simple market-bias and residual searches failed stability gates",
            "priority": "LOW_DO_NOT_LOOSEN",
            "reports": _existing([
                "reports/market_bias_robustness_gate_fin_away_prob28_34/summary.json",
                "reports/market_bias_robustness_gate_fin_away_2p8_3p5/summary.json",
                "reports/cross_league_rule_search_fin_residual_pool_v1/summary.json",
            ]),
            "commands": [
                "python scripts/cross_league_rule_search.py --seasons FIN --first-month 2015-04 --last-month 2025-10 --league-group-scope FIN --output-dir reports\\cross_league_rule_search_fin_new_model_recheck",
            ],
        }
    if code == "SWE":
        return {
            "status": "rejected_by_current_pool_feature_hard_gates",
            "blocker": (
                "SWE is present in the current official pool and has historical odds, but the market-anchored "
                "feature residual scan failed the hard stability gates"
            ),
            "priority": "LOW_DO_NOT_LOOSEN",
            "reports": _existing([
                "reports/official_pool_market_anchored_research_swe_current_fast/summary.json",
            ]),
            "commands": [
                "python scripts/official_pool_market_anchored_research.py --leagues SWE --odds-sources AVG_CLOSE,MAX_CLOSE --first-month 2016-01 --last-month 2025-12 --fast --output-dir reports\\official_pool_market_anchored_research_swe_current_fast",
            ],
        }
    if code == "WORLD_CUP":
        if _history_paths("WORLD_CUP"):
            validation = _world_cup_validation_evidence()
            if validation:
                return validation
            return {
                "status": "historical_1x2_odds_collected_needs_walk_forward_validation",
                "blocker": "World Cup 1X2 odds are archived; no World Cup strategy has passed no-lookahead validation gates yet",
                "priority": "HIGH_RESEARCH",
                "reports": [],
                "commands": [
                    "python scripts/market_bias_diagnostics.py --seasons WORLD_CUP --odds-source AVG_CLOSE --min-samples 20 --min-active-months 2 --output-dir reports\\market_bias_diagnostics_world_cup_avg_close",
                    "python scripts/market_bias_candidate_screen.py --diagnostics-csv reports\\market_bias_diagnostics_world_cup_avg_close\\market_bias.csv --no-include-default-rule --seasons WORLD_CUP --first-month 2018-06 --last-month 2022-12 --validation-odds-source AVG_CLOSE --top-n 8 --output-dir reports\\market_bias_candidate_screen_world_cup",
                ],
            }
        return {
            "status": "missing_historical_1x2_odds",
            "blocker": "World Cup results history is not enough; odds-edge validation requires historical 1X2 prices captured before matches",
            "priority": "DATA_FIRST",
            "reports": [],
            "commands": [
                "python -m football_agents.cli sync-international-odds-history",
                "Collect or import historical World Cup 1X2 odds CSV before running profit search.",
            ],
        }
    if code == "INTERNATIONAL":
        if _history_paths("INTERNATIONAL"):
            return {
                "status": "historical_1x2_odds_collected_needs_walk_forward_validation",
                "blocker": "International 1X2 odds are archived; no international strategy has passed validation gates yet",
                "priority": "HIGH_RESEARCH",
                "reports": [],
                "commands": [
                    "Run market-bias diagnostics and walk-forward validation on data/historical_csv/football-data/new/INTERNATIONAL.csv.",
                ],
            }
        return {
            "status": "missing_historical_1x2_odds",
            "blocker": "International-team results can build features but cannot validate a betting edge without odds history",
            "priority": "DATA_FIRST",
            "reports": [],
            "commands": [
                "python -m football_agents.cli sync-international-odds-history",
                "Collect or import historical international 1X2 odds CSV before running profit search.",
            ],
        }
    return {
        "status": "unmapped_league",
        "blocker": "league is not mapped to a historical odds validation domain",
        "priority": "MAP_FIRST",
        "reports": [],
        "commands": ["Map this league to a historical odds CSV code, then run diagnostics and walk-forward gates."],
    }


def plan_official_pool_profit_research(database: Database = db) -> dict[str, Any]:
    repository = Repository(database)
    buckets: dict[str, dict[str, Any]] = {}
    for match in repository.list_official_matches():
        league = _normalize_league(match.get("league")) or "UNKNOWN"
        bucket = buckets.setdefault(league, {"league": league, "matches": 0, "with_latest_odds": 0})
        bucket["matches"] += 1
        odds = repository.latest_odds(int(match["id"])).get("odds") or {}
        if _valid_three_way_odds(odds):
            bucket["with_latest_odds"] += 1

    leagues: list[OfficialPoolResearchLeague] = []
    for row in sorted(buckets.values(), key=lambda item: item["matches"], reverse=True):
        code = map_league_to_history_code(row["league"])
        history_paths = _history_paths(code) if code else []
        evidence = _league_evidence(code)
        leagues.append(OfficialPoolResearchLeague(
            league=row["league"],
            matches=int(row["matches"]),
            with_latest_odds=int(row["with_latest_odds"]),
            mapped_history_code=code,
            historical_odds_available=bool(history_paths),
            historical_rows=_count_csv_rows(history_paths),
            evidence_status=evidence["status"],
            blocker=evidence["blocker"],
            research_priority=evidence["priority"],
            suggested_commands=evidence["commands"],
            evidence_reports=evidence["reports"],
        ))

    status_counts: dict[str, int] = {}
    for league in leagues:
        status_counts[league.evidence_status] = status_counts.get(league.evidence_status, 0) + league.matches
    actionable = [
        league for league in leagues
        if league.research_priority in {"HIGH_WHEN_PRESENT", "HIGH_RESEARCH", "MEDIUM_RESEARCH", "DATA_FIRST"}
    ]
    next_action = (
        "Run the frozen I2 scorer on official pool when I2 fixtures appear."
        if any(league.mapped_history_code == "I2" for league in actionable) else
        "Run no-lookahead World Cup validation now that historical 1X2 odds are archived."
        if any(league.mapped_history_code == "WORLD_CUP" and league.research_priority == "HIGH_RESEARCH" for league in actionable) else
        "Collect historical 1X2 odds for current no-coverage leagues before inventing new betting rules."
        if any(league.research_priority == "DATA_FIRST" for league in actionable) else
        "Do not loosen rejected leagues; search for a materially different feature model or wait for validated-league coverage."
    )
    return {
        "method": "official-pool-driven profit algorithm research planner",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "official_matches": sum(league.matches for league in leagues),
        "with_latest_odds": sum(league.with_latest_odds for league in leagues),
        "league_count": len(leagues),
        "status_counts": [
            {"status": status, "matches": matches}
            for status, matches in sorted(status_counts.items(), key=lambda item: item[1], reverse=True)
        ],
        "leagues": [league.to_dict() for league in leagues],
        "next_algorithmic_action": next_action,
        "guardrail": "A league may enter allocation only after no-lookahead walk-forward, statistical audit, calibration, and official-SP prospective validation.",
    }
