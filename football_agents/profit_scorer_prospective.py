from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db import Database, db
from .profit_scorer_official import (
    DEFAULT_SCORER_ARTIFACT,
    _artifact_selection,
    _score_from_artifact,
    map_official_match_to_scorer_features,
)
from .profit_scorer_features import FEATURE_ENGINE, ResearchParityFeatureCache
from .repository import Repository


def _load_opening_snapshot_rows(database: Database, limit: int) -> list[dict[str, Any]]:
    with database.connect() as c:
        rows = c.execute("""SELECT m.id match_id,m.official_match_id,m.league,m.home_team,m.away_team,
            m.kickoff_time,m.status,
            opening.id official_odds_observation_id,opening.observed_at,
            opening.home_sp,opening.draw_sp,opening.away_sp,
            closing.observed_at closing_observed_at,
            closing.home_sp closing_home_sp,closing.draw_sp closing_draw_sp,closing.away_sp closing_away_sp,
            r.outcome,r.home_score,r.away_score,r.settled_at
            FROM matches m
            JOIN official_odds_observations opening ON opening.id=(
                SELECT first.id FROM official_odds_observations first
                WHERE first.match_id=m.id AND first.is_pre_match=1
                ORDER BY first.observed_at ASC LIMIT 1)
            LEFT JOIN official_odds_closing_observations closing ON closing.match_id=m.id
            LEFT JOIN results r ON r.match_id=m.id
            ORDER BY m.kickoff_time ASC
            LIMIT ?""", (max(1, min(limit, 100_000)),)).fetchall()
    return [dict(row) for row in rows]


def _valid_three_way(odds: dict[str, Any]) -> bool:
    try:
        return all(float(odds.get(key) or 0) > 1 for key in ("home", "draw", "away"))
    except (TypeError, ValueError):
        return False


def _month(value: str) -> str:
    return str(value)[:7]


def _profit(selected_outcome: str, selected_sp: float, actual: str | None) -> float | None:
    if not actual:
        return None
    return selected_sp - 1.0 if selected_outcome == actual.lower() else -1.0


def _closing_sp(row: dict[str, Any], selected_outcome: str) -> float | None:
    try:
        value = float(row.get(f"closing_{selected_outcome}_sp") or 0)
    except (TypeError, ValueError):
        return None
    return value if value > 1 else None


def _clv(selected_sp: float, closing_sp: float | None) -> float | None:
    if closing_sp is None or closing_sp <= 1:
        return None
    return selected_sp / closing_sp - 1.0


def _max_drawdown(profits: list[float]) -> float:
    equity = peak = worst = 0.0
    for profit in profits:
        equity += profit
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return round(worst, 2)


def validate_profit_scorer_on_official_sp(
    database: Database = db,
    scorer_artifact: Path | str = DEFAULT_SCORER_ARTIFACT,
    limit: int = 100_000,
) -> dict[str, Any]:
    artifact_path = Path(scorer_artifact)
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    artifact_sha256 = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    scope = _artifact_selection(artifact)
    if scope is None:
        raise ValueError("Unsupported scorer artifact selection")
    selected_outcome = str(scope["outcome"])
    repository = Repository(database)
    feature_cache = ResearchParityFeatureCache(repository, scope["league_matches"])
    rows = _load_opening_snapshot_rows(database, limit)
    scored: list[dict[str, Any]] = []
    blocker_counts: dict[str, int] = {}
    valid_three_way = 0
    settled_opening = 0
    evidence_written = 0
    for row in rows:
        match = {
            "id": row["match_id"],
            "official_match_id": row["official_match_id"],
            "league": row["league"],
            "home_team": row["home_team"],
            "away_team": row["away_team"],
            "kickoff_time": row["kickoff_time"],
            "status": row["status"],
        }
        odds = {"home": row["home_sp"], "draw": row["draw_sp"], "away": row["away_sp"]}
        if _valid_three_way(odds):
            valid_three_way += 1
        if row.get("outcome"):
            settled_opening += 1
        mapped, missing, warnings = map_official_match_to_scorer_features(
            repository, match, odds, artifact, feature_cache
        )
        if mapped is None:
            for reason in missing:
                blocker_counts[reason] = blocker_counts.get(reason, 0) + 1
            continue
        probability, ev = _score_from_artifact(mapped, artifact)
        passes = ev >= float(artifact["selection"]["min_predicted_ev"])
        evidence_written += int(repository.add_profit_scorer_evidence({
            "match_id": row["match_id"],
            "official_odds_observation_id": row["official_odds_observation_id"],
            "scorer_artifact_sha256": artifact_sha256,
            "strategy_label": str(artifact.get("strategy_label") or artifact_sha256[:12]),
            "selected_outcome": selected_outcome.upper(),
            "feature_engine": FEATURE_ENGINE,
            "features": mapped,
            "market_probability": mapped["market_probability"],
            "predicted_probability": probability,
            "predicted_ev": ev,
            "passes_scorer": passes,
        }))
        profit = _profit(selected_outcome, float(mapped["odds"]), row.get("outcome")) if passes else None
        closing_sp = _closing_sp(row, selected_outcome)
        clv = _clv(float(mapped["odds"]), closing_sp) if passes else None
        scored.append({
            "match_id": row["match_id"],
            "official_match_id": row["official_match_id"],
            "official_odds_observation_id": row["official_odds_observation_id"],
            "league": row["league"],
            "home_team": row["home_team"],
            "away_team": row["away_team"],
            "kickoff_time": row["kickoff_time"],
            "observed_at": row["observed_at"],
            "month": _month(row["kickoff_time"]),
            "selected_outcome": selected_outcome.upper(),
            "selected_sp": round(float(mapped["odds"]), 4),
            "closing_observed_at": row.get("closing_observed_at"),
            "closing_sp": round(closing_sp, 4) if closing_sp is not None else None,
            "clv": round(clv, 6) if clv is not None else None,
            "market_probability": round(float(mapped["market_probability"]), 6),
            "predicted_probability": round(probability, 6),
            "predicted_ev": round(ev, 6),
            "passes_scorer": passes,
            "settled": bool(row.get("outcome")),
            "actual_outcome": str(row.get("outcome")).upper() if row.get("outcome") else None,
            "profit": round(float(profit), 2) if profit is not None else None,
            "warnings": warnings,
            "feature_engine": FEATURE_ENGINE,
            "feature_snapshot": {key: round(float(value), 8) for key, value in mapped.items()},
        })
    selected = [row for row in scored if row["passes_scorer"]]
    settled_selected = [row for row in selected if row["settled"]]
    profits = [float(row["profit"]) for row in settled_selected if row.get("profit") is not None]
    clv_values = [float(row["clv"]) for row in settled_selected if row.get("clv") is not None]
    wins = sum(1 for row in settled_selected if float(row.get("profit") or 0) > 0)
    monthly: list[dict[str, Any]] = []
    for month in sorted({row["month"] for row in settled_selected}):
        month_rows = [row for row in settled_selected if row["month"] == month]
        profit = round(sum(float(row["profit"] or 0) for row in month_rows), 2)
        monthly.append({
            "month": month,
            "bets": len(month_rows),
            "wins": sum(1 for row in month_rows if float(row.get("profit") or 0) > 0),
            "profit": profit,
            "roi_pct": round(profit / len(month_rows) * 100, 2) if month_rows else 0.0,
        })
    total_profit = round(sum(profits), 2)
    active_months = len(monthly)
    closing_sp_coverage = len(clv_values) / len(settled_selected) if settled_selected else 0.0
    average_clv = sum(clv_values) / len(clv_values) if clv_values else None
    positive_clv_rate = sum(value > 0 for value in clv_values) / len(clv_values) if clv_values else None
    decision_reasons: list[str] = []
    if len(settled_selected) < 200:
        decision_reasons.append("settled_selected<200")
    if active_months < 6:
        decision_reasons.append("settled_months<6")
    if total_profit <= 0:
        decision_reasons.append("profit<=0")
    if sum(1 for row in monthly if row["profit"] > 0) <= sum(1 for row in monthly if row["profit"] < 0):
        decision_reasons.append("positive_months<=negative_months")
    if _max_drawdown(profits) > max(total_profit, 1.0):
        decision_reasons.append("max_drawdown>profit")
    if settled_selected:
        if closing_sp_coverage < 0.80:
            decision_reasons.append("closing_sp_coverage<0.8")
        elif average_clv is None or average_clv <= 0:
            decision_reasons.append("average_clv<=0")
        elif positive_clv_rate is None or positive_clv_rate < 0.50:
            decision_reasons.append("positive_clv_rate<0.5")
    return {
        "method": "prospective official-SP validation for market-anchored profit scorer",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scorer_artifact": str(artifact_path),
        "scorer_artifact_sha256": artifact_sha256,
        "feature_engine": FEATURE_ENGINE,
        "immutable_evidence_written": evidence_written,
        "opening_pre_match_snapshots": len(rows),
        "valid_three_way_snapshots": valid_three_way,
        "settled_opening_snapshots": settled_opening,
        "scored_snapshots": len(scored),
        "selected_snapshots": len(selected),
        "settled_selected_snapshots": len(settled_selected),
        "unsettled_selected_snapshots": len(selected) - len(settled_selected),
        "active_months": active_months,
        "closing_sp_samples": len(clv_values),
        "closing_sp_coverage": round(closing_sp_coverage, 4),
        "average_clv": round(average_clv, 6) if average_clv is not None else None,
        "positive_clv_rate": round(positive_clv_rate, 4) if positive_clv_rate is not None else None,
        "winning_count": wins,
        "profit": total_profit,
        "roi_pct": round(total_profit / len(settled_selected) * 100, 2) if settled_selected else 0.0,
        "hit_rate": round(wins / len(settled_selected), 4) if settled_selected else None,
        "max_drawdown": _max_drawdown(profits),
        "positive_months": sum(1 for row in monthly if row["profit"] > 0),
        "negative_months": sum(1 for row in monthly if row["profit"] < 0),
        "monthly": monthly,
        "blocker_counts": [
            {"reason": reason, "snapshots": count}
            for reason, count in sorted(blocker_counts.items(), key=lambda item: item[1], reverse=True)
        ],
        "decision": "OFFICIAL_SP_PROSPECTIVE_PASS" if not decision_reasons else "OFFICIAL_SP_PROSPECTIVE_BLOCKED",
        "decision_reasons": decision_reasons,
        "selected": selected[:200],
        "guardrail": "Selection uses only the earliest pre-match official SP snapshot; outcome is used only after settlement.",
    }
