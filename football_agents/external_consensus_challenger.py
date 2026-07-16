from __future__ import annotations

import hashlib
import inspect
import json
import math
import uuid
from collections import Counter
from datetime import datetime, timezone
from statistics import fmean, pstdev
from typing import Any

from .db import Database, db
from .prospective_statistics import build_prospective_statistical_evidence
from .repository import Repository
from .research.prospective import ProspectiveResearchService


OUTCOMES = ("home", "draw", "away")
POLICY_CONFIG: dict[str, Any] = {
    "version": "external-consensus-quarter-residual-v1",
    "minimum_bookmakers": 10,
    "maximum_external_age_minutes": 120,
    "maximum_official_sp_age_minutes": 30,
    "maximum_model_age_minutes": 120,
    "maximum_bookmaker_last_update_age_minutes": 180,
    "maximum_probability_dispersion": 0.03,
    "model_residual_weight": 0.25,
    "model_residual_cap": 0.03,
    "minimum_probability_uncertainty": 0.01,
    "dispersion_uncertainty_z": 1.645,
    "minimum_expected_ev": 0.03,
    "minimum_conservative_ev": 0.0,
    "minimum_odds": 1.50,
    "maximum_odds": 6.00,
    "primary_horizon_minutes": 60,
    "horizon_tolerance_minutes": 60,
    "maximum_bets_per_day": 1,
    "minimum_settled_selections": 200,
    "minimum_active_months": 6,
    "minimum_calendar_days": 180,
    "minimum_settlement_days": 30,
    "minimum_closing_sp_coverage": 0.80,
}


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _minutes_between(later: datetime, earlier: str | datetime) -> float:
    return (later - _parse_time(earlier)).total_seconds() / 60.0


def _max_drawdown(profits: list[float]) -> float:
    equity = peak = worst = 0.0
    for profit in profits:
        equity += profit
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return round(worst, 2)


class ExternalConsensusChallengerService:
    """Freezes executable official-SP decisions against independent bookmaker consensus."""

    def __init__(self, database: Database = db, repository: Repository | None = None) -> None:
        self.db = database
        self.repository = repository or Repository(database)

    def ensure_policy(self) -> dict[str, Any]:
        source_sha256 = hashlib.sha256("\n".join((
            inspect.getsource(self._inputs),
            inspect.getsource(self._build_decision),
            inspect.getsource(self._primary_decisions),
        )).encode()).hexdigest()
        policy_hash = hashlib.sha256(_canonical({
            "config": POLICY_CONFIG,
            "source_sha256": source_sha256,
        }).encode()).hexdigest()
        policy_id = f"external-consensus-{policy_hash[:20]}"
        record = {
            "policy_id": policy_id,
            "policy_hash": policy_hash,
            "policy_name": "Official SP versus independent bookmaker consensus challenger",
            "hypothesis": (
                "A strongly shrunk frozen-model residual can identify official-SP prices whose "
                "conservative expected value remains positive against independent de-vig consensus."
            ),
            "config_json": _canonical(POLICY_CONFIG),
            "source_sha256": source_sha256,
            "registered_at": _utcnow().isoformat(),
        }
        with self.db.connect() as connection:
            connection.execute("""INSERT OR IGNORE INTO external_consensus_policy_registrations
                (policy_id,policy_hash,policy_name,hypothesis,config_json,source_sha256,registered_at)
                VALUES(:policy_id,:policy_hash,:policy_name,:hypothesis,:config_json,:source_sha256,:registered_at)""",
                record)
            row = connection.execute(
                "SELECT * FROM external_consensus_policy_registrations WHERE policy_id=?", (policy_id,)
            ).fetchone()
        return self._decode_policy(dict(row))

    def capture(self, limit: int = 100, as_of: str | datetime | None = None) -> dict[str, Any]:
        decided_at = _parse_time(as_of or _utcnow())
        policy = self.ensure_policy()
        study = ProspectiveResearchService(self.db, self.repository).ensure_default_study()
        matches = self.repository.list_active_official_matches(max(1, min(limit, 500)))
        captured = duplicates = eligible = 0
        blockers: Counter[str] = Counter()
        candidates = 0
        for match in matches:
            kickoff = _parse_time(match["kickoff_time"])
            if kickoff <= decided_at:
                blockers["kickoff_not_in_future"] += 1
                continue
            inputs, missing = self._inputs(match["id"], study["study_id"], decided_at)
            if inputs is None:
                blockers[missing] += 1
                continue
            eligible += 1
            record = self._build_decision(policy, study, match, inputs, decided_at)
            try:
                inserted = self._insert_decision(record)
            except ValueError as exc:
                blockers[str(exc)] += 1
                continue
            captured += int(inserted)
            duplicates += int(not inserted)
            candidates += int(inserted and record["action"] == "CANDIDATE")
            for reason in json.loads(record["blockers_json"]):
                blockers[str(reason)] += int(inserted)
        report = self.report(policy["policy_id"], as_of=decided_at)
        return {
            "matches": len(matches),
            "eligible": eligible,
            "decisions": captured,
            "predictions": candidates,
            "duplicates": duplicates,
            "blocker_counts": [
                {"reason": reason, "matches": count}
                for reason, count in blockers.most_common()
            ],
            "policy_id": policy["policy_id"],
            "report": report,
            "warnings": report["decision_reasons"],
        }

    def report(self, policy_id: str | None = None,
               as_of: str | datetime | None = None) -> dict[str, Any]:
        policy = self.get_policy(policy_id) if policy_id else self.ensure_policy()
        now = _parse_time(as_of or _utcnow())
        rows = self._decision_rows(policy["policy_id"])
        candidate_rows = [row for row in rows if row["action"] == "CANDIDATE"]
        primary = self._primary_decisions(candidate_rows, policy["config"])
        settled = [row for row in primary if row.get("outcome") in OUTCOMES]
        statistical_rows: list[dict[str, Any]] = []
        for row in settled:
            outcome = str(row["selected_outcome"])
            selected_sp = float(row["selected_sp"])
            closing_sp = row.get(f"closing_{outcome}_sp")
            profit = selected_sp - 1.0 if row["outcome"] == outcome else -1.0
            clv = selected_sp / float(closing_sp) - 1.0 if closing_sp and float(closing_sp) > 1 else None
            statistical_rows.append({
                "settlement_day": str(row.get("settled_at") or row["kickoff_time"])[:10],
                "kickoff_time": row["kickoff_time"],
                "selected_outcome": outcome.upper(),
                "actual_outcome": str(row["outcome"]).upper(),
                "predicted_probability": float(row["selected_probability"]),
                "market_probability": float(row[f"external_{outcome}_probability"]),
                "profit": profit,
                "clv": clv,
            })
        statistics = build_prospective_statistical_evidence(statistical_rows)
        profits = [float(row["profit"]) for row in statistical_rows]
        clv_values = [float(row["clv"]) for row in statistical_rows if row.get("clv") is not None]
        monthly: list[dict[str, Any]] = []
        for month in sorted({str(row["kickoff_time"])[:7] for row in statistical_rows}):
            month_rows = [row for row in statistical_rows if str(row["kickoff_time"])[:7] == month]
            profit = sum(float(row["profit"]) for row in month_rows)
            monthly.append({
                "month": month,
                "bets": len(month_rows),
                "profit": round(profit, 2),
                "roi_pct": round(profit / len(month_rows) * 100, 2),
            })
        daily: list[dict[str, Any]] = []
        for day in sorted({str(row["kickoff_time"])[:10] for row in statistical_rows}):
            day_rows = [row for row in statistical_rows if str(row["kickoff_time"])[:10] == day]
            daily.append({
                "date": day,
                "bets": len(day_rows),
                "profit": round(sum(float(row["profit"]) for row in day_rows), 2),
            })
        total_profit = sum(profits)
        active_months = len(monthly)
        elapsed_days = max(0, (now - _parse_time(policy["registered_at"])).days)
        coverage = len(clv_values) / len(settled) if settled else 0.0
        mature = (
            len(settled) >= int(policy["config"]["minimum_settled_selections"])
            and active_months >= int(policy["config"]["minimum_active_months"])
            and elapsed_days >= int(policy["config"]["minimum_calendar_days"])
        )
        decision_reasons: list[str] = []
        if len(settled) < int(policy["config"]["minimum_settled_selections"]):
            decision_reasons.append("settled_selections<200")
        if active_months < int(policy["config"]["minimum_active_months"]):
            decision_reasons.append("active_months<6")
        if elapsed_days < int(policy["config"]["minimum_calendar_days"]):
            decision_reasons.append("elapsed_days<180")
        if mature:
            bootstrap = statistics["bootstrap"]
            point = statistics["point_estimates"]
            if int(bootstrap.get("settlement_days") or 0) < int(policy["config"]["minimum_settlement_days"]):
                decision_reasons.append("settlement_days<30")
            if total_profit <= 0:
                decision_reasons.append("profit<=0")
            if sum(row["profit"] > 0 for row in monthly) <= sum(row["profit"] < 0 for row in monthly):
                decision_reasons.append("positive_months<=negative_months")
            if _max_drawdown(profits) > max(total_profit, 1.0):
                decision_reasons.append("max_drawdown>profit")
            if coverage < float(policy["config"]["minimum_closing_sp_coverage"]):
                decision_reasons.append("closing_sp_coverage<0.8")
            if self._p05(bootstrap, "roi_ci_pct") <= 0:
                decision_reasons.append("bootstrap_roi_p05<=0")
            if coverage >= float(policy["config"]["minimum_closing_sp_coverage"]):
                if self._p05(bootstrap, "average_clv_ci") <= 0:
                    decision_reasons.append("bootstrap_clv_p05<=0")
                if sum(value > 0 for value in clv_values) / len(clv_values) < 0.50:
                    decision_reasons.append("positive_clv_rate<0.5")
            if float(point.get("brier_improvement") or -1.0) < 0:
                decision_reasons.append("model_brier_worse_than_external_market")
            if float(point.get("log_loss_improvement") or -1.0) < 0:
                decision_reasons.append("model_log_loss_worse_than_external_market")
            if (
                self._p05(bootstrap, "brier_improvement_ci") <= 0
                and self._p05(bootstrap, "log_loss_improvement_ci") <= 0
            ):
                decision_reasons.append("relative_calibration_confidence_not_positive")
        decision = (
            "EXTERNAL_CONSENSUS_PROSPECTIVE_PASS"
            if mature and not decision_reasons
            else "EXTERNAL_CONSENSUS_PROSPECTIVE_BLOCKED"
            if mature
            else "EXTERNAL_CONSENSUS_PROSPECTIVE_COLLECTING"
        )
        blocker_counts = Counter(
            reason for row in rows for reason in row.get("blockers", [])
        )
        expected_ev_values = [float(row["expected_ev"]) for row in rows]
        conservative_ev_values = [float(row["conservative_ev"]) for row in rows]
        best_expected_ev = max(expected_ev_values) if expected_ev_values else None
        best_conservative_ev = max(conservative_ev_values) if conservative_ev_values else None
        return {
            "method": "pre-registered external consensus versus executable official-SP challenger",
            "created_at": now.isoformat(),
            "policy": policy,
            "decision": decision,
            "decision_reasons": decision_reasons,
            "decisions": len(rows),
            "candidate_decisions": len(candidate_rows),
            "positive_expected_ev_decisions": sum(value > 0 for value in expected_ev_values),
            "best_expected_ev": round(best_expected_ev, 6) if best_expected_ev is not None else None,
            "best_conservative_ev": round(best_conservative_ev, 6) if best_conservative_ev is not None else None,
            "expected_ev_gap_to_entry": round(
                max(0.0, float(policy["config"]["minimum_expected_ev"]) - best_expected_ev), 6
            ) if best_expected_ev is not None else None,
            "primary_horizon_candidates": len(primary),
            "settled_selections": len(settled),
            "active_months": active_months,
            "elapsed_days": elapsed_days,
            "profit": round(total_profit, 2),
            "roi_pct": round(total_profit / len(settled) * 100, 2) if settled else 0.0,
            "max_drawdown": _max_drawdown(profits),
            "closing_sp_coverage": round(coverage, 4),
            "average_clv": round(fmean(clv_values), 6) if clv_values else None,
            "positive_clv_rate": round(sum(value > 0 for value in clv_values) / len(clv_values), 4)
            if clv_values else None,
            "positive_months": sum(row["profit"] > 0 for row in monthly),
            "negative_months": sum(row["profit"] < 0 for row in monthly),
            "statistical_evidence": statistics,
            "monthly": monthly,
            "daily": daily,
            "blocker_counts": [
                {"reason": reason, "decisions": count}
                for reason, count in blocker_counts.most_common()
            ],
            "recent_decisions": rows[-100:],
            "guardrail": (
                "Policy parameters and every decision are immutable. Selection uses only official SP, "
                "independent bookmaker snapshots, and a previously frozen prospective model prediction."
            ),
        }

    def get_policy(self, policy_id: str) -> dict[str, Any]:
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT * FROM external_consensus_policy_registrations WHERE policy_id=?", (policy_id,)
            ).fetchone()
        if not row:
            raise KeyError(policy_id)
        return self._decode_policy(dict(row))

    def _inputs(self, match_id: int, study_id: str, decided_at: datetime) -> tuple[dict[str, Any] | None, str]:
        with self.db.connect() as connection:
            official = connection.execute("""SELECT * FROM official_odds_observations
                WHERE match_id=? AND is_pre_match=1 AND datetime(observed_at)<=datetime(?)
                ORDER BY observed_at DESC LIMIT 1""", (match_id, decided_at.isoformat())).fetchone()
            prediction = connection.execute("""SELECT * FROM prospective_predictions
                WHERE match_id=? AND study_id=? AND datetime(predicted_at)<=datetime(?)
                ORDER BY predicted_at DESC,created_at DESC LIMIT 1""",
                (match_id, study_id, decided_at.isoformat())).fetchone()
            external_time = connection.execute("""SELECT MAX(fetched_at) value
                FROM external_bookmaker_odds WHERE match_id=? AND datetime(fetched_at)<=datetime(?)""",
                (match_id, decided_at.isoformat())).fetchone()["value"]
            bookmaker_rows = connection.execute("""SELECT * FROM external_bookmaker_odds
                WHERE match_id=? AND fetched_at=? ORDER BY bookmaker_key,bookmaker""",
                (match_id, external_time)).fetchall() if external_time else []
        if not official:
            return None, "missing_official_sp"
        if not prediction:
            return None, "missing_frozen_model_prediction"
        if not external_time or not bookmaker_rows:
            return None, "missing_external_bookmakers"
        if _minutes_between(decided_at, official["observed_at"]) > POLICY_CONFIG["maximum_official_sp_age_minutes"]:
            return None, "stale_official_sp"
        if _minutes_between(decided_at, external_time) > POLICY_CONFIG["maximum_external_age_minutes"]:
            return None, "stale_external_consensus"
        if _minutes_between(decided_at, prediction["predicted_at"]) > POLICY_CONFIG["maximum_model_age_minutes"]:
            return None, "stale_frozen_model_prediction"
        deduplicated: dict[str, dict[str, Any]] = {}
        for raw_row in bookmaker_rows:
            row = dict(raw_row)
            key = str(row.get("bookmaker_key") or row.get("bookmaker"))
            try:
                age = _minutes_between(decided_at, row["last_update"])
            except (TypeError, ValueError):
                continue
            if 0 <= age <= POLICY_CONFIG["maximum_bookmaker_last_update_age_minutes"]:
                deduplicated[key] = row
        if len(deduplicated) < POLICY_CONFIG["minimum_bookmakers"]:
            return None, "bookmaker_count<10"
        return {
            "official": dict(official),
            "prediction": dict(prediction),
            "external_fetched_at": external_time,
            "bookmakers": list(deduplicated.values()),
        }, ""

    def _build_decision(self, policy: dict[str, Any], study: dict[str, Any], match: dict[str, Any],
                        inputs: dict[str, Any], decided_at: datetime) -> dict[str, Any]:
        official = inputs["official"]
        prediction = inputs["prediction"]
        books = inputs["bookmakers"]
        bookmaker_probabilities: dict[str, list[float]] = {key: [] for key in OUTCOMES}
        for book in books:
            inverse = {key: 1.0 / float(book[f"{key}_odds"]) for key in OUTCOMES}
            total = sum(inverse.values())
            for key in OUTCOMES:
                bookmaker_probabilities[key].append(inverse[key] / total)
        external = {key: fmean(bookmaker_probabilities[key]) for key in OUTCOMES}
        dispersion = {key: pstdev(bookmaker_probabilities[key]) for key in OUTCOMES}
        candidates: list[dict[str, Any]] = []
        for outcome in OUTCOMES:
            model_probability = float(prediction[f"p_{outcome}"])
            residual = max(
                -POLICY_CONFIG["model_residual_cap"],
                min(POLICY_CONFIG["model_residual_cap"], model_probability - external[outcome]),
            )
            probability = external[outcome] + POLICY_CONFIG["model_residual_weight"] * residual
            uncertainty = max(
                POLICY_CONFIG["minimum_probability_uncertainty"],
                POLICY_CONFIG["dispersion_uncertainty_z"] * dispersion[outcome],
            )
            conservative_probability = max(0.01, probability - uncertainty)
            sp = float(official[f"{outcome}_sp"])
            expected_ev = probability * sp - 1.0
            conservative_ev = conservative_probability * sp - 1.0
            reasons: list[str] = []
            if not POLICY_CONFIG["minimum_odds"] <= sp <= POLICY_CONFIG["maximum_odds"]:
                reasons.append("selected_sp_outside_[1.5,6.0]")
            if dispersion[outcome] > POLICY_CONFIG["maximum_probability_dispersion"]:
                reasons.append("bookmaker_probability_dispersion>0.03")
            if expected_ev < POLICY_CONFIG["minimum_expected_ev"]:
                reasons.append("expected_ev<0.03")
            if conservative_ev < POLICY_CONFIG["minimum_conservative_ev"]:
                reasons.append("conservative_ev<0")
            candidates.append({
                "outcome": outcome, "sp": sp, "probability": probability,
                "conservative_probability": conservative_probability,
                "expected_ev": expected_ev, "conservative_ev": conservative_ev,
                "reasons": reasons,
            })
        selected = max(candidates, key=lambda row: (row["conservative_ev"], row["expected_ev"]))
        action = "CANDIDATE" if not selected["reasons"] else "NO_BET"
        payload = {
            "policy_id": policy["policy_id"], "study_id": study["study_id"],
            "official_odds_observation_id": official["id"],
            "external_fetched_at": inputs["external_fetched_at"],
            "source_prediction_id": prediction["prediction_id"],
            "external": external, "dispersion": dispersion, "selected": selected, "action": action,
        }
        kickoff = _parse_time(match["kickoff_time"])
        return {
            "decision_id": f"consensus-decision-{uuid.uuid4().hex}",
            "policy_id": policy["policy_id"], "study_id": study["study_id"],
            "freeze_id": study["freeze_id"], "match_id": match["id"],
            "official_match_id": match["official_match_id"],
            "official_odds_observation_id": official["id"],
            "external_fetched_at": inputs["external_fetched_at"],
            "source_prediction_id": prediction["prediction_id"],
            "decided_at": decided_at.isoformat(), "kickoff_time": match["kickoff_time"],
            "minutes_to_kickoff": (kickoff - decided_at).total_seconds() / 60.0,
            "bookmaker_count": len(books),
            **{f"external_{key}_probability": external[key] for key in OUTCOMES},
            **{f"external_{key}_std": dispersion[key] for key in OUTCOMES},
            "selected_outcome": selected["outcome"], "selected_sp": selected["sp"],
            "selected_probability": selected["probability"],
            "conservative_probability": selected["conservative_probability"],
            "expected_ev": selected["expected_ev"], "conservative_ev": selected["conservative_ev"],
            "action": action, "blockers_json": _canonical(selected["reasons"]),
            "payload_hash": hashlib.sha256(_canonical(payload).encode()).hexdigest(),
            "created_at": _utcnow().isoformat(),
        }

    def _insert_decision(self, record: dict[str, Any]) -> bool:
        if _parse_time(record["decided_at"]) >= _parse_time(record["kickoff_time"]):
            raise ValueError("decision_at_or_after_kickoff")
        columns = tuple(record)
        placeholders = ",".join(f":{column}" for column in columns)
        with self.db.connect() as connection:
            cursor = connection.execute(
                f"INSERT OR IGNORE INTO external_consensus_decisions ({','.join(columns)}) VALUES({placeholders})",
                record,
            )
        return cursor.rowcount == 1

    def _decision_rows(self, policy_id: str) -> list[dict[str, Any]]:
        with self.db.connect() as connection:
            rows = connection.execute("""SELECT d.*,m.league,m.home_team,m.away_team,r.outcome,r.settled_at,
                closing.home_sp closing_home_sp,closing.draw_sp closing_draw_sp,closing.away_sp closing_away_sp
                FROM external_consensus_decisions d
                JOIN matches m ON m.id=d.match_id
                LEFT JOIN results r ON r.match_id=d.match_id
                LEFT JOIN official_odds_closing_observations closing ON closing.match_id=d.match_id
                WHERE d.policy_id=? ORDER BY d.decided_at""", (policy_id,)).fetchall()
        output = []
        for raw_row in rows:
            row = dict(raw_row)
            row["blockers"] = json.loads(row.pop("blockers_json"))
            output.append(row)
        return output

    @staticmethod
    def _primary_decisions(rows: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
        lower = float(config["primary_horizon_minutes"])
        upper = lower + float(config["horizon_tolerance_minutes"])
        in_horizon = [row for row in rows if lower <= float(row["minutes_to_kickoff"]) <= upper]
        by_match: dict[int, dict[str, Any]] = {}
        for row in in_horizon:
            current = by_match.get(int(row["match_id"]))
            if current is None or abs(float(row["minutes_to_kickoff"]) - lower) < abs(
                float(current["minutes_to_kickoff"]) - lower
            ):
                by_match[int(row["match_id"])] = row
        by_day: dict[str, list[dict[str, Any]]] = {}
        for row in by_match.values():
            by_day.setdefault(str(row["kickoff_time"])[:10], []).append(row)
        selected: list[dict[str, Any]] = []
        for day in sorted(by_day):
            day_rows = sorted(
                by_day[day], key=lambda row: (float(row["conservative_ev"]), row["official_match_id"]),
                reverse=True,
            )
            selected.extend(day_rows[:int(config["maximum_bets_per_day"])])
        return sorted(selected, key=lambda row: row["kickoff_time"])

    @staticmethod
    def _decode_policy(row: dict[str, Any]) -> dict[str, Any]:
        row["config"] = json.loads(row.pop("config_json"))
        return row

    @staticmethod
    def _p05(bootstrap: dict[str, Any], key: str) -> float:
        value = (bootstrap.get(key) or {}).get("p05")
        return float(value) if value is not None else -1.0
