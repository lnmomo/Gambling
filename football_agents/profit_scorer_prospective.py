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
from .prospective_statistics import build_prospective_statistical_evidence
from .repository import Repository


REQUIRED_SETTLEMENT_DAYS = 30


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


def _parse_time(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _load_frozen_evidence_rows(database: Database, artifact_sha256: str,
                               limit: int) -> list[dict[str, Any]]:
    with database.connect() as c:
        rows = c.execute("""SELECT e.*,m.official_match_id,m.league,m.home_team,m.away_team,
            m.kickoff_time,m.status,opening.observed_at,opening.home_sp,opening.draw_sp,opening.away_sp,
            closing.observed_at closing_observed_at,
            closing.home_sp closing_home_sp,closing.draw_sp closing_draw_sp,closing.away_sp closing_away_sp,
            r.outcome,r.home_score,r.away_score,r.settled_at
            FROM profit_scorer_evidence e
            JOIN matches m ON m.id=e.match_id
            JOIN official_odds_observations opening ON opening.id=e.official_odds_observation_id
            LEFT JOIN official_odds_closing_observations closing ON closing.match_id=e.match_id
            LEFT JOIN results r ON r.match_id=e.match_id
            WHERE e.scorer_artifact_sha256=?
            ORDER BY m.kickoff_time ASC LIMIT ?""",
            (artifact_sha256, max(1, min(limit, 100_000)))).fetchall()
    return [dict(row) for row in rows]


def validate_profit_scorer_on_official_sp(
    database: Database = db,
    scorer_artifact: Path | str = DEFAULT_SCORER_ARTIFACT,
    limit: int = 100_000,
    as_of: str | datetime | None = None,
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
    opening_rows = _load_opening_snapshot_rows(database, limit)
    capture_time = _parse_time(as_of or datetime.now(timezone.utc))
    capture_time_text = capture_time.isoformat()
    existing_attempts = repository.list_profit_scorer_freeze_attempts(artifact_sha256, limit)
    attempted_observations = {int(row["official_odds_observation_id"]) for row in existing_attempts}
    existing_evidence = repository.list_profit_scorer_evidence(limit=limit)
    evidenced_observations = {
        int(row["official_odds_observation_id"])
        for row in existing_evidence
        if str(row["scorer_artifact_sha256"]) == artifact_sha256
    }
    attempts_written = 0
    evidence_written = 0
    strategy_label = str(artifact.get("strategy_label") or artifact_sha256[:12])
    for row in opening_rows:
        observation_id = int(row["official_odds_observation_id"])
        if observation_id in attempted_observations or observation_id in evidenced_observations:
            continue
        observed_at = _parse_time(row["observed_at"])
        kickoff_time = _parse_time(row["kickoff_time"])
        if observed_at > capture_time:
            continue
        attempt = {
            "match_id": row["match_id"],
            "official_odds_observation_id": observation_id,
            "scorer_artifact_sha256": artifact_sha256,
            "strategy_label": strategy_label,
            "attempted_at": capture_time_text,
            "kickoff_time": row["kickoff_time"],
        }
        if capture_time >= kickoff_time:
            attempt.update({"status": "MISSED_PRE_MATCH", "blockers": ["capture_started_at_or_after_kickoff"]})
            attempts_written += int(repository.freeze_profit_scorer_attempt(attempt))
            continue
        match = {
            "id": row["match_id"],
            "official_match_id": row["official_match_id"],
            "league": row["league"],
            "home_team": row["home_team"],
            "away_team": row["away_team"],
            "kickoff_time": row["observed_at"],
            "status": row["status"],
        }
        odds = {"home": row["home_sp"], "draw": row["draw_sp"], "away": row["away_sp"]}
        mapped, missing, warnings = map_official_match_to_scorer_features(
            repository, match, odds, artifact, feature_cache
        )
        if mapped is None:
            attempt.update({"status": "BLOCKED", "blockers": missing})
            attempts_written += int(repository.freeze_profit_scorer_attempt(attempt))
            continue
        probability, ev = _score_from_artifact(mapped, artifact)
        passes = ev >= float(artifact["selection"]["min_predicted_ev"])
        frozen_features: dict[str, Any] = {
            **mapped,
            "_feature_cutoff_at": row["observed_at"],
            "_match_kickoff_time": row["kickoff_time"],
            "_warnings": warnings,
        }
        evidence = {
            "match_id": row["match_id"],
            "official_odds_observation_id": observation_id,
            "scorer_artifact_sha256": artifact_sha256,
            "strategy_label": strategy_label,
            "selected_outcome": selected_outcome.upper(),
            "feature_engine": FEATURE_ENGINE,
            "features": frozen_features,
            "market_probability": mapped["market_probability"],
            "predicted_probability": probability,
            "predicted_ev": ev,
            "passes_scorer": passes,
            "scored_at": capture_time_text,
        }
        attempt.update({"status": "SCORED", "blockers": []})
        written = repository.freeze_profit_scorer_attempt(attempt, evidence)
        attempts_written += int(written)
        evidence_written += int(written)

    attempts = repository.list_profit_scorer_freeze_attempts(artifact_sha256, limit)
    blocker_counts: dict[str, int] = {}
    for attempt in attempts:
        for reason in attempt.get("blockers") or []:
            blocker_counts[str(reason)] = blocker_counts.get(str(reason), 0) + 1

    frozen_rows = _load_frozen_evidence_rows(database, artifact_sha256, limit)
    temporal_violations = 0
    scored: list[dict[str, Any]] = []
    for row in frozen_rows:
        if not (_parse_time(row["observed_at"]) <= _parse_time(row["scored_at"]) < _parse_time(row["kickoff_time"])):
            temporal_violations += 1
            continue
        features = json.loads(row["feature_json"])
        outcome = str(row["selected_outcome"]).lower()
        selected_sp = float(features.get("odds") or row[f"{outcome}_sp"])
        passes = bool(row["passes_scorer"])
        profit = _profit(outcome, selected_sp, row.get("outcome")) if passes else None
        closing_sp = _closing_sp(row, outcome)
        clv = _clv(selected_sp, closing_sp) if passes else None
        scored.append({
            "match_id": row["match_id"],
            "official_match_id": row["official_match_id"],
            "official_odds_observation_id": row["official_odds_observation_id"],
            "league": row["league"],
            "home_team": row["home_team"],
            "away_team": row["away_team"],
            "kickoff_time": row["kickoff_time"],
            "observed_at": row["observed_at"],
            "scored_at": row["scored_at"],
            "month": _month(row["kickoff_time"]),
            "selected_outcome": row["selected_outcome"],
            "selected_sp": round(selected_sp, 4),
            "closing_observed_at": row.get("closing_observed_at"),
            "closing_sp": round(closing_sp, 4) if closing_sp is not None else None,
            "clv": round(clv, 6) if clv is not None else None,
            "market_probability": round(float(row["market_probability"]), 6),
            "predicted_probability": round(float(row["predicted_probability"]), 6),
            "predicted_ev": round(float(row["predicted_ev"]), 6),
            "passes_scorer": passes,
            "settled": bool(row.get("outcome")),
            "settled_at": row.get("settled_at"),
            "settlement_day": str(row.get("settled_at") or row["kickoff_time"])[:10],
            "actual_outcome": str(row.get("outcome")).upper() if row.get("outcome") else None,
            "profit": round(float(profit), 2) if profit is not None else None,
            "warnings": features.get("_warnings") or [],
            "feature_engine": row["feature_engine"],
            "feature_cutoff_at": features.get("_feature_cutoff_at"),
            "feature_snapshot": features,
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
    daily: list[dict[str, Any]] = []
    for day in sorted({str(row["kickoff_time"])[:10] for row in settled_selected}):
        day_rows = [row for row in settled_selected if str(row["kickoff_time"])[:10] == day]
        profit = round(sum(float(row["profit"] or 0) for row in day_rows), 2)
        daily.append({
            "date": day,
            "bets": len(day_rows),
            "wins": sum(1 for row in day_rows if float(row.get("profit") or 0) > 0),
            "profit": profit,
        })
    total_profit = round(sum(profits), 2)
    active_months = len(monthly)
    closing_sp_coverage = len(clv_values) / len(settled_selected) if settled_selected else 0.0
    average_clv = sum(clv_values) / len(clv_values) if clv_values else None
    positive_clv_rate = sum(value > 0 for value in clv_values) / len(clv_values) if clv_values else None
    statistical_evidence = build_prospective_statistical_evidence(settled_selected)
    point_estimates = statistical_evidence["point_estimates"]
    bootstrap = statistical_evidence["bootstrap"]
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
    mature_sample = len(settled_selected) >= 200 and active_months >= 6
    if mature_sample:
        if int(bootstrap.get("settlement_days") or 0) < REQUIRED_SETTLEMENT_DAYS:
            decision_reasons.append("settlement_days<30")
        roi_p05 = (bootstrap.get("roi_ci_pct") or {}).get("p05")
        if roi_p05 is None or float(roi_p05) <= 0:
            decision_reasons.append("bootstrap_roi_p05<=0")
        if closing_sp_coverage >= 0.80:
            clv_p05 = (bootstrap.get("average_clv_ci") or {}).get("p05")
            if clv_p05 is None or float(clv_p05) <= 0:
                decision_reasons.append("bootstrap_clv_p05<=0")
        brier_improvement = point_estimates.get("brier_improvement")
        log_loss_improvement = point_estimates.get("log_loss_improvement")
        if brier_improvement is None or float(brier_improvement) < 0:
            decision_reasons.append("model_brier_worse_than_market")
        if log_loss_improvement is None or float(log_loss_improvement) < 0:
            decision_reasons.append("model_log_loss_worse_than_market")
        brier_p05 = (bootstrap.get("brier_improvement_ci") or {}).get("p05")
        log_loss_p05 = (bootstrap.get("log_loss_improvement_ci") or {}).get("p05")
        if not (
            brier_p05 is not None and float(brier_p05) > 0
            or log_loss_p05 is not None and float(log_loss_p05) > 0
        ):
            decision_reasons.append("relative_calibration_confidence_not_positive")
    if temporal_violations:
        decision_reasons.append("frozen_evidence_temporal_violations>0")
    valid_three_way = sum(_valid_three_way({
        "home": row["home_sp"], "draw": row["draw_sp"], "away": row["away_sp"],
    }) for row in opening_rows)
    settled_opening = sum(bool(row.get("outcome")) for row in opening_rows)
    return {
        "method": "prospective official-SP validation for market-anchored profit scorer",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scorer_artifact": str(artifact_path),
        "scorer_artifact_sha256": artifact_sha256,
        "feature_engine": FEATURE_ENGINE,
        "capture_as_of": capture_time_text,
        "immutable_attempts_written": attempts_written,
        "immutable_evidence_written": evidence_written,
        "opening_pre_match_snapshots": len(opening_rows),
        "valid_three_way_snapshots": valid_three_way,
        "settled_opening_snapshots": settled_opening,
        "frozen_attempts": len(attempts),
        "frozen_scored_attempts": sum(row["status"] == "SCORED" for row in attempts),
        "frozen_blocked_attempts": sum(row["status"] == "BLOCKED" for row in attempts),
        "missed_pre_match_attempts": sum(row["status"] == "MISSED_PRE_MATCH" for row in attempts),
        "frozen_evidence_temporal_violations": temporal_violations,
        "scored_snapshots": len(scored),
        "selected_snapshots": len(selected),
        "settled_selected_snapshots": len(settled_selected),
        "unsettled_selected_snapshots": len(selected) - len(settled_selected),
        "active_months": active_months,
        "closing_sp_samples": len(clv_values),
        "closing_sp_coverage": round(closing_sp_coverage, 4),
        "average_clv": round(average_clv, 6) if average_clv is not None else None,
        "positive_clv_rate": round(positive_clv_rate, 4) if positive_clv_rate is not None else None,
        "statistical_evidence": statistical_evidence,
        "winning_count": wins,
        "profit": total_profit,
        "roi_pct": round(total_profit / len(settled_selected) * 100, 2) if settled_selected else 0.0,
        "hit_rate": round(wins / len(settled_selected), 4) if settled_selected else None,
        "max_drawdown": _max_drawdown(profits),
        "positive_months": sum(1 for row in monthly if row["profit"] > 0),
        "negative_months": sum(1 for row in monthly if row["profit"] < 0),
        "monthly": monthly,
        "daily": daily,
        "blocker_counts": [
            {"reason": reason, "snapshots": count}
            for reason, count in sorted(blocker_counts.items(), key=lambda item: item[1], reverse=True)
        ],
        "decision": "OFFICIAL_SP_PROSPECTIVE_PASS" if not decision_reasons else "OFFICIAL_SP_PROSPECTIVE_BLOCKED",
        "decision_reasons": decision_reasons,
        "selected": selected[:200],
        "guardrail": (
            "Each opening snapshot and scorer artifact receives one immutable pre-match freeze attempt. "
            "Settlement reads frozen evidence only; blocked or missed snapshots can never be rescored retrospectively."
        ),
    }
