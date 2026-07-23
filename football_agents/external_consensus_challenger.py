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

from .config import settings
from .db import Database, db
from .prospective_statistics import build_prospective_statistical_evidence
from .repository import Repository
from .research.prospective import ProspectiveResearchService


OUTCOMES = ("home", "draw", "away")
POLICY_CONFIG: dict[str, Any] = {
    "version": "external-consensus-favorite-portfolio-v4",
    "model_source": "pure_football_baseline",
    "minimum_bookmakers": 10,
    "maximum_external_age_minutes": 120,
    "maximum_official_sp_age_minutes": 30,
    "maximum_official_external_skew_minutes": 15,
    "maximum_model_age_minutes": 120,
    "maximum_bookmaker_last_update_age_minutes": 180,
    "maximum_probability_dispersion": 0.03,
    "model_residual_weight": 0.25,
    "model_residual_cap": 0.03,
    "minimum_probability_uncertainty": 0.01,
    "dispersion_uncertainty_z": 1.645,
    "maximum_effective_bookmakers": 5,
    "uncertainty_method": "conservative_effective_sample_standard_error",
    "minimum_expected_ev": 0.03,
    "minimum_conservative_ev": 0.0,
    "minimum_external_probability": 0.40,
    "minimum_odds": 1.50,
    "maximum_odds": 6.00,
    "primary_horizon_minutes": 60,
    "horizon_tolerance_minutes": 60,
    "maximum_bets_per_day": 3,
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


def _fused_probabilities(
    external: dict[str, float],
    pure_model: dict[str, float],
    config: dict[str, Any],
) -> dict[str, float]:
    raw: dict[str, float] = {}
    for outcome in OUTCOMES:
        residual = max(
            -float(config["model_residual_cap"]),
            min(
                float(config["model_residual_cap"]),
                pure_model[outcome] - external[outcome],
            ),
        )
        raw[outcome] = external[outcome] + float(config["model_residual_weight"]) * residual
    total = sum(raw.values())
    if total <= 0:
        raise ValueError("fused_probability_sum_not_positive")
    return {outcome: raw[outcome] / total for outcome in OUTCOMES}


def _consensus_uncertainty(
    dispersion: dict[str, float],
    bookmaker_count: int,
    config: dict[str, Any],
) -> tuple[dict[str, float], dict[str, float], int]:
    effective_count = max(
        1,
        min(int(bookmaker_count), int(config["maximum_effective_bookmakers"])),
    )
    standard_error = {
        outcome: dispersion[outcome] / math.sqrt(effective_count)
        for outcome in OUTCOMES
    }
    uncertainty = {
        outcome: max(
            float(config["minimum_probability_uncertainty"]),
            float(config["dispersion_uncertainty_z"]) * standard_error[outcome],
        )
        for outcome in OUTCOMES
    }
    return standard_error, uncertainty, effective_count


def _probability_diagnostics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    settled = [
        row for row in rows
        if row.get("outcome") in OUTCOMES
        and all(row.get(f"fused_{outcome}_probability") is not None for outcome in OUTCOMES)
    ]
    metrics: dict[str, dict[str, float | None]] = {}
    for source, prefix in (
        ("external_consensus", "external"),
        ("pure_football_model", "pure_model"),
        ("normalized_fusion", "fused"),
    ):
        brier_values: list[float] = []
        log_loss_values: list[float] = []
        for row in settled:
            actual = str(row["outcome"])
            probabilities = {
                outcome: float(row[f"{prefix}_{outcome}_probability"])
                for outcome in OUTCOMES
            }
            brier_values.append(sum(
                (probabilities[outcome] - float(outcome == actual)) ** 2
                for outcome in OUTCOMES
            ) / len(OUTCOMES))
            log_loss_values.append(-math.log(max(1e-15, probabilities[actual])))
        metrics[source] = {
            "brier_score": round(fmean(brier_values), 6) if brier_values else None,
            "log_loss": round(fmean(log_loss_values), 6) if log_loss_values else None,
        }
    external = metrics["external_consensus"]
    fused = metrics["normalized_fusion"]
    brier_improvement = (
        float(external["brier_score"]) - float(fused["brier_score"])
        if external["brier_score"] is not None and fused["brier_score"] is not None else None
    )
    log_loss_improvement = (
        float(external["log_loss"]) - float(fused["log_loss"])
        if external["log_loss"] is not None and fused["log_loss"] is not None else None
    )
    return {
        "matches": len(settled),
        "minimum_matches": 200,
        "metrics": metrics,
        "brier_improvement_vs_external": round(brier_improvement, 6)
        if brier_improvement is not None else None,
        "log_loss_improvement_vs_external": round(log_loss_improvement, 6)
        if log_loss_improvement is not None else None,
        "decision": (
            "INSUFFICIENT_SETTLED_MATCHES"
            if len(settled) < 200
            else "FUSION_CALIBRATION_SUPPORTED"
            if brier_improvement is not None and brier_improvement > 0
            and log_loss_improvement is not None and log_loss_improvement > 0
            else "FUSION_NOT_BETTER_THAN_EXTERNAL"
        ),
        "guardrail": (
            "One pre-registered horizon snapshot per match is used. This diagnostic cannot promote "
            "the strategy before the prospective profitability and drawdown gates also pass."
        ),
    }


class ExternalConsensusChallengerService:
    """Freezes executable official-SP decisions against independent bookmaker consensus."""

    def __init__(self, database: Database = db, repository: Repository | None = None) -> None:
        self.db = database
        self.repository = repository or Repository(database)

    def ensure_policy(self, study: dict[str, Any] | None = None) -> dict[str, Any]:
        prospective = ProspectiveResearchService(self.db, self.repository)
        study = study or prospective.ensure_default_study()
        freeze = prospective.get_freeze(study["freeze_id"])
        policy_config = {
            **POLICY_CONFIG,
            "external_odds_regions": settings.odds_api_regions,
            "external_odds_capture_window_minutes": settings.external_odds_capture_window_minutes,
            "prospective_study_id": study["study_id"],
            "model_freeze_id": freeze["freeze_id"],
            "model_algorithm_hash": freeze["algorithm_hash"],
        }
        source_sha256 = hashlib.sha256("\n".join((
            inspect.getsource(self._inputs),
            inspect.getsource(self._build_decision),
            inspect.getsource(self._primary_decisions),
            inspect.getsource(_fused_probabilities),
            inspect.getsource(_consensus_uncertainty),
            inspect.getsource(_probability_diagnostics),
            inspect.getsource(self._horizon_decisions),
        )).encode()).hexdigest()
        policy_hash = hashlib.sha256(_canonical({
            "config": policy_config,
            "source_sha256": source_sha256,
        }).encode()).hexdigest()
        policy_id = f"external-consensus-{policy_hash[:20]}"
        record = {
            "policy_id": policy_id,
            "policy_hash": policy_hash,
            "policy_name": "Official SP versus independent bookmaker consensus challenger",
            "hypothesis": (
                "A strongly shrunk, market-independent Elo/Poisson baseline residual can identify "
                "official-SP prices whose conservative expected value remains positive against "
                "independent de-vig bookmaker consensus."
            ),
            "config_json": _canonical(policy_config),
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
        study = ProspectiveResearchService(self.db, self.repository).ensure_default_study()
        policy = self.ensure_policy(study)
        matches = self.repository.list_active_official_matches(max(1, min(limit, 500)))
        captured = duplicates = eligible = 0
        blockers: Counter[str] = Counter()
        candidates = 0
        for match in matches:
            kickoff = _parse_time(match["kickoff_time"])
            if kickoff <= decided_at:
                blockers["kickoff_not_in_future"] += 1
                continue
            inputs, missing = self._inputs(
                match["id"], study["study_id"], decided_at, policy["config"]
            )
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
        horizon_rows = self._horizon_decisions(rows, policy["config"])
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
        expected_threshold = float(policy["config"]["minimum_expected_ev"])
        conservative_threshold = float(policy["config"]["minimum_conservative_ev"])
        minimum_odds = float(policy["config"]["minimum_odds"])
        maximum_odds = float(policy["config"]["maximum_odds"])
        price_eligible_rows = [
            row for row in rows
            if minimum_odds <= float(row["selected_sp"]) <= maximum_odds
        ]
        price_eligible_expected = [float(row["expected_ev"]) for row in price_eligible_rows]
        price_eligible_conservative = [float(row["conservative_ev"]) for row in price_eligible_rows]
        best_price_eligible_expected = max(price_eligible_expected) if price_eligible_expected else None
        best_price_eligible_conservative = (
            max(price_eligible_conservative) if price_eligible_conservative else None
        )
        return {
            "method": "pre-registered external consensus versus executable official-SP challenger",
            "created_at": now.isoformat(),
            "policy": policy,
            "decision": decision,
            "decision_reasons": decision_reasons,
            "decisions": len(rows),
            "candidate_decisions": len(candidate_rows),
            "positive_expected_ev_decisions": sum(value > 0 for value in expected_ev_values),
            "expected_ev_threshold_pass_decisions": sum(
                value >= expected_threshold for value in expected_ev_values
            ),
            "entry_price_eligible_decisions": len(price_eligible_rows),
            "entry_price_and_expected_ev_pass_decisions": sum(
                value >= expected_threshold for value in price_eligible_expected
            ),
            "positive_conservative_ev_decisions": sum(
                value >= conservative_threshold for value in conservative_ev_values
            ),
            "best_expected_ev": round(best_expected_ev, 6) if best_expected_ev is not None else None,
            "best_conservative_ev": round(best_conservative_ev, 6) if best_conservative_ev is not None else None,
            "expected_ev_gap_to_entry": round(
                max(0.0, expected_threshold - best_price_eligible_expected), 6
            ) if best_price_eligible_expected is not None else None,
            "conservative_ev_gap_to_entry": round(
                max(0.0, conservative_threshold - best_price_eligible_conservative), 6
            ) if best_price_eligible_conservative is not None else None,
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
            "all_match_probability_diagnostics": _probability_diagnostics(horizon_rows),
            "bookmaker_probability_diagnostics": self._bookmaker_probability_diagnostics(horizon_rows),
            "monthly": monthly,
            "daily": daily,
            "blocker_counts": [
                {"reason": reason, "decisions": count}
                for reason, count in blocker_counts.most_common()
            ],
            "recent_decisions": rows[-100:],
            "guardrail": (
                "Policy parameters and every decision are immutable. Selection uses only official SP, "
                "independent bookmaker snapshots, and a pre-decision Elo/Poisson baseline that does not "
                "consume official or external market odds."
            ),
        }

    def _bookmaker_probability_diagnostics(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        minimum_matches = 200
        minimum_months = 6
        settled = [row for row in rows if row.get("outcome") in OUTCOMES]
        samples: dict[str, dict[str, Any]] = {}
        with self.db.connect() as connection:
            for decision in settled:
                bookmaker_rows = connection.execute("""SELECT * FROM external_bookmaker_odds
                    WHERE match_id=? AND fetched_at=? ORDER BY bookmaker_key,bookmaker,id""", (
                        decision["match_id"], decision["external_fetched_at"],
                    )).fetchall()
                seen: set[str] = set()
                for raw_row in bookmaker_rows:
                    row = dict(raw_row)
                    key = str(row.get("bookmaker_key") or row.get("bookmaker") or "").strip()
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    try:
                        if _parse_time(row["last_update"]) > _parse_time(decision["decided_at"]):
                            continue
                        inverse = {
                            outcome: 1.0 / float(row[f"{outcome}_odds"])
                            for outcome in OUTCOMES
                        }
                    except (KeyError, TypeError, ValueError, ZeroDivisionError):
                        continue
                    total = sum(inverse.values())
                    if total <= 0:
                        continue
                    probabilities = {outcome: inverse[outcome] / total for outcome in OUTCOMES}
                    actual = str(decision["outcome"])
                    brier = sum(
                        (probabilities[outcome] - float(outcome == actual)) ** 2
                        for outcome in OUTCOMES
                    ) / len(OUTCOMES)
                    log_loss = -math.log(max(1e-15, probabilities[actual]))
                    entry = samples.setdefault(key, {
                        "bookmaker_key": key,
                        "bookmaker": str(row.get("bookmaker") or key),
                        "brier": [],
                        "log_loss": [],
                        "months": set(),
                    })
                    entry["brier"].append(brier)
                    entry["log_loss"].append(log_loss)
                    entry["months"].add(str(decision["kickoff_time"])[:7])

        rankings: list[dict[str, Any]] = []
        for entry in samples.values():
            sample_count = len(entry["brier"])
            active_months = len(entry["months"])
            rankings.append({
                "bookmaker_key": entry["bookmaker_key"],
                "bookmaker": entry["bookmaker"],
                "matches": sample_count,
                "active_months": active_months,
                "brier_score": round(fmean(entry["brier"]), 6),
                "log_loss": round(fmean(entry["log_loss"]), 6),
                "weighting_eligible": sample_count >= minimum_matches and active_months >= minimum_months,
            })
        rankings.sort(key=lambda row: (row["log_loss"], row["brier_score"], row["bookmaker_key"]))
        eligible = [row for row in rankings if row["weighting_eligible"]]
        return {
            "settled_horizon_matches": len(settled),
            "bookmakers_observed": len(rankings),
            "bookmaker_match_observations": sum(row["matches"] for row in rankings),
            "minimum_matches_per_bookmaker": minimum_matches,
            "minimum_active_months": minimum_months,
            "eligible_bookmakers": len(eligible),
            "decision": (
                "RELIABILITY_WEIGHT_RESEARCH_ELIGIBLE"
                if len(eligible) >= 3
                else "INSUFFICIENT_BOOKMAKER_CALIBRATION_EVIDENCE"
            ),
            "rankings": rankings,
            "guardrail": (
                "Diagnostic only. It uses one frozen T-60 to T-120 snapshot per settled match. "
                "No bookmaker weights are applied to the active policy; an eligible result must "
                "be frozen as a separate prospective challenger."
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

    def _inputs(self, match_id: int, study_id: str, decided_at: datetime,
                config: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        with self.db.connect() as connection:
            official = connection.execute("""SELECT * FROM official_odds_observations
                WHERE match_id=? AND is_pre_match=1 AND datetime(observed_at)<=datetime(?)
                ORDER BY observed_at DESC LIMIT 1""", (match_id, decided_at.isoformat())).fetchone()
            availability = connection.execute("""SELECT raw_sale_status,normalized_status,
                has_valid_three_way_sp,missing_reason FROM official_market_availability_observations
                WHERE match_id=? AND datetime(observed_at)<=datetime(?)
                ORDER BY observed_at DESC LIMIT 1""", (match_id, decided_at.isoformat())).fetchone()
            prediction = connection.execute("""SELECT * FROM prospective_predictions
                WHERE match_id=? AND study_id=? AND datetime(predicted_at)<=datetime(?)
                ORDER BY predicted_at DESC,created_at DESC LIMIT 1""",
                (match_id, study_id, decided_at.isoformat())).fetchone()
            pure_model = connection.execute("""SELECT * FROM model_predictions
                WHERE match_id=? AND model_name='baseline' AND datetime(predicted_at)<=datetime(?)
                ORDER BY predicted_at DESC,id DESC LIMIT 1""", (
                    match_id,
                    prediction["predicted_at"] if prediction else decided_at.isoformat(),
                )).fetchone()
            external_time = connection.execute("""SELECT MAX(fetched_at) value
                FROM external_bookmaker_odds WHERE match_id=? AND datetime(fetched_at)<=datetime(?)""",
                (match_id, decided_at.isoformat())).fetchone()["value"]
            bookmaker_rows = connection.execute("""SELECT * FROM external_bookmaker_odds
                WHERE match_id=? AND fetched_at=? ORDER BY bookmaker_key,bookmaker""",
                (match_id, external_time)).fetchall() if external_time else []
        if not official:
            if availability:
                reason = str(availability["missing_reason"] or "")
                if reason == "not_on_sale":
                    return None, "official_sp_not_on_sale"
                if reason == "invalid_or_incomplete_three_way_sp":
                    return None, "official_sp_invalid_or_incomplete"
                if reason == "post_match":
                    return None, "official_sp_post_match"
            return None, "missing_official_sp_no_availability"
        if not prediction:
            return None, "missing_frozen_model_prediction"
        if not pure_model:
            return None, "missing_independent_pure_model_prediction"
        if not external_time or not bookmaker_rows:
            return None, "missing_external_bookmakers"
        if _minutes_between(decided_at, official["observed_at"]) > config["maximum_official_sp_age_minutes"]:
            return None, "stale_official_sp"
        if _minutes_between(decided_at, external_time) > config["maximum_external_age_minutes"]:
            return None, "stale_external_consensus"
        official_external_skew = abs(
            (_parse_time(official["observed_at"]) - _parse_time(external_time)).total_seconds() / 60.0
        )
        if official_external_skew > config["maximum_official_external_skew_minutes"]:
            return None, "official_external_time_skew>15m"
        if _minutes_between(decided_at, prediction["predicted_at"]) > config["maximum_model_age_minutes"]:
            return None, "stale_frozen_model_prediction"
        if _minutes_between(decided_at, pure_model["predicted_at"]) > config["maximum_model_age_minutes"]:
            return None, "stale_independent_pure_model_prediction"
        if _parse_time(pure_model["predicted_at"]) > _parse_time(prediction["predicted_at"]):
            return None, "pure_model_prediction_after_frozen_prediction"
        deduplicated: dict[str, dict[str, Any]] = {}
        for raw_row in bookmaker_rows:
            row = dict(raw_row)
            key = str(row.get("bookmaker_key") or row.get("bookmaker"))
            try:
                age = _minutes_between(decided_at, row["last_update"])
            except (TypeError, ValueError):
                continue
            if 0 <= age <= config["maximum_bookmaker_last_update_age_minutes"]:
                deduplicated[key] = row
        if len(deduplicated) < config["minimum_bookmakers"]:
            return None, "bookmaker_count<10"
        return {
            "official": dict(official),
            "prediction": dict(prediction),
            "pure_model": dict(pure_model),
            "external_fetched_at": external_time,
            "bookmakers": list(deduplicated.values()),
        }, ""

    def _build_decision(self, policy: dict[str, Any], study: dict[str, Any], match: dict[str, Any],
                        inputs: dict[str, Any], decided_at: datetime) -> dict[str, Any]:
        official = inputs["official"]
        prediction = inputs["prediction"]
        pure_model = inputs["pure_model"]
        books = inputs["bookmakers"]
        bookmaker_probabilities: dict[str, list[float]] = {key: [] for key in OUTCOMES}
        for book in books:
            inverse = {key: 1.0 / float(book[f"{key}_odds"]) for key in OUTCOMES}
            total = sum(inverse.values())
            for key in OUTCOMES:
                bookmaker_probabilities[key].append(inverse[key] / total)
        external = {key: fmean(bookmaker_probabilities[key]) for key in OUTCOMES}
        dispersion = {key: pstdev(bookmaker_probabilities[key]) for key in OUTCOMES}
        pure_model_probability = {
            key: float(pure_model[f"p_{key}"])
            for key in OUTCOMES
        }
        config = policy["config"]
        fused = _fused_probabilities(external, pure_model_probability, config)
        standard_error, uncertainty, effective_count = _consensus_uncertainty(
            dispersion, len(books), config
        )
        candidates: list[dict[str, Any]] = []
        for outcome in OUTCOMES:
            probability = fused[outcome]
            conservative_probability = max(0.01, probability - uncertainty[outcome])
            sp = float(official[f"{outcome}_sp"])
            expected_ev = probability * sp - 1.0
            conservative_ev = conservative_probability * sp - 1.0
            reasons: list[str] = []
            if external[outcome] < config["minimum_external_probability"]:
                reasons.append("external_probability<0.40")
            if not config["minimum_odds"] <= sp <= config["maximum_odds"]:
                reasons.append("selected_sp_outside_[1.5,6.0]")
            if dispersion[outcome] > config["maximum_probability_dispersion"]:
                reasons.append("bookmaker_probability_dispersion>0.03")
            if expected_ev < config["minimum_expected_ev"]:
                reasons.append("expected_ev<0.03")
            if conservative_ev < config["minimum_conservative_ev"]:
                reasons.append("conservative_ev<0")
            candidates.append({
                "outcome": outcome, "sp": sp, "probability": probability,
                "external_probability": external[outcome],
                "conservative_probability": conservative_probability,
                "probability_uncertainty": uncertainty[outcome],
                "expected_ev": expected_ev, "conservative_ev": conservative_ev,
                "reasons": reasons,
            })
        eligible_candidates = [row for row in candidates if not row["reasons"]]
        selected = max(
            eligible_candidates or candidates,
            key=lambda row: (row["conservative_ev"], row["expected_ev"]),
        )
        action = "CANDIDATE" if not selected["reasons"] else "NO_BET"
        payload = {
            "policy_id": policy["policy_id"], "study_id": study["study_id"],
            "official_odds_observation_id": official["id"],
            "external_fetched_at": inputs["external_fetched_at"],
            "source_prediction_id": prediction["prediction_id"],
            "pure_model_prediction_id": pure_model["id"],
            "external": external, "dispersion": dispersion, "standard_error": standard_error,
            "fused": fused, "effective_bookmaker_count": effective_count,
            "selected": selected, "action": action,
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
            "pure_model_prediction_id": pure_model["id"],
            "decided_at": decided_at.isoformat(), "kickoff_time": match["kickoff_time"],
            "minutes_to_kickoff": (kickoff - decided_at).total_seconds() / 60.0,
            "bookmaker_count": len(books),
            "effective_bookmaker_count": effective_count,
            **{f"external_{key}_probability": external[key] for key in OUTCOMES},
            **{f"external_{key}_std": dispersion[key] for key in OUTCOMES},
            **{f"external_{key}_sem": standard_error[key] for key in OUTCOMES},
            **{f"pure_model_{key}_probability": pure_model_probability[key] for key in OUTCOMES},
            **{f"fused_{key}_probability": fused[key] for key in OUTCOMES},
            "selected_outcome": selected["outcome"], "selected_sp": selected["sp"],
            "selected_probability": selected["probability"],
            "conservative_probability": selected["conservative_probability"],
            "selected_probability_uncertainty": selected["probability_uncertainty"],
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
    def _horizon_decisions(rows: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
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
        return sorted(by_match.values(), key=lambda row: row["kickoff_time"])

    @classmethod
    def _primary_decisions(cls, rows: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
        horizon_rows = cls._horizon_decisions(rows, config)
        by_day: dict[str, list[dict[str, Any]]] = {}
        for row in horizon_rows:
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
