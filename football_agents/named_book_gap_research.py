"""Prospective-only validation of a named Bet365 versus Pinnacle price gap."""
from __future__ import annotations

import hashlib
import inspect
import json
import math
import random
import uuid
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from statistics import fmean, median
from typing import Any
from zoneinfo import ZoneInfo

from .db import Database, db
from .config import settings
from .clv_ridge_shadow import load_frozen_model, odds_band, score_opening_features
from .repository import Repository


OUTCOMES = ("home", "draw", "away")
CONTROL_POLICY_CONFIG = {
    "version": "robust-leave-one-book-out-market-residual-prospective-v3.1-cost-aware",
    "reference_method": "normalized_component_median_leave_execution_book_out",
    "minimum_reference_bookmakers": 4,
    "minimum_price_ratio": 1.02,
    "minimum_conservative_ev": 0.02,
    "minimum_odds": 1.50,
    "maximum_odds": 6.00,
    "minimum_reference_probability": 0.0,
    "primary_horizon_minutes": 60,
    "horizon_tolerance_minutes": 60,
    "maximum_snapshot_age_minutes": 15,
    "maximum_bookmaker_last_update_age_minutes": 15,
    "maximum_bookmaker_update_skew_minutes": 10,
    "model_residual_reliability": 0.15,
    "maximum_probability_shift": 0.02,
    "uncertainty_floor": 0.005,
    "dispersion_uncertainty_multiplier": 1.5,
    "model_disagreement_uncertainty_multiplier": 0.25,
    "slippage_rate": 0.02,
    "exchange_commission_rate": settings.exchange_commission_rate,
    "exchange_bookmaker_keys": ["betfair_ex_eu", "betfair_ex_uk", "smarkets", "matchbook"],
    "daily_budget": 100.0,
    "maximum_single_stake": 10.0,
    "kelly_fraction": 0.25,
}

POLICY_CONFIG = {
    **CONTROL_POLICY_CONFIG,
    "version": "robust-consensus-no-longshot-prospective-v4.1-cost-aware",
    "minimum_price_ratio": 1.01,
    "minimum_conservative_ev": 0.01,
    "maximum_odds": 4.00,
    "minimum_reference_probability": 0.25,
    "dispersion_uncertainty_multiplier": 1.0,
}
_CLV_RIDGE_MODEL = load_frozen_model()
CLV_RIDGE_POLICY_CONFIG = {
    **CONTROL_POLICY_CONFIG,
    "version": "clv-ridge-v6.2-fixed-cap5-prospective-shadow",
    "decision_model": "frozen_json_clv_ridge",
    "ranker_model_sha256": _CLV_RIDGE_MODEL["model_sha256"],
    "ranker_training_window": _CLV_RIDGE_MODEL["training_window"],
    "live_feature_contract": "unmapped_official_league_uses_zero_coefficient",
    "feature_portability_status": "PROSPECTIVE_VALIDATION_REQUIRED",
    "minimum_price_ratio": 0.97,
    "minimum_conservative_ev": -0.05,
    "minimum_odds": 1.50,
    "maximum_odds": 5.00,
    "minimum_reference_probability": 0.12,
    "model_residual_reliability": 0.0,
    "uncertainty_floor": 0.002,
    "dispersion_uncertainty_multiplier": 1.0,
    "model_disagreement_uncertainty_multiplier": 0.0,
    "minimum_lower_clv_pct": 1.0,
    "daily_budget": 100.0,
    "maximum_single_stake": 5.0,
    "kelly_fraction": 0.10,
}
CLV_RIDGE_HALF_KELLY_POLICY_CONFIG = {
    **CLV_RIDGE_POLICY_CONFIG,
    "version": "clv-ridge-v6.3-fixed-cap5-half-kelly-prospective-shadow",
    "maximum_single_stake": 15.0,
    "kelly_fraction": 0.50,
    "stake_challenger_of": "clv-ridge-v6.2-fixed-cap5-prospective-shadow",
}
EXPERIMENT_POLICY_CONFIGS = (
    CONTROL_POLICY_CONFIG,
    POLICY_CONFIG,
    CLV_RIDGE_POLICY_CONFIG,
    CLV_RIDGE_HALF_KELLY_POLICY_CONFIG,
)
EXPERIMENT_NAME = "v3.1-v4.1-market-vs-v6.2-v6.3-clv-ridge-shadow"

CHINA_TZ = ZoneInfo("Asia/Shanghai")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _time(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _age_minutes(later: datetime, earlier: str | datetime) -> float:
    return (later - _time(earlier)).total_seconds() / 60.0


def _devig(row: dict[str, Any]) -> dict[str, float] | None:
    try:
        inverse = {outcome: 1.0 / float(row[f"{outcome}_odds"]) for outcome in OUTCOMES}
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None
    total = sum(inverse.values())
    return {outcome: inverse[outcome] / total for outcome in OUTCOMES} if total > 0 else None


def _robust_consensus(rows: list[dict[str, Any]]) -> tuple[dict[str, float], dict[str, float]] | None:
    probabilities = [value for row in rows if (value := _devig(row)) is not None]
    if not probabilities:
        return None
    centers = {outcome: median(item[outcome] for item in probabilities) for outcome in OUTCOMES}
    total = sum(centers.values())
    consensus = {outcome: centers[outcome] / total for outcome in OUTCOMES}
    dispersion = {
        outcome: 1.4826 * median(abs(item[outcome] - consensus[outcome]) for item in probabilities)
        for outcome in OUTCOMES
    }
    return consensus, dispersion


def _execution_cost_rate(bookmaker_key: str, config: dict[str, Any]) -> float:
    keys = {str(value).lower() for value in config.get("exchange_bookmaker_keys", [])}
    return float(config.get("exchange_commission_rate", 0.0)) if bookmaker_key.lower() in keys else 0.0


def _net_execution_odds(raw_odds: float, cost_rate: float) -> float:
    return 1.0 + (float(raw_odds) - 1.0) * (1.0 - cost_rate)


def _slippage_adjusted_odds(net_odds: float, slippage_rate: float) -> float:
    return 1.0 + (float(net_odds) - 1.0) * (1.0 - slippage_rate)


def _historical_bookmaker_feature(bookmaker_key: str) -> str:
    key = bookmaker_key.lower()
    aliases = {
        "bet365": "B365", "pinnacle": "PS", "williamhill": "WH",
        "betfair_ex_eu": "BFE", "betfair_ex_uk": "BFE",
        "smarkets": "BFE", "matchbook": "BFE",
    }
    return aliases.get(key, bookmaker_key.upper())


def _market_residual_probabilities(
    reference: dict[str, float],
    model: dict[str, float] | None,
    reliability: float,
    maximum_shift: float,
) -> dict[str, float]:
    if not model:
        return dict(reference)
    lower = {outcome: max(0.001, reference[outcome] - maximum_shift) for outcome in OUTCOMES}
    upper = {outcome: min(0.999, reference[outcome] + maximum_shift) for outcome in OUTCOMES}
    adjusted = {
        outcome: min(upper[outcome], max(
            lower[outcome], reference[outcome] + reliability * (model[outcome] - reference[outcome])
        ))
        for outcome in OUTCOMES
    }
    for _ in range(6):
        remainder = 1.0 - sum(adjusted.values())
        if abs(remainder) < 1e-12:
            break
        eligible = [
            outcome for outcome in OUTCOMES
            if (remainder > 0 and adjusted[outcome] < upper[outcome] - 1e-12)
            or (remainder < 0 and adjusted[outcome] > lower[outcome] + 1e-12)
        ]
        if not eligible:
            break
        share = remainder / len(eligible)
        for outcome in eligible:
            adjusted[outcome] = min(upper[outcome], max(lower[outcome], adjusted[outcome] + share))
    return adjusted


def _quantile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _settlement_day_bootstrap_roi(
    positions: list[dict[str, Any]], iterations: int = 5000, seed: int = 42,
) -> dict[str, Any]:
    settled = [item for item in positions if item.get("status") == "SETTLED"]
    days = sorted({str(item["settlement_date"]) for item in settled})
    if len(settled) < 30 or len(days) < 10:
        return {
            "status": "INSUFFICIENT_SAMPLE", "settled_bets": len(settled),
            "settlement_days": len(days), "minimum_bets": 30, "minimum_days": 10,
            "lower_95_pct": None, "median_pct": None, "upper_95_pct": None,
        }
    groups = [[item for item in settled if item["settlement_date"] == day] for day in days]
    rng = random.Random(seed)
    estimates: list[float] = []
    for _ in range(iterations):
        sample = [groups[rng.randrange(len(groups))] for _ in groups]
        flat = [item for group in sample for item in group]
        stake = sum(float(item["stake"]) for item in flat)
        estimates.append(sum(float(item["profit"]) for item in flat) / stake if stake else 0.0)
    return {
        "status": "READY", "settled_bets": len(settled), "settlement_days": len(days),
        "iterations": iterations, "seed": seed,
        "lower_95_pct": round(float(_quantile(estimates, 0.025)) * 100, 4),
        "median_pct": round(float(_quantile(estimates, 0.5)) * 100, 4),
        "upper_95_pct": round(float(_quantile(estimates, 0.975)) * 100, 4),
    }


class NamedBookGapResearchService:
    """Stores immutable, timestamp-aligned market-gap observations; never allocates capital."""

    def __init__(self, database: Database = db, repository: Repository | None = None) -> None:
        self.db = database
        self.repository = repository or Repository(database)

    def ensure_policy(self, policy_config: dict[str, Any] | None = None) -> dict[str, Any]:
        registered_config = policy_config or POLICY_CONFIG
        source = "\n".join((inspect.getsource(self.capture), inspect.getsource(self._inputs),
                             inspect.getsource(self.report), inspect.getsource(self._paper_portfolio),
                             inspect.getsource(_devig), inspect.getsource(_robust_consensus),
                             inspect.getsource(score_opening_features), inspect.getsource(odds_band),
                             inspect.getsource(_historical_bookmaker_feature),
                             inspect.getsource(_market_residual_probabilities),
                             inspect.getsource(_settlement_day_bootstrap_roi)))
        source_sha = hashlib.sha256(source.encode()).hexdigest()
        policy_hash = hashlib.sha256(_canonical({"config": registered_config, "source_sha256": source_sha}).encode()).hexdigest()
        policy_id = f"named-book-gap-{policy_hash[:20]}"
        with self.db.connect() as connection:
            connection.execute("""INSERT OR IGNORE INTO named_book_gap_policies
                (policy_id,policy_hash,config_json,source_sha256,registered_at) VALUES(?,?,?,?,?)""", (
                policy_id, policy_hash, _canonical(registered_config), source_sha, _now().isoformat(),
            ))
            row = connection.execute("SELECT * FROM named_book_gap_policies WHERE policy_id=?", (policy_id,)).fetchone()
        return {**dict(row), "config": json.loads(row["config_json"])}

    def _inputs(self, match_id: int, decided_at: datetime, config: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        with self.db.connect() as connection:
            fetched_at = connection.execute("""SELECT MAX(captured_at) value
                FROM prospective_external_odds_snapshots
                WHERE match_id=? AND capture_window='T_MINUS_1H'
                  AND datetime(captured_at)<=datetime(?)""", (match_id, decided_at.isoformat())).fetchone()["value"]
            rows = connection.execute("""SELECT * FROM prospective_external_odds_snapshots
                WHERE match_id=? AND captured_at=? ORDER BY bookmaker_key""", (match_id, fetched_at)).fetchall() if fetched_at else []
            pure_model = connection.execute("""SELECT * FROM model_predictions
                WHERE match_id=? AND model_name='baseline' AND datetime(predicted_at)<=datetime(?)
                ORDER BY predicted_at DESC,id DESC LIMIT 1""", (
                match_id, fetched_at or decided_at.isoformat(),
            )).fetchone()
        if not fetched_at or not rows:
            return None, "missing_external_snapshot"
        if _age_minutes(decided_at, fetched_at) > float(config["maximum_snapshot_age_minutes"]):
            return None, "stale_external_snapshot"
        books: dict[str, dict[str, Any]] = {}
        for raw in rows:
            row = dict(raw)
            key = str(row.get("bookmaker_key") or "").lower().strip()
            quote_age = _age_minutes(decided_at, row["bookmaker_last_update"])
            if key and _devig(row) is not None and -2 <= quote_age <= float(
                config["maximum_bookmaker_last_update_age_minutes"]
            ):
                books.setdefault(key, row)
        minimum_books = int(config["minimum_reference_bookmakers"]) + 1
        if len(books) < minimum_books:
            return None, f"fresh_bookmakers<{minimum_books}"
        updates = [_time(row["bookmaker_last_update"]) for row in books.values()]
        newest = max(updates)
        books = {
            key: row for key, row in books.items()
            if (newest - _time(row["bookmaker_last_update"])).total_seconds() / 60.0
            <= float(config["maximum_bookmaker_update_skew_minutes"])
        }
        if len(books) < minimum_books:
            return None, f"aligned_bookmakers<{minimum_books}"
        adjusted_books = []
        for row in books.values():
            adjusted = dict(row)
            cost_rate = _execution_cost_rate(str(row["bookmaker_key"]), config)
            adjusted["execution_cost_rate"] = cost_rate
            for outcome in OUTCOMES:
                raw_odds = float(row[f"{outcome}_odds"])
                adjusted[f"raw_{outcome}_odds"] = raw_odds
                adjusted[f"{outcome}_odds"] = _net_execution_odds(raw_odds, cost_rate)
            adjusted_books.append(adjusted)
        model_probabilities = None
        if pure_model:
            model_probabilities = {outcome: float(pure_model[f"p_{outcome}"]) for outcome in OUTCOMES}
        return {"fetched_at": fetched_at, "books": adjusted_books,
                "model_probabilities": model_probabilities}, ""

    def capture(self, limit: int = 100, as_of: str | datetime | None = None,
                policy_config: dict[str, Any] | None = None) -> dict[str, Any]:
        decided_at = _time(as_of or _now())
        policy = self.ensure_policy(policy_config)
        config = policy["config"]
        counters: Counter[str] = Counter()
        inserted = candidates = 0
        for match in self.repository.list_active_official_matches(max(1, min(limit, 500))):
            kickoff = _time(match["kickoff_time"])
            minutes = (kickoff - decided_at).total_seconds() / 60.0
            lower = float(config["primary_horizon_minutes"])
            upper = lower + float(config["horizon_tolerance_minutes"])
            if not lower <= minutes <= upper:
                counters["outside_primary_horizon"] += 1
                continue
            inputs, blocker = self._inputs(int(match["id"]), decided_at, config)
            if inputs is None:
                counters[blocker] += 1
                continue
            possible = []
            for outcome in OUTCOMES:
                execution = max(inputs["books"], key=lambda row: float(row[f"{outcome}_odds"]))
                references = [
                    row for row in inputs["books"]
                    if row["bookmaker_key"] != execution["bookmaker_key"]
                ]
                robust = _robust_consensus(references)
                if robust is None or len(references) < int(config["minimum_reference_bookmakers"]):
                    continue
                probabilities, dispersions = robust
                price = _slippage_adjusted_odds(
                    float(execution[f"{outcome}_odds"]), float(config["slippage_rate"])
                )
                probability = float(probabilities[outcome])
                ref_price = 1.0 / probability
                pure_probability = (
                    float(inputs["model_probabilities"][outcome])
                    if inputs["model_probabilities"] else probability
                )
                residual_probabilities = _market_residual_probabilities(
                    probabilities, inputs["model_probabilities"],
                    float(config["model_residual_reliability"]),
                    float(config["maximum_probability_shift"]),
                )
                residual_probability = residual_probabilities[outcome]
                model_disagreement = abs(pure_probability - probability) if inputs["model_probabilities"] else 0.0
                uncertainty = (
                    float(config["uncertainty_floor"])
                    + float(config["dispersion_uncertainty_multiplier"]) * dispersions[outcome]
                    + float(config["model_disagreement_uncertainty_multiplier"]) * model_disagreement
                )
                conservative_probability = max(0.001, residual_probability - uncertainty)
                ev = residual_probability * price - 1.0
                conservative_ev = conservative_probability * price - 1.0
                reasons = []
                if price < float(config["minimum_odds"]) or price > float(config["maximum_odds"]):
                    reasons.append("execution_price_outside_range")
                if probability < float(config.get("minimum_reference_probability", 0.0)):
                    reasons.append("reference_probability_below_minimum")
                if price < ref_price * float(config["minimum_price_ratio"]):
                    reasons.append("execution_price_not_2pct_above_consensus_fair_price")
                if conservative_ev < float(config["minimum_conservative_ev"]):
                    reasons.append("conservative_ev<2pct")
                possible.append((outcome, price, ref_price, probability, pure_probability,
                                 residual_probability, conservative_probability, ev, conservative_ev, reasons,
                                 execution, references, dispersions[outcome]))
            if not possible:
                counters["insufficient_valid_outcomes"] += 1
                continue
            selected = max(possible, key=lambda item: (item[8], item[1]))
            predicted_clv = lower_predicted_clv = ranker_model_sha = None
            stored_expected_ev = selected[7]
            stored_conservative_ev = selected[8]
            stored_conservative_probability = selected[6]
            if config.get("decision_model") == "frozen_json_clv_ridge":
                execution = selected[10]
                feature_row = {
                    "probability": selected[3],
                    "conservative_probability": selected[6],
                    "odds": selected[1],
                    "raw_odds": execution[f"raw_{selected[0]}_odds"],
                    "conservative_ev_pct": selected[8] * 100.0,
                    "reference_dispersion": selected[12],
                    "reference_bookmakers": len(selected[11]),
                    "execution_cost_rate": execution["execution_cost_rate"],
                    "outcome": selected[0],
                    "odds_band": odds_band(selected[1]),
                    "source_type": "exchange" if execution["execution_cost_rate"] > 0 else "sportsbook",
                    "execution_bookmaker": _historical_bookmaker_feature(execution["bookmaker_key"]),
                    "league": str(match.get("league") or ""),
                }
                try:
                    ranker = score_opening_features(feature_row)
                    predicted_clv = float(ranker["predicted_closing_edge_pct"])
                    lower_predicted_clv = float(ranker["lower_predicted_closing_edge_pct"])
                    ranker_model_sha = str(ranker["model_sha256"])
                    if lower_predicted_clv < float(config["minimum_lower_clv_pct"]):
                        selected[9].append("predicted_lower_clv<1pct")
                    stored_expected_ev = predicted_clv / 100.0
                    stored_conservative_ev = lower_predicted_clv / 100.0
                    stored_conservative_probability = min(
                        0.999, max(0.001, (1.0 + stored_conservative_ev) / selected[1])
                    )
                except (KeyError, OSError, TypeError, ValueError) as exc:
                    selected[9].append(f"clv_ranker_unavailable:{type(exc).__name__}")
            action = "CANDIDATE" if not selected[9] else "NO_BET"
            execution = selected[10]
            references = selected[11]
            reference_keys = sorted(str(row["bookmaker_key"]) for row in references)
            payload = {
                "policy_id": policy["policy_id"], "match_id": match["id"], "external_fetched_at": inputs["fetched_at"],
                "selected_outcome": selected[0], "bet365_odds": selected[1], "pinnacle_odds": selected[2],
                "reference_probability": selected[3], "pure_model_probability": selected[4],
                "residual_probability": selected[5], "conservative_probability": stored_conservative_probability,
                "expected_ev": stored_expected_ev, "conservative_ev": stored_conservative_ev, "action": action,
                "execution_bookmaker_key": execution["bookmaker_key"],
                "reference_bookmakers": reference_keys,
                "snapshot_payload_hash": execution["payload_hash"],
                "raw_execution_odds": execution[f"raw_{selected[0]}_odds"],
                "execution_cost_rate": execution["execution_cost_rate"],
                "predicted_closing_edge_pct": predicted_clv,
                "lower_predicted_closing_edge_pct": lower_predicted_clv,
                "ranker_model_sha256": ranker_model_sha,
            }
            payload_hash = hashlib.sha256(_canonical(payload).encode()).hexdigest()
            try:
                with self.db.connect() as connection:
                    connection.execute("""INSERT INTO named_book_gap_decisions
                        (decision_id,policy_id,match_id,official_match_id,external_fetched_at,bet365_last_update,pinnacle_last_update,
                         decided_at,kickoff_time,minutes_to_kickoff,selected_outcome,bet365_odds,pinnacle_odds,reference_probability,
                         expected_ev,action,blockers_json,payload_hash,created_at,pure_model_probability,
                         residual_probability,conservative_probability,conservative_ev,slippage_rate,
                         execution_bookmaker,execution_bookmaker_key,reference_method,reference_bookmakers_json,
                         reference_dispersion,snapshot_payload_hash,raw_execution_odds,execution_cost_rate,
                         predicted_closing_edge_pct,lower_predicted_closing_edge_pct,ranker_model_sha256)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                        str(uuid.uuid4()), policy["policy_id"], match["id"], match["official_match_id"], inputs["fetched_at"],
                        execution["bookmaker_last_update"], max(row["bookmaker_last_update"] for row in references),
                        decided_at.isoformat(), match["kickoff_time"], minutes,
                        selected[0], selected[1], selected[2], selected[3], stored_expected_ev, action,
                        _canonical(selected[9]), payload_hash, _now().isoformat(), selected[4], selected[5],
                        stored_conservative_probability, stored_conservative_ev,
                        float(config["slippage_rate"]), execution["bookmaker"],
                        execution["bookmaker_key"], config["reference_method"], _canonical(reference_keys),
                        selected[12], execution["payload_hash"], execution[f"raw_{selected[0]}_odds"],
                        execution["execution_cost_rate"], predicted_clv, lower_predicted_clv, ranker_model_sha,
                    ))
                inserted += 1
                candidates += int(action == "CANDIDATE")
            except Exception as exc:
                if "UNIQUE constraint failed" in str(exc):
                    counters["duplicate_decision"] += 1
                else:
                    raise
        report = self.report(policy["policy_id"])
        return {"matches": len(self.repository.list_active_official_matches(limit)), "decisions": inserted,
                "predictions": candidates, "blocker_counts": [{"reason": key, "matches": value} for key, value in counters.most_common()],
                "report": report, "warnings": report["decision_reasons"]}

    def capture_experiment(self, limit: int = 100, as_of: str | datetime | None = None) -> dict[str, Any]:
        frozen_at = _time(as_of or _now())
        reports = [self.capture(limit, frozen_at, config) for config in EXPERIMENT_POLICY_CONFIGS]
        return {
            "experiment": EXPERIMENT_NAME,
            "matches": max((int(row.get("matches") or 0) for row in reports), default=0),
            "decisions": sum(int(row.get("decisions") or 0) for row in reports),
            "predictions": sum(int(row.get("predictions") or 0) for row in reports),
            "policies": reports,
            "blocker_counts": [
                {"policy_version": row["report"]["policy"]["config"]["version"], **blocker}
                for row in reports for blocker in row.get("blocker_counts", [])
            ],
            "warnings": sorted({warning for row in reports for warning in row.get("warnings", [])}),
        }

    def experiment_report(self) -> dict[str, Any]:
        reports = [self.report(self.ensure_policy(config)["policy_id"]) for config in EXPERIMENT_POLICY_CONFIGS]
        return {
            "experiment": EXPERIMENT_NAME,
            "selection_locked_before_future_results": True,
            "policies": reports,
            "comparison_ready": all(row["settled_selections"] >= 200 for row in reports),
            "guardrail": "All policies consume the same prospective snapshot; none places real orders.",
        }

    def report(self, policy_id: str | None = None) -> dict[str, Any]:
        policy = self.ensure_policy() if policy_id is None else self._policy(policy_id)
        with self.db.connect() as connection:
            rows = connection.execute("""SELECT d.*,
                CASE WHEN datetime(r.settled_at)>=datetime(d.kickoff_time)
                       AND datetime(r.settled_at)>datetime(d.decided_at) THEN r.outcome END actual_outcome,
                CASE WHEN datetime(r.settled_at)>=datetime(d.kickoff_time)
                       AND datetime(r.settled_at)>datetime(d.decided_at) THEN r.settled_at END result_settled_at
                FROM named_book_gap_decisions d LEFT JOIN results r ON r.match_id=d.match_id
                WHERE d.policy_id=? ORDER BY d.decided_at""", (policy["policy_id"],)).fetchall()
        decisions = [dict(row) for row in rows]
        candidates = [row for row in decisions if row["action"] == "CANDIDATE"]
        settled = [row for row in candidates if row["actual_outcome"] in {"home", "draw", "away"}]
        profits = [float(row["bet365_odds"]) - 1.0 if row["actual_outcome"] == row["selected_outcome"] else -1.0 for row in settled]
        paper = self._paper_portfolio(candidates, policy["config"])
        bootstrap = _settlement_day_bootstrap_roi(paper["positions"])
        months = sorted({str(row["kickoff_time"])[:7] for row in settled})
        mature = len(settled) >= 200 and len(months) >= 6
        brier = fmean(
            (float(row["conservative_probability"]) - float(row["actual_outcome"] == row["selected_outcome"])) ** 2
            for row in settled
        ) if settled else None
        reference_brier = fmean(
            (float(row["reference_probability"]) - float(row["actual_outcome"] == row["selected_outcome"])) ** 2
            for row in settled
        ) if settled else None
        selected_outcomes = Counter(str(row["selected_outcome"]) for row in candidates)
        execution_books = Counter(str(row.get("execution_bookmaker_key") or "unknown") for row in candidates)
        ranked = [row for row in decisions if row.get("ranker_model_sha256")]
        outcome_concentration = max(selected_outcomes.values(), default=0) / len(candidates) if candidates else 0.0
        reasons = []
        if len(settled) < 200: reasons.append("settled_selections<200")
        if len(months) < 6: reasons.append("active_months<6")
        if mature and (bootstrap["lower_95_pct"] is None or float(bootstrap["lower_95_pct"]) <= 0):
            reasons.append("settlement_day_bootstrap_roi_lower_95<=0")
        if mature and brier is not None and reference_brier is not None and brier > reference_brier + 0.002:
            reasons.append("conservative_probability_brier_worse_than_market")
        if mature and outcome_concentration > 0.75:
            reasons.append("selected_outcome_concentration>75pct")
        return {"method": "timestamp-aligned best named-book quote versus robust leave-one-book-out consensus",
                "policy": policy, "decision": "NAMED_BOOK_GAP_PROSPECTIVE_PASS" if mature and not reasons else "NAMED_BOOK_GAP_PROSPECTIVE_COLLECTING",
                "decision_reasons": reasons, "decisions": len(decisions), "candidate_decisions": sum(row["action"] == "CANDIDATE" for row in decisions),
                "settled_selections": len(settled), "active_months": len(months), "profit": round(sum(profits), 2),
                "roi_pct": round(sum(profits) / len(settled) * 100, 2) if settled else 0.0,
                "average_expected_ev": round(fmean(float(row["expected_ev"]) for row in settled), 6) if settled else None,
                "calibration": {
                    "selected_binary_brier": round(brier, 6) if brier is not None else None,
                    "reference_binary_brier": round(reference_brier, 6) if reference_brier is not None else None,
                },
                "selection_diagnostics": {
                    "outcome_counts": dict(selected_outcomes),
                    "maximum_outcome_concentration_pct": round(outcome_concentration * 100, 2),
                    "execution_bookmaker_counts": dict(execution_books),
                    "ranker_evidence_rows": len(ranked),
                    "average_predicted_closing_edge_pct": round(fmean(
                        float(row["predicted_closing_edge_pct"]) for row in ranked
                    ), 4) if ranked else None,
                    "ranker_model_sha256": policy["config"].get("ranker_model_sha256"),
                },
                "settlement_day_bootstrap_roi": bootstrap,
                "prospective_warnings": ([
                    "historical_league_codes_do_not_match_official_pool_labels; unknown-category fallback is under validation"
                ] if policy["config"].get("feature_portability_status") == "PROSPECTIVE_VALIDATION_REQUIRED" else []),
                "paper_portfolio": paper,
                "anti_leakage": "A result is usable only when settled_at is after both kickoff_time and decided_at.",
                "guardrail": "Research-only immutable paper simulation. It never creates real orders."}

    @staticmethod
    def _paper_portfolio(candidates: list[dict[str, Any]], config: dict[str, Any],
                         as_of: datetime | None = None) -> dict[str, Any]:
        daily_budget = float(config["daily_budget"])
        single_cap = float(config["maximum_single_stake"])
        fraction = float(config["kelly_fraction"])
        daily_used: dict[str, float] = {}
        positions: list[dict[str, Any]] = []
        for row in sorted(candidates, key=lambda item: (str(item["decided_at"]), str(item["decision_id"]))):
            decision_time = _time(row["decided_at"]).astimezone(CHINA_TZ)
            day = decision_time.date().isoformat()
            remaining = max(0.0, daily_budget - daily_used.get(day, 0.0))
            odds = float(row["bet365_odds"])
            probability = float(row.get("conservative_probability") or row["reference_probability"])
            full_kelly = max(0.0, (probability * odds - 1.0) / max(odds - 1.0, 1e-9))
            stake = round(min(single_cap, remaining, daily_budget * full_kelly * fraction), 2)
            if stake <= 0:
                continue
            daily_used[day] = daily_used.get(day, 0.0) + stake
            settled_at = row.get("result_settled_at")
            won = str(row.get("actual_outcome")) == str(row["selected_outcome"]) if settled_at else None
            profit = round(stake * (odds - 1.0) if won else -stake, 2) if settled_at else None
            settlement_day = _time(settled_at).astimezone(CHINA_TZ).date().isoformat() if settled_at else None
            positions.append({"decision_date": day, "settlement_date": settlement_day,
                              "match_id": row["match_id"], "outcome": row["selected_outcome"],
                              "bookmaker": row.get("execution_bookmaker"), "odds": odds,
                              "stake": stake, "status": "SETTLED" if settled_at else "PENDING",
                              "profit": profit})
        daily: list[dict[str, Any]] = []
        equity = peak = max_drawdown = 0.0
        today = (as_of or _now()).astimezone(CHINA_TZ).date()
        current = today - timedelta(days=29)
        while current <= today:
            day_text = current.isoformat()
            day_positions = [item for item in positions if item["decision_date"] == day_text]
            settlements = [item for item in positions if item["settlement_date"] == day_text]
            day_profit = round(sum(float(item["profit"] or 0) for item in settlements), 2)
            equity = round(equity + day_profit, 2)
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, peak - equity)
            daily.append({"date": day_text, "bets": len(day_positions),
                          "staked": round(sum(item["stake"] for item in day_positions), 2),
                          "pending": sum(item["status"] == "PENDING" for item in day_positions),
                          "settlements": len(settlements), "settled_profit": day_profit, "equity": equity,
                          "cash_reserved": round(daily_budget - sum(item["stake"] for item in day_positions), 2)})
            current += timedelta(days=1)
        staked = round(sum(item["stake"] for item in positions), 2)
        settled_staked = round(sum(item["stake"] for item in positions if item["status"] == "SETTLED"), 2)
        profit = round(sum(float(item["profit"] or 0) for item in positions), 2)
        monthly = []
        for month in sorted({item["decision_date"][:7] for item in positions}):
            selected = [item for item in positions if item["decision_date"].startswith(month)]
            month_staked = round(sum(item["stake"] for item in selected), 2)
            month_settled_staked = round(sum(item["stake"] for item in selected if item["status"] == "SETTLED"), 2)
            month_profit = round(sum(float(item["profit"] or 0) for item in selected), 2)
            monthly.append({"month": month, "bets": len(selected),
                            "settled": sum(item["status"] == "SETTLED" for item in selected), "staked": month_staked,
                            "profit": month_profit,
                            "roi_pct": round(month_profit / month_settled_staked * 100, 2) if month_settled_staked else 0.0})
        return {"daily_budget_limit": daily_budget, "maximum_single_stake": single_cap,
                "staking": f"{fraction:g}_kelly_with_cash_reserve", "same_day_results_hidden": True,
                "daily_window": "latest_30_calendar_days_Asia/Shanghai",
                "bets": len(positions), "pending_bets": sum(item["status"] == "PENDING" for item in positions),
                "settled_bets": sum(item["status"] == "SETTLED" for item in positions),
                "staked": staked, "settled_staked": settled_staked, "profit": profit,
                "roi_pct": round(profit / settled_staked * 100, 2) if settled_staked else 0.0,
                "ending_equity": profit, "max_drawdown": round(max_drawdown, 2),
                "positive_months": sum(item["profit"] > 0 for item in monthly),
                "negative_months": sum(item["profit"] < 0 for item in monthly),
                "monthly": monthly, "daily": daily, "positions": positions}

    def _policy(self, policy_id: str) -> dict[str, Any]:
        with self.db.connect() as connection:
            row = connection.execute("SELECT * FROM named_book_gap_policies WHERE policy_id=?", (policy_id,)).fetchone()
        if not row:
            raise KeyError(policy_id)
        return {**dict(row), "config": json.loads(row["config_json"])}
