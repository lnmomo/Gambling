"""Prospective-only validation of a named Bet365 versus Pinnacle price gap."""
from __future__ import annotations

import hashlib
import inspect
import json
import math
import uuid
from collections import Counter
from datetime import datetime, timezone
from statistics import fmean
from typing import Any

from .db import Database, db
from .repository import Repository


OUTCOMES = ("home", "draw", "away")
POLICY_CONFIG = {
    "version": "named-book-gap-prospective-v1",
    "execution_bookmaker_key": "bet365",
    "reference_bookmaker_key": "pinnacle",
    "minimum_price_ratio": 1.06,
    "minimum_expected_ev": 0.0,
    "minimum_odds": 1.50,
    "maximum_odds": 6.00,
    "primary_horizon_minutes": 60,
    "horizon_tolerance_minutes": 60,
    "maximum_snapshot_age_minutes": 15,
    "maximum_bookmaker_last_update_age_minutes": 15,
    "maximum_bookmaker_update_skew_minutes": 10,
}


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


class NamedBookGapResearchService:
    """Stores immutable, timestamp-aligned market-gap observations; never allocates capital."""

    def __init__(self, database: Database = db, repository: Repository | None = None) -> None:
        self.db = database
        self.repository = repository or Repository(database)

    def ensure_policy(self) -> dict[str, Any]:
        source = "\n".join((inspect.getsource(self.capture), inspect.getsource(self._inputs), inspect.getsource(_devig)))
        source_sha = hashlib.sha256(source.encode()).hexdigest()
        policy_hash = hashlib.sha256(_canonical({"config": POLICY_CONFIG, "source_sha256": source_sha}).encode()).hexdigest()
        policy_id = f"named-book-gap-{policy_hash[:20]}"
        with self.db.connect() as connection:
            connection.execute("""INSERT OR IGNORE INTO named_book_gap_policies
                (policy_id,policy_hash,config_json,source_sha256,registered_at) VALUES(?,?,?,?,?)""", (
                policy_id, policy_hash, _canonical(POLICY_CONFIG), source_sha, _now().isoformat(),
            ))
            row = connection.execute("SELECT * FROM named_book_gap_policies WHERE policy_id=?", (policy_id,)).fetchone()
        return {**dict(row), "config": json.loads(row["config_json"])}

    def _inputs(self, match_id: int, decided_at: datetime, config: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        with self.db.connect() as connection:
            fetched_at = connection.execute("""SELECT MAX(fetched_at) value FROM external_bookmaker_odds
                WHERE match_id=? AND datetime(fetched_at)<=datetime(?)""", (match_id, decided_at.isoformat())).fetchone()["value"]
            rows = connection.execute("""SELECT * FROM external_bookmaker_odds
                WHERE match_id=? AND fetched_at=? ORDER BY id""", (match_id, fetched_at)).fetchall() if fetched_at else []
        if not fetched_at or not rows:
            return None, "missing_external_snapshot"
        if _age_minutes(decided_at, fetched_at) > float(config["maximum_snapshot_age_minutes"]):
            return None, "stale_external_snapshot"
        books: dict[str, dict[str, Any]] = {}
        for raw in rows:
            row = dict(raw)
            key = str(row.get("bookmaker_key") or "").lower().strip()
            if key:
                books.setdefault(key, row)
        execution = books.get(str(config["execution_bookmaker_key"]).lower())
        reference = books.get(str(config["reference_bookmaker_key"]).lower())
        if not execution:
            return None, "missing_bet365"
        if not reference:
            return None, "missing_pinnacle"
        if any(_age_minutes(decided_at, row["last_update"]) > float(config["maximum_bookmaker_last_update_age_minutes"])
               for row in (execution, reference)):
            return None, "stale_named_bookmaker_quote"
        skew = abs((_time(execution["last_update"]) - _time(reference["last_update"])).total_seconds() / 60.0)
        if skew > float(config["maximum_bookmaker_update_skew_minutes"]):
            return None, "named_bookmaker_update_skew>10m"
        probabilities = _devig(reference)
        if probabilities is None:
            return None, "invalid_pinnacle_three_way_quote"
        return {"fetched_at": fetched_at, "execution": execution, "reference": reference, "probabilities": probabilities}, ""

    def capture(self, limit: int = 100, as_of: str | datetime | None = None) -> dict[str, Any]:
        decided_at = _time(as_of or _now())
        policy = self.ensure_policy()
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
            execution = inputs["execution"]
            reference = inputs["reference"]
            possible = []
            for outcome in OUTCOMES:
                price = float(execution[f"{outcome}_odds"])
                ref_price = float(reference[f"{outcome}_odds"])
                probability = float(inputs["probabilities"][outcome])
                ev = probability * price - 1.0
                reasons = []
                if price < float(config["minimum_odds"]) or price > float(config["maximum_odds"]):
                    reasons.append("execution_price_outside_range")
                if price < ref_price * float(config["minimum_price_ratio"]):
                    reasons.append("price_gap<6pct")
                if ev < float(config["minimum_expected_ev"]):
                    reasons.append("expected_ev<0")
                possible.append((outcome, price, ref_price, probability, ev, reasons))
            selected = max(possible, key=lambda item: (item[4], item[1]))
            action = "CANDIDATE" if not selected[5] else "NO_BET"
            payload = {
                "policy_id": policy["policy_id"], "match_id": match["id"], "external_fetched_at": inputs["fetched_at"],
                "selected_outcome": selected[0], "bet365_odds": selected[1], "pinnacle_odds": selected[2],
                "reference_probability": selected[3], "expected_ev": selected[4], "action": action,
            }
            payload_hash = hashlib.sha256(_canonical(payload).encode()).hexdigest()
            try:
                with self.db.connect() as connection:
                    connection.execute("""INSERT INTO named_book_gap_decisions
                        (decision_id,policy_id,match_id,official_match_id,external_fetched_at,bet365_last_update,pinnacle_last_update,
                         decided_at,kickoff_time,minutes_to_kickoff,selected_outcome,bet365_odds,pinnacle_odds,reference_probability,
                         expected_ev,action,blockers_json,payload_hash,created_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                        str(uuid.uuid4()), policy["policy_id"], match["id"], match["official_match_id"], inputs["fetched_at"],
                        execution["last_update"], reference["last_update"], decided_at.isoformat(), match["kickoff_time"], minutes,
                        selected[0], selected[1], selected[2], selected[3], selected[4], action,
                        _canonical(selected[5]), payload_hash, _now().isoformat(),
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

    def report(self, policy_id: str | None = None) -> dict[str, Any]:
        policy = self.ensure_policy() if policy_id is None else self._policy(policy_id)
        with self.db.connect() as connection:
            rows = connection.execute("""SELECT d.*,r.outcome actual_outcome FROM named_book_gap_decisions d
                LEFT JOIN results r ON r.match_id=d.match_id WHERE d.policy_id=? ORDER BY d.decided_at""", (policy["policy_id"],)).fetchall()
        decisions = [dict(row) for row in rows]
        settled = [row for row in decisions if row["action"] == "CANDIDATE" and row["actual_outcome"] in {"home", "draw", "away"}]
        profits = [float(row["bet365_odds"]) - 1.0 if row["actual_outcome"] == row["selected_outcome"] else -1.0 for row in settled]
        months = sorted({str(row["kickoff_time"])[:7] for row in settled})
        mature = len(settled) >= 200 and len(months) >= 6
        reasons = []
        if len(settled) < 200: reasons.append("settled_selections<200")
        if len(months) < 6: reasons.append("active_months<6")
        if sum(profits) <= 0 and mature: reasons.append("profit<=0")
        return {"method": "timestamp-aligned Bet365 execution versus Pinnacle de-vig prospective shadow study",
                "policy": policy, "decision": "NAMED_BOOK_GAP_PROSPECTIVE_PASS" if mature and not reasons else "NAMED_BOOK_GAP_PROSPECTIVE_COLLECTING",
                "decision_reasons": reasons, "decisions": len(decisions), "candidate_decisions": sum(row["action"] == "CANDIDATE" for row in decisions),
                "settled_selections": len(settled), "active_months": len(months), "profit": round(sum(profits), 2),
                "roi_pct": round(sum(profits) / len(settled) * 100, 2) if settled else 0.0,
                "average_expected_ev": round(fmean(float(row["expected_ev"]) for row in settled), 6) if settled else None,
                "guardrail": "Research-only. This study never creates paper-portfolio positions or real orders."}

    def _policy(self, policy_id: str) -> dict[str, Any]:
        with self.db.connect() as connection:
            row = connection.execute("SELECT * FROM named_book_gap_policies WHERE policy_id=?", (policy_id,)).fetchone()
        if not row:
            raise KeyError(policy_id)
        return {**dict(row), "config": json.loads(row["config_json"])}
