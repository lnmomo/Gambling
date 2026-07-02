from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db import Database, db
from .market_bias_shadow_strategy import (
    I2_DRAW_STRATEGY_ID,
    find_market_bias_research_candidates,
    find_market_bias_shadow_candidates,
    is_i2_league,
    is_jpn_league,
    is_sp1_league,
)
from .repository import Repository


FIN_AWAY_RESEARCH_RULE = "league|outcome|market_prob_bucket=FIN|away|[0.28,0.34)"


@dataclass(frozen=True)
class LeagueRelevance:
    league: str
    matches: int
    with_latest_odds: int
    missing_latest_odds: int
    mapped_history_code: str | None
    strategy_coverage: str
    validated_shadow_candidates: int
    research_watch_candidates: int
    evidence_status: str
    evidence_reports: list[str]
    blocker: str
    recommended_action: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _repo_exists(path: str) -> bool:
    return Path(path).exists()


def _league_mapping(league: Any) -> dict[str, Any]:
    raw = str(league or "").strip()
    normalized = raw.casefold()
    if is_i2_league(raw):
        return {
            "code": "I2",
            "coverage": "VALIDATED_SHADOW_RULE",
            "evidence_status": "validated historical edge; official prospective samples still required",
            "reports": [
                "reports/market_bias_robustness_gate_i2_draw/summary.json",
                "reports/market_bias_portfolio_simulation_i2_draw_avg_open_default/summary.json",
                "reports/market_bias_multi_window_optimizer_i2_sp1_default/summary.json",
                "reports/market_bias_profit_algorithm_scorecard_i2_draw/summary.json",
            ],
            "action": "Keep I2 draw band in shadow; promote only after official-SP prospective samples pass.",
        }
    if is_sp1_league(raw):
        return {
            "code": "SP1",
            "coverage": "RESEARCH_ONLY",
            "evidence_status": "full-period signal exists but rolling windows are unstable",
            "reports": [
                "reports/market_bias_multi_window_optimizer_i2_sp1_default/summary.json",
                "reports/market_bias_promotion_gate_sp1_home_prob55_100/summary.json",
            ],
            "action": "Do not use for allocation; keep as research watch until multi-window stability improves.",
        }
    if is_jpn_league(raw):
        return {
            "code": "JPN",
            "coverage": "RESEARCH_WATCH_ONLY",
            "evidence_status": "historical signal failed source-diversity promotion gates",
            "reports": [
                "reports/market_bias_research_candidate_jpn_away_prob28_34/summary.json",
                "reports/market_bias_robustness_gate_worldwide_jpn_away_prob28_34/summary.json",
            ],
            "action": "Do not use for allocation; collect official-SP prospective evidence first.",
        }
    if raw == "\u82ac\u8d85" or "finland" in normalized or "veikkausliiga" in normalized or normalized == "fin":
        return {
            "code": "FIN",
            "coverage": "REJECTED_RESEARCH_RULE",
            "evidence_status": "FIN away probability rule failed robustness and selected no settlement-aware bets",
            "reports": [
                "reports/market_bias_robustness_gate_fin_away_prob28_34/summary.json",
                "reports/market_bias_portfolio_simulation_fin_away_prob28_34_ps_close/summary.json",
            ],
            "action": "Do not loosen FIN into live allocation; run new FIN-specific research before using it.",
        }
    if raw == "\u4e16\u754c\u676f" or "world cup" in normalized:
        return {
            "code": "WORLD_CUP",
            "coverage": "NO_MARKET_BIAS_VALIDATION_SOURCE",
            "evidence_status": "results history may exist, but no validated 1X2 odds-bias history is available here",
            "reports": [],
            "action": "Collect historical 1X2 odds for World Cup/international matches before creating a market-bias rule.",
        }
    if raw == "\u56fd\u9645\u8d5b" or "international" in normalized:
        return {
            "code": "INTERNATIONAL",
            "coverage": "NO_MARKET_BIAS_VALIDATION_SOURCE",
            "evidence_status": "international-team results are not enough for odds-bias profit validation",
            "reports": [],
            "action": "Collect match odds plus results before considering allocation.",
        }
    return {
        "code": None,
        "coverage": "UNMAPPED",
        "evidence_status": "no mapped historical validation package",
        "reports": [],
        "action": "Map the league to historical odds data, then require multi-window and portfolio validation.",
    }


def diagnose_market_bias_official_pool_relevance(database: Database = db) -> dict[str, Any]:
    repository = Repository(database)
    league_rows: dict[str, dict[str, Any]] = {}
    for match in repository.list_official_matches():
        league = str(match.get("league") or "UNKNOWN")
        bucket = league_rows.setdefault(league, {
            "league": league,
            "matches": 0,
            "with_latest_odds": 0,
            "validated_shadow_candidates": 0,
            "research_watch_candidates": 0,
        })
        bucket["matches"] += 1
        odds = repository.latest_odds(match["id"]).get("odds") or {}
        has_odds = all(float(odds.get(key) or 0) > 1 for key in ("home", "draw", "away"))
        if not has_odds:
            continue
        bucket["with_latest_odds"] += 1
        bucket["validated_shadow_candidates"] += len(find_market_bias_shadow_candidates(match, odds))
        bucket["research_watch_candidates"] += len(find_market_bias_research_candidates(match, odds))

    leagues: list[LeagueRelevance] = []
    for row in sorted(league_rows.values(), key=lambda item: item["matches"], reverse=True):
        mapping = _league_mapping(row["league"])
        missing = int(row["matches"]) - int(row["with_latest_odds"])
        existing_reports = [path for path in mapping["reports"] if _repo_exists(path)]
        if row["validated_shadow_candidates"] > 0:
            blocker = "validated shadow candidates exist; await settlement and official-SP promotion checks"
        elif row["with_latest_odds"] == 0:
            blocker = "no latest official 1X2 odds in current pool"
        elif mapping["coverage"] == "VALIDATED_SHADOW_RULE":
            blocker = "validated league exists but current odds do not match the frozen rule band"
        elif mapping["coverage"] == "REJECTED_RESEARCH_RULE":
            blocker = "current league has historical data, but candidate rule failed robustness"
        elif mapping["coverage"] == "NO_MARKET_BIAS_VALIDATION_SOURCE":
            blocker = "current league has no validated odds-bias history package"
        elif mapping["coverage"].startswith("RESEARCH"):
            blocker = "only research-watch candidates exist; allocation is blocked by validation gates"
        else:
            blocker = "league is not mapped to a validated market-bias package"
        leagues.append(LeagueRelevance(
            league=row["league"],
            matches=int(row["matches"]),
            with_latest_odds=int(row["with_latest_odds"]),
            missing_latest_odds=missing,
            mapped_history_code=mapping["code"],
            strategy_coverage=mapping["coverage"],
            validated_shadow_candidates=int(row["validated_shadow_candidates"]),
            research_watch_candidates=int(row["research_watch_candidates"]),
            evidence_status=mapping["evidence_status"],
            evidence_reports=existing_reports,
            blocker=blocker,
            recommended_action=mapping["action"],
        ))

    total_matches = sum(row.matches for row in leagues)
    total_with_odds = sum(row.with_latest_odds for row in leagues)
    total_validated = sum(row.validated_shadow_candidates for row in leagues)
    total_research = sum(row.research_watch_candidates for row in leagues)
    blockers: dict[str, int] = {}
    for row in leagues:
        blockers[row.blocker] = blockers.get(row.blocker, 0) + row.matches
    return {
        "method": "market-bias official pool relevance diagnostics",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "strategy_id": I2_DRAW_STRATEGY_ID,
        "official_matches": total_matches,
        "with_latest_odds": total_with_odds,
        "missing_latest_odds": total_matches - total_with_odds,
        "validated_shadow_candidates": total_validated,
        "research_watch_candidates": total_research,
        "league_count": len(leagues),
        "leagues": [row.to_dict() for row in leagues],
        "blocker_summary": [
            {"blocker": blocker, "matches": matches}
            for blocker, matches in sorted(blockers.items(), key=lambda item: item[1], reverse=True)
        ],
        "recommended_next_experiment": (
            "Do not force NO_BET bypasses. First collect World Cup/international 1X2 odds history, "
            "or run a new FIN-specific multi-window search; current validated I2 rule has no live pool coverage."
            if total_validated == 0 else
            "Keep validated candidates in shadow and wait for settlement evidence before production allocation."
        ),
    }
