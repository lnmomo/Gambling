from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import settings
from .db import Database, db
from .profit_allocation_readiness import build_profit_allocation_readiness
from .profit_strategy_registry import list_profit_strategy_packages


CHINA_TZ = timezone(timedelta(hours=8))
MAX_LEAGUE_DAILY_SHARE = 0.40
MAX_OUTCOME_DAILY_SHARE = 0.50
MAX_LONGSHOT_DAILY_SHARE = 0.25
LONGSHOT_ODDS_THRESHOLD = 4.00
DEFAULT_MAX_SINGLE_STAKE = 10.0
RISK_POLICY: dict[str, Any] = {
    "version": "settled-day-drawdown-shadow-v2",
    "enforcement": "SHADOW_ONLY",
    "half_stake_losing_days": 999,
    "pause_losing_days": 2,
    "half_stake_drawdown_budget_multiple": 999.0,
    "pause_drawdown_budget_multiple": 999.0,
    "pause_days": 3,
    "recovery_multiplier": 1.0,
    "half_stake_multiplier": 1.0,
    "maximum_league_daily_share": MAX_LEAGUE_DAILY_SHARE,
    "maximum_outcome_daily_share": MAX_OUTCOME_DAILY_SHARE,
    "maximum_longshot_daily_share": MAX_LONGSHOT_DAILY_SHARE,
    "longshot_odds_threshold": LONGSHOT_ODDS_THRESHOLD,
}


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _parse_time(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _artifact_hash(path_text: str | None) -> str | None:
    if not path_text:
        return None
    path = Path(path_text)
    if not path.is_absolute():
        path = settings.project_dir / path
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _selected_sp(row: dict[str, Any]) -> float:
    key = str(row["selected_outcome"]).lower()
    return float(row[f"{key}_sp"])


def _quarter_kelly(probability: float, odds: float) -> float:
    full = (probability * odds - 1.0) / (odds - 1.0)
    return max(0.0, min(0.10, full * 0.25))


def settled_risk_state(
    daily: list[dict[str, Any]],
    as_of: datetime,
    daily_budget: float,
    last_settled_at: datetime | None,
) -> dict[str, Any]:
    equity = peak = max_drawdown = 0.0
    for row in daily:
        equity += float(row["profit"])
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    current_drawdown = max(0.0, peak - equity)
    losing_days = 0
    for row in reversed(daily):
        if float(row["profit"]) < 0:
            losing_days += 1
        elif float(row["profit"]) > 0:
            break
    days_since_last_settlement = (
        max(0, (as_of - last_settled_at).days) if last_settled_at is not None else None
    )
    pause_trigger = (
        losing_days >= int(RISK_POLICY["pause_losing_days"])
        or current_drawdown >= daily_budget * float(RISK_POLICY["pause_drawdown_budget_multiple"])
    )
    last_day_lost = bool(daily and float(daily[-1]["profit"]) < 0)
    in_pause = bool(
        pause_trigger
        and last_day_lost
        and days_since_last_settlement is not None
        and days_since_last_settlement < int(RISK_POLICY["pause_days"])
    )
    if in_pause:
        multiplier, status = 0.0, "PAUSED"
    elif pause_trigger:
        multiplier = float(RISK_POLICY["recovery_multiplier"])
        status = "RECOVERY"
    elif (
        losing_days >= int(RISK_POLICY["half_stake_losing_days"])
        or current_drawdown >= daily_budget * float(
            RISK_POLICY["half_stake_drawdown_budget_multiple"]
        )
    ):
        multiplier = float(RISK_POLICY["half_stake_multiplier"])
        status = "REDUCED"
    else:
        multiplier, status = 1.0, "NORMAL"
    applied_multiplier = multiplier if RISK_POLICY["enforcement"] == "ACTIVE" else 1.0
    return {
        "policy": RISK_POLICY,
        "policy_hash": _hash(RISK_POLICY),
        "status": status,
        "stake_multiplier": multiplier,
        "recommended_stake_multiplier": multiplier,
        "applied_stake_multiplier": applied_multiplier,
        "enforcement": RISK_POLICY["enforcement"],
        "settled_days": len(daily),
        "consecutive_losing_settlement_days": losing_days,
        "equity": round(equity, 2),
        "peak_equity": round(peak, 2),
        "current_drawdown": round(current_drawdown, 2),
        "max_drawdown": round(max_drawdown, 2),
        "last_settled_at": last_settled_at.isoformat() if last_settled_at else None,
        "days_since_last_settlement": days_since_last_settlement,
        "uses_only_settled_ledger": True,
    }


class PaperPortfolioService:
    """Create and settle an immutable paper-only portfolio from promoted evidence."""

    def __init__(self, database: Database = db) -> None:
        self.database = database

    def _strategy_map(self) -> dict[str, dict[str, Any]]:
        output: dict[str, dict[str, Any]] = {}
        for package in list_profit_strategy_packages():
            strategy_id = str(package.get("strategy_id"))
            if (
                package.get("source_type") == "EXTERNAL_CONSENSUS"
                and package.get("policy_id") and package.get("policy_hash")
            ):
                output[strategy_id] = package
                continue
            artifact_hash = _artifact_hash(package.get("scorer_artifact_report"))
            if artifact_hash:
                output[strategy_id] = {
                    **package, "source_type": "PROFIT_SCORER", "artifact_hash": artifact_hash,
                }
        return output

    def _risk_state(self, as_of: datetime, daily_budget: float) -> dict[str, Any]:
        with self.database.connect() as connection:
            rows = connection.execute("""SELECT s.settled_at,s.profit
                FROM paper_portfolio_settlements s
                WHERE unixepoch(s.settled_at)<=unixepoch(?)
                ORDER BY s.settled_at,s.settlement_id""", (as_of.isoformat(),)).fetchall()
        by_day: dict[str, float] = {}
        last_settled_at: datetime | None = None
        for row in rows:
            settled_at = _parse_time(row["settled_at"]).astimezone(CHINA_TZ)
            by_day[settled_at.date().isoformat()] = (
                by_day.get(settled_at.date().isoformat(), 0.0) + float(row["profit"])
            )
            last_settled_at = _parse_time(row["settled_at"]).astimezone(timezone.utc)
        daily = [{"date": day, "profit": round(by_day[day], 2)} for day in sorted(by_day)]
        return settled_risk_state(daily, as_of, daily_budget, last_settled_at)

    def _strategy_candidates(self, strategy: dict[str, Any], as_of: str) -> list[dict[str, Any]]:
        if strategy.get("source_type") == "EXTERNAL_CONSENSUS":
            return self._external_consensus_candidates(strategy, as_of)
        return self._profit_scorer_candidates(
            str(strategy["strategy_id"]), str(strategy["artifact_hash"]), as_of
        )

    def _profit_scorer_candidates(self, strategy_id: str, artifact_hash: str,
                                  as_of: str) -> list[dict[str, Any]]:
        # Keep the SQL strategy predicate exact without interpolating identifiers.
        with self.database.connect() as connection:
            rows = connection.execute("""SELECT e.*,m.official_match_id,m.league,m.home_team,m.away_team,
                m.kickoff_time,o.id current_odds_observation_id,o.observed_at current_odds_observed_at,
                o.home_sp,o.draw_sp,o.away_sp
                FROM profit_scorer_evidence e
                JOIN matches m ON m.id=e.match_id
                JOIN official_odds_observations o ON o.id=(
                    SELECT latest.id FROM official_odds_observations latest
                    WHERE latest.match_id=e.match_id AND latest.is_pre_match=1
                      AND unixepoch(latest.observed_at)<=unixepoch(?)
                    ORDER BY latest.observed_at DESC,latest.id DESC LIMIT 1
                )
                WHERE e.scorer_artifact_sha256=? AND e.passes_scorer=1
                  AND unixepoch(e.scored_at)<=unixepoch(?)
                  AND unixepoch(m.kickoff_time)>unixepoch(?)
                  AND NOT EXISTS(SELECT 1 FROM paper_portfolio_positions occupied
                      WHERE occupied.match_id=e.match_id)
                  AND NOT EXISTS(SELECT 1 FROM paper_portfolio_positions p
                      WHERE p.strategy_id=? AND p.scorer_evidence_id=e.id)
                ORDER BY e.predicted_ev DESC,m.kickoff_time,e.id""",
                (as_of, artifact_hash, as_of, as_of, strategy_id),
            ).fetchall()
        return [{**dict(row), "source_type": "PROFIT_SCORER"} for row in rows]

    def _external_consensus_candidates(self, strategy: dict[str, Any], as_of: str) -> list[dict[str, Any]]:
        selection = strategy.get("selection") or {}
        lower = float(selection.get("primary_horizon_minutes") or 60)
        upper = lower + float(selection.get("horizon_tolerance_minutes") or 60)
        with self.database.connect() as connection:
            rows = connection.execute("""SELECT d.*,m.league,m.home_team,m.away_team,
                o.id current_odds_observation_id,o.observed_at current_odds_observed_at,
                o.home_sp,o.draw_sp,o.away_sp
                FROM external_consensus_decisions d
                JOIN matches m ON m.id=d.match_id
                JOIN official_odds_observations o ON o.id=(
                    SELECT latest.id FROM official_odds_observations latest
                    WHERE latest.match_id=d.match_id AND latest.is_pre_match=1
                      AND unixepoch(latest.observed_at)<=unixepoch(?)
                    ORDER BY latest.observed_at DESC,latest.id DESC LIMIT 1
                )
                WHERE d.policy_id=? AND d.action='CANDIDATE'
                  AND d.decision_id=(SELECT latest_decision.decision_id
                      FROM external_consensus_decisions latest_decision
                      WHERE latest_decision.policy_id=d.policy_id
                        AND latest_decision.match_id=d.match_id
                        AND latest_decision.action='CANDIDATE'
                        AND unixepoch(latest_decision.decided_at)<=unixepoch(?)
                      ORDER BY latest_decision.decided_at DESC LIMIT 1)
                  AND d.minutes_to_kickoff BETWEEN ? AND ?
                  AND (unixepoch(d.kickoff_time)-unixepoch(?))/60.0 BETWEEN ? AND ?
                  AND unixepoch(d.kickoff_time)>unixepoch(?)
                  AND NOT EXISTS(SELECT 1 FROM paper_portfolio_positions occupied
                      WHERE occupied.match_id=d.match_id)
                  AND NOT EXISTS(SELECT 1 FROM paper_portfolio_positions p
                      WHERE p.strategy_id=? AND p.external_consensus_decision_id=d.decision_id)
                ORDER BY d.conservative_ev DESC,d.kickoff_time,d.decision_id""", (
                    as_of, strategy["policy_id"], as_of, lower, upper,
                    as_of, lower, upper, as_of, strategy["strategy_id"],
                )).fetchall()
        return [{
            **dict(row),
            "source_type": "EXTERNAL_CONSENSUS",
            "predicted_probability": row["conservative_probability"],
            "predicted_ev": row["conservative_ev"],
        } for row in rows]

    def allocate(self, as_of: datetime | str | None = None, daily_budget: float | None = None) -> dict[str, Any]:
        now = _parse_time(as_of or datetime.now(timezone.utc)).astimezone(timezone.utc)
        now_text = now.isoformat()
        allocation_date = now.astimezone(CHINA_TZ).date().isoformat()
        budget = float(settings.profit_daily_budget if daily_budget is None else daily_budget)
        risk_state = self._risk_state(now, budget)
        recommended_risk_multiplier = float(risk_state["recommended_stake_multiplier"])
        risk_multiplier = float(risk_state["applied_stake_multiplier"])
        effective_budget = round(budget * risk_multiplier, 2)
        readiness = build_profit_allocation_readiness(budget)
        readiness_hash = _hash(readiness)
        strategies = self._strategy_map()
        skipped: dict[str, int] = {}
        positions: list[dict[str, Any]] = []

        with self.database.connect() as connection:
            staked_today = float(connection.execute(
                "SELECT COALESCE(SUM(stake),0) FROM paper_portfolio_positions WHERE allocation_date=?",
                (allocation_date,),
            ).fetchone()[0])
            strategy_staked = {
                str(row[0]): float(row[1])
                for row in connection.execute("""SELECT strategy_id,COALESCE(SUM(stake),0)
                    FROM paper_portfolio_positions WHERE allocation_date=? GROUP BY strategy_id""",
                    (allocation_date,)).fetchall()
            }
            strategy_position_count = {
                str(row[0]): int(row[1])
                for row in connection.execute("""SELECT strategy_id,COUNT(*)
                    FROM paper_portfolio_positions WHERE allocation_date=? GROUP BY strategy_id""",
                    (allocation_date,)).fetchall()
            }
            league_staked = {
                str(row[0]): float(row[1])
                for row in connection.execute("""SELECT m.league,COALESCE(SUM(p.stake),0)
                    FROM paper_portfolio_positions p JOIN matches m ON m.id=p.match_id
                    WHERE p.allocation_date=? GROUP BY m.league""", (allocation_date,)).fetchall()
            }
            outcome_staked = {
                str(row[0]): float(row[1])
                for row in connection.execute("""SELECT selected_outcome,COALESCE(SUM(stake),0)
                    FROM paper_portfolio_positions WHERE allocation_date=?
                    GROUP BY selected_outcome""", (allocation_date,)).fetchall()
            }
            longshot_staked = float(connection.execute("""SELECT COALESCE(SUM(stake),0)
                FROM paper_portfolio_positions WHERE allocation_date=? AND selected_sp>=?""", (
                    allocation_date, LONGSHOT_ODDS_THRESHOLD,
                )).fetchone()[0])
            occupied_matches = {
                int(row[0]) for row in connection.execute(
                    "SELECT match_id FROM paper_portfolio_positions"
                ).fetchall()
            }

        for allocation in readiness.get("allocations", []):
            strategy_id = str(allocation.get("strategy_id"))
            strategy = strategies.get(strategy_id)
            if not strategy:
                skipped["missing_frozen_scorer_artifact"] = skipped.get("missing_frozen_scorer_artifact", 0) + 1
                continue
            strategy_budget = max(
                0.0, float(allocation.get("paper_budget") or 0) * risk_multiplier
            )
            strategy_remaining = max(0.0, strategy_budget - strategy_staked.get(strategy_id, 0.0))
            max_bets = max(1, int((strategy.get("selection") or {}).get("max_bets_per_day") or 1))
            max_single = min(
                strategy_remaining,
                float((strategy.get("risk_control") or {}).get("max_single_stake") or DEFAULT_MAX_SINGLE_STAKE),
            )
            placed_for_strategy = strategy_position_count.get(strategy_id, 0)
            for row in self._strategy_candidates(strategy, now_text):
                if (
                    placed_for_strategy >= max_bets
                    or strategy_remaining <= 0
                    or staked_today >= effective_budget
                ):
                    break
                if int(row["match_id"]) in occupied_matches:
                    skipped["match_already_in_portfolio"] = skipped.get("match_already_in_portfolio", 0) + 1
                    continue
                observed = _parse_time(row["current_odds_observed_at"])
                max_age = max(settings.odds_max_age_minutes, settings.official_sp_refresh_minutes * 2)
                if (now - observed.astimezone(timezone.utc)).total_seconds() > max_age * 60:
                    skipped["stale_current_official_sp"] = skipped.get("stale_current_official_sp", 0) + 1
                    continue
                odds = _selected_sp(row)
                probability = float(row["predicted_probability"])
                ev = probability * odds - 1.0
                min_ev = float((strategy.get("selection") or {}).get("min_predicted_ev") or 0.0)
                if ev < min_ev:
                    skipped["current_ev_below_frozen_threshold"] = skipped.get(
                        "current_ev_below_frozen_threshold", 0
                    ) + 1
                    continue
                outcome = str(row["selected_outcome"]).upper()
                league_room = max(
                    0.0,
                    effective_budget * MAX_LEAGUE_DAILY_SHARE
                    - league_staked.get(str(row["league"]), 0.0),
                )
                outcome_room = max(
                    0.0,
                    effective_budget * MAX_OUTCOME_DAILY_SHARE
                    - outcome_staked.get(outcome, 0.0),
                )
                longshot_room = (
                    max(
                        0.0,
                        effective_budget * MAX_LONGSHOT_DAILY_SHARE - longshot_staked,
                    )
                    if odds >= LONGSHOT_ODDS_THRESHOLD else effective_budget
                )
                fraction = _quarter_kelly(probability, odds)
                stake = round(min(
                    effective_budget * fraction,
                    max_single,
                    strategy_remaining,
                    effective_budget - staked_today,
                    league_room,
                    outcome_room,
                    longshot_room,
                ), 2)
                if stake <= 0:
                    skipped["zero_after_risk_caps"] = skipped.get("zero_after_risk_caps", 0) + 1
                    continue
                source = {
                    "strategy_id": strategy_id,
                    "source_type": row["source_type"],
                    "source_evidence_id": (
                        int(row["id"]) if row["source_type"] == "PROFIT_SCORER"
                        else str(row["decision_id"])
                    ),
                    "current_odds_observation_id": int(row["current_odds_observation_id"]),
                    "selected_outcome": row["selected_outcome"],
                    "selected_sp": odds,
                    "predicted_probability": probability,
                    "predicted_ev": ev,
                    "stake": stake,
                    "risk_policy_hash": risk_state["policy_hash"],
                    "risk_multiplier": risk_multiplier,
                    "placed_at": now_text,
                }
                positions.append({
                    "position_id": f"paper-pos-{uuid.uuid4().hex}",
                    "allocation_date": allocation_date,
                    "strategy_id": strategy_id,
                    "source_type": row["source_type"],
                    "scorer_evidence_id": int(row["id"]) if row["source_type"] == "PROFIT_SCORER" else None,
                    "external_consensus_decision_id": (
                        str(row["decision_id"]) if row["source_type"] == "EXTERNAL_CONSENSUS" else None
                    ),
                    "match_id": int(row["match_id"]),
                    "official_match_id": str(row["official_match_id"]),
                    "official_odds_observation_id": int(row["current_odds_observation_id"]),
                    "selected_outcome": str(row["selected_outcome"]).upper(),
                    "selected_sp": odds,
                    "predicted_probability": probability,
                    "predicted_ev": ev,
                    "quarter_kelly_fraction": fraction,
                    "stake": stake,
                    "placed_at": now_text,
                    "kickoff_time": str(row["kickoff_time"]),
                    "scorer_artifact_sha256": str(
                        strategy.get("artifact_hash") or strategy.get("policy_hash")
                    ),
                    "source_payload_hash": _hash(source),
                })
                placed_for_strategy += 1
                strategy_remaining -= stake
                staked_today += stake
                strategy_staked[strategy_id] = strategy_staked.get(strategy_id, 0.0) + stake
                strategy_position_count[strategy_id] = strategy_position_count.get(strategy_id, 0) + 1
                league_staked[str(row["league"])] = league_staked.get(str(row["league"]), 0.0) + stake
                outcome_staked[outcome] = outcome_staked.get(outcome, 0.0) + stake
                if odds >= LONGSHOT_ODDS_THRESHOLD:
                    longshot_staked += stake
                occupied_matches.add(int(row["match_id"]))

        if readiness.get("decision") != "PAPER_ALLOCATION_READY" or risk_multiplier <= 0:
            status = "HOLD"
        elif positions:
            status = "ALLOCATED"
        else:
            status = "NO_ELIGIBLE_POSITIONS"
        details = {
            "readiness_decision": readiness.get("decision"),
            "readiness_reason": readiness.get("reason"),
            "readiness_allocations": readiness.get("allocations", []),
            "skipped": skipped,
            "position_count": len(positions),
            "risk_state": risk_state,
            "effective_daily_budget": effective_budget,
            "guardrail": "Paper ledger only; no external order or payment interface is called.",
        }
        run_payload = {
            "decision_at": now_text,
            "allocation_date": allocation_date,
            "daily_budget": budget,
            "risk_policy_hash": risk_state["policy_hash"],
            "risk_multiplier": risk_multiplier,
            "recommended_risk_multiplier": recommended_risk_multiplier,
            "risk_status": risk_state["status"],
            "readiness_hash": readiness_hash,
            "status": status,
            "positions": [{key: row[key] for key in (
                "strategy_id", "source_type", "scorer_evidence_id",
                "external_consensus_decision_id", "official_odds_observation_id", "stake"
            )} for row in positions],
        }
        run_hash = _hash(run_payload)
        run_id = f"paper-run-{run_hash[:24]}"
        with self.database.connect() as connection:
            existing = connection.execute(
                "SELECT * FROM paper_portfolio_runs WHERE run_hash=?", (run_hash,)
            ).fetchone()
            if existing:
                return {"status": "duplicate", "run": dict(existing), "positions_created": 0, "skipped": skipped}
            connection.execute("""INSERT INTO paper_portfolio_runs(
                run_id,run_hash,decision_at,allocation_date,daily_budget,readiness_decision,
                readiness_hash,allocated_budget,cash_reserved,status,details_json,
                risk_policy_hash,risk_multiplier,risk_state_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                run_id, run_hash, now_text, allocation_date, budget,
                str(readiness.get("decision")), readiness_hash,
                round(sum(row["stake"] for row in positions), 2),
                round(max(0.0, budget - staked_today), 2), status, _canonical(details),
                risk_state["policy_hash"], risk_multiplier, _canonical(risk_state),
            ))
            for row in positions:
                connection.execute("""INSERT INTO paper_portfolio_positions(
                    position_id,run_id,allocation_date,strategy_id,source_type,scorer_evidence_id,
                    external_consensus_decision_id,match_id,
                    official_match_id,official_odds_observation_id,selected_outcome,selected_sp,
                    predicted_probability,predicted_ev,quarter_kelly_fraction,stake,placed_at,
                    kickoff_time,scorer_artifact_sha256,source_payload_hash
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                    row["position_id"], run_id, row["allocation_date"], row["strategy_id"],
                    row["source_type"], row["scorer_evidence_id"],
                    row["external_consensus_decision_id"], row["match_id"], row["official_match_id"],
                    row["official_odds_observation_id"], row["selected_outcome"], row["selected_sp"],
                    row["predicted_probability"], row["predicted_ev"], row["quarter_kelly_fraction"],
                    row["stake"], row["placed_at"], row["kickoff_time"],
                    row["scorer_artifact_sha256"], row["source_payload_hash"],
                ))
        return {
            "status": status.lower(),
            "run_id": run_id,
            "matches": len(positions),
            "positions_created": len(positions),
            "new_stake": round(sum(row["stake"] for row in positions), 2),
            "cash_reserved": round(max(0.0, budget - staked_today), 2),
            "skipped": skipped,
            "readiness_decision": readiness.get("decision"),
            "risk_status": risk_state["status"],
            "risk_multiplier": risk_multiplier,
            "recommended_risk_multiplier": recommended_risk_multiplier,
            "effective_daily_budget": effective_budget,
        }

    def settle(self, as_of: datetime | str | None = None) -> dict[str, Any]:
        now = _parse_time(as_of or datetime.now(timezone.utc)).astimezone(timezone.utc)
        now_text = now.isoformat()
        with self.database.connect() as connection:
            rows = connection.execute("""SELECT p.*,r.id result_id,r.outcome,r.settled_at result_settled_at,
                closing.id closing_id,
                CASE lower(p.selected_outcome)
                    WHEN 'home' THEN closing.home_sp WHEN 'draw' THEN closing.draw_sp
                    WHEN 'away' THEN closing.away_sp END closing_sp
                FROM paper_portfolio_positions p
                JOIN results r ON r.match_id=p.match_id
                LEFT JOIN official_odds_closing_observations closing ON closing.match_id=p.match_id
                WHERE NOT EXISTS(SELECT 1 FROM paper_portfolio_settlements s
                    WHERE s.position_id=p.position_id)
                ORDER BY p.kickoff_time,p.position_id""").fetchall()
            settlements: list[dict[str, Any]] = []
            for raw in rows:
                row = dict(raw)
                actual = str(row["outcome"]).upper()
                hit = actual == str(row["selected_outcome"]).upper()
                stake = float(row["stake"])
                selected_sp = float(row["selected_sp"])
                profit = round(stake * (selected_sp - 1.0) if hit else -stake, 2)
                closing_sp = float(row["closing_sp"]) if row.get("closing_sp") else None
                clv = selected_sp / closing_sp - 1.0 if closing_sp and closing_sp > 1 else None
                source = {
                    "position_id": row["position_id"], "result_id": row["result_id"],
                    "actual_outcome": actual, "result_settled_at": row["result_settled_at"],
                    "closing_id": row.get("closing_id"), "closing_sp": closing_sp,
                    "profit": profit, "clv": clv,
                }
                settlement = {
                    "settlement_id": f"paper-settle-{uuid.uuid4().hex}",
                    "position_id": row["position_id"], "result_id": int(row["result_id"]),
                    "closing_odds_observation_id": row.get("closing_id"),
                    "actual_outcome": actual, "closing_sp": closing_sp, "clv": clv,
                    "profit": profit, "settled_at": now_text,
                    "source_payload_hash": _hash(source),
                }
                connection.execute("""INSERT INTO paper_portfolio_settlements(
                    settlement_id,position_id,result_id,closing_odds_observation_id,actual_outcome,
                    closing_sp,clv,profit,settled_at,source_payload_hash
                ) VALUES(?,?,?,?,?,?,?,?,?,?)""", (
                    settlement["settlement_id"], settlement["position_id"], settlement["result_id"],
                    settlement["closing_odds_observation_id"], settlement["actual_outcome"],
                    settlement["closing_sp"], settlement["clv"], settlement["profit"],
                    settlement["settled_at"], settlement["source_payload_hash"],
                ))
                settlements.append(settlement)
        return {
            "status": "success", "matches": len(settlements), "settled": len(settlements),
            "profit": round(sum(row["profit"] for row in settlements), 2),
            "missing_closing_sp": sum(row["closing_sp"] is None for row in settlements),
        }

    def summary(self, limit: int = 500) -> dict[str, Any]:
        with self.database.connect() as connection:
            run_count = int(connection.execute("SELECT COUNT(*) FROM paper_portfolio_runs").fetchone()[0])
            hold_count = int(connection.execute(
                "SELECT COUNT(*) FROM paper_portfolio_runs WHERE status='HOLD'"
            ).fetchone()[0])
            runs = [dict(row) for row in connection.execute(
                "SELECT * FROM paper_portfolio_runs ORDER BY decision_at DESC LIMIT ?", (limit,)
            ).fetchall()]
            positions = [dict(row) for row in connection.execute("""SELECT p.*,m.league,m.home_team,m.away_team,
                s.actual_outcome,s.closing_sp,s.clv,s.profit,s.settled_at
                FROM paper_portfolio_positions p JOIN matches m ON m.id=p.match_id
                LEFT JOIN paper_portfolio_settlements s ON s.position_id=p.position_id
                ORDER BY p.placed_at,p.position_id""").fetchall()]
        settled = [row for row in positions if row.get("settled_at")]
        equity = peak = max_drawdown = 0.0
        curve: list[dict[str, Any]] = []
        for row in sorted(settled, key=lambda item: (str(item["settled_at"]), str(item["position_id"]))):
            equity += float(row["profit"])
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, peak - equity)
            curve.append({"settled_at": row["settled_at"], "profit": row["profit"], "equity": round(equity, 2)})
        clv = [float(row["clv"]) for row in settled if row.get("clv") is not None]
        staked = sum(float(row["stake"]) for row in settled)
        return {
            "method": "immutable official-SP paper portfolio ledger",
            "runs": run_count,
            "hold_runs": hold_count,
            "positions": len(positions),
            "open_positions": len(positions) - len(settled),
            "settled_positions": len(settled),
            "total_staked": round(staked, 2),
            "profit": round(equity, 2),
            "roi_pct": round(equity / staked * 100, 2) if staked else 0.0,
            "max_drawdown": round(max_drawdown, 2),
            "current_drawdown": round(max(0.0, peak - equity), 2),
            "closing_sp_coverage": round(len(clv) / len(settled), 4) if settled else 0.0,
            "average_clv": round(sum(clv) / len(clv), 6) if clv else None,
            "positive_clv_rate": round(sum(value > 0 for value in clv) / len(clv), 4) if clv else None,
            "equity_curve": curve,
            "risk_state": self._risk_state(datetime.now(timezone.utc), settings.profit_daily_budget),
            "recent_runs": runs[:20],
            "recent_positions": list(reversed(positions[-100:])),
            "guardrail": "Paper-only accounting. No real order placement is implemented.",
        }
